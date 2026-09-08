"""Translate Local_AI_Agent folder policy into an OI Host permission profile."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import folder_policy

HOST_PERMISSION_PROFILE = "local-ai-host"


@dataclass(frozen=True)
class HostPermissionSpec:
    profile_name: str
    workspace_roots: tuple[str, ...]
    denied_paths: tuple[str, ...]


def _canonical(path) -> str:
    return str(Path(path).expanduser().resolve())


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = os.path.normcase(os.path.abspath(value))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def build_host_permission_spec(workspace: Path) -> HostPermissionSpec:
    workspace_path = Path(workspace).expanduser().resolve()
    roots = [_canonical(workspace_path)]
    try:
        allowed = folder_policy.list_allowed()
    except Exception:
        allowed = []
    for raw in allowed:
        try:
            candidate = Path(raw).expanduser().resolve()
            if candidate.exists() and candidate.is_dir():
                roots.append(str(candidate))
        except (OSError, RuntimeError, ValueError):
            continue

    denied: list[str] = []
    try:
        deny_values = folder_policy.list_denied()
    except Exception:
        deny_values = []
    for raw in deny_values:
        try:
            denied.append(_canonical(raw))
        except (OSError, RuntimeError, ValueError):
            continue

    return HostPermissionSpec(
        profile_name=HOST_PERMISSION_PROFILE,
        workspace_roots=_dedupe(roots),
        denied_paths=_dedupe(denied),
    )


def _q(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_host_permission_toml(spec: HostPermissionSpec) -> str:
    profile = spec.profile_name
    lines = [
        f"[permissions.{profile}.workspace_roots]",
    ]
    lines.extend(f"{_q(root)} = true" for root in spec.workspace_roots)
    lines.extend([
        "",
        f"[permissions.{profile}.filesystem]",
        '":minimal" = "read"',
    ])
    lines.extend(f"{_q(path)} = \"deny\"" for path in spec.denied_paths)
    lines.extend([
        "",
        f"[permissions.{profile}.filesystem.\":workspace_roots\"]",
        '"." = "write"',
        "",
        f"[permissions.{profile}.network]",
        "enabled = true",
    ])
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "HOST_PERMISSION_PROFILE",
    "HostPermissionSpec",
    "build_host_permission_spec",
    "render_host_permission_toml",
]
