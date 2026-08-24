from types import SimpleNamespace

from launcher.agent.events import AgentEventType, from_legacy_message


def _msg(level: str, text: str = "payload"):
    return SimpleNamespace(level=level, text=text)


def test_maps_current_legacy_levels():
    cases = {
        "stdout": AgentEventType.TEXT,
        "stderr": AgentEventType.ERROR,
        "info": AgentEventType.STATUS,
        "warn": AgentEventType.WARNING,
        "error": AgentEventType.ERROR,
        "terminated": AgentEventType.TERMINATED,
    }
    for level, expected in cases.items():
        event = from_legacy_message(_msg(level))
        assert event.type is expected
        assert event.content == "payload"
        assert event.source_level == level


def test_unknown_legacy_level_becomes_status_without_losing_level_or_text():
    event = from_legacy_message(_msg("custom-level", "keep me"))
    assert event.type is AgentEventType.STATUS
    assert event.content == "keep me"
    assert event.source_level == "custom-level"
