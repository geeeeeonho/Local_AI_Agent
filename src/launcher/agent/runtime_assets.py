from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_MANAGED_BEGIN = "# >>> LOCAL_AI_AGENT_LOCAL_SEARCH_MCP >>>"
_MANAGED_END = "# <<< LOCAL_AI_AGENT_LOCAL_SEARCH_MCP <<<"


def _toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _managed_block(*, command: str, command_args: list[str], searxng_url: str) -> str:
    return "\n".join(
        [
            _MANAGED_BEGIN,
            "[mcp_servers.local_search]",
            f"command = {_toml_string(command)}",
            f"args = {_toml_array(command_args)}",
            "startup_timeout_sec = 10",
            "tool_timeout_sec = 60",
            "required = false",
            'enabled_tools = ["search", "fetch_page"]',
            'default_tools_approval_mode = "approve"',
            "",
            "[mcp_servers.local_search.env]",
            f"SEARXNG_URL = {_toml_string(searxng_url)}",
            _MANAGED_END,
        ]
    )


def _replace_managed_block(existing: str, block: str) -> str:
    start = existing.find(_MANAGED_BEGIN)
    end = existing.find(_MANAGED_END)
    if start >= 0 and end >= start:
        end += len(_MANAGED_END)
        prefix = existing[:start].rstrip()
        suffix = existing[end:].lstrip()
        pieces = [part for part in (prefix, block, suffix) if part]
        return "\n\n".join(pieces).rstrip() + "\n"
    prefix = existing.rstrip()
    return ((prefix + "\n\n") if prefix else "") + block.rstrip() + "\n"


def prepare_runtime_assets(
    *,
    interpreter_home: Path,
    source_script: Path,
    runtime_script_path: Path,
    command: str,
    command_args: list[str],
    searxng_url: str,
) -> Path:
    home = Path(interpreter_home)
    source = Path(source_script)
    target = Path(runtime_script_path)
    home.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    config_path = home / "config.toml"
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    block = _managed_block(
        command=command,
        command_args=[str(value) for value in command_args],
        searxng_url=searxng_url,
    )
    config_path.write_text(_replace_managed_block(existing, block), encoding="utf-8")
    return config_path


def source_search_mcp() -> Path:
    return Path(__file__).resolve().with_name("search_mcp.py")


def prepare_host_runtime_assets(interpreter_home: Path, *, searxng_url: str) -> Path:
    home = Path(interpreter_home).resolve()
    target = home / "tools" / "local_search_mcp.py"
    return prepare_runtime_assets(
        interpreter_home=home,
        source_script=source_search_mcp(),
        runtime_script_path=target,
        command=sys.executable,
        command_args=[str(target)],
        searxng_url=searxng_url,
    )


def prepare_sandbox_runtime_assets(state_dir: Path, *, searxng_url: str) -> Path:
    state = Path(state_dir).resolve()
    home = state / "open_interpreter"
    target = state / "local_search_mcp.py"
    return prepare_runtime_assets(
        interpreter_home=home,
        source_script=source_search_mcp(),
        runtime_script_path=target,
        command="python",
        command_args=["/home/agent/.agent_state/local_search_mcp.py"],
        searxng_url=searxng_url,
    )
