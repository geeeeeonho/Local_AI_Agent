from pathlib import Path

from launcher.agent.backend import AgentConfig, ProcessRuntimeSpec
from launcher.agent.events import AgentEvent, AgentEventType
from launcher.agent.service import AgentService


class FakeBackend:
    def __init__(self):
        self.running = False
        self.started = []
        self.sent = []
        self.stops = []
        self.poll_limits = []
        self.approvals = []
        self.cancels = 0
        self.resumes = []
        self.session = None
        self.events = [AgentEvent(AgentEventType.STATUS, "ready", "info")]

    def start(self, config):
        if self.running:
            return False
        self.started.append(config)
        self.running = True
        self.session = "thread-1"
        return True

    def send(self, message):
        self.sent.append(message)
        return self.running

    def approve(self, request_id, decision):
        self.approvals.append((request_id, decision))
        return True

    def cancel(self):
        self.cancels += 1
        return self.running

    def resume(self, session_id):
        self.resumes.append(session_id)
        self.session = session_id
        return True

    def session_id(self):
        return self.session

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
        runtime_spec=ProcessRuntimeSpec(command=("python", "-V")),
        instructions="Follow project rules.",
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
    assert service.session_id() == "thread-1"
    assert service.approve(7, "accept") is True
    assert backend.approvals == [(7, "accept")]
    assert service.cancel() is True
    assert backend.cancels == 1
    assert service.resume("thread-old") is True
    assert backend.resumes == ["thread-old"]
    assert service.session_id() == "thread-old"
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


def test_config_can_describe_non_legacy_backend_without_fake_command():
    config = AgentConfig(
        workspace=Path("workspace"),
        mode="host",
        model="qwen3:8b",
        network_mode="direct",
        profile_name="coding",
        instructions="Use only the selected workspace.",
    )
    assert config.runtime_spec is None
    assert config.instructions == "Use only the selected workspace."
