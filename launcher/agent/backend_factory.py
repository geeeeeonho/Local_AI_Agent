from __future__ import annotations

from pathlib import Path

from .interpreter_backend import OpenInterpreterBackend, managed_interpreter_exe
from .legacy_backend import LegacyBackend


def create_backend(mode: str, env: Path):
    """Select the Stage 2 backend without changing Sandbox behavior."""
    if mode == "host":
        env_path = Path(env)
        project_root = env_path.parent if env_path.name == "llm_environment" else None
        if managed_interpreter_exe(project_root).is_file():
            return OpenInterpreterBackend()
    return LegacyBackend()
