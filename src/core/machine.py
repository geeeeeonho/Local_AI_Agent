"""Who administers this PC's LocalAI, and who may use it.

The first Windows account to install LocalAI becomes its administrator. Two
local groups carry the roles from then on, so Windows - not a file LocalAI
could be talked out of - enforces them:

``LocalAI-Admins``
    May update the shared program and runtimes, manage the model store's
    access, and manage the other accounts: allow or remove them, make them
    administrators, delete their records. Never read them - those are
    encrypted with each account's own key (``core.vault``).

``LocalAI-Users``
    Used only when access is restricted to members. By default every account
    on the PC may use LocalAI (``BUILTIN\\Users``).

The policy file beside the shared folders records the decisions. Only
administrators can write it; everyone can read it. A role is still checked
against Windows - the file only remembers SIDs Windows already enforces.

This module decides; ``integrations.windows.machine`` touches the machine.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple

from core import sddl

ADMINS_GROUP = 'LocalAI-Admins'
USERS_GROUP = 'LocalAI-Users'

ACCESS_EVERYONE = 'everyone'
ACCESS_MEMBERS = 'members'

POLICY_FILENAME = 'machine.json'
SCHEMA = 1

_SID = re.compile(r'S-1-\d+(?:-\d+)+')


def is_sid(value) -> bool:
    return isinstance(value, str) and bool(_SID.fullmatch(value))


@dataclass
class Policy:
    """What this machine decided. SIDs only - names change, SIDs do not."""

    admins: Tuple[str, ...] = ()
    access: str = ACCESS_EVERYONE
    admins_group_sid: Optional[str] = None
    users_group_sid: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    schema: int = SCHEMA
    notes: dict = field(default_factory=dict)

    def principal(self) -> str:
        """The SID that stands for "accounts allowed to use LocalAI"."""
        if self.access == ACCESS_MEMBERS and is_sid(self.users_group_sid):
            return self.users_group_sid
        return sddl.USERS_SID

    def admin_sids(self) -> Tuple[str, ...]:
        """Every SID given full control of the shared folders."""
        sids = [sid for sid in self.admins if is_sid(sid)]
        if is_sid(self.admins_group_sid):
            sids.append(self.admins_group_sid)
        seen, ordered = set(), []
        for sid in sids:
            if sid.upper() not in seen:
                seen.add(sid.upper())
                ordered.append(sid)
        return tuple(ordered)

    def is_admin(self, user_sid: Optional[str], token_groups: Iterable[str] = ()) -> bool:
        """Listed directly, or a member of LocalAI-Admins in this logon token."""
        if user_sid and any(user_sid.upper() == sid.upper() for sid in self.admins):
            return True
        groups = {str(sid).upper() for sid in token_groups}
        return bool(self.admins_group_sid and self.admins_group_sid.upper() in groups)

    def with_admin(self, sid: str, present: bool = True) -> 'Policy':
        rest = tuple(item for item in self.admins if item.upper() != sid.upper())
        return Policy(**{**asdict(self), 'admins': rest + ((sid,) if present else ())})

    def to_json(self) -> str:
        data = asdict(self)
        data['admins'] = list(self.admins)
        return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


def new_policy(first_admin: str, *, admins_group_sid=None, users_group_sid=None) -> Policy:
    return Policy(admins=(first_admin,), access=ACCESS_EVERYONE,
                  admins_group_sid=admins_group_sid, users_group_sid=users_group_sid,
                  created_by=first_admin,
                  created_at=datetime.now(timezone.utc).isoformat())


def parse(text: str) -> Optional[Policy]:
    """A policy from its JSON, or None when it is not one this version reads."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        return None
    admins = tuple(sid for sid in data.get('admins') or () if is_sid(sid))
    access = data.get('access')
    if access not in (ACCESS_EVERYONE, ACCESS_MEMBERS):
        access = ACCESS_EVERYONE
    def sid_or_none(key):
        value = data.get(key)
        return value if is_sid(value) else None
    return Policy(admins=admins, access=access,
                  admins_group_sid=sid_or_none('admins_group_sid'),
                  users_group_sid=sid_or_none('users_group_sid'),
                  created_by=sid_or_none('created_by'),
                  created_at=str(data.get('created_at') or '') or None,
                  notes=data.get('notes') if isinstance(data.get('notes'), dict) else {})


def load(path) -> Optional[Policy]:
    try:
        return parse(Path(path).read_text(encoding='utf-8'))
    except OSError:
        return None


def first_admin_candidate(owner: Optional[str], user_sid: Optional[str]) -> bool:
    """May this account become the first administrator?

    The account that created the LocalAI folder is the first installer. A
    folder owned by the Administrators group (an elevated install) or by
    nobody readable names no one, and then whoever runs Setup first - with
    the UAC prompt that requires - takes the role.
    """
    if not user_sid:
        return False
    if owner and is_sid(owner) and owner.upper().startswith('S-1-5-21-'):
        return owner.upper() == user_sid.upper()
    return True


__all__ = ['ADMINS_GROUP', 'USERS_GROUP', 'ACCESS_EVERYONE', 'ACCESS_MEMBERS',
           'POLICY_FILENAME', 'Policy', 'new_policy', 'parse', 'load', 'is_sid',
           'first_admin_candidate']
