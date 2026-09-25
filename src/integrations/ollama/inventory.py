"""The one place that asks Ollama, and the store, what models are here.

``core.models.registry`` holds the rule; this binds it to the real router and
the real store. Everything that wants to know whether a model is available
calls :func:`read` - the model screen, the role resolver, the installer's
management screen, the setup plan and the health poll - so they can no longer
disagree.

Router first, because Ollama is the router: what it lists is what a prompt
will actually reach. The store is the fallback for a stopped server and the
second opinion that reveals a router pointed at a different directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.models import registry
from core.models.registry import Inventory, ROUTER, STORE, UNKNOWN  # re-exported

__all__ = ['read', 'Inventory', 'ROUTER', 'STORE', 'UNKNOWN',
           'canonical', 'router_endpoint', 'router_reachable']

# How long a status-line lookup may block. The router is on loopback, so a
# slow answer means something is wrong, not that the machine is busy.
DEFAULT_TIMEOUT = 5.0


def router_endpoint(host=None, port=None) -> str:
    """The loopback endpoint the router listens on, from the one config."""
    from launcher import config
    return 'http://%s:%d' % (host or config.OLLAMA_HOST,
                             int(port if port is not None else config.OLLAMA_PORT))


def _endpoint(value) -> str:
    """Tolerate a trailing slash rather than reading it as a stopped server.

    The transport requires a bare scheme://host:port and rejects anything with
    a path, so a caller passing "http://127.0.0.1:11434/" raised - and the
    raise was indistinguishable here from a server that is not running.
    """
    return str(value).rstrip('/') if value else router_endpoint()


def canonical(names):
    """Catalogue spelling, applied to every side of every lookup.

    Vendor tags mix case (prutser/...:Q4_K_S) and neither Ollama nor a
    directory listing guarantees the spelling comes back unchanged. Comparing
    raw strings reported installed models as missing.
    """
    from launcher.models import model_catalog
    return model_catalog.canonicalize_installed(names)


def _from_router(endpoint, timeout):
    """Names the running Ollama will serve, or None if it is not answering."""
    def read_router():
        from .client import OllamaClient
        # This client refuses proxies and redirects. The old ad-hoc lookups
        # used a bare urlopen, so an http_proxy in the environment could send
        # a loopback request through a proxy.
        client = OllamaClient(endpoint, timeout=timeout)
        names = set()
        for model in client.list_models():
            name = model.get('name') or model.get('model')
            if name:
                names.add(str(name))
        return names
    return read_router


def _from_store(model_dir, problems):
    """Names the store holds, or None if it cannot be read."""
    if model_dir is None:
        return None

    def read_store():
        # Manifests only. The full index also stats every blob, which answers
        # a question nobody asked here and grows with the size of the store.
        from launcher.models import model_index
        names = set(model_index.read_manifests(model_dir, problems))
        # A store that is not there yet holds nothing, and that is a fact, not
        # a failed read - a fresh install must not report "I could not check".
        # Only a tree that exists and cannot be walked makes absence a guess.
        if problems and not (Path(model_dir) / 'manifests').exists():
            problems.clear()
        return names
    return read_store


def read(model_dir=None, *, endpoint=None, timeout=DEFAULT_TIMEOUT,
         router=True, store=True) -> Inventory:
    """What this machine can use right now.

    ``model_dir`` defaults to the resolved shared store. Pass ``router=False``
    to answer from disk alone - the model screen does that so it still tells
    the truth while the server is stopped - or ``store=False`` to ask only the
    router.
    """
    if model_dir is None:
        from project_paths import MODEL_STORAGE_DIR
        model_dir = MODEL_STORAGE_DIR
    model_dir = Path(model_dir)
    problems: list = []
    return registry.resolve(
        read_router=_from_router(_endpoint(endpoint), timeout) if router else None,
        read_store=_from_store(model_dir, problems) if store else None,
        canonical=canonical,
        store_path=model_dir,
        # Deferred: the list is filled while the store is being read.
        store_complete=lambda: not problems,
    )


def router_reachable(*, endpoint=None, timeout=DEFAULT_TIMEOUT) -> bool:
    """Is Ollama answering? One probe, through the same hardened transport."""
    return read(model_dir=None, endpoint=endpoint, timeout=timeout,
                store=False).router_reachable
