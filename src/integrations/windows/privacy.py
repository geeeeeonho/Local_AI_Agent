"""Close one account's records folder to the machine's other accounts.

The model store under the same root deliberately grants ``BUILTIN\\Users``
Modify - that is how a second Windows account can use and manage the models
without downloading them again. A folder created underneath inherits that
grant, so ``C:\\LocalAI\\users\\Someone\\user_data`` would be readable by everyone
on the PC the moment it is created: settings, project list, chat history, the
AnythingLLM vector store, every agent trace.

Being in the right place is therefore not enough. The inheritance has to be
broken and the ACL rewritten to the owner, SYSTEM and Administrators - and
then read back, because a failure here is silent and the thing it protects is
the user's own record of what they asked an AI to do.

Administrators keep access on purpose: locking out the only account that can
repair a broken ACL, or run a backup, turns one bad permission into an
unrecoverable folder. SYSTEM keeps it because Windows services - search
indexing, Defender, Volume Shadow Copy - need it, and removing it breaks
backups rather than improving privacy.

The lock is done in two steps. The folder itself is rewritten on its own - one
object, so it either succeeds or says exactly why not - and everything already
inside is then reset to inherit from it. Doing both in one ``/T`` pass made a
single stale file below (a log an elevated run left behind, a lock file held by
another process) fail the whole call, and Setup stopped on a folder whose own
ACL was perfectly fine.

When the signed-in token cannot rewrite the folder at all - it is owned by
Administrators after a "Run as administrator" install - the repair asks
Windows for elevation once, gives the folder back to this account's SID, and
the ordinary check runs again as the user.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Optional

from core import accounts, sddl
from . import acl

#: Language-neutral SIDs for the three that keep access.
SYSTEM_SID = 'S-1-5-18'
ADMINISTRATORS_SID = 'S-1-5-32-544'
CREATOR_OWNER_SID = 'S-1-3-0'

#: Set to 1 to never show a UAC prompt from Setup (automation, CI).
NO_ELEVATION_VARIABLE = 'LOCAL_AI_NO_ELEVATION'

#: Characters that would change the meaning of a ``cmd /c`` line.
_UNSAFE_FOR_CMD = re.compile(r'["%^&|<>!\r\n]')
_SID = re.compile(r'S-1-\d+(?:-\d+)+')

_OWNER_NAMES = {
    'BA': 'Administrators 그룹', ADMINISTRATORS_SID: 'Administrators 그룹',
    'SY': 'SYSTEM', SYSTEM_SID: 'SYSTEM',
}


def owner_token(environ=None) -> str:
    """How to name "this account" to icacls.

    This process's own SID (``*S-1-5-21-...``) when it can be read: it needs no
    name lookup, so it works for a local, Microsoft, Entra ID or domain account
    alike. ``%USERDOMAIN%\\%USERNAME%`` is the fallback, and is what an explicit
    ``environ`` - naming an account rather than this process - asks for.
    """
    if environ is None:
        sid = acl.current_user_sid()
        if sid:
            return '*' + sid
    environ = os.environ if environ is None else environ
    name = accounts.current_name(environ)
    domain = environ.get('USERDOMAIN')
    return ('%s\\%s' % (domain, name)) if domain else name


def grants(environ=None) -> list:
    """The only entries the private folder should hold, in icacls syntax."""
    return ['%s:(OI)(CI)F' % owner_token(environ),
            '*%s:(OI)(CI)F' % SYSTEM_SID,
            '*%s:(OI)(CI)F' % ADMINISTRATORS_SID]


def is_private(path, *, windows=None) -> Optional[bool]:
    """Is this folder closed to the other accounts? None when unreadable.

    ``None`` is not ``False``. A caller that cannot read the ACL must say it
    does not know, rather than telling the user their records are exposed - or,
    worse, that they are safe.
    """
    path = Path(path)
    if not acl.on_windows(windows):
        return None
    if not path.exists():
        return None
    text = acl.saved_sddl(path)
    if text is None:
        return None
    for line in text.splitlines():
        answer = accounts.private_from_sddl(line.strip())
        if answer is not None:
            return answer
    return None


def current_user_can_write(path) -> bool:
    """Prove this process can create and remove a file in the private folder."""
    path = Path(path)
    if not path.exists() or not path.is_dir():
        return False
    probe = path / (".localai-write-probe-%d" % os.getpid())
    try:
        with probe.open("xb") as stream:
            stream.write(b"ok")
        probe.unlink()
        return True
    except FileExistsError:
        try:
            probe.unlink()
        except OSError:
            pass
        return False
    except OSError:
        return False


def unwritable_files(folder, *, limit=5000) -> list:
    """Files below ``folder`` whose ACL no longer lets this process append.

    Opening for append changes nothing. It is the exact operation that failed
    on ``ollama_run.log``, so it is the honest test of whether a stale child
    ACL still blocks the account that owns the tree. Two refusals are not ACL
    problems and are skipped, because no permission repair can fix them: a
    file another process holds open (sharing violation, Windows error 32) and
    a file with the read-only attribute.
    """
    folder = Path(folder)
    found, seen = [], 0
    if not folder.is_dir():
        return found
    for root, _dirs, files in os.walk(folder):
        for name in files:
            seen += 1
            if seen > limit:
                return found
            target = Path(root) / name
            try:
                if not os.stat(target).st_mode & stat.S_IWRITE:
                    continue
                handle = os.open(str(target), os.O_WRONLY | os.O_APPEND)
            except PermissionError as exc:
                if getattr(exc, 'winerror', None) in (None, acl.ERROR_ACCESS_DENIED):
                    found.append(target)
                continue
            except OSError:
                continue
            os.close(handle)
    return found


def lock_command(path, environ=None) -> list:
    """Rewrite one folder's own DACL: protected, three explicit grants.

    ``/inheritance:r`` drops the inherited entries and ``/grant:r`` replaces
    the explicit ones in the same call, so nothing from the parent survives.
    """
    command = ['icacls', str(path), '/inheritance:r']
    for entry in grants(environ):
        command += ['/grant:r', entry]
    return command + ['/Q']


def reset_children_command(path) -> list:
    """Make everything inside inherit from the locked folder and nothing else."""
    return ['icacls', str(Path(path) / '*'), '/reset', '/T', '/C', '/Q']


def reset_children(path, *, windows=None) -> bool:
    """Best effort: clear stale explicit ACLs below an already-locked folder.

    ``/C`` keeps going past the one object it cannot change, so a single file
    held by another process does not leave the rest of the tree as it was.
    """
    path = Path(path)
    if not acl.on_windows(windows):
        return True
    try:
        if not any(path.iterdir()):
            return True
    except OSError:
        pass
    return acl.succeeded(acl.run(reset_children_command(path), timeout=900))


def reset_tree(path, *, windows=None) -> bool:
    """Make a folder and everything in it inherit from its (private) parent."""
    path = Path(path)
    if not acl.on_windows(windows):
        return True
    if not path.exists():
        return False
    return acl.succeeded(acl.run(['icacls', str(path), '/reset', '/T', '/C', '/Q'],
                                 timeout=900))


def make_private(path, *, windows=None, environ=None) -> bool:
    """Lock the folder to this account, SYSTEM and Administrators.

    True means the folder's own DACL was replaced. Resetting what is already
    inside follows as a separate best-effort pass: the folder's ACL is what
    decides who can open anything below it.
    """
    path = Path(path)
    if not acl.on_windows(windows):
        return True
    if not path.exists():
        return False
    if not acl.succeeded(acl.run(lock_command(path, environ), timeout=600)):
        return False
    reset_children(path, windows=windows)
    return True


def ensure_private(path, *, windows=None, environ=None) -> Optional[bool]:
    """Make it private if it is not already. The answer is the final state.

    Idempotent, and cheap when nothing is wrong: reading the descriptor costs
    one in-process API call and rewriting a large tree does not happen on every
    start.
    """
    already = is_private(path, windows=windows)
    # "Nobody else can read it" is only half the contract. An account folder
    # left by an elevated/different installer can be private while the signed-in
    # user cannot write runtime-state.json.lock inside it.
    if already is True and current_user_can_write(path):
        return True
    if not make_private(path, windows=windows, environ=environ):
        return already if already is not True else False
    final = is_private(path, windows=windows)
    if final is True and not current_user_can_write(path):
        return False
    return final


# ── when the signed-in token cannot fix its own folder ───────────────────

def _system_tool(name) -> str:
    root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    return str(Path(root) / 'System32' / name)


def admin_repair_commands(path, sid) -> list:
    """What an administrator runs to give the folder back to ``sid``.

    Ownership first: the owner can always rewrite a DACL, so once the tree
    belongs to the account again its own Setup can keep it right without
    elevation. Then the same lock and reset the ordinary repair does.
    """
    path = Path(path)
    grant = ['*%s:(OI)(CI)F' % sid, '*%s:(OI)(CI)F' % SYSTEM_SID,
             '*%s:(OI)(CI)F' % ADMINISTRATORS_SID]
    lock = ['icacls', str(path), '/inheritance:r']
    for entry in grant:
        lock += ['/grant:r', entry]
    return [
        ['icacls', str(path), '/setowner', '*' + sid, '/T', '/C', '/Q'],
        lock + ['/C', '/Q'],
        reset_children_command(path),
    ]


_SWITCH = re.compile(r'/[A-Za-z]+(?::[A-Za-z]+)?')


def _quoted(command) -> str:
    """One command line: switches bare, every path, SID and grant quoted."""
    return ' '.join(part if _SWITCH.fullmatch(part) else '"%s"' % part
                    for part in command)


def manual_repair_text(path, sid=None) -> str:
    """The same repair as lines a user can paste into an administrator prompt."""
    sid = sid or acl.current_user_sid() or '<whoami /user 의 SID>'
    return '\n'.join(_quoted(command) for command in admin_repair_commands(path, sid))


def _cmd_line(commands) -> Optional[str]:
    """``cmd /d /s /c`` parameters running every command, or None if unsafe.

    ``/s`` strips exactly the outer pair of quotes, so every quoted path inside
    reaches icacls intact. A path holding a character cmd would interpret is
    refused rather than escaped: this line runs as administrator.
    """
    icacls = _system_tool('icacls.exe')
    pieces = []
    for command in commands:
        parts = [icacls] + list(command[1:])
        if any(_UNSAFE_FOR_CMD.search(part) for part in parts):
            return None
        pieces.append(_quoted(parts))
    return '/d /s /c "%s"' % ' & '.join(pieces)


def repair_as_admin(path, *, windows=None, log=None) -> Optional[bool]:
    """Ask Windows for elevation once and give the folder back to this account.

    Returns the folder's state afterwards as the signed-in user sees it, or
    None when no elevated repair was attempted (not Windows, opted out, the SID
    is unknown, the user declined the prompt).
    """
    path = Path(path)
    if not acl.on_windows(windows) or not path.exists():
        return None
    if os.environ.get(NO_ELEVATION_VARIABLE, '').strip() in ('1', 'true', 'yes'):
        return None
    sid = acl.current_user_sid()
    if not sid or not _SID.fullmatch(sid):
        return None
    commands = admin_repair_commands(path, sid)
    say = log or (lambda message: None)
    if acl.is_elevated():
        say('관리자 권한으로 개인 폴더 소유권과 권한을 복구합니다: %s' % path)
        for command in commands:
            acl.run(command, timeout=900)
    else:
        parameters = _cmd_line(commands)
        if parameters is None:
            return None
        say('개인 폴더 권한 복구에 관리자 승인이 필요합니다. '
            'Windows 확인 창(UAC)에서 [예]를 누르세요: %s' % path)
        code, error = acl.run_elevated(_system_tool('cmd.exe'), parameters)
        if code is None:
            if error == acl.ERROR_CANCELLED:
                say('관리자 승인이 취소되어 권한을 복구하지 않았습니다.')
            elif error is not None:
                say('관리자 권한으로 실행하지 못했습니다: %s' % acl.describe_error(error))
            return None
    return ensure_private(path, windows=windows)


def diagnose(path, *, windows=None) -> dict:
    """Everything a user or a bug report needs about one private folder."""
    path = Path(path)
    sid = acl.current_user_sid() if acl.on_windows(windows) else None
    owner = acl.owner_sid(path) if acl.on_windows(windows) else None
    return {
        'path': str(path),
        'exists': path.exists(),
        'private': is_private(path, windows=windows),
        'writable': current_user_can_write(path),
        'user_sid': sid,
        'owner': owner,
        'owner_is_user': bool(owner and sid and owner.upper() == sid.upper()),
        'elevated': acl.is_elevated() if acl.on_windows(windows) else None,
        'read_error': acl.dacl_error(path) if acl.on_windows(windows) else None,
    }


def describe_diagnosis(report: dict) -> str:
    """The diagnosis in one line of plain words."""
    owner = report.get('owner')
    if report.get('owner_is_user'):
        owner_text = '현재 계정'
    elif owner:
        owner_text = '%s (%s)' % (_OWNER_NAMES.get(owner.upper(), '다른 계정'), owner)
    else:
        owner_text = '확인 불가'
    error = report.get('read_error')
    parts = [
        '현재 계정 SID: %s' % (report.get('user_sid') or '확인 불가'),
        '폴더 소유자: %s' % owner_text,
        'ACL 읽기: %s' % ('정상' if error is None and report.get('private') is not None
                          else acl.describe_error(error) if error is not None
                          else '실패'),
        '쓰기: %s' % ('가능' if report.get('writable') else '불가'),
    ]
    if report.get('elevated') is not None:
        parts.append('관리자 실행: %s' % ('예' if report['elevated'] else '아니오'))
    return ' · '.join(parts)


def describe(path, *, windows=None) -> str:
    """One line for the window: what is true, in the words a user needs."""
    state = is_private(path, windows=windows)
    if state is True:
        return '이 계정 전용입니다 · 다른 Windows 계정은 읽을 수 없습니다'
    if state is False:
        return ('이 PC의 다른 Windows 계정이 %s 를 읽을 수 있습니다 · '
                '[설치 / 복구]를 한 번 실행하면 이 계정 전용으로 잠급니다' % path)
    return '이 폴더의 접근 권한을 확인하지 못했습니다: %s' % path


__all__ = ['SYSTEM_SID', 'ADMINISTRATORS_SID', 'CREATOR_OWNER_SID',
           'NO_ELEVATION_VARIABLE',
           'owner_token', 'grants', 'is_private', 'current_user_can_write',
           'unwritable_files', 'lock_command', 'reset_children_command',
           'reset_children', 'reset_tree', 'make_private', 'ensure_private',
           'admin_repair_commands', 'manual_repair_text', 'repair_as_admin',
           'diagnose', 'describe_diagnosis', 'describe']
