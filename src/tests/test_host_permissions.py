import os
import tomllib
from pathlib import Path

import pytest

from launcher.agent import host_permissions


def _norm(value):
    return os.path.normcase(os.path.abspath(str(value)))


def test_host_permission_spec_contains_workspace_and_valid_allowed(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    allowed = tmp_path / "shared"
    allowed.mkdir()
    missing = tmp_path / "missing"
    denied = tmp_path / "private"

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [str(allowed), str(workspace), str(missing)])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied)])

    spec = host_permissions.build_host_permission_spec(workspace)
    roots = {_norm(value) for value in spec.workspace_roots}
    assert roots == {_norm(workspace), _norm(allowed)}
    assert len(spec.workspace_roots) == 2
    assert tuple(map(_norm, spec.denied_paths)) == (_norm(denied),)
    assert spec.profile_name == "local-ai-host"


def test_host_permission_spec_dedupes_paths_with_platform_normcase(monkeypatch, tmp_path):
    workspace = tmp_path / "Work"
    workspace.mkdir()
    duplicate = str(workspace)
    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [duplicate, duplicate])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])
    spec = host_permissions.build_host_permission_spec(workspace)
    assert len(spec.workspace_roots) == 1


def test_rendered_host_permissions_are_valid_toml_and_deny_wins(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    denied = tmp_path / "denied"
    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied)])

    spec = host_permissions.build_host_permission_spec(workspace)
    text = host_permissions.render_host_permission_toml(spec)
    parsed = tomllib.loads(text)
    profile = parsed["permissions"]["local-ai-host"]

    assert profile["workspace_roots"][str(workspace.resolve())] is True
    assert profile["filesystem"][":minimal"] == "read"
    assert profile["filesystem"][str(denied.resolve())] == "deny"
    assert profile["filesystem"][":workspace_roots"]["."] == "write"
    assert profile["network"]["enabled"] is True


def test_render_does_not_embed_proxy_routing(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])
    text = host_permissions.render_host_permission_toml(
        host_permissions.build_host_permission_spec(workspace)
    )
    lowered = text.lower()
    assert "proxy_url" not in lowered
    assert "socks_url" not in lowered
    assert "http_proxy" not in lowered
