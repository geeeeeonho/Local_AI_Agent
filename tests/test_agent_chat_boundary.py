from pathlib import Path


def test_agent_chat_uses_service_boundary_without_unified_agent_private_access():
    source = Path("launcher/actions/agent_chat.py").read_text(encoding="utf-8")

    assert "AgentService" in source
    assert "LegacyBackend" in source
    assert "UnifiedAgent" not in source
    assert "agent._proc" not in source
    assert "build_sandbox_pipe_cmd" in source
    assert "build_host_pipe_cmd" in source
