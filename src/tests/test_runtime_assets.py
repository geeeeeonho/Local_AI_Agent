from pathlib import Path

from launcher.agent import runtime_assets


def test_host_runtime_assets_write_local_search_mcp_config(tmp_path):
    source = tmp_path / "source_search_mcp.py"
    source.write_text("print('mcp')\n", encoding="utf-8")
    home = tmp_path / "open_interpreter"

    result = runtime_assets.prepare_runtime_assets(
        interpreter_home=home,
        source_script=source,
        runtime_script_path=home / "tools" / "local_search_mcp.py",
        command="python",
        command_args=[str(home / "tools" / "local_search_mcp.py")],
        searxng_url="http://127.0.0.1:8888",
    )

    copied = home / "tools" / "local_search_mcp.py"
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.local_search]" in config
    assert 'command = "python"' in config
    assert 'enabled_tools = ["search", "fetch_page"]' in config
    assert 'SEARXNG_URL = "http://127.0.0.1:8888"' in config
    assert result == home / "config.toml"


def test_runtime_assets_preserve_unmanaged_existing_config(tmp_path):
    source = tmp_path / "source_search_mcp.py"
    source.write_text("print('mcp')\n", encoding="utf-8")
    home = tmp_path / "open_interpreter"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text('model = "keep-me"\n', encoding="utf-8")

    runtime_assets.prepare_runtime_assets(
        interpreter_home=home,
        source_script=source,
        runtime_script_path=home / "tools" / "local_search_mcp.py",
        command="python",
        command_args=[str(home / "tools" / "local_search_mcp.py")],
        searxng_url="http://127.0.0.1:8888",
    )

    config = config_path.read_text(encoding="utf-8")
    assert 'model = "keep-me"' in config
    assert config.count("[mcp_servers.local_search]") == 1
