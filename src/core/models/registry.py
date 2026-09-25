"""One answer to "which models can this machine use", and how it is reached.

Before this, seven places asked that question and each answered differently:
the launcher parsed ``ollama list`` stdout, the role resolver made its own
unproxied HTTP call, the management screen made another, the model screen read
manifests off disk, and the Ollama service read both and compared them. They
disagreed about the canonical spelling of a tag, about what a failed lookup
means, and about which host to ask - so the same store could read as full on
one screen and empty on the next.

Ollama is the router. It is the process that will actually serve a prompt, so
while it is running, what it lists is what this machine can use - not what
happens to sit in a directory. When it is not running, the store on disk is the
best answer available: those models will be served the moment it starts. If
neither can be read, that is reported as not knowing rather than as an empty
library, because "you have no models" and "I could not check" lead a user to
opposite actions.

This module holds only that policy. Reading the router and reading the store
are passed in, so the rule stays testable without a server, a disk, or an
import of any layer above ``core``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, FrozenSet, Optional

# Where the answer came from, in the order the policy prefers.
ROUTER = 'router'   # Ollama answered; this is what it will serve
STORE = 'store'     # Ollama is not answering; this is what is on disk
UNKNOWN = 'unknown'  # neither could be read; not the same as "none installed"


@dataclass(frozen=True)
class Inventory:
    """What models are usable, where that was learned, and what each side saw.

    ``tags`` is the answer callers should act on. ``served`` and ``on_disk``
    are kept so a caller can explain a disagreement instead of only reporting
    one, and are ``None`` when that side could not be read at all.
    """

    tags: FrozenSet[str]
    source: str
    served: Optional[FrozenSet[str]]
    on_disk: Optional[FrozenSet[str]]
    store_path: str = ''
    #: False when the store was read but not all of it could be understood - a
    #: half-finished download, a manifest from a newer Ollama, a directory we
    #: may not enter. Those names are missing from ``on_disk`` without being
    #: absent from the machine, so they cannot be used to prove disagreement.
    on_disk_complete: bool = True

    @property
    def router_reachable(self) -> bool:
        return self.served is not None

    @property
    def known(self) -> bool:
        """False means nothing could be read, not that nothing is installed."""
        return self.source != UNKNOWN

    @property
    def agreement(self) -> Optional[bool]:
        """Is the running router serving out of the store we resolved?

        ``None`` when either side is unreadable. A router listing models the
        store does not hold is pointed somewhere else - the store we are about
        to download into is not the one being served from.
        """
        if self.served is None or self.on_disk is None:
            return None
        if not self.on_disk_complete:
            # Part of the store is unreadable, so "not on disk" would be a
            # guess. Unknown sends the caller down the warn-and-continue path;
            # False would have it refuse over something it cannot see.
            return None
        served = {name for name in self.served if not _is_remote(name)}
        if not served:
            # A router with nothing local loaded contradicts no store.
            return True
        # Folded, because neither side controls the spelling. Vendor tags mix
        # case (prutser/...:Q4_K_S), Ollama does not promise to echo a name
        # unchanged, and canonicalization can only fix the spelling of tags the
        # catalogue knows. A raw comparison would read a case difference in a
        # model the user pulled themselves as "the router is pointed elsewhere".
        lowered = {name.lower() for name in self.on_disk}
        return all(name.lower() in lowered for name in served)

    def has(self, tag, match: Callable[[str, FrozenSet[str]], object] | None = None) -> bool:
        """Is this tag usable? Unknown reads as not usable, never as usable."""
        if not self.known or not tag:
            return False
        if match is not None:
            return bool(match(tag, self.tags))
        return tag in self.tags


def _is_remote(name) -> bool:
    """A cloud tag is served without ever being on this disk.

    Ollama proxies these to its own servers, so requiring one to exist locally
    turned "the user is signed in to Ollama cloud" into "this router is pointed
    at a different store".
    """
    return str(name).strip().lower().endswith('-cloud') or '-cloud:' in str(name).lower()


def _read(reader) -> Optional[set]:
    """Run one side of the lookup. Any failure means "could not read"."""
    if reader is None:
        return None
    try:
        value = reader()
    except Exception:
        return None
    if value is None:
        return None
    try:
        return {str(name) for name in value if str(name)}
    except TypeError:
        return None


def resolve(read_router=None, read_store=None, canonical=None, store_path='',
            store_complete=None) -> Inventory:
    # ``store_complete`` may be a callable, because whether the store could be
    # read in full is only known once it has been read - passing the value
    # itself evaluated it before the reader had run, so an unreadable manifest
    # always reported the scan as complete.
    """Ask the router first, fall back to the store, and canonicalize once.

    Both readers return an iterable of names, or ``None``/raise to mean the
    lookup failed. ``canonical`` maps names onto catalogue spelling; it runs on
    both sides so a later ``tag in tags`` comparison is meaningful whichever
    side answered.
    """
    normalize = canonical if canonical is not None else (lambda names: set(names))

    def shaped(names):
        if names is None:
            return None
        try:
            return frozenset(normalize(names))
        except Exception:
            return frozenset(names)

    served = shaped(_read(read_router))
    on_disk = shaped(_read(read_store))

    if served is not None:
        tags, source = served, ROUTER
    elif on_disk is not None:
        tags, source = on_disk, STORE
    else:
        tags, source = frozenset(), UNKNOWN
    if store_complete is None:
        complete = True
    elif callable(store_complete):
        complete = bool(store_complete())
    else:
        complete = bool(store_complete)
    return Inventory(tags=tags, source=source, served=served,
                     on_disk=on_disk, store_path=str(store_path),
                     on_disk_complete=complete)


EMPTY = Inventory(tags=frozenset(), source=UNKNOWN, served=None, on_disk=None)
