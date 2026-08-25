from pathlib import Path
from types import SimpleNamespace

from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEventType
from launcher.agent.legacy_backend import LegacyBackend


class FakeUnifiedAgent:
    def __init__(self):
        self.running = False
        self.starts = []
        self.inputs = []
        self.stops = []
        self._proc = SimpleNamespace(pid=4321)
        self.messages = []

    def start(self, cmd, env=None, cwd=None):
        self.starts.append((cmd, env, cwd))
        self.running = True
        return True

    def send_input(self, message):
        self.inputs.append(message)
        return self.running

    def stop(self, timeout=3.0):
        self.stops.append(timeout)
        self.running = False

    def drain_messages(self, max_n=200):
        return list(self.messages[:max_n])

    def is_running(self):
        return self.running


def _config(mode="sandbox"):
    return AgentConfig(
        workspace=Path("workspace"),
        mode=mode,
        model="model:tag",
        network_mode="block",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(
            command=("docker", "run", "--rm"),
            env={"X": "1"},
            cwd=Path("cwd"),
        ),
    )


def test_legacy_backend_preserves_runtime_arguments_and_delegation():
    agent = FakeUnifiedAgent()
    backend = LegacyBackend(agent_factory=lambda: agent)

    assert backend.start(_config()) is True
    assert agent.starts == [(["docker", "run", "--rm"], {"X": "1"}, Path("cwd"))]
    assert backend.send("hello") is True
    assert agent.inputs == ["hello"]
    assert backend.is_running() is True
    backend.stop(timeout=2.0)
    backend.stop(timeout=2.0)
    assert agent.stops == [2.0, 2.0]


def test_legacy_backend_converts_messages():
    agent = FakeUnifiedAgent()
    agent.messages = [
        SimpleNamespace(level="stdout", text="answer"),
        SimpleNamespace(level="terminated", text="done"),
    ]
    backend = LegacyBackend(agent_factory=lambda: agent)
    events = backend.poll_events(10)
    assert [e.type for e in events] == [AgentEventType.TEXT, AgentEventType.TERMINATED]
    assert [e.content for e in events] == ["answer", "done"]


def test_host_cleanup_callback_is_registered_by_adapter(monkeypatch):
    agent = FakeUnifiedAgent()
    callbacks = []

    import launcher.core.lifelog as lifelog
    monkeypatch.setattr(lifelog, "register_host_process_cleanup", callbacks.append)

    backend = LegacyBackend(agent_factory=lambda: agent)
    assert backend.start(_config(mode="host")) is True
    assert len(callbacks) == 1
    assert callbacks[0]() == 4321


def test_legacy_backend_fails_closed_for_structured_only_operations():
    backend = LegacyBackend(agent_factory=FakeUnifiedAgent)
    assert backend.approve(1, "accept") is False
    assert backend.cancel() is False
    assert backend.resume("thread-1") is False
    assert backend.session_id() is None


def test_legacy_backend_requires_runtime_spec():
    backend = LegacyBackend(agent_factory=FakeUnifiedAgent)
    config = AgentConfig(
        workspace=Path("workspace"),
        mode="host",
        model="model:tag",
        network_mode="direct",
        profile_name="coding",
    )
    assert backend.start(config) is False
