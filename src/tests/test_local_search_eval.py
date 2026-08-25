from launcher.agent.events import AgentEvent, AgentEventType
from launcher.agent.local_search_eval import analyze_trace, assess_case, collect_turn


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


def test_assess_case_accepts_required_search_and_fetch_with_sources():
    report = {
        "search_calls": 1,
        "fetch_calls": 2,
        "failed_tool_calls": 0,
        "repeated_identical_calls": 0,
        "source_urls": ["https://a.test", "https://b.test"],
        "turn_completed": True,
        "final_text": "answer",
    }
    result = assess_case(report, expect_search=True, min_fetch=1, min_sources=2)
    assert result["passed"] is True
    assert result["failures"] == []


def test_assess_case_rejects_unnecessary_search_for_control_prompt():
    report = {
        "search_calls": 1,
        "fetch_calls": 0,
        "failed_tool_calls": 0,
        "repeated_identical_calls": 0,
        "source_urls": ["https://example.test"],
        "turn_completed": True,
        "final_text": "4",
    }
    result = assess_case(report, expect_search=False)
    assert result["passed"] is False
    assert "unexpected_search" in result["failures"]


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


def test_analyze_trace_flags_a_url_the_answer_invented():
    events = [
        _mcp_event(
            AgentEventType.TOOL_COMPLETED,
            "search",
            {"query": "current release"},
            result={"content": [{"type": "text", "text": '[{"url":"https://real.test/a"}]'}]},
        ),
        AgentEvent(
            AgentEventType.TEXT_DELTA,
            "See https://real.test/a and https://invented.test/b for details.",
        ),
        AgentEvent(AgentEventType.STATUS, "Turn completed"),
    ]
    report = analyze_trace(events)

    assert report["cited_sources"] == ["https://real.test/a"]
    assert report["fabricated_source_urls"] == ["https://invented.test/b"]
    assert report["observable_agent_score"] < 100


def test_analyze_trace_flags_an_answer_that_cites_nothing_it_retrieved():
    events = [
        _mcp_event(
            AgentEventType.TOOL_COMPLETED,
            "search",
            {"query": "current release"},
            result={"content": [{"type": "text", "text": '[{"url":"https://real.test/a"}]'}]},
        ),
        AgentEvent(AgentEventType.TEXT_DELTA, "The current release is 9.9.9."),
        AgentEvent(AgentEventType.STATUS, "Turn completed"),
    ]
    report = analyze_trace(events)

    assert report["source_urls"] == ["https://real.test/a"]
    assert report["cited_sources"] == []
    assert report["observable_agent_score"] < 100


def test_assess_case_rejects_a_fabricated_citation():
    report = {
        "search_calls": 1,
        "fetch_calls": 1,
        "failed_tool_calls": 0,
        "repeated_identical_calls": 0,
        "source_urls": ["https://real.test/a"],
        "cited_sources": ["https://real.test/a"],
        "fabricated_source_urls": ["https://invented.test/b"],
        "turn_completed": True,
        "final_text": "answer",
    }
    result = assess_case(report, expect_search=True, min_fetch=1, min_sources=1)
    assert result["passed"] is False
    assert "fabricated_source" in result["failures"]


def test_assess_case_can_require_the_answer_to_cite_its_sources():
    report = {
        "search_calls": 1,
        "fetch_calls": 1,
        "failed_tool_calls": 0,
        "repeated_identical_calls": 0,
        "source_urls": ["https://real.test/a"],
        "cited_sources": [],
        "fabricated_source_urls": [],
        "turn_completed": True,
        "final_text": "The answer is 42.",
    }
    strict = assess_case(
        report, expect_search=True, min_fetch=1, min_sources=1, require_citation=True
    )
    assert strict["passed"] is False
    assert "missing_citation" in strict["failures"]

    lenient = assess_case(report, expect_search=True, min_fetch=1, min_sources=1)
    assert lenient["passed"] is True


def test_tool_usage_alone_no_longer_earns_a_perfect_score():
    """One search call plus an invented answer used to score 100."""
    events = [
        _mcp_event(
            AgentEventType.TOOL_COMPLETED,
            "search",
            {"query": "todays exchange rate"},
            result={"content": [{"type": "text", "text": '[{"url":"https://real.test/rate"}]'}]},
        ),
        AgentEvent(AgentEventType.TEXT_DELTA, "It is 1234.5 according to https://made-up.test/x."),
        AgentEvent(AgentEventType.STATUS, "Turn completed"),
    ]
    report = analyze_trace(events)
    assert report["observable_agent_score"] <= 60
