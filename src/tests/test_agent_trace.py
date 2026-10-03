import json

from launcher.agent.agent_trace import AgentTrace, redact


def _trace_dir():
    """Where traces land for the account running this test.

    Traces are personal records, so they live under the account folder
    rather than at the runtime root that the machine shares.
    """
    import project_paths
    return project_paths.logs_dir()


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


def test_agent_trace_writes_flush_safe_jsonl_under_account_logs(tmp_path, monkeypatch):
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

    paths = list(_trace_dir().glob("agent_trace_*.jsonl"))
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


def test_detailed_rows_are_omitted_when_user_turns_logging_off(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    trace = AgentTrace(
        mode="host",
        model="model:q4",
        network_mode="direct",
        profile_name="universal",
        workspace=tmp_path / "workspace",
        detailed=False,
    )

    trace.record("session_started", details={"session_id": "t-1", "resumed": False})
    trace.record("turn_started", details={"input": "my private prompt"}, detailed=True)
    trace.close()

    text = trace.path.read_text(encoding="utf-8")
    assert "my private prompt" not in text

    rows = [json.loads(line) for line in text.splitlines()]
    lifecycle = next(row for row in rows if row["event"] == "session_started")
    assert lifecycle["details"]["session_id"] == "t-1"
    assert "detail_omitted" not in lifecycle

    turn = next(row for row in rows if row["event"] == "turn_started")
    assert turn["detail_omitted"] is True
    assert turn["details"] == "[OMITTED: detailed logging disabled]"


def test_detailed_rows_are_kept_when_logging_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    trace = AgentTrace(
        mode="host",
        model="model:q4",
        network_mode="direct",
        profile_name="universal",
        workspace=tmp_path / "workspace",
        detailed=True,
    )
    trace.record("turn_started", details={"input": "keep this"}, detailed=True)
    trace.close()

    row = json.loads(trace.path.read_text(encoding="utf-8").strip())
    assert row["details"]["input"] == "keep this"
    assert "detail_omitted" not in row


def test_trace_detail_flag_follows_the_user_setting(tmp_path, monkeypatch):
    from launcher import settings_store
    from launcher.agent.agent_trace import detailed_logging_enabled

    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    # The settings screen writes the account's canonical settings file; the
    # trace has to read that same file, not a root-relative copy of it.
    assert detailed_logging_enabled() is True

    assert settings_store.set_logging_enabled(False)
    assert detailed_logging_enabled() is False

    trace = AgentTrace(
        mode="host",
        model="m",
        network_mode="direct",
        profile_name="universal",
        workspace=tmp_path,
    )
    assert trace.detailed is False
    trace.close()


def test_old_trace_files_are_pruned(tmp_path, monkeypatch):
    import launcher.agent.agent_trace as module

    monkeypatch.setenv("LLM_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_KEEP_TRACE_FILES", 3)
    logs = _trace_dir()
    logs.mkdir(parents=True)
    for i in range(6):
        (logs / f"agent_trace_old_{i}.jsonl").write_text("{}\n", encoding="utf-8")

    trace = AgentTrace(
        mode="host",
        model="m",
        network_mode="direct",
        profile_name="universal",
        workspace=tmp_path,
        detailed=True,
    )
    trace.record("backend_starting")
    trace.close()

    remaining = list(logs.glob("agent_trace_*.jsonl"))
    assert len(remaining) == 4  # 3 kept + the new one
    assert trace.path in remaining
