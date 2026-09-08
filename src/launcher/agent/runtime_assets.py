from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

try:
    from .. import network_policy
except Exception:  # pragma: no cover
    from launcher import network_policy

_MCP_MANAGED_BEGIN = "# >>> LOCAL_AI_AGENT_LOCAL_SEARCH_MCP >>>"
_MCP_MANAGED_END = "# <<< LOCAL_AI_AGENT_LOCAL_SEARCH_MCP <<<"
_HOST_PERMISSIONS_BEGIN = "# >>> LOCAL_AI_AGENT_HOST_PERMISSIONS >>>"
_HOST_PERMISSIONS_END = "# <<< LOCAL_AI_AGENT_HOST_PERMISSIONS <<<"


def _toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _managed_block(
    *,
    command: str,
    command_args: list[str],
    searxng_url: str,
    network_mode: str,
) -> str:
    return "\n".join(
        [
            _MCP_MANAGED_BEGIN,
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
            f"LOCAL_AI_NETWORK_MODE = {_toml_string(network_mode)}",
            _MCP_MANAGED_END,
        ]
    )


def _replace_block(existing: str, begin: str, end_marker: str, block: str) -> str:
    start = existing.find(begin)
    end = existing.find(end_marker)
    if start >= 0 and end >= start:
        end += len(end_marker)
        prefix = existing[:start].rstrip()
        suffix = existing[end:].lstrip()
        pieces = [part for part in (prefix, block, suffix) if part]
        return "\n\n".join(pieces).rstrip() + "\n"
    prefix = existing.rstrip()
    return ((prefix + "\n\n") if prefix else "") + block.rstrip() + "\n"


def _replace_managed_block(existing: str, block: str) -> str:
    return _replace_block(existing, _MCP_MANAGED_BEGIN, _MCP_MANAGED_END, block)


def _host_permissions_block(permission_toml: str) -> str:
    return "\n".join(
        [
            _HOST_PERMISSIONS_BEGIN,
            permission_toml.rstrip(),
            _HOST_PERMISSIONS_END,
        ]
    )


def _write_host_permissions(config_path: Path, workspace: Path) -> str:
    from .host_permissions import (
        build_host_permission_spec,
        host_permission_fingerprint,
        render_host_permission_toml,
    )

    spec = build_host_permission_spec(workspace)
    permission_toml = render_host_permission_toml(spec)
    fingerprint = host_permission_fingerprint(spec)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    block = _host_permissions_block(permission_toml)
    updated = _replace_block(
        existing,
        _HOST_PERMISSIONS_BEGIN,
        _HOST_PERMISSIONS_END,
        block,
    )
    config_path.write_text(updated, encoding="utf-8")
    return fingerprint


def prepare_runtime_assets(
    *,
    interpreter_home: Path,
    source_script: Path,
    privacy_source: Path | None = None,
    web_safety_source: Path | None = None,
    runtime_script_path: Path,
    command: str,
    command_args: list[str],
    searxng_url: str,
    network_mode: str | None = None,
) -> Path:
    home = Path(interpreter_home)
    source = Path(source_script)
    target = Path(runtime_script_path)
    home.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    privacy = Path(privacy_source) if privacy_source is not None else source_privacy_policy()
    shutil.copy2(privacy, target.parent / "privacy_policy.py")
    safety = Path(web_safety_source) if web_safety_source is not None else source_web_safety()
    shutil.copy2(safety, target.parent / "web_safety.py")

    canonical_mode = network_policy.normalize_mode(network_mode).value
    config_path = home / "config.toml"
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    block = _managed_block(
        command=command,
        command_args=[str(value) for value in command_args],
        searxng_url=searxng_url,
        network_mode=canonical_mode,
    )
    config_path.write_text(_replace_managed_block(existing, block), encoding="utf-8")
    return config_path


def source_search_mcp() -> Path:
    return Path(__file__).resolve().with_name("search_mcp.py")


def source_web_safety() -> Path:
    return Path(__file__).resolve().with_name("web_safety.py")


def source_privacy_policy() -> Path:
    return Path(__file__).resolve().parents[1] / "privacy_policy.py"


def prepare_host_runtime_assets_with_fingerprint(
    interpreter_home: Path,
    *,
    searxng_url: str,
    network_mode: str | None = None,
    workspace: Path,
) -> tuple[Path, str]:
    """Prepare Host MCP/permission assets and return the exact policy identity written."""
    home = Path(interpreter_home).resolve()
    target = home / "tools" / "local_search_mcp.py"
    config_path = prepare_runtime_assets(
        interpreter_home=home,
        source_script=source_search_mcp(),
        privacy_source=source_privacy_policy(),
        web_safety_source=source_web_safety(),
        runtime_script_path=target,
        command=sys.executable,
        command_args=[str(target)],
        searxng_url=searxng_url,
        network_mode=network_mode,
    )
    fingerprint = _write_host_permissions(config_path, Path(workspace))
    return config_path, fingerprint


def prepare_host_runtime_assets(
    interpreter_home: Path,
    *,
    searxng_url: str,
    network_mode: str | None = None,
    workspace: Path | None = None,
) -> Path:
    home = Path(interpreter_home).resolve()
    if workspace is not None:
        config_path, _fingerprint = prepare_host_runtime_assets_with_fingerprint(
            home,
            searxng_url=searxng_url,
            network_mode=network_mode,
            workspace=Path(workspace),
        )
        return config_path

    target = home / "tools" / "local_search_mcp.py"
    return prepare_runtime_assets(
        interpreter_home=home,
        source_script=source_search_mcp(),
        privacy_source=source_privacy_policy(),
        web_safety_source=source_web_safety(),
        runtime_script_path=target,
        command=sys.executable,
        command_args=[str(target)],
        searxng_url=searxng_url,
        network_mode=network_mode,
    )


def prepare_sandbox_runtime_assets(
    state_dir: Path,
    *,
    searxng_url: str,
    network_mode: str | None = None,
) -> Path:
    state = Path(state_dir).resolve()
    home = state / "open_interpreter"
    target = state / "local_search_mcp.py"
    return prepare_runtime_assets(
        interpreter_home=home,
        source_script=source_search_mcp(),
        privacy_source=source_privacy_policy(),
        web_safety_source=source_web_safety(),
        runtime_script_path=target,
        command="python",
        command_args=["/home/agent/.agent_state/local_search_mcp.py"],
        searxng_url=searxng_url,
        network_mode=network_mode,
    )
