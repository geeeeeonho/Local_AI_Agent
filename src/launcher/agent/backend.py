from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .events import AgentEvent


@dataclass(frozen=True)
class ProcessRuntimeSpec:
    """How to launch the backend's runtime process.

    In sandbox mode this is the full ``docker run`` command including the outer
    security policy. In host mode the backend builds its own command and only
    ``env`` is consulted (for proxy settings).
    """
    command: tuple[str, ...]
    env: Mapping[str, str] | None = None
    cwd: Path | None = None


@dataclass(frozen=True)
class AgentConfig:
    workspace: Path
    mode: str
    model: str
    network_mode: str
    profile_name: str
    runtime_spec: ProcessRuntimeSpec | None = None
    instructions: str = ""


class AgentBackend(Protocol):
    def start(self, config: AgentConfig) -> bool: ...
    def send(self, message: str) -> bool: ...
    def approve(self, request_id: int | str, decision: str) -> bool: ...
    def cancel(self) -> bool: ...
    def resume(self, session_id: str) -> bool: ...
    def session_id(self) -> str | None: ...
    def stop(self, timeout: float = 3.0) -> None: ...
    def poll_events(self, max_n: int = 200) -> list[AgentEvent]: ...
    def is_running(self) -> bool: ...
