from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (SRC_ROOT / relative).read_text(encoding="utf-8")


def test_agent_chat_uses_service_boundary_without_unified_agent_private_access():
    source = _source("launcher/actions/agent_chat.py")

    assert "AgentService" in source
    assert "create_backend" in source
    assert "LegacyBackend()" not in source
    assert "UnifiedAgent" not in source
    assert "agent._proc" not in source
    assert "build_sandbox_pipe_cmd" in source
    assert "build_host_pipe_cmd" in source


def test_agent_chat_handles_structured_host_controls():
    source = _source("launcher/actions/agent_chat.py")
    assert "AgentEventType.APPROVAL_REQUIRED" in source
    assert "service.approve" in source
    assert "service.cancel" in source
    assert "service.resume" in source
    assert '"/session"' in source
    assert '"/resume"' in source


def test_structured_sandbox_does_not_relax_outer_docker_security():
    source = _source("launcher/agent/sandbox_backend.py")
    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in source


def test_danger_full_access_is_confined_to_structured_sandbox_module():
    host_source = _source("launcher/agent/interpreter_backend.py")
    sandbox_source = _source("launcher/agent/sandbox_backend.py")
    assert 'return "workspace-write"' in host_source
    assert "danger-full-access" not in host_source
    assert 'return "danger-full-access"' in sandbox_source
