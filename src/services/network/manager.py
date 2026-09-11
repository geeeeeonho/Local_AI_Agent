"""Strict network intent -> existing, fail-closed runtime preparation."""
from core.network.policy import NetworkMode
from .ownership import RuntimeOwner


class NetworkManager:
    def __init__(self, backend, owner: RuntimeOwner, events):
        self.backend, self.owner, self.events = backend, owner, events
        self.mode = None

    def prepare(self, mode):
        selected = NetworkMode(mode)
        if self.mode is not None and self.mode != selected:
            raise RuntimeError('An active session pins the network mode. Close that session first.')
        self.owner.acquire()
        log = lambda message: self.events.emit('runtime.progress',
                        {'service': 'network', 'message': str(message)})
        if not self.backend.prepare_network(selected.value, log):
            raise RuntimeError('Network preparation failed; no direct fallback is allowed.')
        self.mode = selected
        self.events.emit('network.changed', {'mode': selected.value})
        return selected
