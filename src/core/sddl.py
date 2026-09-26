"""Read a Windows security descriptor without depending on the display language.

``icacls`` prints account names in the language Windows is installed in, so on
a Korean install an ACL lists ``BUILTIN\\사용자`` rather than ``BUILTIN\\Users``.
Matching the English name reported every Korean machine as unreadable -
permanently, including right after a repair that had actually worked. SDDL
names the same group ``BU`` whatever the display language, so that is what is
parsed here.

Two questions are asked of the same descriptor, from opposite directions: can
the machine's other accounts read the shared model store (they must), and can
they read one account's own records (they must not). Both are the same parse,
so it lives in one place.
"""
from __future__ import annotations

import re
from typing import Optional

#: Groups that mean "somebody other than the owner", by their language-neutral
#: SDDL abbreviation. A grant to any of these makes a folder readable by the
#: machine's other accounts.
USERS_SDDL = 'BU'                 # BUILTIN\Users
USERS_SID = 'S-1-5-32-545'
EVERYONE_SDDL = 'WD'              # Everyone
AUTHENTICATED_SDDL = 'AU'         # Authenticated Users
INTERACTIVE_SDDL = 'IU'           # Interactive (anyone logged on at the console)

EVERYONE_SID = 'S-1-1-0'
AUTHENTICATED_SID = 'S-1-5-11'
INTERACTIVE_SID = 'S-1-5-4'

#: Every way of naming "not just me", for a privacy question.
OTHER_ACCOUNTS = (USERS_SDDL, USERS_SID, EVERYONE_SDDL, EVERYONE_SID,
                  AUTHENTICATED_SDDL, AUTHENTICATED_SID,
                  INTERACTIVE_SDDL, INTERACTIVE_SID)

# Access-mask bits that matter for "can another account read this file".
FILE_READ_DATA = 0x1
FILE_WRITE_DATA = 0x2
FILE_APPEND_DATA = 0x4
FILE_DELETE_CHILD = 0x40
DELETE = 0x10000
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
GENERIC_ALL = 0x10000000

# SDDL rights aliases, expanded to their masks. Execute-only aliases are here
# too and deliberately lack FILE_READ_DATA: running a file is not reading it.
_RIGHTS = {
    'FA': 0x1F01FF, 'FR': 0x120089, 'FW': 0x120116, 'FX': 0x1200A0,
    'GA': GENERIC_ALL, 'GR': GENERIC_READ, 'GW': 0x40000000, 'GX': 0x20000000,
    'KA': 0xF003F, 'KR': 0x20019, 'KW': 0x20006, 'KX': 0x20019,
}


def mask(text: str) -> int:
    """An SDDL rights field as a number. Aliases concatenate, so sum them."""
    text = (text or '').strip()
    if not text:
        return 0
    try:
        return int(text, 16) if text.lower().startswith('0x') else int(text)
    except ValueError:
        pass
    total = 0
    for index in range(0, len(text) - 1, 2):
        total |= _RIGHTS.get(text[index:index + 2].upper(), 0)
    return total


def grants_read(value: int) -> bool:
    return bool(value & (FILE_READ_DATA | GENERIC_READ | GENERIC_ALL))


def grants_modify(value: int) -> bool:
    """Enough rights to create/replace/delete shared model-store children."""
    if value & GENERIC_ALL:
        return True
    readable = grants_read(value)
    writable = bool(value & (FILE_WRITE_DATA | FILE_APPEND_DATA | GENERIC_WRITE))
    deletable = bool(value & (DELETE | FILE_DELETE_CHILD))
    return readable and writable and deletable


def modify_access(sddl: str, accounts) -> Optional[bool]:
    """Can any of accounts modify children, per this descriptor?

    LocalAI grants the Windows Modify preset. The saved SDDL commonly expands
    that preset to a numeric mask, so inspect rights rather than localized
    icacls display text. An explicit deny that intersects the required access
    wins over an allow.
    """
    if not isinstance(sddl, str) or 'D:' not in sddl:
        return None
    body = sddl[sddl.index('D:'):]
    aces = re.findall(r'\(([^()]*)\)', body)
    if not aces:
        return None
    wanted = {str(name).upper() for name in accounts}
    allowed = False
    for ace in aces:
        parts = ace.split(';')
        if len(parts) < 6:
            continue
        kind, _flags, rights, _obj, _inherit, account = (p.strip() for p in parts[:6])
        if account.upper() not in wanted:
            continue
        value = mask(rights)
        if kind.upper().startswith('D') and (
            grants_read(value)
            or value & (FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_DELETE_CHILD
                        | DELETE | GENERIC_WRITE | GENERIC_ALL)
        ):
            return False
        if kind.upper().startswith('A') and grants_modify(value):
            allowed = True
    return allowed


def read_access(sddl: str, accounts) -> Optional[bool]:
    """Can any of ``accounts`` read, per this descriptor? None if unparsable.

    An explicit deny wins over any allow, the way Windows evaluates it.
    """
    if not isinstance(sddl, str) or 'D:' not in sddl:
        return None
    body = sddl[sddl.index('D:'):]
    aces = re.findall(r'\(([^()]*)\)', body)
    if not aces:
        return None
    wanted = {str(name).upper() for name in accounts}
    allowed = False
    for ace in aces:
        parts = ace.split(';')
        if len(parts) < 6:
            continue
        kind, _flags, rights, _obj, _inherit, account = (p.strip() for p in parts[:6])
        if account.upper() not in wanted:
            continue
        if not grants_read(mask(rights)):
            continue
        if kind.upper().startswith('D'):
            return False
        if kind.upper().startswith('A'):
            allowed = True
    return allowed


__all__ = ['USERS_SDDL', 'USERS_SID', 'EVERYONE_SDDL', 'AUTHENTICATED_SDDL',
           'INTERACTIVE_SDDL', 'EVERYONE_SID', 'AUTHENTICATED_SID',
           'INTERACTIVE_SID', 'OTHER_ACCOUNTS',
           'FILE_READ_DATA', 'FILE_WRITE_DATA', 'FILE_APPEND_DATA',
           'FILE_DELETE_CHILD', 'DELETE', 'GENERIC_READ', 'GENERIC_WRITE',
           'GENERIC_ALL', 'mask', 'grants_read', 'grants_modify',
           'read_access', 'modify_access']
