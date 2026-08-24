from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .backend import AgentConfig
from .interpreter_backend import OI_VERSION, OpenInterpreterBackend

SANDBOX_RUNTIME_LABEL = "local-ai-agent.runtime"
SANDBOX_RUNTIME_VALUE = "app-server"
SANDBOX_OI_LABEL = "local-ai-agent.open-interpreter-version"

_LEGACY_ENV_KEYS = {
    "AGENT_REPL_SRC",
    "AGENT_MODEL_LADDER",
    "LITELLM_LOG",
}
_OVERRIDE_ENV = {
    "INTERPRETER_HOME": "/home/agent/.agent_state/open_interpreter",
    "CODEX_OSS_BASE_URL": "http://host.docker.internal:11434/v1",
    "NO_PROXY": "host.docker.internal,localhost,127.0.0.1,::1,llm_searxng",
    "no_proxy": "host.docker.internal,localhost,127.0.0.1,::1,llm_searxng",
    "SEARXNG_URL": "http://llm_searxng:8080",
    "PYTHONPATH": "/home/agent/.agent_state",
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


def transform_legacy_sandbox_command(command: tuple[str, ...] | list[str]) -> list[str]:
    """Reuse the legacy Docker policy while replacing only its runtime tail."""
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
    override_keys = set(_OVERRIDE_ENV)
    while i < image_index:
        token = source[i]
        if token == "-e" and i + 1 < image_index:
            value = source[i + 1]
            key = _env_key(value)
            if key in _LEGACY_ENV_KEYS or key in override_keys:
                i += 2
                continue
            prefix.extend([token, value])
            i += 2
            continue
        prefix.append(token)
        i += 1

    for key, value in _OVERRIDE_ENV.items():
        prefix.extend(["-e", f"{key}={value}"])

    return prefix + [
        image,
        "interpreter",
        "-c", "check_for_update_on_startup=false",
        "-c", 'web_search="disabled"',
        "app-server", "--listen", "stdio://",
    ]


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

    def _runtime_available(self, config: AgentConfig) -> bool:
        return config.legacy_runtime is not None and sandbox_image_supports_app_server()

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        runtime = config.legacy_runtime
        if runtime is None:
            raise ValueError("Sandbox backend requires legacy Docker policy command")
        command = transform_legacy_sandbox_command(runtime.command)
        self._container_name = _container_name(command)
        return command, dict(os.environ), config.workspace.resolve()

    def _thread_sandbox_mode(self, config: AgentConfig) -> str:
        # Docker is the mandatory outer sandbox. Do not weaken Docker to nest
        # Open Interpreter's Linux sandbox inside it.
        return "danger-full-access"

    def _thread_cwd(self, config: AgentConfig) -> str:
        return "/home/agent/workspace"

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
