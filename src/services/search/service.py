"""One search lifecycle entrypoint; Block is never an alias for Direct."""
from core.network.policy import NetworkMode


class SearchService:
    def __init__(self, backend, network, events):
        self.backend, self.network, self.events = backend, network, events
        self.attempted = False

    def start(self, mode):
        if NetworkMode(mode) is NetworkMode.BLOCK:
            raise RuntimeError('Search is unavailable in Block mode.')
        # Chat/Agent already pinned and verified the network. Preparing it again
        # reboots/probes WARP, Tor and Docker without changing the policy.
        selected = NetworkMode(mode)
        if self.network.mode is None:
            selected = self.network.prepare(selected.value)
        elif self.network.mode is not selected:
            raise RuntimeError('Search cannot change an active session network mode.')
        self.attempted = True
        return bool(self.backend.search_start(selected.value, lambda message:
            self.events.emit('runtime.progress', {'service': 'search', 'message': str(message)})))

    def stop(self):
        if not self.attempted:
            return True
        if not self.backend.search_stop():
            return False
        self.attempted = False
        return True
