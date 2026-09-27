"""Policy for sharing the LocalAI-managed model library across accounts.

The managed library lives at ``C:\\LocalAI\\models``. Every LocalAI broker is
started with that path explicitly, so per-user or machine-scope
``OLLAMA_MODELS`` registry values do not decide LocalAI sharing.

For LocalAI accounts, sharing requires two facts:

* the library is the machine-wide LocalAI store, not a profile-local path;
* ``BUILTIN\\Users`` can read and modify the model store.

Standalone Ollama compatibility is handled separately when LocalAI publishes
``OLLAMA_MODELS``; it is not part of the LocalAI sharing state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from core import sddl

# The variable Ollama itself reads to find its store.
VARIABLE = 'OLLAMA_MODELS'

# Why the machine's other accounts would not share this store.
NOT_SHARED_PATH = 'not_shared_path'
PER_USER_PATH = 'per_user_path'
NOT_READABLE = 'not_readable'
NOT_MANAGEABLE = 'not_manageable'


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

    ACL-derived read/manage values are ``None`` when the descriptor cannot
    be read, and on platforms where the question does not arise.
    """

    path: str
    intended_shared: bool
    readable_by_users: Optional[bool] = None
    per_user_path: bool = False
    windows: bool = True
    manageable_by_users: Optional[bool] = None

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
        could not read the ACL: the model-access repair is idempotent.
        """
        fixable = {NOT_READABLE, NOT_MANAGEABLE}
        blockers = set(self.blockers)
        if blockers:
            return blockers <= fixable
        return self.windows and self.every_account is None
