"""Policy for sharing the LocalAI-managed model library across accounts.

The managed library lives at ``C:\\LocalAI\\models``. Every LocalAI broker is
started with that path explicitly, so per-user or machine-scope
``OLLAMA_MODELS`` registry values do not decide LocalAI sharing.

For LocalAI accounts, sharing requires two facts:

* the library is the machine-wide LocalAI store, not a profile-local path;
* ``BUILTIN\\Users`` can read and modify the model store.

Registry values remain on ``Sharing`` as external-Ollama diagnostics only.
They help explain what a separately launched Ollama CLI/Tray might do, but are
not blockers for the LocalAI-managed broker.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from core import sddl

# The variable Ollama itself reads to find its store.
VARIABLE = 'OLLAMA_MODELS'

# Why the machine's other accounts would not see this store. Stable keys: the
# UI turns them into sentences, and tests name them.
NOT_SHARED_PATH = 'not_shared_path'      # the store is not the machine-wide one
PER_USER_PATH = 'per_user_path'          # it sits inside one profile
# Retained as stable diagnostic keys for external-Ollama compatibility.
VARIABLE_MISSING = 'variable_missing'
VARIABLE_ELSEWHERE = 'variable_elsewhere'
USER_OVERRIDE = 'user_override'
NOT_READABLE = 'not_readable'            # BUILTIN\Users cannot read the files
NOT_MANAGEABLE = 'not_manageable'        # BUILTIN\Users cannot install/remove


def _same(left, right, windows: bool = True) -> bool:
    """Compare two stored paths the way the platform they belong to would.

    These come out of the Windows registry, so they are compared by Windows
    rules - case-folded, separators unified - whatever platform this code is
    running on. Doing it through ``os.path`` meant the rule could only be
    checked on Windows, which is where it is hardest to check.

    Values arrive quoted and with trailing separators, because that is what a
    Windows dialog and a batch file hand back; Ollama strips them too.
    """
    if not left or not right:
        return False
    import ntpath
    import posixpath
    module = ntpath if windows else posixpath

    def shape(value):
        text = str(value).strip().strip('"\'')
        return module.normcase(module.normpath(text))
    return shape(left) == shape(right)


# ── reading an ACL without depending on the display language ─────────────
# The parse itself lives in ``core.sddl``: the same descriptor answers the
# opposite question for an account's private folder, and one parser with two
# callers beats two parsers that disagree.
USERS_SDDL = sddl.USERS_SDDL
USERS_SID = sddl.USERS_SID

FILE_READ_DATA = sddl.FILE_READ_DATA
GENERIC_READ = sddl.GENERIC_READ
GENERIC_ALL = sddl.GENERIC_ALL


def readable_from_sddl(descriptor: str) -> Optional[bool]:
    """Can BUILTIN\\Users read, per this security descriptor? None if unparsable."""
    return sddl.read_access(descriptor, (USERS_SDDL, USERS_SID))


def manageable_from_sddl(descriptor: str) -> Optional[bool]:
    """Can BUILTIN\\Users manage model-store children? None if unparsable."""
    return sddl.modify_access(descriptor, (USERS_SDDL, USERS_SID))


@dataclass(frozen=True)
class Sharing:
    """What is true about the store, and what that means for other accounts.

    ``machine_value`` and ``user_value`` are the two scopes of ``OLLAMA_MODELS``:
    ``''`` means the scope was read and holds nothing, ``None`` means it could
    not be read at all. ``readable_by_users`` is ``None`` for the same reason,
    and on a platform where the question does not arise.
    """

    path: str
    intended_shared: bool
    machine_value: Optional[str] = None
    user_value: Optional[str] = None
    readable_by_users: Optional[bool] = None
    manageable_by_users: Optional[bool] = None
    per_user_path: bool = False
    windows: bool = True

    @property
    def blockers(self) -> Tuple[str, ...]:
        """Everything standing between this store and the machine's accounts."""
        found = []
        if self.per_user_path:
            found.append(PER_USER_PATH)
        elif not self.intended_shared:
            found.append(NOT_SHARED_PATH)
        if self.windows and self.readable_by_users is False:
            found.append(NOT_READABLE)
        elif self.windows and self.manageable_by_users is False:
            found.append(NOT_MANAGEABLE)
        return tuple(found)

    @property
    def every_account(self) -> Optional[bool]:
        """True only when nothing is in the way. None when a fact is missing.

        Unknown is reported as unknown rather than as success, because the
        cost of being wrong here is a second account silently re-downloading
        the whole library.
        """
        if self.blockers:
            return False
        if not self.windows:
            return True
        if self.readable_by_users is None or self.manageable_by_users is None:
            return None
        return True

    @property
    def repairable(self) -> bool:
        """Can the program fix this itself, given the rights to do it?

        Offered when something is wrong that we may fix, and also when we
        could not read the ACL: the model-access repair is idempotent. Registry
        OLLAMA_MODELS values are not part of LocalAI's sharing decision because
        the managed broker receives its model path explicitly.
        """
        fixable = {NOT_READABLE, NOT_MANAGEABLE}
        blockers = set(self.blockers)
        if blockers:
            return blockers <= fixable
        return self.windows and self.every_account is None
