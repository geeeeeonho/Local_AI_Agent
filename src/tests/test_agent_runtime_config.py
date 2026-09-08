from pathlib import Path

import launcher.config as config


def test_runtime_config_builds_block_sandbox_from_canonical_mode(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_config

    monkeypatch.setattr(network_policy, "current_mode", lambda: network_policy.NetworkMode.BLOCK)
    command, is_host = runtime_config.build_cmd_for_mode(
        "sandbox",
        tmp_path / "env",
        None,
        tmp_path / "workspace",
        "llm_agent_test",
        "2g",
        "1",
        model_tag="qwen3:8b",
    )

    assert is_host is False
    assert command[command.index("--network") + 1] == network_policy.block_network_name()
    assert "LOCAL_AI_NETWORK_MODE=block" in command


def test_runtime_network_label_comes_from_canonical_policy(monkeypatch):
    from launcher import network_policy
    from launcher.agent import runtime_config

    monkeypatch.setattr(network_policy, "current_mode", lambda: network_policy.NetworkMode.WARP)
    assert "WARP" in runtime_config.network_label()


def test_legacy_internet_picker_persists_block_to_canonical_policy(monkeypatch):
    from launcher import network_policy
    from launcher.agent import setup_flow

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

    assert setup_flow.select_internet_mode(Presenter()) is False
    assert selected == ["block"]


def test_e2e_tool_no_longer_imports_runtime_builder_from_action_module():
    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "evaluate_local_search_e2e.py").read_text(encoding="utf-8")
    assert "launcher.agent.runtime_config" in source
    assert "launcher.actions.agent_chat import _build_cmd_for_mode" not in source
