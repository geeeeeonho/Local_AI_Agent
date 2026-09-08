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
    assert _norm(spec.workspace_root) == _norm(workspace)
    assert spec.profile_name == "local-ai-host"
    assert spec.profile_version == host_permissions.HOST_PERMISSION_PROFILE_VERSION


def test_host_permission_spec_dedupes_paths_with_platform_normcase(monkeypatch, tmp_path):
    workspace = tmp_path / "Work"
    workspace.mkdir()
    duplicate = str(workspace)
    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [duplicate, duplicate])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])
    spec = host_permissions.build_host_permission_spec(workspace)
    assert len(spec.workspace_roots) == 1


def test_folder_policy_allowed_read_failure_is_fail_closed(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail():
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", fail)
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])

    with pytest.raises(host_permissions.HostPermissionPolicyError):
        host_permissions.build_host_permission_spec(workspace)


def test_folder_policy_denied_read_failure_is_fail_closed(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail():
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", fail)

    with pytest.raises(host_permissions.HostPermissionPolicyError):
        host_permissions.build_host_permission_spec(workspace)


def test_corrupt_persisted_folder_policy_is_fail_closed(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy_path = tmp_path / "folder_policy.json"
    policy_path.write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(host_permissions.folder_policy, "_store_path", lambda: policy_path)
    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])

    with pytest.raises(host_permissions.HostPermissionPolicyError):
        host_permissions.build_host_permission_spec(workspace)


def test_policy_fingerprint_is_stable_across_allowed_and_denied_order(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    allowed_a = tmp_path / "allowed-a"
    allowed_b = tmp_path / "allowed-b"
    allowed_a.mkdir()
    allowed_b.mkdir()
    denied_a = tmp_path / "denied-a"
    denied_b = tmp_path / "denied-b"

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [str(allowed_b), str(allowed_a), str(allowed_b)])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied_b), str(denied_a)])
    first = host_permissions.host_permission_fingerprint(
        host_permissions.build_host_permission_spec(workspace)
    )

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [str(allowed_a), str(allowed_b)])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied_a), str(denied_b)])
    second = host_permissions.host_permission_fingerprint(
        host_permissions.build_host_permission_spec(workspace)
    )

    assert first == second
    assert len(first) == 64


def test_policy_fingerprint_changes_for_workspace_allowed_denied_and_version(monkeypatch, tmp_path):
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    for path in (workspace_a, workspace_b, allowed):
        path.mkdir()

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [])
    base_spec = host_permissions.build_host_permission_spec(workspace_a)
    base = host_permissions.host_permission_fingerprint(base_spec)

    workspace_changed = host_permissions.host_permission_fingerprint(
        host_permissions.build_host_permission_spec(workspace_b)
    )

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [str(allowed)])
    allowed_changed = host_permissions.host_permission_fingerprint(
        host_permissions.build_host_permission_spec(workspace_a)
    )

    monkeypatch.setattr(host_permissions.folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(host_permissions.folder_policy, "list_denied", lambda: [str(denied)])
    denied_changed = host_permissions.host_permission_fingerprint(
        host_permissions.build_host_permission_spec(workspace_a)
    )

    version_changed = host_permissions.host_permission_fingerprint(
        base_spec,
        profile_version=base_spec.profile_version + 1,
    )

    assert len({base, workspace_changed, allowed_changed, denied_changed, version_changed}) == 5


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
