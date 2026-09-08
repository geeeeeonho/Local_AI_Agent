import ast
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
    assert "build_sandbox_docker_command" in source
    assert "build_host_pipe_cmd" not in source


def test_agent_chat_handles_structured_host_controls():
    source = _source("launcher/actions/agent_chat.py")
    assert "AgentEventType.APPROVAL_REQUIRED" in source
    assert "service.approve" in source
    assert "service.cancel" in source
    assert "service.resume" in source
    assert '"/session"' in source
    assert '"/resume"' in source


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


def test_legacy_network_picker_commits_block_to_canonical_policy(monkeypatch):
    from launcher import network_policy
    from launcher.actions import agent_chat

    selected = []
    monkeypatch.setattr(
        network_policy,
        "set_mode",
        lambda mode: selected.append(network_policy.normalize_mode(mode).value)
        or network_policy.normalize_mode(mode),
    )

    class Presenter:
        def show_menu(self, **kwargs):
            return "block"

    assert agent_chat._select_internet_mode(Presenter()) is False
    assert selected == ["block"]


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


def test_host_network_label_reflects_the_actual_proxy_decision():
    from launcher.actions.agent_chat import _net_mode_label

    marker = ["managed-open-interpreter", "--model", "ollama/qwen3:8b"]
    assert _net_mode_label(marker, is_host=True, tor_proxy=False) == "개방 (직접 연결)"
    assert _net_mode_label(marker, is_host=True, tor_proxy=True) != "개방 (직접 연결)"

    blocked = ["docker", "run", "--dns=0.0.0.0", "image"]
    assert _net_mode_label(blocked) == "차단 (인터넷 없음)"
