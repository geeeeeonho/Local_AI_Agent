import ast
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (SRC_ROOT / relative).read_text(encoding="utf-8")


def test_agent_chat_uses_service_boundary_without_unified_agent_private_access():
    action = _source("launcher/actions/agent_chat.py")
    runtime = _source("launcher/agent/runtime_config.py")
    coordinator = _source("launcher/agent/runtime_coordinator.py")

    assert "launcher.agent.setup_flow" in action
    assert "launcher.agent.runtime_config" in action
    assert "launcher.agent.runtime_coordinator" in action
    assert "launcher.agent.chat_session_controller" in action
    assert "AgentService(" not in action
    assert "create_backend(" not in action
    assert "AgentConfig(" not in action
    assert "ProcessRuntimeSpec(" not in action
    assert "AgentService(" in coordinator
    assert "create_backend(" in coordinator
    assert "AgentConfig(" in coordinator
    assert "ProcessRuntimeSpec(" in coordinator
    assert "LegacyBackend()" not in action
    assert "UnifiedAgent" not in action
    assert "agent._proc" not in action
    assert "build_sandbox_docker_command" not in action
    assert "build_sandbox_docker_command" in runtime
    assert "build_host_pipe_cmd" not in action


def test_structured_host_controls_belong_to_session_controller():
    action = _source("launcher/actions/agent_chat.py")
    controller = _source("launcher/agent/chat_session_controller.py")

    assert "AgentEventType.APPROVAL_REQUIRED" not in action
    assert "AgentEventType.APPROVAL_REQUIRED" in controller
    assert "service.approve" in controller
    assert "service.cancel" in controller
    assert "service.resume" in controller
    assert '"/session"' in controller
    assert '"/resume"' in controller


def test_entry_dialog_commits_network_mode_for_host_and_sandbox():
    source = _source("launcher/agent/entry_dialog.py")
    assert "network_policy.set_mode(_nm)" in source
    assert 'selected["tor"] = _nm in ("warp", "tor")' in source
    tor_assignment = source.index('selected["tor"]')
    result_assignment = source.index('result["value"]', tor_assignment)
    assert 'mode_var.get() == "sandbox"' not in source[tor_assignment:result_assignment]
    assert '_radio(\n                sec3,\n                net_var,\n                "direct"' in source


def test_entry_dialog_refuses_unenforceable_host_block_mode():
    source = _source("launcher/agent/entry_dialog.py")
    assert 'mode_var.get() == "host" and _nm == "block"' in source
    assert "Host 차단 모드" in source


def test_structured_sandbox_does_not_relax_outer_docker_security():
    source = _source("launcher/agent/sandbox_backend.py")
    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in source


def test_open_interpreter_execution_policy_is_centralized():
    policy_source = _source("launcher/agent/execution_policy.py")
    host_source = _source("launcher/agent/interpreter_backend.py")
    sandbox_source = _source("launcher/agent/sandbox_backend.py")
    assert "sandbox_mode=None" in policy_source
    assert 'permission_profile="local-ai-host"' in policy_source
    assert 'sandbox_mode="danger-full-access"' in policy_source
    assert 'approval_policy="on-request"' in policy_source
    assert 'approvals_reviewer="user"' in policy_source
    assert '"workspace-write"' not in host_source
    assert '"on-request"' not in host_source
    assert '"danger-full-access"' not in sandbox_source


def _source_files():
    for path in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_module_ships_an_embedded_agent_payload():
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert len(node.value) < 8000, (
                    f"{path}:{node.lineno} embeds a {len(node.value)}-char literal"
                )


def test_agent_runtime_never_executes_a_decoded_source_payload():
    paths = list((SRC_ROOT / "launcher" / "agent").rglob("*.py"))
    paths.append(SRC_ROOT / "launcher" / "actions" / "agent_chat.py")
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "b64decode" not in text, path
        assert "exec(" not in text, path


def test_sandbox_still_filters_retired_runtime_env_keys():
    from launcher.agent.sandbox_backend import _LEGACY_ENV_KEYS

    assert "AGENT_REPL_SRC" in _LEGACY_ENV_KEYS


def test_start_failure_diagnostics_never_run_the_agent_command():
    source = _source("launcher/actions/agent_chat.py")
    assert "START_DIAG2_v1" not in source
    assert "_spC.run(cmd" not in source
    assert "subprocess.run(cmd" not in source


def test_pretool_subsystem_is_fully_removed_from_the_agent_path():
    source = _source("launcher/actions/agent_chat.py")
    assert "PreTool" not in source


def test_network_labels_come_from_canonical_runtime_config():
    from launcher import network_policy
    from launcher.agent import runtime_config

    for mode in ("direct", "warp", "tor", "block"):
        assert runtime_config.network_label(mode) == network_policy.display_label(mode)
