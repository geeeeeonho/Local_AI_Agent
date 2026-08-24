from pathlib import Path


def test_agent_chat_uses_service_boundary_without_unified_agent_private_access():
    source = Path("launcher/actions/agent_chat.py").read_text(encoding="utf-8")

    assert "AgentService" in source
    assert "create_backend" in source
    assert "LegacyBackend()" not in source
    assert "UnifiedAgent" not in source
    assert "agent._proc" not in source
    assert "build_sandbox_pipe_cmd" in source
    assert "build_host_pipe_cmd" in source


def test_agent_chat_handles_structured_host_controls():
    source = Path("launcher/actions/agent_chat.py").read_text(encoding="utf-8")
    assert "AgentEventType.APPROVAL_REQUIRED" in source
    assert "service.approve" in source
    assert "service.cancel" in source
    assert "service.resume" in source
    assert '"/session"' in source
    assert '"/resume"' in source


def test_structured_sandbox_does_not_relax_outer_docker_security():
    source = Path("launcher/agent/sandbox_backend.py").read_text(encoding="utf-8")
    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in source


def test_danger_full_access_is_confined_to_structured_sandbox_module():
    host_source = Path("launcher/agent/interpreter_backend.py").read_text(encoding="utf-8")
    sandbox_source = Path("launcher/agent/sandbox_backend.py").read_text(encoding="utf-8")
    assert 'return "workspace-write"' in host_source
    assert "danger-full-access" not in host_source
    assert 'return "danger-full-access"' in sandbox_source
