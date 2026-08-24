from launcher.agent import profiles
from launcher.agent.instructions import build_structured_instructions


def test_host_structured_instructions_keep_privacy_without_docker_claim():
    text = build_structured_instructions("You are a coding agent.", sandbox=False)
    assert text.startswith("You are a coding agent.")
    assert "개인정보 보호" in text
    assert "API 키" in text
    assert "외부 서비스" in text
    assert "Docker sandbox" not in text
    assert "PreTool" not in text


def test_sandbox_structured_instructions_use_native_oi_and_mcp_search_guidance():
    text = build_structured_instructions("You are a coding agent.", sandbox=True)
    assert "개인정보 보호" in text
    assert "Local_AI_Agent Docker sandbox" in text
    assert "Do not attempt to escape the container" in text
    assert "Open Interpreter built-in web search is disabled" in text
    assert "local_search" in text
    assert "MCP" in text
    assert "SearXNG" in text
    assert "private local content" in text
    assert "PreTool" not in text


def test_active_profiles_do_not_reference_pretool():
    assert profiles.PROFILES
    assert all("PreTool" not in profile.system_message for profile in profiles.PROFILES)
