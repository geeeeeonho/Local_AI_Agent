from pathlib import Path

from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEvent, AgentEventType
from launcher.agent.service import AgentService


class FakeBackend:
    def __init__(self):
        self.running = False
        self.started = []
        self.sent = []
        self.stops = []
        self.poll_limits = []
        self.events = [AgentEvent(AgentEventType.STATUS, "ready", "info")]

    def start(self, config):
        if self.running:
            return False
        self.started.append(config)
        self.running = True
        return True

    def send(self, message):
        self.sent.append(message)
        return self.running

    def stop(self, timeout=3.0):
        self.stops.append(timeout)
        self.running = False

    def poll_events(self, max_n=200):
        self.poll_limits.append(max_n)
        return list(self.events)

    def is_running(self):
        return self.running


def _config():
    return AgentConfig(
        workspace=Path("workspace"),
        mode="sandbox",
        model="model:tag",
        network_mode="block",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(command=("python", "-V")),
    )


def test_service_delegates_and_keeps_current_config():
    backend = FakeBackend()
    service = AgentService(backend)
    config = _config()

    assert service.start(config) is True
    assert backend.started == [config]
    assert service.current_config is config
    assert service.send("hello") is True
    assert backend.sent == ["hello"]
    assert service.poll_events(17) == backend.events
    assert backend.poll_limits == [17]
    assert service.is_running() is True
    service.stop(timeout=1.5)
    assert backend.stops == [1.5]
    assert service.is_running() is False


def test_service_rejects_second_start_while_running():
    backend = FakeBackend()
    service = AgentService(backend)
    first = _config()
    second = _config()

    assert service.start(first) is True
    assert service.start(second) is False
    assert backend.started == [first]
    assert service.current_config is first
