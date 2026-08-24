import json

from launcher.agent.backend import AgentConfig
from launcher.agent.interpreter_backend import OpenInterpreterBackend


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
    exe = tmp_path / "llm_environment" / "open_interpreter" / "bin" / "interpreter.exe"
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

    paths = list((tmp_path / "user_data" / "logs").glob("agent_trace_*.jsonl"))
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
