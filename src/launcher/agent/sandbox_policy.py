"""Docker and proxy policy for the Open Interpreter agent runtime.

The outer Sandbox boundary is still enforced here. Network-mode meaning comes
from ``launcher.network_policy`` so Host WARP can no longer accidentally reuse
Tor endpoints through the historic ``build_tor_env`` compatibility name.
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
    network_mode: Optional[str] = None,
) -> List[str]:
    """Assemble the ``docker run`` command for one sandboxed agent session.

    ``network_mode`` is the canonical policy input. The older booleans remain
    source-compatible, but they no longer override a canonical mode already
    chosen by the launcher. This is important for Direct: the historic
    ``block_internet`` boolean must not turn a Direct session into Block.
    """
    try:
        from launcher import network_policy
        selected = (
            network_policy.normalize_mode(network_mode)
            if network_mode is not None
            else network_policy.current_mode()
        )
    except Exception:
        selected = None

    cmd = [
        "docker", "run", "--rm", "-i",
        "--name", container_name,
        "-v", f"{workspace}:{workspace_mount}",
        "--add-host=host.docker.internal:host-gateway",
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",
        "-e", "PYTHONUNBUFFERED=1",
    ]

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

    try:
        from launcher.agent import folder_policy
        for host_path, container_path in folder_policy.mounts_for():
            cmd += ["-v", host_path + ":" + container_path]
        for mask in folder_policy.tmpfs_masks_for():
            cmd += ["--tmpfs", mask]
    except Exception:
        pass

    try:
        from launcher import config, network_policy
        if selected is network_policy.NetworkMode.BLOCK:
            cmd += [
                "--network", network_policy.block_network_name(),
                "-e", "LOCAL_AI_NETWORK_MODE=block",
                "--dns=0.0.0.0",
            ]
        elif selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR):
            cmd += ["--network", str(getattr(config, "LLM_NETWORK", "llm_net"))]
            cmd += _proxy_args(selected)
        elif selected is network_policy.NetworkMode.DIRECT:
            cmd += ["-e", "LOCAL_AI_NETWORK_MODE=direct"]
        elif tor_proxy:
            cmd += ["--network", str(getattr(config, "LLM_NETWORK", "llm_net"))]
            cmd += _proxy_args()
        elif block_internet:
            cmd += ["-e", "LOCAL_AI_NETWORK_MODE=block", "--dns=0.0.0.0"]
    except Exception:
        if tor_proxy:
            cmd += _proxy_args()
        elif block_internet:
            cmd += ["-e", "LOCAL_AI_NETWORK_MODE=block", "--dns=0.0.0.0"]
        else:
            cmd += ["-e", "LOCAL_AI_NETWORK_MODE=direct"]

    if cpu_limit:
        cmd += [f"--cpus={cpu_limit}"]
    if memory_limit:
        cmd += [f"--memory={memory_limit}"]

    cmd += app_server_tail(image)
    if extra_args:
        cmd += list(extra_args)
    return cmd


def _proxy_args(mode=None) -> List[str]:
    """``-e`` pairs routing a container through the canonical selected proxy."""
    try:
        from launcher import network_policy
        selected = network_policy.current_mode() if mode is None else network_policy.normalize_mode(mode)
        proxy_env = network_policy.container_proxy_env(selected)
    except Exception:
        proxy_env = {
            "LOCAL_AI_NETWORK_MODE": "warp",
            "HTTP_PROXY": "http://llm_httpbridge:8118",
            "HTTPS_PROXY": "http://llm_httpbridge:8118",
            "http_proxy": "http://llm_httpbridge:8118",
            "https_proxy": "http://llm_httpbridge:8118",
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
    """Compatibility Host proxy-env builder using the canonical selected mode.

    The historic function name remains because older callers still import it,
    but it no longer means "always Tor". On a real Host launch (``base`` is
    omitted), the selected WARP/Tor runtime is prepared before the environment
    is returned. If preparation fails, the selected proxy environment is still
    returned rather than silently downgrading to Direct; network clients that
    honor the managed environment therefore fail closed.
    """
    env = dict(base) if base is not None else dict(os.environ)
    try:
        from launcher import network_policy
        selected = network_policy.current_mode()
        if base is None and selected in (
            network_policy.NetworkMode.WARP,
            network_policy.NetworkMode.TOR,
        ):
            network_policy.prepare_runtime(selected)
        managed = network_policy.host_proxy_env(selected)
    except Exception:
        managed = {
            "LOCAL_AI_NETWORK_MODE": "tor",
            "HTTP_PROXY": "http://127.0.0.1:8118",
            "HTTPS_PROXY": "http://127.0.0.1:8118",
            "http_proxy": "http://127.0.0.1:8118",
            "https_proxy": "http://127.0.0.1:8118",
            "ALL_PROXY": "socks5h://127.0.0.1:9050",
            "all_proxy": "socks5h://127.0.0.1:9050",
            "NO_PROXY": "127.0.0.1,localhost,::1,host.docker.internal",
            "no_proxy": "127.0.0.1,localhost,::1,host.docker.internal",
        }
    env.update(managed)
    return env


__all__ = ["build_sandbox_docker_command", "build_tor_env"]
