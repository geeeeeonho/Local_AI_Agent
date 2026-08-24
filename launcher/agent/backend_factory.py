from __future__ import annotations

from pathlib import Path

from .interpreter_backend import OpenInterpreterBackend, managed_interpreter_exe
from .legacy_backend import LegacyBackend
from .sandbox_backend import SandboxOpenInterpreterBackend, sandbox_image_supports_app_server


def create_backend(mode: str, env: Path):
    """Select managed structured runtimes only when their pinned assets exist."""
    if mode == "sandbox":
        if sandbox_image_supports_app_server():
            return SandboxOpenInterpreterBackend()
        return LegacyBackend()

    if mode == "host":
        env_path = Path(env)
        project_root = env_path.parent if env_path.name == "llm_environment" else None
        if managed_interpreter_exe(project_root).is_file():
            return OpenInterpreterBackend()

    return LegacyBackend()
