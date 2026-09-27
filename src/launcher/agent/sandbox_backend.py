from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from runtime_versions import (
    SANDBOX_OI_LABEL,
    SANDBOX_RUNTIME_LABEL,
    SANDBOX_RUNTIME_VALUE,
)

from .backend import AgentConfig
from .events import AgentEvent, AgentEventType
from .interpreter_backend import OI_VERSION, OpenInterpreterBackend

#: Used only when launcher.config cannot be imported at all.
SANDBOX_SEARXNG_URL_FALLBACK = "http://llm_searxng:8080"

#: Environment keys from the retired custom agent loop. Nothing produces them
#: any more; they are still filtered so a stale or hand-built command cannot
#: smuggle that payload — and its conflicting system prompt — into the runtime.
_RETIRED_ENV_KEYS = {
    "AGENT_REPL_SRC",
    "AGENT_MODEL_LADDER",
    "LITELLM_LOG",
}


def _override_env() -> dict[str, str]:
    """Environment the container runtime must use, whatever the caller passed.

    The Ollama port follows configuration: hardcoding 11434 silently broke every
    sandbox session for users who moved the service.
    """
    try:
        from launcher import config
        ollama_port = int(getattr(config, "OLLAMA_PORT", 11434))
        searxng_url = str(config.SEARXNG_INTERNAL_URL)
        state_dir = str(config.AGENT_STATE_DIR)
    except Exception:
        ollama_port = 11434
        searxng_url = SANDBOX_SEARXNG_URL_FALLBACK
        state_dir = "/home/agent/.agent_state"
    no_proxy = "host.docker.internal,localhost,127.0.0.1,::1,llm_searxng"
    return {
        "INTERPRETER_HOME": f"{state_dir}/open_interpreter",
        "CODEX_OSS_BASE_URL": f"http://host.docker.internal:{ollama_port}/v1",
        "NO_PROXY": no_proxy,
        "no_proxy": no_proxy,
        "SEARXNG_URL": searxng_url,
        "PYTHONPATH": state_dir,
    }


def _sandbox_image() -> str:
    from launcher import config
    return str(config.SANDBOX_IMAGE)


def sandbox_image_supports_app_server(image: str | None = None) -> bool:
    image_name = image or _sandbox_image()
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 12,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        result = subprocess.run(
            [
                "docker", "image", "inspect", image_name,
                "--format", "{{json .Config.Labels}}",
            ],
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        labels = json.loads((result.stdout or "").strip())
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(labels, dict):
        return False
    return (
        labels.get(SANDBOX_RUNTIME_LABEL) == SANDBOX_RUNTIME_VALUE
        and labels.get(SANDBOX_OI_LABEL) == OI_VERSION
    )


def _env_key(value: str) -> str:
    return str(value).split("=", 1)[0]


def app_server_tail(image: str | None = None) -> list[str]:
    """Canonical container runtime tail: image plus the App Server invocation.

    Both the command builder and :func:`normalize_sandbox_command` use
    this, so transforming an already-current command is a no-op.
    """
    return [
        image or _sandbox_image(),
        "interpreter",
        "-c", "check_for_update_on_startup=false",
        "-c", 'web_search="disabled"',
        "app-server", "--listen", "stdio://",
    ]


def normalize_sandbox_command(command: tuple[str, ...] | list[str]) -> list[str]:
    """Force any ``docker run`` command onto the current runtime contract.

    The caller's outer security policy — mounts, tmpfs masks, network flags,
    resource ceilings — is preserved exactly. Everything the runtime owns is
    replaced: environment keys from the retired agent loop are dropped, the
    runtime environment is re-applied, and the tail becomes the App Server
    invocation. Running this on an already-current command is a no-op.
    """
    source = [str(token) for token in command]
    if len(source) < 3 or source[0:2] != ["docker", "run"]:
        raise ValueError("structured sandbox requires a docker run command")

    image = _sandbox_image()
    try:
        image_index = source.index(image)
    except ValueError as exc:
        raise ValueError(f"sandbox image token not found: {image}") from exc

    prefix = source[:2]
    i = 2
    override_env = _override_env()
    override_keys = set(override_env)
    while i < image_index:
        token = source[i]
        if token == "-e" and i + 1 < image_index:
            value = source[i + 1]
            key = _env_key(value)
            if key in _RETIRED_ENV_KEYS or key in override_keys:
                i += 2
                continue
            prefix.extend([token, value])
            i += 2
            continue
        prefix.append(token)
        i += 1

    for key, value in override_env.items():
        prefix.extend(["-e", f"{key}={value}"])

    return prefix + app_server_tail(image)


def _container_name(command: list[str]) -> str | None:
    try:
        index = command.index("--name")
        return command[index + 1] if index + 1 < len(command) else None
    except ValueError:
        return None


class SandboxOpenInterpreterBackend(OpenInterpreterBackend):
    """Open Interpreter App Server inside Local_AI_Agent's Docker boundary."""

    def __init__(self, client_factory=None):
        if client_factory is None:
            super().__init__()
        else:
            super().__init__(client_factory=client_factory)
        self._container_name: str | None = None

    def start(self, config: AgentConfig) -> bool:
        """Start only after the hard Block network has been proven safe."""
        try:
            from launcher import network_policy
            selected = network_policy.normalize_mode(config.network_mode)
            if selected is network_policy.NetworkMode.BLOCK:
                if not network_policy.ensure_block_network():
                    self._emit(AgentEvent(
                        AgentEventType.ERROR,
                        "Block 네트워크를 안전하게 준비할 수 없어 샌드박스 시작을 중단했습니다.",
                        "error",
                    ))
                    return False
        except Exception as exc:
            # A Block request must never continue when policy resolution itself
            # fails. Non-Block modes retain the existing generic start path.
            if str(config.network_mode).strip().lower() == "block":
                self._emit(AgentEvent(
                    AgentEventType.ERROR,
                    f"Block 네트워크 정책 확인 실패: {type(exc).__name__}",
                    "error",
                ))
                return False
        return super().start(config)

    def _runtime_available(self, config: AgentConfig) -> bool:
        return config.runtime_spec is not None and sandbox_image_supports_app_server()

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        runtime = config.runtime_spec
        if runtime is None:
            raise ValueError("Sandbox backend requires a docker run command")
        command = normalize_sandbox_command(runtime.command)
        self._container_name = _container_name(command)
        return command, dict(os.environ), config.workspace.resolve()

    def _thread_cwd(self, config: AgentConfig) -> str:
        return "/home/agent/workspace"

    def _instruction_profile(self, config: AgentConfig) -> str:
        try:
            from launcher.agent.profiles import build_session_addendum
            addendum = build_session_addendum(config.workspace)
        except Exception:
            addendum = ""
        return config.instructions + addendum

    def _instruction_is_sandbox(self, config: AgentConfig) -> bool:
        return True

    def stop(self, timeout: float = 3.0) -> None:
        container_name = self._container_name
        super().stop(timeout=timeout)
        if not container_name:
            return
        kwargs = {"capture_output": True, "timeout": 7}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000
        try:
            subprocess.run(
                ["docker", "stop", "-t", "2", container_name],
                **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
