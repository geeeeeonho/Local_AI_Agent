"""Strict network intent -> existing, fail-closed runtime preparation."""
import inspect
from core.network.policy import NetworkMode
from .ownership import RuntimeOwner


class NetworkManager:
    def __init__(self, backend, owner: RuntimeOwner, events):
        self.backend, self.owner, self.events = backend, owner, events
        self.mode = None

    def _prepare_backend(self, mode, log, cancel):
        """Pass the cancel check only to a backend that accepts one.

        Starting Docker Desktop for WARP/Tor/Block can take a minute and a half.
        Without this the window close the user already asked for had to wait it
        out, and older backends would break on an unexpected argument.
        """
        prepare = self.backend.prepare_network
        if cancel is None:
            return prepare(mode, log)
        try:
            parameters = inspect.signature(prepare).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts = 'cancel' in parameters or any(
            value.kind is value.VAR_KEYWORD for value in parameters.values())
        if accepts:
            return prepare(mode, log, cancel=cancel)
        return prepare(mode, log)

    def prepare(self, mode, cancel=None):
        selected = NetworkMode(mode)
        if self.mode is not None and self.mode != selected:
            raise RuntimeError('An active session pins the network mode. Close that session first.')
        acquired_here = not self.owner.owned
        self.owner.acquire()
        log = lambda message: self.events.emit('runtime.progress',
                        {'service': 'network', 'message': str(message)})
        try:
            if not self._prepare_backend(selected.value, log, cancel):
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
