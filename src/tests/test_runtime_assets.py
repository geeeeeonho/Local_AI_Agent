from pathlib import Path

from launcher.agent import host_permissions, runtime_assets


def test_host_runtime_assets_write_local_search_mcp_config(tmp_path):
    source = tmp_path / "source_search_mcp.py"
    source.write_text("print('mcp')\n", encoding="utf-8")
    privacy = tmp_path / "privacy_policy.py"
    privacy.write_text("def blocked_outbound_reason(text): return None\n", encoding="utf-8")
    home = tmp_path / "open_interpreter"

    result = runtime_assets.prepare_runtime_assets(
        interpreter_home=home,
        source_script=source,
        privacy_source=privacy,
        runtime_script_path=home / "tools" / "local_search_mcp.py",
        command="python",
        command_args=[str(home / "tools" / "local_search_mcp.py")],
        searxng_url="http://127.0.0.1:8888",
        network_mode="warp",
    )

    copied = home / "tools" / "local_search_mcp.py"
    copied_privacy = home / "tools" / "privacy_policy.py"
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert copied_privacy.read_text(encoding="utf-8") == privacy.read_text(encoding="utf-8")
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.local_search]" in config
    assert 'command = "python"' in config
    assert 'enabled_tools = ["search", "fetch_page"]' in config
    assert 'SEARXNG_URL = "http://127.0.0.1:8888"' in config
    assert 'LOCAL_AI_NETWORK_MODE = "warp"' in config
    assert result == home / "config.toml"


def test_runtime_assets_preserve_unmanaged_existing_config(tmp_path):
    source = tmp_path / "source_search_mcp.py"
    source.write_text("print('mcp')\n", encoding="utf-8")
    privacy = tmp_path / "privacy_policy.py"
    privacy.write_text("def blocked_outbound_reason(text): return None\n", encoding="utf-8")
    home = tmp_path / "open_interpreter"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text('model = "keep-me"\n', encoding="utf-8")

    runtime_assets.prepare_runtime_assets(
        interpreter_home=home,
        source_script=source,
        privacy_source=privacy,
        runtime_script_path=home / "tools" / "local_search_mcp.py",
        command="python",
        command_args=[str(home / "tools" / "local_search_mcp.py")],
        searxng_url="http://127.0.0.1:8888",
        network_mode="tor",
    )

    config = config_path.read_text(encoding="utf-8")
    assert 'model = "keep-me"' in config
    assert config.count("[mcp_servers.local_search]") == 1
    assert 'LOCAL_AI_NETWORK_MODE = "tor"' in config


def test_host_runtime_assets_return_fingerprint_for_exact_written_policy(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    denied = tmp_path / "denied"
    home = tmp_path / "home"

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [str(allowed)])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied)])
    monkeypatch.setattr(runtime_assets, "source_search_mcp", lambda: Path(__file__))
    monkeypatch.setattr(runtime_assets, "source_privacy_policy", lambda: Path(__file__))
    monkeypatch.setattr(runtime_assets, "source_web_safety", lambda: Path(__file__))

    config_path, fingerprint = runtime_assets.prepare_host_runtime_assets_with_fingerprint(
        home,
        searxng_url="http://127.0.0.1:8888",
        network_mode="direct",
        workspace=workspace,
    )

    expected_spec = host_permissions.build_host_permission_spec(workspace)
    assert fingerprint == host_permissions.host_permission_fingerprint(expected_spec)
    config = config_path.read_text(encoding="utf-8")
    assert str(workspace.resolve()) in config
    assert str(allowed.resolve()) in config
    assert str(denied.resolve()) in config


def test_legacy_host_runtime_assets_helper_keeps_path_only_contract(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])
    monkeypatch.setattr(runtime_assets, "source_search_mcp", lambda: Path(__file__))
    monkeypatch.setattr(runtime_assets, "source_privacy_policy", lambda: Path(__file__))
    monkeypatch.setattr(runtime_assets, "source_web_safety", lambda: Path(__file__))

    result = runtime_assets.prepare_host_runtime_assets(
        home,
        searxng_url="http://127.0.0.1:8888",
        network_mode="direct",
        workspace=workspace,
    )

    assert result == home.resolve() / "config.toml"
