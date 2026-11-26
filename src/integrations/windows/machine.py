"""The Windows side of LocalAI administration: groups, accounts, one UAC prompt.

Everything here that changes the machine - creating the two local groups,
adding a member, deleting another account's records, making the Start menu
shortcut every account sees - needs a Windows administrator. Each such change is one
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


def run_as_admin(script: str, *, log=None, timeout=900, report_path=None) -> bool:
    """Elevate once and report actual script failure, not misleading UAC denial.

    A diagnostic file is emitted by the elevated script itself only on
    nonzero exit. This path must be random and guarded by the caller; no
    file from an arbitrary path is executed or trusted as an instruction.
    """
    say = log or (lambda message: None)

    def report_failure(code, stderr=''):
        say('관리자 권한 작업은 시작됐지만 실패했습니다 (종료 코드 %d).' % code)
        details = ''
        if report_path is not None:
            try:
                details = Path(report_path).read_text(encoding='utf-8-sig')[:1600].strip()
            except OSError:
                pass
        if not details and stderr:
            details = str(stderr).strip()[-1600:]
        if details:
            say('실패 단계: ' + details)
        elif report_path is not None:
            say('상세 원인 기록을 읽지 못했습니다. 확인 위치: ' + str(report_path))

    if os.environ.get(privacy.NO_ELEVATION_VARIABLE, '').strip() in ('1', 'true', 'yes'):
        say('관리자 작업을 건너뜁니다 (%s=1).' % privacy.NO_ELEVATION_VARIABLE)
        return False
    if acl.is_elevated():
        result = run_script(script, timeout=timeout)
        if acl.succeeded(result):
            return True
        report_failure(result.returncode if result is not None else 1,
                       (result.stderr or '') if result is not None else '')
        return False
    say('Windows 관리자 승인이 필요합니다. 확인 창(UAC)에서 [예]를 누르세요.')
    code, error = acl.run_elevated(
        powershell(),
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden '
        '-EncodedCommand ' + encoded(script),
        timeout=timeout)
    if code is None:
        if error == acl.ERROR_CANCELLED:
            say('Windows 관리자 승인이 취소되었습니다.')
        elif error is not None:
            say('관리자 프로세스를 시작하지 못했습니다: ' + acl.describe_error(error))
        else:
            say('관리자 프로세스를 시작하거나 결과를 확인하지 못했습니다.')
        return False
    if code != 0:
        report_failure(code)
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


#: A local group's SID never changes once the group exists. Only found SIDs
#: are remembered, so a group created later by UAC is seen on the next ask.
_GROUP_SIDS: dict = {}


def group_sid(name: str) -> Optional[str]:
    if name in _GROUP_SIDS:
        return _GROUP_SIDS[name]
    # Always qualify local groups by this machine's name. A bare name can
    # resolve to a different domain principal or fail on localized systems.
    script = ("$localGroup = $env:COMPUTERNAME + '\\' + %s; "
              "try { ([System.Security.Principal.NTAccount]::new($localGroup))"
              ".Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { }"
              % quote(name))
    result = run_script(script, timeout=30)
    found = _SID.findall((result.stdout or '') if result is not None else '')
    if found:
        _GROUP_SIDS[name] = found[0]
    return found[0] if found else None


_LIST_SCRIPT = r'''
$ErrorActionPreference = 'SilentlyContinue'
function Members($name) {
  $out = @()
  try {
    $g = [ADSI]("WinNT://$env:COMPUTERNAME/$name,group")
    foreach ($m in @($g.Invoke('Members'))) {
      $raw = $m.GetType().InvokeMember('objectSid', 'GetProperty', $null, $m, $null)
      $out += ([System.Security.Principal.SecurityIdentifier]::new([byte[]]$raw, 0)).Value
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


_MEMBERS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$g = [ADSI]("WinNT://$env:COMPUTERNAME/GROUP_NAME,group")
$out = @()
foreach ($m in @($g.Invoke('Members'))) {
  $raw = $m.GetType().InvokeMember('objectSid', 'GetProperty', $null, $m, $null)
  $out += ([System.Security.Principal.SecurityIdentifier]::new([byte[]]$raw, 0)).Value
}
'members=' + ($out -join ',')
'''


def group_member_sids(name: str) -> Optional[Set[str]]:
    """Current members of a local group by SID, or None if not readable.

    ADSI reads the account database, not this logon token, so a member added
    a moment ago by the first-install UAC script is already listed here.
    """
    if name not in (machine.ADMINS_GROUP, machine.USERS_GROUP):
        return None
    result = run_script(_MEMBERS_SCRIPT.replace('GROUP_NAME', name), timeout=30)
    text = (result.stdout or '') if acl.succeeded(result) else ''
    marker = text.rfind('members=')
    if marker < 0:
        return None
    return {sid.upper() for sid in _SID.findall(text[marker:])}


def trusted_policy(policy: Optional[machine.Policy], *,
                   members: bool = True) -> Optional[machine.Policy]:
    """``policy`` reduced to what Windows enforces (``core.machine.reconcile``).

    ``members=False`` skips the membership lookup for callers that only need
    the read/execute principal; the administrator list is then emptied.
    """
    if policy is None:
        return None
    admins_group = group_sid(machine.ADMINS_GROUP)
    users_group = group_sid(machine.USERS_GROUP)
    listed = group_member_sids(machine.ADMINS_GROUP) if (members and admins_group) else None
    return machine.reconcile(policy, admins_group_sid=admins_group,
                             users_group_sid=users_group, admin_members=listed)


def load_trusted_policy(root, *, members: bool = True) -> Optional[machine.Policy]:
    return trusted_policy(machine.load(Path(root) / machine.POLICY_FILENAME),
                          members=members)


def records_folder(users_root: Path, name: str) -> Path:
    return Path(users_root) / accounts.slug(name)


# ── scripts that need an administrator ───────────────────────────────────

def lockable_root(root) -> bool:
    """Is ``root`` a folder whose inheritance LocalAI may cut?

    ``LOCAL_AI_ROOT`` can point anywhere. Locking a drive root, the Windows
    folder or a profile folder would lock the machine's other software out
    of its own files, so only a dedicated folder at least one level below a
    drive root, and not one of those, qualifies.
    """
    path = Path(root)
    if path.parent == path or not path.name:
        return False
    protected = []
    for variable in ('SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)',
                     'ProgramData', 'USERPROFILE', 'PUBLIC'):
        value = os.environ.get(variable)
        if value:
            protected.append(Path(value))
    protected.append(Path(os.environ.get('SystemDrive', 'C:') + '\\') / 'Users')
    key = os.path.normcase(str(path)).rstrip('\\/')
    for item in protected:
        other = os.path.normcase(str(item)).rstrip('\\/')
        if key == other or other.startswith(key + os.sep):
            return False
    return True


def _safe(value: str) -> bool:
    return bool(_SAFE_NAME.match(str(value or '')))


def _group_lines() -> List[str]:
    """Create both groups if missing - through ADSI, which takes no localized text."""
    lines = ["$computer = [ADSI]('WinNT://' + $env:COMPUTERNAME + ',computer')"]
    for group in (machine.ADMINS_GROUP, machine.USERS_GROUP):
        lines.append(
            "if (-not [ADSI]::Exists('WinNT://' + $env:COMPUTERNAME + '/%s,group')) "
            "{ try { $made = $computer.Create('group', %s); $made.SetInfo() } "
            "catch { $failed = 1; "
            "if ($null -ne $localaiIssues) { "
            "[void]$localaiIssues.Add('create group %s: ' + $_.Exception.Message) } } }"
            % (group, quote(group), group))
    return lines


def _member_line(group: str, sid: str, present: bool) -> str:
    """Add/remove a SID and verify by enumerating the actual member SIDs.

    Microsoft explicitly documents that WinNT IADsGroup.IsMember does NOT
    support a SID ADsPath even though IADsGroup.Add/Remove support it. The
    old implementation therefore marked a successful install as exit-code 1.
    """
    verb, want = ('Add', '$true') if present else ('Remove', '$false')
    return (
        # TestGroupSid reads objectSid of each COM member, the same
        # language-independent route used by list_accounts().
        "function Test-LocalAISidMember($groupObj, $targetSid) { "
        "foreach ($entry in @($groupObj.psbase.Invoke('Members'))) { "
        "try { $raw = $entry.GetType().InvokeMember('objectSid', 'GetProperty', $null, $entry, $null); "
        "$found = ([System.Security.Principal.SecurityIdentifier]::new([byte[]]$raw, 0)).Value; "
        "if ($found -ieq $targetSid) { return $true } } catch { } "
        "} return $false }; "
        "try { $g = [ADSI]('WinNT://' + $env:COMPUTERNAME + '/%s,group'); "
        "$target = '%s'; $m = 'WinNT://' + $target; "
        "if ((Test-LocalAISidMember $g $target) -ne %s) { "
        "[void]$g.psbase.Invoke('%s', $m) }; "
        "if ((Test-LocalAISidMember $g $target) -ne %s) { "
        "$failed = 1; if ($null -ne $localaiIssues) { "
        "[void]$localaiIssues.Add('member %s: SID not present after update') } "
        "} } catch { $failed = 1; if ($null -ne $localaiIssues) { "
        "[void]$localaiIssues.Add('member %s: ' + $_.Exception.Message) } }"
        % (group, sid, want, verb, want, group, group)
    )

# Only the shared Start menu gets a LocalAI entry. Setup does not touch any
# desktop: the public desktop shows on every account, and RUN.bat in the
# program folder remains the entry point.
_SHORTCUT_FOLDERS = ("[Environment]::GetFolderPath('CommonPrograms')",)


def _shortcut_lines(app_dir: Path) -> List[str]:
    target = Path(app_dir) / 'RUN.bat'
    lines = ['$shell = New-Object -ComObject WScript.Shell']
    for folder in _SHORTCUT_FOLDERS:
        lines.append(
            "try { $s = $shell.CreateShortcut((Join-Path (%s) 'LocalAI.lnk')); "
            "$s.TargetPath = %s; $s.WorkingDirectory = %s; $s.WindowStyle = 7; "
            "$s.Description = 'LocalAI'; $s.Save() } catch { }"
            % (folder, quote(target), quote(app_dir)))
    return lines


def first_install_script(user_sid: str, root: Path, app_dir: Path,
                         *, shortcuts=True, report_path=None) -> Optional[str]:
    """Groups, this account as administrator, the shared root locked, shortcuts.

    The root keeps SYSTEM and Administrators, gives this account and
    LocalAI-Admins full control and every account read/execute. Private
    account folders (users) keep their own grants; what changes is the
    ``Authenticated Users: Modify`` inherited from C:\\, which let any account
    replace the program everyone else runs.
    """
    if not machine.is_sid(user_sid):
        return None
    lines = ['$failed = 0',
             '$localaiIssues = New-Object System.Collections.Generic.List[string]'] + _group_lines() + [
        _member_line(machine.ADMINS_GROUP, user_sid, True),
        "$admins = $null; try { $localGroup = $env:COMPUTERNAME + '\\' + %s; "
        "$admins = ([System.Security.Principal.NTAccount]::new($localGroup))"
        ".Translate([System.Security.Principal.SecurityIdentifier]).Value } "
        "catch { $failed = 1; [void]$localaiIssues.Add('admin group SID: ' + $_.Exception.Message) }"
        % quote(machine.ADMINS_GROUP),
    ]
    if lockable_root(root):
        # The legacy /grant:r call alone cannot remove an unknown explicit
        # Modify grant left on C:\\LocalAI. Replace the entire root DACL and
        # reset protected descendants in the *same* UAC transaction.
        from . import program_security
        lines += lock_root_lines(root, admin_sids=(user_sid,), group_variable='$admins',
                                 principal=machine.Policy().principal())
        lines += program_security.protection_lines(
            root, (user_sid,), machine.Policy().principal(),
            group_variable='$admins')
    if shortcuts:
        lines += _shortcut_lines(app_dir)
    if report_path is not None:
        # The random report path is created exclusively by elevated PowerShell.
        # It lives under the protected program root and is read by the
        # unelevated UI if the script exits non-zero.
        from pathlib import Path
        report = Path(report_path)
        if report.parent != Path(root) or not report.name.startswith('.localai-admin-'):
            raise ValueError("Unsafe administrator diagnostics path")
        lines.extend([
            'if ($failed -ne 0) {',
            "  try {",
            "    $reportText = @($localaiIssues | Select-Object -First 8) -join [Environment]::NewLine",
            "    if (-not $reportText) { $reportText = 'Unspecified Windows administrator step failed' }",
            "    $payload = [System.Text.Encoding]::UTF8.GetBytes($reportText)",
            "    $file = [System.IO.File]::Open(" + quote(report) +
            ", [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)",
            "    try { $file.Write($payload, 0, $payload.Length) } finally { $file.Dispose() }",
            "  } catch { }",
            '}',
        ])
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
    lines.append("$localaiAclOutput = & icacls.exe %s /inheritance:r @grants /Q 2>&1; "
                 "if ($LASTEXITCODE -ne 0) { $failed = 1; if ($null -ne $localaiIssues) { "
                 "[void]$localaiIssues.Add('root ACL: ' + "
                 "(($localaiAclOutput | Out-String).Trim())) } }" % quote(root))
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
    run the program), the model store (read models - only administrators
    change them), the runtimes (read and run), the users parent (create
    one's own folder) and the shared runtime lock (take it). Run by a LocalAI administrator, who holds full
    control of all of them, so no UAC prompt is needed.
    """
    root = Path(root)
    new = policy.principal()
    changed = previous.upper() != new.upper()
    commands = []
    if changed:
        commands.append(remove_grants_command(root, previous))
    commands.append(lock_root_command(root, policy))
    for name, rights in (('models', '(OI)(CI)(RX)'), ('environment', '(OI)(CI)(RX)'),
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
           'records_folder', 'group_member_sids', 'trusted_policy',
           'load_trusted_policy', 'lockable_root', 'first_install_script', 'lock_root_lines',
           'lock_root_command', 'remove_grants_command', 'access_commands',
           'membership_script', 'delete_records_script']
