"""Docker and proxy policy for the Open Interpreter agent runtime.

This module owns the *outer* security boundary: which host folders reach the
container, whether it can talk to the internet and through which proxy, and the
resource ceilings it runs under. The *inner* runtime (Open Interpreter's App
Server) is appended by :func:`launcher.agent.sandbox_backend.app_server_tail`,
so the command produced here is already the final one.

It replaces the previous builder, which embedded a base64 copy of a retired
custom agent loop and shipped it into the container through ``AGENT_REPL_SRC``.
That payload carried its own system prompt telling the model to call undefined
global helpers, which is exactly the behaviour the current instructions forbid.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .sandbox_backend import app_server_tail


def build_sandbox_docker_command(
    image: str,
    container_name: str,
    workspace: Path,
    workspace_mount: str,
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    block_internet: bool = True,
    tor_proxy: bool = False,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Assemble the ``docker run`` command for one sandboxed agent session.

    Args:
        block_internet: add ``--dns=0.0.0.0`` so the container cannot resolve
            external names. Container-to-container names on the shared network
            still resolve, which is how the local SearXNG stays reachable.
        tor_proxy: route the container through the configured anonymising proxy
            instead of blocking it.

    The model is deliberately absent: the App Server is configured over its
    JSON-RPC ``thread/start`` call, so switching models restarts the session
    rather than rewriting this command. The Ollama endpoint is injected by
    :func:`launcher.agent.sandbox_backend._override_env`.
    """
    cmd = [
        "docker", "run", "--rm", "-i",
        "--name", container_name,
        "-v", f"{workspace}:{workspace_mount}",
        "--add-host=host.docker.internal:host-gateway",
        # No display exists in the container; make GUI automation fail fast
        # rather than hang.
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",
        "-e", "PYTHONUNBUFFERED=1",
    ]

    # Persistent agent state: Open Interpreter home plus the local_search MCP
    # server the product installs into it.
    try:
        from launcher.core import user_data
        state_host = str(user_data.interpreter_dir("sandbox"))
        cmd += [
            "-v", state_host + ":/home/agent/.agent_state",
            "-e", "AGENT_STATE_DIR=/home/agent/.agent_state",
            "-e", "AGENT_STATE_KIND=sandbox",
        ]
    except Exception:
        pass

    # Standing folder policy. Paths that are not mounted are not merely
    # forbidden by prompt, they are physically absent from the container.
    try:
        from launcher.agent import folder_policy
        for host_path, container_path in folder_policy.mounts_for():
            cmd += ["-v", host_path + ":" + container_path]
        for mask in folder_policy.tmpfs_masks_for():
            cmd += ["--tmpfs", mask]
    except Exception:
        pass

    if tor_proxy:
        cmd += _proxy_args()
    elif block_internet:
        cmd += ["--dns=0.0.0.0"]
    if cpu_limit:
        cmd += [f"--cpus={cpu_limit}"]
    if memory_limit:
        cmd += [f"--memory={memory_limit}"]

    cmd += app_server_tail(image)
    if extra_args:
        cmd += list(extra_args)
    return cmd


def _proxy_args() -> List[str]:
    """``-e`` pairs routing the container through the selected proxy."""
    try:
        from launcher import config
        proxy_env = config.net_proxy_env()
    except Exception:
        proxy_env = {
            "HTTP_PROXY": "socks5h://llm_warp:1080",
            "HTTPS_PROXY": "socks5h://llm_warp:1080",
            "http_proxy": "socks5h://llm_warp:1080",
            "https_proxy": "socks5h://llm_warp:1080",
            "ALL_PROXY": "socks5h://llm_warp:1080",
            "all_proxy": "socks5h://llm_warp:1080",
            "NO_PROXY": "host.docker.internal,localhost,127.0.0.1",
            "no_proxy": "host.docker.internal,localhost,127.0.0.1",
        }
    args: List[str] = []
    for key, value in proxy_env.items():
        args += ["-e", f"{key}={value}"]
    return args


def build_tor_env(base=None) -> dict:
    """Environment forcing a host process through the local Tor proxy.

    - HTTP/HTTPS go through Privoxy, because urllib cannot speak SOCKS.
    - ALL_PROXY uses ``socks5h`` so DNS is resolved remotely, not locally.
    - NO_PROXY must keep local Ollama direct or every model call fails.

    Returns a new dict; ``base`` is not modified.
    """
    env = dict(base) if base is not None else dict(os.environ)
    http_port, socks_port = 8118, 9050
    try:
        from launcher import tor_runtime
        http_port = int(getattr(tor_runtime, "TOR_HTTP_PORT", 8118))
        socks_port = int(getattr(tor_runtime, "TOR_HOST_PORT", 9050))
    except Exception:
        pass

    http_proxy = "http://127.0.0.1:%d" % http_port
    socks_proxy = "socks5h://127.0.0.1:%d" % socks_port
    no_proxy = "127.0.0.1,localhost,::1,host.docker.internal"
    try:
        from launcher import config
        ollama_host = str(getattr(config, "OLLAMA_HOST", "") or "")
        if ollama_host and ollama_host not in no_proxy:
            no_proxy += "," + ollama_host
    except Exception:
        pass

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[key] = http_proxy
    for key in ("ALL_PROXY", "all_proxy"):
        env[key] = socks_proxy
    for key in ("NO_PROXY", "no_proxy"):
        env[key] = no_proxy
    return env


__all__ = ["build_sandbox_docker_command", "build_tor_env"]
