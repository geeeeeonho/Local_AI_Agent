"""Translate Local_AI_Agent folder policy into an OI Host permission profile."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from core import vault

from . import folder_policy

HOST_PERMISSION_PROFILE = "local-ai-host"
HOST_PERMISSION_PROFILE_VERSION = 1


class HostPermissionPolicyError(RuntimeError):
    """Raised when the product folder policy cannot be represented safely."""


@dataclass(frozen=True)
class HostPermissionSpec:
    profile_name: str
    workspace_root: str
    workspace_roots: tuple[str, ...]
    denied_paths: tuple[str, ...]
    profile_version: int = HOST_PERMISSION_PROFILE_VERSION


def _canonical(path) -> str:
    return str(Path(path).expanduser().resolve())


def _identity(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _identity(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _validate_persisted_policy_store() -> None:
    """Reject a present-but-unreadable/corrupt policy before permissive legacy load()."""
    try:
        policy_path = Path(folder_policy._store_path())
        exists = policy_path.exists()
    except Exception as exc:
        raise HostPermissionPolicyError("folder policy store could not be inspected") from exc
    if not exists:
        return
    try:
        data = json.loads(vault.read_text(policy_path))
    except Exception as exc:
        raise HostPermissionPolicyError("folder policy store could not be read") from exc
    if not isinstance(data, dict):
        raise HostPermissionPolicyError("folder policy store must contain an object")
    for key in ("allowed", "denied"):
        values = data.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise HostPermissionPolicyError(f"folder policy {key} must be a list of paths")


def _read_policy_values(name: str) -> list[str]:
    reader = getattr(folder_policy, name)
    try:
        values = reader()
    except Exception as exc:
        raise HostPermissionPolicyError(f"folder policy {name} failed") from exc
    if values is None:
        raise HostPermissionPolicyError(f"folder policy {name} returned no values")
    try:
        return [str(value) for value in values]
    except Exception as exc:
        raise HostPermissionPolicyError(f"folder policy {name} returned invalid values") from exc


def build_host_permission_spec(workspace: Path) -> HostPermissionSpec:
    _validate_persisted_policy_store()
    try:
        workspace_root = _canonical(workspace)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HostPermissionPolicyError("workspace path could not be canonicalized") from exc

    roots = [workspace_root]
    allowed = _read_policy_values("list_allowed")
    for raw in allowed:
        try:
            candidate = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HostPermissionPolicyError(f"allowed path could not be canonicalized: {raw!r}") from exc
        # Historical/nonexistent allow entries are not permissions. They are
        # ignored rather than materialized as writable roots.
        if candidate.exists() and candidate.is_dir():
            roots.append(str(candidate))

    denied: list[str] = []
    deny_values = _read_policy_values("list_denied")
    for raw in deny_values:
        try:
            denied.append(_canonical(raw))
        except (OSError, RuntimeError, ValueError) as exc:
            raise HostPermissionPolicyError(f"denied path could not be canonicalized: {raw!r}") from exc

    return HostPermissionSpec(
        profile_name=HOST_PERMISSION_PROFILE,
        workspace_root=workspace_root,
        workspace_roots=_dedupe(roots),
        denied_paths=_dedupe(denied),
    )


def host_permission_fingerprint(
    spec: HostPermissionSpec,
    *,
    profile_version: int | None = None,
) -> str:
    """Return a deterministic identity for the effective Host permission policy."""
    version = spec.profile_version if profile_version is None else int(profile_version)
    workspace_identity = _identity(spec.workspace_root)
    allowed_identities = sorted(
        _identity(root)
        for root in spec.workspace_roots
        if _identity(root) != workspace_identity
    )
    denied_identities = sorted(_identity(path) for path in spec.denied_paths)
    payload = {
        "profile": spec.profile_name,
        "profile_version": version,
        "workspace": workspace_identity,
        "allowed": allowed_identities,
        "denied": denied_identities,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    "HOST_PERMISSION_PROFILE_VERSION",
    "HostPermissionPolicyError",
    "HostPermissionSpec",
    "build_host_permission_spec",
    "host_permission_fingerprint",
    "render_host_permission_toml",
]
