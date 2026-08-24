from pathlib import Path

from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEventType
from launcher.agent.interpreter_backend import OI_VERSION, OpenInterpreterBackend


class FakeClient:
    def __init__(self, command, env, cwd):
        self.command = command
        self.env = env
        self.cwd = cwd
        self.running = False
        self.requests = []
        self.notifications = []
        self.responses = []
        self.messages = []
        self._pid = 2222

    def start(self):
        self.running = True
        return True

    def request(self, method, params, timeout=10.0):
        self.requests.append((method, params))
        if method == "initialize":
            return {"userAgent": "Open Interpreter"}
        if method == "thread/start":
            return {"thread": {"id": "thread-new"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        if method == "turn/interrupt":
            return {}
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"]}}
        raise AssertionError(method)

    def notify(self, method, params=None):
        self.notifications.append((method, params))
        return True

    def respond(self, request_id, result):
        self.responses.append((request_id, result))
        return True

    def drain_messages(self, max_n=200):
        out = self.messages[:max_n]
        del self.messages[:max_n]
        return out

    def stop(self, timeout=3.0):
        self.running = False

    def is_running(self):
        return self.running

    def pid(self):
        return self._pid


def _config(tmp_path):
    return AgentConfig(
        workspace=tmp_path,
        mode="host",
        model="qwen3:8b",
        network_mode="direct",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(
            command=("legacy",), env={"HTTP_PROXY": "http://127.0.0.1:8118"}
        ),
        instructions="You are the coding profile.",
    )


def _backend(tmp_path, monkeypatch):
    exe = tmp_path / "llm_environment" / "open_interpreter" / "bin" / "interpreter.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    made = []

    def factory(command, env, cwd):
        client = FakeClient(command, env, cwd)
        made.append(client)
        return client

    return OpenInterpreterBackend(client_factory=factory), made


def test_version_is_pinned():
    assert OI_VERSION == "0.0.38"


def test_start_uses_managed_app_server_and_exact_thread_policy(tmp_path, monkeypatch):
    backend, made = _backend(tmp_path, monkeypatch)
    config = _config(tmp_path / "work")
    config.workspace.mkdir()

    assert backend.start(config) is True
    client = made[0]
    assert client.command[-2:] == ["--listen", "stdio://"]
    assert "app-server" in client.command
    assert "check_for_update_on_startup=false" in client.command
    assert 'web_search="disabled"' in client.command
    assert client.env["CODEX_OSS_BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert client.env["HTTP_PROXY"] == "http://127.0.0.1:8118"
    assert "127.0.0.1" in client.env["NO_PROXY"]
    assert client.requests[0] == (
        "initialize",
        {
            "clientInfo": {"name": "local_ai_agent", "title": "Local_AI_Agent", "version": "1"},
            "capabilities": {"experimentalApi": False},
        },
    )
    assert client.notifications == [("initialized", {})]
    method, params = client.requests[1]
    assert method == "thread/start"
    assert params == {
        "model": "qwen3:8b",
        "modelProvider": "ollama",
        "cwd": str(config.workspace.resolve()),
        "approvalPolicy": "on-request",
        "approvalsReviewer": "user",
        "sandbox": "workspace-write",
        "serviceName": "Local_AI_Agent",
        "developerInstructions": "You are the coding profile.",
    }
    assert backend.session_id() == "thread-new"


def test_send_cancel_approve_and_resume_use_structured_rpc(tmp_path, monkeypatch):
    backend, made = _backend(tmp_path, monkeypatch)
    config = _config(tmp_path / "work")
    config.workspace.mkdir()
    assert backend.start(config)
    client = made[0]

    assert backend.send("hello") is True
    assert client.requests[-1] == (
        "turn/start",
        {"threadId": "thread-new", "input": [{"type": "text", "text": "hello"}]},
    )
    assert backend.cancel() is True
    assert client.requests[-1] == (
        "turn/interrupt",
        {"threadId": "thread-new", "turnId": "turn-1"},
    )
    assert backend.approve(91, "accept") is True
    assert client.responses[-1] == (91, {"decision": "accept"})
    assert backend.approve(92, "always") is False
    assert backend.resume("thread-old") is True
    assert client.requests[-1][0] == "thread/resume"
    assert client.requests[-1][1]["threadId"] == "thread-old"
    assert backend.session_id() == "thread-old"


def test_notifications_map_to_agent_events(tmp_path, monkeypatch):
    backend, made = _backend(tmp_path, monkeypatch)
    config = _config(tmp_path / "work")
    config.workspace.mkdir()
    assert backend.start(config)
    backend.poll_events(10)  # discard STARTED + SESSION_STARTED for this focused mapping test
    client = made[0]
    client.messages.extend([
        {"method": "item/agentMessage/delta", "params": {"delta": "hi"}},
        {"method": "item/reasoning/summaryTextDelta", "params": {"delta": "thinking"}},
        {"method": "item/started", "params": {"item": {"type": "commandExecution", "command": "pwd"}}},
        {"method": "item/commandExecution/outputDelta", "params": {"delta": "out"}},
        {"method": "item/completed", "params": {"item": {"type": "fileChange", "changes": []}}},
        {"id": 44, "method": "item/commandExecution/requestApproval", "params": {"command": "rm x", "cwd": "/w", "reason": "requested"}},
        {"method": "local/stderr", "params": {"text": "warning"}},
        {"method": "local/protocolError", "params": {"text": "bad json"}},
        {"method": "local/terminated", "params": {"returncode": 1}},
    ])
    events = backend.poll_events(20)
    assert [event.type for event in events] == [
        AgentEventType.TEXT_DELTA,
        AgentEventType.REASONING,
        AgentEventType.TOOL_STARTED,
        AgentEventType.TOOL_PROGRESS,
        AgentEventType.FILE_CHANGED,
        AgentEventType.APPROVAL_REQUIRED,
        AgentEventType.WARNING,
        AgentEventType.ERROR,
        AgentEventType.TERMINATED,
    ]
    approval = events[5]
    assert approval.request_id == 44
    assert approval.data["kind"] == "command"


def test_restart_reregisters_active_lifecycle_without_duplicate_global_cleanup(tmp_path, monkeypatch):
    backend, _ = _backend(tmp_path, monkeypatch)
    config = _config(tmp_path / "work")
    config.workspace.mkdir()

    import launcher.agent.agent_lifecycle as lifecycle
    import launcher.core.lifelog as lifelog

    registered = []
    unregistered = []
    cleanups = []
    monkeypatch.setattr(lifecycle, "register", registered.append)
    monkeypatch.setattr(lifecycle, "unregister", unregistered.append)
    monkeypatch.setattr(lifelog, "register_cleanup", cleanups.append)

    assert backend.start(config) is True
    backend.stop()
    assert backend.start(config) is True

    assert registered == [backend, backend]
    assert unregistered == [backend]
    assert len(cleanups) == 1
