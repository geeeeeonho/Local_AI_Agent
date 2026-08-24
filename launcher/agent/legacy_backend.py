from __future__ import annotations

from collections.abc import Callable

from .backend import AgentConfig
from .events import AgentEvent, from_legacy_message


class LegacyBackend:
    def __init__(self, agent_factory: Callable[[], object] | None = None):
        if agent_factory is None:
            from .agent_runner import UnifiedAgent
            agent_factory = UnifiedAgent
        self._agent = agent_factory()
        self._host_cleanup_registered = False

    def start(self, config: AgentConfig) -> bool:
        runtime = config.legacy_runtime
        if runtime is None:
            return False
        started = self._agent.start(
            list(runtime.command),
            env=runtime.env,
            cwd=runtime.cwd,
        )
        if started and config.mode == "host" and not self._host_cleanup_registered:
            self._register_host_cleanup()
        return started

    def _register_host_cleanup(self) -> None:
        from launcher.core import lifelog

        def _get_pid():
            try:
                proc = getattr(self._agent, "_proc", None)
                return proc.pid if proc else None
            except Exception:
                return None

        lifelog.register_host_process_cleanup(_get_pid)
        self._host_cleanup_registered = True

    def send(self, message: str) -> bool:
        return self._agent.send_input(message)

    def approve(self, request_id: int | str, decision: str) -> bool:
        return False

    def cancel(self) -> bool:
        return False

    def resume(self, session_id: str) -> bool:
        return False

    def session_id(self) -> str | None:
        return None

    def stop(self, timeout: float = 3.0) -> None:
        self._agent.stop(timeout=timeout)

    def poll_events(self, max_n: int = 200) -> list[AgentEvent]:
        return [from_legacy_message(msg) for msg in self._agent.drain_messages(max_n=max_n)]

    def is_running(self) -> bool:
        return self._agent.is_running()
