"""Windows security boundary for the shared LocalAI *program*, not user data.

Only administrators may replace code or runtimes in C:\\LocalAI\\app,
C:\\LocalAI\\environment and C:\\LocalAI\\ollama. The model library deliberately
remains writable by users under the existing model-sharing contract.

The protection script is run through UAC; it takes ownership of protected
objects, removes *all* pre-existing explicit permissions on the shared root,
and resets stale ACLs on protected program subtrees. Never traverse models
or users: their permissions are separate and must not be changed here.
"""
from __future__ import annotations

import re
from pathlib import Path

from core import machine, sddl
from . import acl, privacy

_PROTECTED = ("app", "environment", "ollama")
_ADMINISTRATORS = privacy.ADMINISTRATORS_SID
_SYSTEM = privacy.SYSTEM_SID
_MUTATING_RIGHTS = (
    0x00000002  # FILE_WRITE_DATA / FILE_ADD_FILE
    | 0x00000004  # FILE_APPEND_DATA / FILE_ADD_SUBDIRECTORY
    | 0x00000010  # FILE_WRITE_EA
    | 0x00000040  # FILE_DELETE_CHILD
    | 0x00000100  # FILE_WRITE_ATTRIBUTES
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | sddl.GENERIC_WRITE
    | sddl.GENERIC_ALL
)


def _quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _valid_sids(values):
    return tuple(dict.fromkeys(sid for sid in values if machine.is_sid(sid)))


def protection_lines(root, admin_sids, principal, *, group_variable=None):
    """PowerShell instructions for atomic root DACL replacement + tree repair.

    Requires a previously approved LocalAI-specific root and an elevated
    process. Existing individual/unknown grants are *removed*, not merely
    superseded with icacls /grant:r. Built-in SYSTEM/Administrators retain F.
    """
    if not machine.is_sid(principal):
        raise ValueError("Invalid program read/execute principal")
    root = Path(root)
    admin_sids = _valid_sids(admin_sids)
    lines = [
        "$localaiRoot = " + _quote(root),
        "$localaiProtected = @(" + ", ".join(
            _quote(root / name) for name in _PROTECTED) + ")",
        "$ErrorActionPreference = 'Stop'",
        "try {",
        "  $rootNode = Get-Item -LiteralPath $localaiRoot -Force",
        "  if (-not $rootNode.PSIsContainer -or ($rootNode.Attributes -band "
        "[System.IO.FileAttributes]::ReparsePoint)) { throw 'LocalAI root is a link' }",
        "  $dacl = Get-Acl -LiteralPath $localaiRoot",
        "  $dacl.SetAccessRuleProtection($true, $false)",
        "  $identityType = [System.Security.Principal.SecurityIdentifier]",
        "  foreach ($oldRule in @($dacl.GetAccessRules($true, $false, $identityType))) {",
        "    [void]$dacl.RemoveAccessRuleSpecific($oldRule)",
        "  }",
        "  $builtinAdmin = [System.Security.Principal.SecurityIdentifier]::new(" +
        _quote(_ADMINISTRATORS) + ")",
        "  $dacl.SetOwner($builtinAdmin)",
        "  $flags = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit "
        "-bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit",
        "  $propagation = [System.Security.AccessControl.PropagationFlags]::None",
        "  $allow = [System.Security.AccessControl.AccessControlType]::Allow",
        "  $full = [System.Security.AccessControl.FileSystemRights]::FullControl",
        "  $read = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute",
        "  $fullSids = @(" + ", ".join(_quote(v) for v in
            (_SYSTEM, _ADMINISTRATORS) + admin_sids) + ")",
    ]
    if group_variable:
        # The group was just created in this same elevated Setup script.
        lines.append("  if (" + group_variable +
                     ") { $fullSids += " + group_variable + " }")
    lines += [
        "  foreach ($sid in ($fullSids | Select-Object -Unique)) {",
        "    $who = [System.Security.Principal.SecurityIdentifier]::new($sid)",
        "    $dacl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new("
        "$who, $full, $flags, $propagation, $allow))",
        "  }",
        "  $reader = [System.Security.Principal.SecurityIdentifier]::new(" +
        _quote(principal) + ")",
        "  $dacl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new("
        "$reader, $read, $flags, $propagation, $allow))",
        "  Set-Acl -LiteralPath $localaiRoot -AclObject $dacl",
        "  foreach ($folder in $localaiProtected) {",
        "    if (-not (Test-Path -LiteralPath $folder)) { continue }",
        "    $node = Get-Item -LiteralPath $folder -Force",
        "    if (-not $node.PSIsContainer -or ($node.Attributes -band "
        "[System.IO.FileAttributes]::ReparsePoint)) { throw 'Protected path is a link: ' + $folder }",
        "    & icacls.exe $folder /reset /T /C /Q /L 2>&1 | Out-Null",
        "    if ($LASTEXITCODE -ne 0) { throw 'Unable to reset ACLs: ' + $folder }",
        "    & icacls.exe $folder /setowner " + _quote("*" + _ADMINISTRATORS) +
        " /T /C /Q /L 2>&1 | Out-Null",
        "    if ($LASTEXITCODE -ne 0) { throw 'Unable to set owner: ' + $folder }",
        "  }",
        # The machine-wide role policy must not retain a writable old ACL.
        "  $policyFile = Join-Path $localaiRoot 'machine.json'",
        "  if (Test-Path -LiteralPath $policyFile -PathType Leaf) {",
        "    & icacls.exe $policyFile /reset /Q /L 2>&1 | Out-Null",
        "    if ($LASTEXITCODE -ne 0) { throw 'Unable to reset policy ACL' }",
        "    & icacls.exe $policyFile /setowner " + _quote("*" + _ADMINISTRATORS) +
        " /Q /L 2>&1 | Out-Null",
        "    if ($LASTEXITCODE -ne 0) { throw 'Unable to set policy owner' }",
        "  }",
        "  $runtimeLock = Join-Path $localaiRoot 'environment\\desktop-runtime.lock'",
        "  if (Test-Path -LiteralPath $runtimeLock -PathType Leaf) {",
        "    & icacls.exe $runtimeLock /grant:r " +
        _quote("*" + principal + ":(R,W)") + " /Q 2>&1 | Out-Null",
        "    if ($LASTEXITCODE -ne 0) { throw 'Unable to restore runtime lock access' }",
        "  }",
        "} catch { Write-Error $_; $failed = 1 }",
    ]
    return lines


def reject_reparse_root(root):
    """A junction/symlink cannot be made the target of recursive ACL repair."""
    path = Path(root)
    try:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RuntimeError("공용 설치 루트가 연결/정션 경로입니다: " + str(root))
        # A parent junction also redirects the recursion outside LocalAI.
        if path.exists() and path.resolve() != path.absolute():
            raise RuntimeError("공용 설치 경로의 상위 폴더가 연결 경로입니다: " + str(root))
    except (OSError, ValueError) as exc:
        raise RuntimeError("공용 설치 경로의 실제 위치를 확인할 수 없습니다.") from exc


def protection_script(root, policy: machine.Policy):
    """The one elevated repair script for a previously registered LocalAI."""
    return "\n".join(["$failed = 0"] + protection_lines(
        root, policy.admin_sids(), policy.principal()) + ["exit $failed"])


def _owner_allowed(owner, policy):
    value = (owner or "").upper()
    return value in ("BA", _ADMINISTRATORS, "SY", _SYSTEM) or value in {
        sid.upper() for sid in policy.admin_sids()
    }


def _acl_is_safe(descriptor, policy, *, require_protected=False):
    """Reject any writable non-admin ACE, including a SID not in known groups.

    The standard sddl.grants_modify() intentionally tests the stronger Modify
    preset. Executable integrity needs to reject even WriteData or WriteDac.
    """
    if not isinstance(descriptor, str):
        return False
    match = re.search(r"D:([^\r\n]*)", descriptor)
    if not match:
        return False
    dacl = match.group(1)
    if require_protected and not dacl.startswith("P"):
        return False
    trusted = {sid.upper() for sid in
               (_ADMINISTRATORS, "BA", _SYSTEM, "SY") + policy.admin_sids()}
    aces = re.findall(r"\(([^()]*)\)", dacl)
    if not aces:
        return False
    aliases = {
        "S-1-5-32-545": "BU",  # BUILTIN Users
        "S-1-1-0": "WD",       # Everyone
        "S-1-5-11": "AU",      # Authenticated Users
    }
    principal_aliases = {policy.principal().upper()}
    principal_aliases.add(aliases.get(policy.principal().upper(), ""))
    readable = False
    for ace in aces:
        fields = ace.split(";")
        if len(fields) < 6:
            continue
        kind, rights, who = fields[0].upper(), fields[2], fields[5].upper()
        mask = sddl.mask(rights)
        if kind in ("A", "OA", "XA"):
            if who in principal_aliases and sddl.grants_read(mask):
                readable = True
            if who not in trusted and mask & _MUTATING_RIGHTS:
                return False
    return readable


def verify(root, policy: machine.Policy):
    """Audit installed executable boundary; fail closed on an unreadable ACL."""
    root = Path(root)
    targets = [root] + [root / name for name in _PROTECTED]
    # A few particularly important executable entry points as well as the
    # directory policies. The elevated repair reports a failure if ANY of the
    # recursive reset/owner steps failed, not just these representative checks.
    targets.extend((root / machine.POLICY_FILENAME,
                    root / "app" / "RUN.bat",
                    root / "app" / "src",
                    root / "ollama" / "ollama.exe"))
    reasons = []
    for path in targets:
        if not path.exists() and not path.is_symlink():
            if path == root:
                reasons.append("공용 루트가 없습니다")
            continue
        try:
            if path.is_symlink() or (
                    hasattr(path, "is_junction") and path.is_junction()):
                reasons.append("연결된 외부 경로는 보호할 수 없음: " + str(path))
                continue
        except OSError:
            reasons.append("경로 확인 실패: " + str(path))
            continue
        owner = acl.owner_sid(path)
        if not _owner_allowed(owner, policy):
            reasons.append("프로그램 소유자 불일치: " + str(path))
        descriptor = acl.saved_sddl(path)
        if not _acl_is_safe(descriptor, policy, require_protected=path == root):
            reasons.append("보호되지 않은 쓰기 권한 또는 ACL 확인 실패: " + str(path))
    return reasons


def ensure(root, policy: machine.Policy, *, log=None, force=False):
    """Repair/verify executable trees or abort, never leave setup unlocked.

    force=True resets *every* executable file after a third-party installer,
    even when directory ACLs and representative files already look safe.
    """
    from . import machine as windows
    if not acl.on_windows():
        return True
    from .machine import lockable_root
    if not lockable_root(root):
        raise RuntimeError("보안 정책을 적용할 수 없는 공용 설치 경로입니다: " + str(root))
    reject_reparse_root(root)
    reasons = verify(root, policy)
    if not reasons and not force:
        return True
    if not windows.run_as_admin(protection_script(root, policy), log=log):
        raise RuntimeError("Windows 관리자 승인 또는 프로그램 ACL 복구 실패. "
                           "공용 프로그램은 갱신하지 않습니다. " + "; ".join(reasons[:3]))
    remaining = verify(root, policy)
    if remaining:
        raise RuntimeError("Windows ACL 복구 후에도 프로그램 보호를 검증할 수 없습니다: " +
                           "; ".join(remaining[:4]))
    return True


__all__ = ["protection_lines", "protection_script", "verify", "ensure"]
