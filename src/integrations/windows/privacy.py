"""Close one account's records folder to the machine's other accounts.

The model store under the same root is deliberately readable by
``BUILTIN\\Users`` - that is how a second Windows account uses the models
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
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from core import accounts, sddl
from . import acl

#: Language-neutral SIDs for the three that keep access.
SYSTEM_SID = 'S-1-5-18'
ADMINISTRATORS_SID = 'S-1-5-32-544'
CREATOR_OWNER_SID = 'S-1-3-0'


def owner_token(environ=None) -> str:
    """How to name "this account" to icacls.

    ``%USERDOMAIN%\\%USERNAME%`` is what Windows itself uses and works for a
    local account and a domain one alike. Falling back to the bare name covers
    a machine that does not set USERDOMAIN.
    """
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


def make_private(path, *, windows=None, environ=None) -> bool:
    """Break inheritance and leave only the owner, SYSTEM and Administrators.

    ``/inheritance:r`` copies the inherited entries into the folder before
    removing the link, which would keep the very grant being removed, so
    ``/grant:r`` replaces the list outright in the same call.
    """
    path = Path(path)
    if not acl.on_windows(windows):
        return True
    if not path.exists():
        return False
    command = ['icacls', str(path), '/inheritance:r']
    for entry in grants(environ):
        command += ['/grant:r', entry]
    command += ['/T', '/C', '/Q']
    return acl.succeeded(acl.run(command, timeout=120))


def ensure_private(path, *, windows=None, environ=None) -> Optional[bool]:
    """Make it private if it is not already. The answer is the final state.

    Idempotent, and cheap when nothing is wrong: reading the descriptor costs
    one ``icacls /save`` and rewriting a large tree does not happen on every
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
           'owner_token', 'grants', 'is_private', 'current_user_can_write',
           'make_private', 'ensure_private', 'describe']
