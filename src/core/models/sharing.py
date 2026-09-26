"""Whether every account on this machine can actually use the model store.

The store lives at ``C:\\LocalAI\\models`` so one copy serves the whole machine
rather than one copy per Windows profile. Putting it there is not enough:

  * another account's Ollama reads ``OLLAMA_MODELS`` from its own environment,
    and with no machine-scope value it falls back to that account's
    ``%USERPROFILE%\\.ollama\\models`` and re-downloads tens of gigabytes;
  * a machine-scope value is overridden by a user-scope one, so an account
    that set its own keeps pointing somewhere else;
  * and the files still have to be readable by ``BUILTIN\\Users``.

Setting the machine-scope variable needs administrator rights, so it can
simply fail during setup. Until now the program reported "모든 계정 공용"
whenever the path had the right shape, which is a claim about a string, not
about the machine - a user whose setup ran without admin was told the store
was shared when no other account could see a single file.

This module decides what those facts mean. Reading them is someone else's
job, so the rule stays testable without a registry or an ACL.
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
VARIABLE_MISSING = 'variable_missing'    # no machine-scope value: they look elsewhere
VARIABLE_ELSEWHERE = 'variable_elsewhere'  # machine-scope value names another store
USER_OVERRIDE = 'user_override'          # this account's own value hides it
NOT_READABLE = 'not_readable'            # BUILTIN\Users cannot read the files


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
        if self.windows:
            if self.machine_value == '':
                found.append(VARIABLE_MISSING)
            elif self.machine_value and not _same(self.machine_value, self.path, self.windows):
                found.append(VARIABLE_ELSEWHERE)
            if self.user_value and not _same(self.user_value, self.path, self.windows):
                found.append(USER_OVERRIDE)
            if self.readable_by_users is False:
                found.append(NOT_READABLE)
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
        if self.machine_value is None or self.readable_by_users is None:
            return None
        return True

    @property
    def repairable(self) -> bool:
        """Can the program fix this itself, given the rights to do it?

        Offered when something is wrong that we may fix, and also when we
        could not read the facts: both steps are idempotent and neither grants
        anything beyond read access, so trying is better than a screen that
        says it does not know and offers nothing. Not offered for the blockers
        that are somebody's decision rather than a fault - a store the caller
        chose, or this account's own OLLAMA_MODELS.
        """
        fixable = {VARIABLE_MISSING, VARIABLE_ELSEWHERE, NOT_READABLE}
        blockers = set(self.blockers)
        if blockers:
            return blockers <= fixable
        return self.windows and self.every_account is None
