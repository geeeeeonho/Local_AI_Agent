from launcher.agent.events import AgentEvent, AgentEventType
from launcher.agent.local_search_eval import analyze_trace, collect_turn


def _mcp_event(kind, tool, arguments=None, *, status="completed", result=None, error=None, duration_ms=None):
    item = {
        "type": "mcpToolCall",
        "server": "local_search",
        "tool": tool,
        "arguments": arguments or {},
        "status": status,
    }
    if result is not None:
        item["result"] = result
    if error is not None:
        item["error"] = error
    if duration_ms is not None:
        item["duration_ms"] = duration_ms
    return AgentEvent(kind, tool, "system", data={"item": item})


def test_analyze_trace_scores_search_then_fetch_as_grounded_tool_flow():
    events = [
        _mcp_event(
            AgentEventType.TOOL_COMPLETED,
            "search",
            {"query": "Open Interpreter 0.0.38 MCP", "limit": 5},
            result={"content": [{"type": "text", "text": '[{"title":"OI","url":"https://example.com/oi","snippet":"MCP"}]'}]},
            duration_ms=120,
        ),
        _mcp_event(
            AgentEventType.TOOL_COMPLETED,
            "fetch_page",
            {"url": "https://example.com/oi"},
            result={"content": [{"type": "text", "text": '{"url":"https://example.com/oi","text":"Open Interpreter supports MCP."}'}]},
            duration_ms=80,
        ),
        AgentEvent(AgentEventType.TEXT_DELTA, "According to https://example.com/oi, MCP is supported."),
        AgentEvent(AgentEventType.STATUS, "Turn completed", data={"status": "completed"}),
    ]

    report = analyze_trace(events)

    assert report["search_calls"] == 1
    assert report["fetch_calls"] == 1
    assert report["failed_tool_calls"] == 0
    assert report["repeated_identical_calls"] == 0
    assert report["tool_sequence"] == ["local_search.search", "local_search.fetch_page"]
    assert report["source_urls"] == ["https://example.com/oi"]
    assert report["turn_completed"] is True
    assert report["observable_agent_score"] == 100


def test_analyze_trace_penalizes_repeated_failed_search_calls():
    failed = _mcp_event(
        AgentEventType.TOOL_COMPLETED,
        "search",
        {"query": "latest AI news", "limit": 5},
        status="failed",
        error={"message": "SearXNG unavailable"},
    )
    report = analyze_trace([failed, failed])

    assert report["search_calls"] == 2
    assert report["failed_tool_calls"] == 2
    assert report["repeated_identical_calls"] == 1
    assert report["observable_agent_score"] < 50


def test_analyze_trace_keeps_reasoning_summary_separate_from_hidden_reasoning():
    events = [
        AgentEvent(AgentEventType.REASONING, "Need current information; search first."),
        AgentEvent(AgentEventType.TEXT_DELTA, "Final answer"),
    ]
    report = analyze_trace(events)

    assert report["reasoning_summaries"] == ["Need current information; search first."]
    assert report["final_text"] == "Final answer"


def test_collect_turn_returns_real_service_events_until_turn_completed():
    class FakeService:
        def __init__(self):
            self.sent = []
            self.polls = 0

        def send(self, message):
            self.sent.append(message)
            return True

        def poll_events(self, max_n=200):
            self.polls += 1
            if self.polls == 1:
                return [_mcp_event(AgentEventType.TOOL_COMPLETED, "search", {"query": "fresh fact"})]
            return [
                AgentEvent(AgentEventType.TEXT_DELTA, "done"),
                AgentEvent(AgentEventType.STATUS, "Turn completed"),
            ]

    ticks = iter([0.0, 0.1, 0.2, 0.3])
    service = FakeService()
    events = collect_turn(
        service,
        "find a fresh fact",
        timeout_s=2.0,
        poll_interval_s=0.0,
        time_fn=lambda: next(ticks),
        sleep_fn=lambda _: None,
    )

    assert service.sent == ["find a fresh fact"]
    assert [event.type for event in events] == [
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.TEXT_DELTA,
        AgentEventType.STATUS,
    ]


def test_collect_turn_raises_when_turn_cannot_start():
    class FakeService:
        def send(self, message):
            return False

    try:
        collect_turn(FakeService(), "search", timeout_s=1)
    except RuntimeError as exc:
        assert "turn" in str(exc).lower()
    else:
        raise AssertionError("collect_turn should reject a failed turn start")
