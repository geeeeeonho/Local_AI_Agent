"""The Windows side of LocalAI administration: groups, accounts, one UAC prompt.

Everything here that changes the machine - creating the two local groups,
adding a member, deleting another account's records, making shortcuts every
account sees - needs a Windows administrator. Each such change is one
PowerShell script run through a single UAC prompt (``-EncodedCommand``, so
nothing is written to disk for the elevated process to read back). Reading -
which accounts exist, who is in which group - needs no elevation.

Language-neutral throughout: groups are matched by SID, never by the
localized names ``net`` prints.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set

from core import accounts, machine
from . import acl, privacy

_SID = re.compile(r'S-1-\d+(?:-\d+)+')
_SAFE_NAME = re.compile(r'^[^"\'`$;|&<>\r\n]+$')


def powershell() -> str:
    """64-bit Windows PowerShell even from a 32-bit Python.

    A 32-bit process asking for System32 is silently given SysWOW64, whose
    PowerShell lacks the local-accounts module; Sysnative is the real one.
    """
    root = os.environ.get('SystemRoot') or r'C:\Windows'
    native = Path(root) / 'Sysnative' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    if native.exists():
        return str(native)
    return str(Path(root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')


def quote(value) -> str:
    """A PowerShell single-quoted literal."""
    return "'" + str(value).replace("'", "''") + "'"


def encoded(script: str) -> str:
    return base64.b64encode(script.encode('utf-16-le')).decode('ascii')


def run_script(script: str, *, timeout=120):
    """Run a script as the signed-in user (no elevation)."""
    return acl.run([powershell(), '-NoProfile', '-NonInteractive',
                    '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded(script)],
                   timeout=timeout)


def run_as_admin(script: str, *, log=None, timeout=900) -> bool:
    """Run ``script`` with administrator rights: directly if already elevated,
    otherwise through one UAC prompt. True when it ran and exited 0."""
    say = log or (lambda message: None)
    if os.environ.get(privacy.NO_ELEVATION_VARIABLE, '').strip() in ('1', 'true', 'yes'):
        say('관리자 작업을 건너뜁니다 (%s=1).' % privacy.NO_ELEVATION_VARIABLE)
        return False
    if acl.is_elevated():
        return acl.succeeded(run_script(script, timeout=timeout))
    say('Windows 관리자 승인이 필요합니다. 확인 창(UAC)에서 [예]를 누르세요.')
    code, error = acl.run_elevated(
        powershell(),
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden '
        '-EncodedCommand ' + encoded(script),
        timeout=timeout)
    if code is None:
        if error == acl.ERROR_CANCELLED:
            say('관리자 승인이 취소되었습니다.')
        elif error is not None:
            say('관리자 권한으로 실행하지 못했습니다: ' + acl.describe_error(error))
        return False
    if code != 0:
        say('관리자 작업이 실패했습니다 (종료 코드 %d).' % code)
    return code == 0


# ── reading the machine ──────────────────────────────────────────────────

def token_group_sids() -> Set[str]:
    """Group SIDs in this process's logon token (membership as Windows sees it)."""
    result = acl.run(['whoami', '/groups', '/fo', 'csv', '/nh'])
    if not acl.succeeded(result):
        return set()
    return {sid.upper() for sid in _SID.findall(result.stdout or '')}


def account_name() -> Optional[str]:
    """``COMPUTER\\name`` for this account, as ``net`` and ACL tools accept it."""
    result = acl.run(['whoami'])
    name = (result.stdout or '').strip() if acl.succeeded(result) else ''
    return name or None


def group_sid(name: str) -> Optional[str]:
    script = ("try { (New-Object System.Security.Principal.NTAccount(%s))"
              ".Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { }"
              % quote(name))
    result = run_script(script, timeout=30)
    found = _SID.findall((result.stdout or '') if result is not None else '')
    return found[0] if found else None


_LIST_SCRIPT = r'''
$ErrorActionPreference = 'SilentlyContinue'
function Members($name) {
  $out = @()
  try {
    $g = [ADSI]("WinNT://$env:COMPUTERNAME/$name,group")
    foreach ($m in @($g.Invoke('Members'))) {
      $raw = $m.GetType().InvokeMember('objectSid', 'GetProperty', $null, $m, $null)
      $out += (New-Object System.Security.Principal.SecurityIdentifier($raw, 0)).Value
    }
  } catch { }
  return ,$out
}
$users = @(Get-CimInstance -ClassName Win32_UserAccount -Filter 'LocalAccount=True' |
  ForEach-Object { [pscustomobject]@{ name = $_.Name; sid = $_.SID; disabled = [bool]$_.Disabled } })
[pscustomobject]@{
  users = $users
  admins = (Members 'GROUP_ADMINS')
  members = (Members 'GROUP_USERS')
  administrators = (Members 'Administrators')
} | ConvertTo-Json -Depth 4 -Compress
'''


def list_accounts() -> Optional[dict]:
    """Local accounts and LocalAI group membership, or None if unreadable.

    ``administrators`` lists the built-in Administrators group by its English
    name, which ADSI accepts on every display language.
    """
    script = (_LIST_SCRIPT.replace('GROUP_ADMINS', machine.ADMINS_GROUP)
              .replace('GROUP_USERS', machine.USERS_GROUP))
    result = run_script(script, timeout=60)
    if not acl.succeeded(result):
        return None
    try:
        data = json.loads((result.stdout or '').strip() or 'null')
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def sids(value):
        if isinstance(value, str):
            value = [value]
        return {str(item).upper() for item in (value or ()) if _SID.fullmatch(str(item))}

    users = data.get('users') or []
    if isinstance(users, dict):
        users = [users]
    return {
        'users': [{'name': str(row.get('name') or ''), 'sid': str(row.get('sid') or ''),
                   'disabled': bool(row.get('disabled'))}
                  for row in users if isinstance(row, dict) and _SID.fullmatch(str(row.get('sid') or ''))],
        'admins': sids(data.get('admins')),
        'members': sids(data.get('members')),
        'administrators': sids(data.get('administrators')),
    }


def records_folder(users_root: Path, name: str) -> Path:
    return Path(users_root) / accounts.slug(name)


# ── scripts that need an administrator ───────────────────────────────────

def _safe(value: str) -> bool:
    return bool(_SAFE_NAME.match(str(value or '')))


def _group_lines() -> List[str]:
    """Create both groups if missing - through ADSI, which takes no localized text."""
    lines = ["$computer = [ADSI]('WinNT://' + $env:COMPUTERNAME + ',computer')"]
    for group in (machine.ADMINS_GROUP, machine.USERS_GROUP):
        lines.append(
            "if (-not [ADSI]::Exists('WinNT://' + $env:COMPUTERNAME + '/%s,group')) "
            "{ try { $made = $computer.Create('group', %s); $made.SetInfo() } "
            "catch { $failed = 1 } }" % (group, quote(group)))
    return lines


def _member_line(group: str, sid: str, present: bool) -> str:
    """Add or remove a member by SID (``WinNT://<SID>``), then check it took."""
    verb, want = ('Add', '$true') if present else ('Remove', '$false')
    return ("try { $g = [ADSI]('WinNT://' + $env:COMPUTERNAME + '/%s,group'); "
            "$m = 'WinNT://%s'; "
            "if ($g.psbase.Invoke('IsMember', $m) -ne %s) { [void]$g.psbase.Invoke('%s', $m) }; "
            "if ($g.psbase.Invoke('IsMember', $m) -ne %s) { $failed = 1 } } catch { $failed = 1 }"
            % (group, sid, want, verb, want))


def _shortcut_lines(app_dir: Path) -> List[str]:
    target = Path(app_dir) / 'RUN.bat'
    lines = ['$shell = New-Object -ComObject WScript.Shell']
    for folder in ("[Environment]::GetFolderPath('CommonDesktopDirectory')",
                   "[Environment]::GetFolderPath('CommonPrograms')"):
        lines.append(
            "try { $s = $shell.CreateShortcut((Join-Path (%s) 'LocalAI.lnk')); "
            "$s.TargetPath = %s; $s.WorkingDirectory = %s; $s.WindowStyle = 7; "
            "$s.Description = 'LocalAI'; $s.Save() } catch { }"
            % (folder, quote(target), quote(app_dir)))
    return lines


def first_install_script(user_sid: str, root: Path, app_dir: Path,
                         *, shortcuts=True) -> Optional[str]:
    """Groups, this account as administrator, the shared root locked, shortcuts.

    The root keeps SYSTEM and Administrators, gives this account and
    LocalAI-Admins full control and every account read/execute. Folders with
    their own grants (models, users) keep them; what changes is the
    ``Authenticated Users: Modify`` inherited from C:\\, which let any account
    replace the program everyone else runs.
    """
    if not machine.is_sid(user_sid):
        return None
    lines = ['$failed = 0'] + _group_lines() + [
        _member_line(machine.ADMINS_GROUP, user_sid, True),
        "$admins = $null; try { $admins = (New-Object System.Security.Principal.NTAccount(%s))"
        ".Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $failed = 1 }"
        % quote(machine.ADMINS_GROUP),
    ]
    lines += lock_root_lines(root, admin_sids=(user_sid,), group_variable='$admins',
                             principal=machine.Policy().principal())
    if shortcuts:
        lines += _shortcut_lines(app_dir)
    lines.append('exit $failed')
    return '\n'.join(lines)


def lock_root_lines(root: Path, *, admin_sids: Iterable[str], principal: str,
                    group_variable: Optional[str] = None) -> List[str]:
    grants = ['*%s:(OI)(CI)F' % privacy.SYSTEM_SID, '*%s:(OI)(CI)F' % privacy.ADMINISTRATORS_SID]
    grants += ['*%s:(OI)(CI)F' % sid for sid in admin_sids if machine.is_sid(sid)]
    grants.append('*%s:(OI)(CI)RX' % principal)
    lines = ['$grants = @(%s)' % ', '.join("'/grant:r', %s" % quote(g) for g in grants)]
    if group_variable:
        lines.append("if (%s) { $grants += @('/grant:r', ('*' + %s + ':(OI)(CI)F')) }"
                     % (group_variable, group_variable))
    lines.append("& icacls.exe %s /inheritance:r @grants /Q | Out-Null; "
                 "if ($LASTEXITCODE -ne 0) { $failed = 1 }" % quote(root))
    return lines


def lock_root_command(root: Path, policy: machine.Policy) -> List[str]:
    """The same root lock as an icacls argument list, for an administrator
    who already holds full control (no UAC needed)."""
    command = ['icacls', str(root), '/inheritance:r',
               '/grant:r', '*%s:(OI)(CI)F' % privacy.SYSTEM_SID,
               '/grant:r', '*%s:(OI)(CI)F' % privacy.ADMINISTRATORS_SID]
    for sid in policy.admin_sids():
        command += ['/grant:r', '*%s:(OI)(CI)F' % sid]
    command += ['/grant:r', '*%s:(OI)(CI)RX' % policy.principal(), '/Q']
    return command


def remove_grants_command(path: Path, sid: str, *, tree=False) -> List[str]:
    """Drop every explicit grant to ``sid`` on ``path`` (and below, for ``tree``).

    ``/grant:r`` replaces a listed SID's entries but leaves unlisted ones, so a
    removed administrator or a retired principal has to be removed by name.
    """
    command = ['icacls', str(path), '/remove:g', '*' + sid]
    return command + (['/T', '/C', '/Q'] if tree else ['/Q'])


def access_commands(root: Path, policy: machine.Policy, previous: str) -> List[List[str]]:
    """Point every shared grant at ``policy.principal()`` instead of ``previous``.

    The same five places Setup grants "every account": the root (read and
    run the program), the model store (manage models), the runtimes (read
    and run), the users parent (create one's own folder) and the shared
    runtime lock (take it). Run by a LocalAI administrator, who holds full
    control of all of them, so no UAC prompt is needed.
    """
    root = Path(root)
    new = policy.principal()
    changed = previous.upper() != new.upper()
    commands = []
    if changed:
        commands.append(remove_grants_command(root, previous))
    commands.append(lock_root_command(root, policy))
    for name, rights in (('models', '(OI)(CI)(M)'), ('environment', '(OI)(CI)(RX)'),
                         ('ollama', '(OI)(CI)(RX)')):
        path = root / name
        if changed:
            commands.append(remove_grants_command(path, previous, tree=True))
        commands.append(['icacls', str(path), '/grant', '*%s:%s' % (new, rights), '/T', '/C', '/Q'])
    users = root / 'users'
    if changed:
        commands.append(remove_grants_command(users, previous))
    commands.append(['icacls', str(users), '/grant', '*%s:(RD,X,AD,RA,REA)' % new, '/Q'])
    lock = root / 'environment' / 'desktop-runtime.lock'
    if changed:
        commands.append(remove_grants_command(lock, previous))
    commands.append(['icacls', str(lock), '/grant', '*%s:(R,W)' % new, '/Q'])
    return commands


def membership_script(group: str, sid: str, present: bool) -> Optional[str]:
    if not machine.is_sid(sid) or group not in (machine.ADMINS_GROUP, machine.USERS_GROUP):
        return None
    return '\n'.join(['$failed = 0'] + _group_lines()
                     + [_member_line(group, sid, present), 'exit $failed'])


def delete_records_script(folder: Path, users_root: Path) -> Optional[str]:
    """Remove one account's records folder - only a folder directly in ``users``.

    Ownership goes to Administrators first (``icacls /setowner``, not the
    localized ``takeown /D Y``), so a tree whose ACL names only its owner can
    still be deleted. Nothing is read on the way: the files stay encrypted
    with that account's key until they are gone.
    """
    folder, users_root = Path(folder), Path(users_root)
    if folder.parent != users_root or not _safe(str(folder)):
        return None
    admins = '*%s' % privacy.ADMINISTRATORS_SID
    return '\n'.join([
        '$failed = 0',
        "$target = %s" % quote(folder),
        "if (Test-Path -LiteralPath $target) {",
        "  & icacls.exe $target /setowner %s /T /C /Q 2>&1 | Out-Null" % quote(admins),
        "  & icacls.exe $target /grant %s /T /C /Q 2>&1 | Out-Null" % quote(admins + ':(OI)(CI)F'),
        "  Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue",
        "  if (Test-Path -LiteralPath $target) { $failed = 1 }",
        "}",
        'exit $failed',
    ])


__all__ = ['powershell', 'quote', 'encoded', 'run_script', 'run_as_admin',
           'token_group_sids', 'account_name', 'group_sid', 'list_accounts',
           'records_folder', 'first_install_script', 'lock_root_lines',
           'lock_root_command', 'remove_grants_command', 'access_commands',
           'membership_script', 'delete_records_script']
