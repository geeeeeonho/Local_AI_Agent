from launcher.agent.events import AgentEvent, AgentEventType


def test_structured_event_keeps_request_and_metadata():
    event = AgentEvent(
        AgentEventType.APPROVAL_REQUIRED,
        "Run command?",
        source_level="approval",
        request_id=42,
        data={"kind": "command", "command": "git status"},
    )
    assert event.request_id == 42
    assert event.data == {"kind": "command", "command": "git status"}
    assert AgentEventType.TEXT_DELTA.value == "text_delta"
    assert AgentEventType.SESSION_STARTED.value == "session_started"


def test_structured_event_defaults_are_explicit():
    event = AgentEvent(AgentEventType.STATUS, "ready")
    assert event.content == "ready"
    assert event.source_level is None
    assert event.request_id is None
    assert event.data is None
