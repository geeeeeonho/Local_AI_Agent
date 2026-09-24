"""Strict network intent -> existing, fail-closed runtime preparation."""
from core.calls import invoke
from core.network.policy import NetworkMode
from .ownership import RuntimeOwner


class NetworkManager:
    def __init__(self, backend, owner: RuntimeOwner, events):
        self.backend, self.owner, self.events = backend, owner, events
        self.mode = None

    def prepare(self, mode, cancel=None):
        selected = NetworkMode(mode)
        if self.mode is not None and self.mode != selected:
            raise RuntimeError('An active session pins the network mode. Close that session first.')
        acquired_here = not self.owner.owned
        self.owner.acquire()
        log = lambda message: self.events.emit('runtime.progress',
                        {'service': 'network', 'message': str(message)})
        try:
            # Starting Docker Desktop for WARP/Tor/Block takes up to a minute
            # and a half; a close the user already asked for must not wait it
            # out. Backends without a cancel parameter simply do not get one.
            if not invoke(self.backend.prepare_network, selected.value, log, cancel=cancel):
                raise RuntimeError('Network preparation failed; no direct fallback is allowed.')
        except Exception:
            # A failed preparation is not an active session. Keeping the OS lock
            # here prevented another LocalAI window from retrying or repairing.
            if acquired_here and self.mode is None:
                self.owner.release()
            raise
        self.mode = selected
        self.events.emit('network.changed', {'mode': selected.value})
        return selected

    def reset(self):
        """Release a network lease that did not produce an active session."""
        self.mode = None
        self.owner.release()
