from __future__ import annotations

from pathlib import Path

from .native_backend import (
    NativeOpenInterpreterBackend as OpenInterpreterBackend,
    NativeSandboxOpenInterpreterBackend as SandboxOpenInterpreterBackend,
)


def create_backend(mode: str, env: Path):
    """Return the managed Open Interpreter backend for the selected boundary.

    Runtime availability is checked by the backend itself. We intentionally do
    not fall back to the retired custom agent loop because changing runtimes
    silently also changes tool, approval, session, and security semantics.
    """
    if mode == "sandbox":
        return SandboxOpenInterpreterBackend()
    if mode == "host":
        return OpenInterpreterBackend()
    raise ValueError(f"unsupported agent mode: {mode}")
