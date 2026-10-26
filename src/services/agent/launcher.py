"""Desktop facade for the existing Interpreter coordinator and approval flow."""
from core.calls import invoke
from .session import AgentSession


class AgentLauncher:
    def __init__(self, backend, network, events, stores=None):
        self.backend, self.network, self.events = backend, network, events
        self.session = None
        # Agent sessions stay sealed for this account between runs.
        self.stores = stores

    @property
    def opened(self):
        return self.session is not None

    def open(self, presenter, mode, *, project=None, cancel=None):
        if self.opened:
            raise RuntimeError('An Agent view is already active. Close it before opening a new one.')
        if cancel is not None and cancel():
            return None
        network_was_prepared = self.network.mode is not None
        selected = self.network.prepare(mode, cancel=cancel)
        if self.stores is not None:
            self.stores.open('agent')
        # Agent preparation starts Docker, Ollama and SearXNG; each of those
        # waits was uninterruptible, so a window close during the wizard had to
        # sit through all three.
        try:
            binding = invoke(self.backend.agent_open, presenter, selected.value, project,
                             cancel=cancel)
        except Exception:
            # No session was started, so nothing can be writing the stores.
            self._seal()
            raise
        if binding is None or (cancel is not None and cancel()):
            self._seal()
            if not network_was_prepared:
                self.network.reset()
            return None
        self.session = AgentSession(binding, self.events)
        if not self.session.start():
            closed = self.session.close()
            if closed:
                self.session = None
                self._seal()
                if not network_was_prepared:
                    self.network.reset()
            raise RuntimeError('Interpreter startup failed. Check Setup / Repair.')
        self.events.emit('agent.started', {'mode': selected.value, 'session': self.session.id})
        return self.session

    def stop(self):
        if self.session is None:
            return True
        if not self.session.close():
            return False
        self.session = None
        self._seal()
        self.events.emit('agent.stopped', {})
        return True

    def _seal(self):
        """Seal agent stores once no session runs. Never raises."""
        if self.stores is None:
            return
        try:
            self.stores.close('agent')
        except Exception:
            pass
