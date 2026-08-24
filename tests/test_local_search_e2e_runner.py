from tools.evaluate_local_search_e2e import CASES, build_agent_config, serialize_event
from launcher.agent.events import AgentEvent, AgentEventType


def test_cases_cover_required_search_deep_fetch_and_no_search_control():
    by_name = {case["name"]: case for case in CASES}
    assert by_name["current_python_version"]["expect_search"] is True
    assert by_name["oi_search_architecture"]["min_fetch"] >= 2
    assert by_name["oi_search_architecture"]["min_sources"] >= 2
    assert by_name["arithmetic_control"]["expect_search"] is False


def test_build_agent_config_uses_requested_quantized_model_and_profile(tmp_path):
    cfg = build_agent_config(
        workspace=tmp_path,
        mode="sandbox",
        model="example:Q4_K_S",
        network_mode="warp",
    )
    assert cfg.workspace == tmp_path
    assert cfg.mode == "sandbox"
    assert cfg.model == "example:Q4_K_S"
    assert cfg.network_mode == "warp"
    assert cfg.profile_name == "universal"
    assert "Open Interpreter" in cfg.instructions


def test_serialize_event_preserves_observable_mcp_payload_only():
    event = AgentEvent(
        AgentEventType.TOOL_COMPLETED,
        "search",
        "system",
        data={"item": {"type": "mcpToolCall", "server": "local_search", "tool": "search"}},
    )
    payload = serialize_event(event)
    assert payload["type"] == "tool_completed"
    assert payload["content"] == "search"
    assert payload["data"]["item"]["server"] == "local_search"
