"""One machine, one copy of the models, and one private folder per account.

The two halves of this product want opposite things from the filesystem.

The models are a *machine* asset. Tens of gigabytes that take a day to
download and are identical for everyone, so every Windows account on the PC
reads the same copy and nobody downloads them twice.

Everything a person does with them is *theirs*. Settings, projects, chat
history, the AnythingLLM vector store, agent traces, session logs. Another
account on the same PC has no business reading any of it, and sharing one
``user_data`` between accounts does not merely leak - it corrupts, because two
signed-in users write the same settings file and the same session state.

So the root splits:

    C:\\LocalAI\\models              shared, readable by every account
    C:\\LocalAI\\environment         shared, the installed runtimes
    C:\\LocalAI\\users\\<account>\\    private, one per Windows account

This module decides the naming and what an ACL means. Touching the real
machine is someone else's job, so the rules stay testable without Windows.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Optional

from core import sddl

#: Overrides the account this process belongs to. For tests and for a
#: deployment that runs the product as a service account but wants the records
#: filed under the person.
ACCOUNT_VARIABLE = 'LOCAL_AI_ACCOUNT'

#: Characters a folder name may keep. Deliberately narrow: this name ends up
#: in a ``docker -v`` argument, so a space or a non-ASCII character is not a
#: cosmetic problem - Docker Desktop refuses the mount and the sandbox never
#: starts.
_SAFE = re.compile(r'[^A-Za-z0-9._-]+')

#: Names Windows will not give a folder, whatever the filesystem says.
_RESERVED = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + ['COM%d' % n for n in range(1, 10)]
    + ['LPT%d' % n for n in range(1, 10)])

_MAX = 32


def _fingerprint(name: str) -> str:
    return hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:8]


def slug(name) -> str:
    """A folder name for a Windows account: safe, stable, and still readable.

    An ASCII account name is kept exactly, because ``C:\\LocalAI\\users\\Geonho``
    tells the owner whose folder it is at a glance. Anything else - a Korean
    name, a name with a space, a reserved device name - keeps what it can and
    carries a fingerprint of the original, so two accounts that sanitize to the
    same text still get separate folders. ``Hong Gil-dong`` and ``HongGil-dong``
    are different Windows accounts; without the fingerprint they would share
    one records folder, which is the failure this whole split exists to avoid.
    """
    name = '' if name is None else str(name).strip()
    cleaned = _SAFE.sub('', name).strip('._-')[:_MAX]
    if cleaned and cleaned == name and cleaned.upper() not in _RESERVED:
        return cleaned
    return '%s-%s' % (cleaned or 'user', _fingerprint(name))


def current_name(environ=None) -> str:
    """The signed-in account's name, as this machine reports it."""
    environ = os.environ if environ is None else environ
    for key in (ACCOUNT_VARIABLE, 'USERNAME', 'USER', 'LOGNAME'):
        value = environ.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return 'user'


def current_slug(environ=None) -> str:
    return slug(current_name(environ))


def private_from_sddl(descriptor: str) -> Optional[bool]:
    """Is this folder closed to the machine's other accounts? None if unknown.

    A folder created under a root that grants ``BUILTIN\\Users`` read - which
    the model store deliberately does - inherits that grant. So the private
    folder is not private by being in the right place; the inheritance has to
    be broken, and this is how the program checks that it was.
    """
    readable = sddl.read_access(descriptor, sddl.OTHER_ACCOUNTS)
    return None if readable is None else not readable


__all__ = ['ACCOUNT_VARIABLE', 'slug', 'current_name', 'current_slug',
           'private_from_sddl']
