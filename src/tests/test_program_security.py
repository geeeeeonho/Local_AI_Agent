"""Fail-closed Windows executable integrity boundary.

Tests don't mutate real Windows ACLs. They assert the exact privileged script
scope and exercise the same SDDL parser used after an elevated repair.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import machine
from integrations.windows import acl, program_security as security

ME = "S-1-5-21-111-222-333-1001"
OTHER = "S-1-5-21-111-222-333-1002"
GROUP = "S-1-5-21-111-222-333-1010"
POLICY = machine.new_policy(ME, admins_group_sid=GROUP)
ROOT_SDDL = ("O:BA G:BA D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
             "(A;OICI;FA;;;" + ME + ")(A;OICI;FR;;;BU)")
CHILD_SDDL = ROOT_SDDL.replace("D:PAI", "D:AI")


def test_repair_script_removes_every_old_explicit_ace_and_takes_owner():
    script = security.protection_script(Path("C:/LocalAI"), POLICY)
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "RemoveAccessRuleSpecific($oldRule)" in script
    assert "SetOwner($builtinAdmin)" in script
    assert "Set-Acl -LiteralPath $localaiRoot" in script
    assert script.count("/reset /T") == 1  # one loop, three protected folders
    assert "icacls.exe $folder /setowner" in script
    assert "ReparsePoint" in script and " /L " in script
    assert "app" in script and "environment" in script and "ollama" in script
    assert "models" not in script and "users" not in script
    assert "desktop-runtime.lock" in script and "(R,W)" in script
    assert script.rstrip().endswith("exit $failed")


@pytest.mark.parametrize("bad", [
    "D:PAI(A;OICI;FA;;;BU)",
    "D:PAI(A;OICI;FW;;;AU)",
    "D:PAI(A;OICI;GW;;;WD)",
    "D:PAI(A;OICI;0x00040000;;;" + OTHER + ")",
    "D:PAI(A;OICI;0x00080000;;;" + OTHER + ")",
    "D:PAI(A;OICI;0x00000002;;;BU)",
    "D:PAI(A;OICI;0x00000040;;;IU)",
])
def test_any_nonadmin_write_or_acl_ownership_right_is_rejected(bad):
    assert not security._acl_is_safe(ROOT_SDDL + bad, POLICY, require_protected=True)


def test_legacy_unprotected_root_is_not_accepted():
    assert not security._acl_is_safe(CHILD_SDDL, POLICY, require_protected=True)
    assert not security._acl_is_safe(None, POLICY)
    assert security._acl_is_safe(ROOT_SDDL, POLICY, require_protected=True)


def test_a_restricted_reader_sid_and_bu_alias_are_understood():
    policy = machine.new_policy(ME, users_group_sid=GROUP)
    policy.access = machine.ACCESS_MEMBERS
    sd = ("D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
          "(A;OICI;FR;;;" + GROUP + ")")
    assert security._acl_is_safe(sd, policy, require_protected=True)
    assert security._acl_is_safe(ROOT_SDDL, POLICY, require_protected=True)


def test_program_verification_rejects_files_owned_by_another_account(tmp_path, monkeypatch):
    root = tmp_path / "LocalAI"
    (root / "app").mkdir(parents=True)
    (root / "app" / "RUN.bat").write_text("echo localai")
    monkeypatch.setattr(acl, "owner_sid",
                        lambda path: OTHER if Path(path).name == "RUN.bat" else "BA")
    monkeypatch.setattr(acl, "saved_sddl",
                        lambda path: ROOT_SDDL if Path(path) == root else CHILD_SDDL)
    problems = security.verify(root, POLICY)
    assert any("소유자 불일치" in item and "RUN.bat" in item for item in problems)


def test_program_verification_rejects_direct_write_grant_on_child(tmp_path, monkeypatch):
    root = tmp_path / "LocalAI"
    (root / "environment").mkdir(parents=True)
    monkeypatch.setattr(acl, "owner_sid", lambda path: "BA")
    monkeypatch.setattr(acl, "saved_sddl", lambda path:
                        CHILD_SDDL + "(A;OICI;FW;;;BU)"
                        if Path(path).name == "environment" else ROOT_SDDL)
    assert any("쓰기 권한" in item for item in security.verify(root, POLICY))


def test_failed_uac_cannot_report_protection_success(tmp_path, monkeypatch):
    from integrations.windows import machine as windows
    root = tmp_path / "LocalAI"
    root.mkdir()
    monkeypatch.setattr(acl, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "lockable_root", lambda path: True)
    monkeypatch.setattr(security, "verify",
                        lambda root, policy: ["root has nonadmin write"])
    monkeypatch.setattr(windows, "run_as_admin", lambda script, **kw: False)
    with pytest.raises(RuntimeError, match="관리자 승인"):
        security.ensure(root, POLICY)


def test_successful_repair_must_be_verified_again(tmp_path, monkeypatch):
    from integrations.windows import machine as windows
    root = tmp_path / "LocalAI"
    root.mkdir()
    monkeypatch.setattr(acl, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "lockable_root", lambda path: True)
    calls = []
    monkeypatch.setattr(security, "verify",
                        lambda root, policy: calls.append("check") or ["still writable"])
    monkeypatch.setattr(windows, "run_as_admin",
                        lambda script, **kw: calls.append("uac") or True)
    with pytest.raises(RuntimeError, match="검증할 수 없습니다"):
        security.ensure(root, POLICY)
    assert calls == ["check", "uac", "check"]
