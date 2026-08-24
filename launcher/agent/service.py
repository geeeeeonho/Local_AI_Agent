from __future__ import annotations

from .backend import AgentBackend, AgentConfig
from .events import AgentEvent


class AgentService:
    def __init__(self, backend: AgentBackend):
        self._backend = backend
        self._current_config: AgentConfig | None = None

    @property
    def current_config(self) -> AgentConfig | None:
        return self._current_config

    def start(self, config: AgentConfig) -> bool:
        if self._backend.is_running():
            return False
        started = self._backend.start(config)
        if started:
            self._current_config = config
        return started

    def send(self, message: str) -> bool:
        return self._backend.send(message)

    def stop(self, timeout: float = 3.0) -> None:
        self._backend.stop(timeout=timeout)

    def poll_events(self, max_n: int = 200) -> list[AgentEvent]:
        return self._backend.poll_events(max_n=max_n)

    def is_running(self) -> bool:
        return self._backend.is_running()
