import json

from launcher.agent.backend import AgentConfig
from launcher.agent.interpreter_backend import OpenInterpreterBackend



def _trace_dir():
    """Where traces land for the account running this test.

    Traces are personal records, so they live under the account folder
    rather than at the runtime root that the machine shares.
    """
    import project_paths
    return project_paths.logs_dir()

class FakeClient:
    def __init__(self, command, env, cwd):
        self.running = False
        self.messages = []
        self.requests = []

    def start(self):
        self.running = True
        return True

    def request(self, method, params, timeout=10.0):
        self.requests.append((method, params))
        if method == "initialize":
            return {}
        if method == "thread/start":
            return {"thread": {"id": "thread-trace"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-trace"}}
        raise AssertionError(method)

    def notify(self, method, params=None):
        return True

    def respond(self, request_id, result):
        return True

    def drain_messages(self, max_n=200):
        out = self.messages[:max_n]
        del self.messages[:max_n]
        return out

    def stop(self, timeout=3.0):
        self.running = False

    def is_running(self):
        return self.running


def test_backend_traces_lifecycle_turn_and_completed_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    exe = tmp_path / "environment" / "open_interpreter" / "bin" / "interpreter.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")

    made = []

    def factory(command, env, cwd):
        client = FakeClient(command, env, cwd)
        made.append(client)
        return client

    workspace = tmp_path / "work"
    config = AgentConfig(
        workspace=workspace,
        mode="host",
        model="model:q4",
        network_mode="warp",
        profile_name="universal",
        instructions="trace test",
    )
    backend = OpenInterpreterBackend(client_factory=factory)
    assert backend.start(config)
    assert backend.send("find current info")

    made[0].messages.extend([
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "mcpToolCall",
                    "server": "local_search",
                    "tool": "search",
                    "arguments": {"query": "current info", "api_key": "never-log"},
                    "result": {"url": "https://example.com/result"},
                    "duration_ms": 45,
                }
            },
        },
        {"method": "turn/completed", "params": {"turn": {"id": "turn-trace"}}},
    ])
    backend.poll_events(20)
    backend.stop()

    paths = list(_trace_dir().glob("agent_trace_*.jsonl"))
    assert len(paths) == 1
    rows = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    names = [row["event"] for row in rows]

    assert "backend_starting" in names
    assert "session_started" in names
    assert "turn_started" in names
    assert "oi_notification" in names
    assert "mcp_tool_completed" in names
    assert "turn_completed" in names
    assert "backend_stopped" in names

    mcp = next(row for row in rows if row["event"] == "mcp_tool_completed")
    assert mcp["thread_id"] == "thread-trace"
    assert mcp["turn_id"] == "turn-trace"
    assert mcp["details"]["server"] == "local_search"
    assert mcp["details"]["tool"] == "search"
    assert mcp["details"]["arguments"]["api_key"] == "[REDACTED]"
    assert "never-log" not in paths[0].read_text(encoding="utf-8")


def test_streaming_deltas_are_counted_not_traced_per_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    exe = tmp_path / "environment" / "open_interpreter" / "bin" / "interpreter.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")

    made = []

    def factory(command, env, cwd):
        client = FakeClient(command, env, cwd)
        made.append(client)
        return client

    config = AgentConfig(
        workspace=tmp_path / "work",
        mode="host",
        model="model:q4",
        network_mode="warp",
        profile_name="universal",
        instructions="trace test",
    )
    backend = OpenInterpreterBackend(client_factory=factory)
    assert backend.start(config)
    assert backend.send("hello")

    made[0].messages.extend(
        [{"method": "item/agentMessage/delta", "params": {"delta": "tok"}} for _ in range(50)]
        + [{"method": "turn/completed", "params": {}}]
    )
    events = backend.poll_events(200)
    backend.stop()

    # Deltas still reach the UI.
    assert sum(1 for e in events if e.type.value == "text_delta") == 50

    path = next(_trace_dir().glob("agent_trace_*.jsonl"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    notifications = [r for r in rows if r["event"] == "oi_notification"]
    assert all(
        r["details"]["method"] != "item/agentMessage/delta" for r in notifications
    ), "per-token deltas must not each produce a trace row"

    summary = next(r for r in rows if r["event"] == "stream_summary")
    assert summary["details"]["item/agentMessage/delta"] == 50


def test_trace_omits_payload_rows_when_logging_disabled(tmp_path, monkeypatch):
    from launcher import settings_store

    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    assert settings_store.set_logging_enabled(False, tmp_path)

    exe = tmp_path / "environment" / "open_interpreter" / "bin" / "interpreter.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")

    made = []

    def factory(command, env, cwd):
        client = FakeClient(command, env, cwd)
        made.append(client)
        return client

    config = AgentConfig(
        workspace=tmp_path / "work",
        mode="host",
        model="model:q4",
        network_mode="warp",
        profile_name="universal",
        instructions="trace test",
    )
    backend = OpenInterpreterBackend(client_factory=factory)
    assert backend.start(config)
    assert backend.send("a very private prompt")
    made[0].messages.append({"method": "turn/completed", "params": {}})
    backend.poll_events(20)
    backend.stop()

    path = next(_trace_dir().glob("agent_trace_*.jsonl"))
    text = path.read_text(encoding="utf-8")
    assert "a very private prompt" not in text

    rows = [json.loads(line) for line in text.splitlines()]
    names = [row["event"] for row in rows]
    # Lifecycle stays diagnosable with logging off.
    assert "backend_starting" in names
    assert "session_started" in names
    assert "turn_started" in names
    assert next(r for r in rows if r["event"] == "turn_started")["detail_omitted"] is True
