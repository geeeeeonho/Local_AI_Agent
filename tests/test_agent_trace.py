import json

from launcher.agent.agent_trace import AgentTrace, redact


def test_redact_masks_nested_secrets_and_sensitive_text():
    payload = {
        "token": "top-secret-token",
        "nested": {
            "password": "hunter2",
            "Authorization": "Bearer abcdefghijklmnop",
            "cookie": "session=private-cookie",
            "safe": "keep-me",
        },
        "text": "api_key=sk-test-secret password=my-pass Bearer bearer-secret",
    }

    cleaned = redact(payload)
    rendered = json.dumps(cleaned, ensure_ascii=False)

    assert "top-secret-token" not in rendered
    assert "hunter2" not in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "private-cookie" not in rendered
    assert "sk-test-secret" not in rendered
    assert "my-pass" not in rendered
    assert "bearer-secret" not in rendered
    assert "keep-me" in rendered
    assert "[REDACTED]" in rendered


def test_agent_trace_writes_flush_safe_jsonl_under_user_data_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    trace = AgentTrace(
        mode="sandbox",
        model="model:q4",
        network_mode="WARP",
        profile_name="coding",
        workspace=tmp_path / "workspace",
    )

    trace.record(
        "mcp_tool_completed",
        thread_id="thread-1",
        turn_id="turn-1",
        details={
            "server": "local_search",
            "tool": "search",
            "arguments": {"query": "Open Interpreter", "token": "do-not-log"},
            "duration_ms": 321,
        },
    )

    paths = list((tmp_path / "user_data" / "logs").glob("agent_trace_*.jsonl"))
    assert len(paths) == 1
    line = paths[0].read_text(encoding="utf-8").strip()
    row = json.loads(line)

    assert row["event"] == "mcp_tool_completed"
    assert row["mode"] == "sandbox"
    assert row["model"] == "model:q4"
    assert row["thread_id"] == "thread-1"
    assert row["turn_id"] == "turn-1"
    assert row["details"]["server"] == "local_search"
    assert row["details"]["tool"] == "search"
    assert row["details"]["duration_ms"] == 321
    assert row["details"]["arguments"]["query"] == "Open Interpreter"
    assert row["details"]["arguments"]["token"] == "[REDACTED]"
    assert "do-not-log" not in line
