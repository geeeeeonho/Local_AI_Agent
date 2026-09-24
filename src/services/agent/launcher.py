"""Desktop facade for the existing Interpreter coordinator and approval flow."""
from core.calls import invoke
from .session import AgentSession


class AgentLauncher:
    def __init__(self, backend, network, events):
        self.backend, self.network, self.events = backend, network, events
        self.session = None

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
        # Agent preparation starts Docker, Ollama and SearXNG; each of those
        # waits was uninterruptible, so a window close during the wizard had to
        # sit through all three.
        binding = invoke(self.backend.agent_open, presenter, selected.value, project,
                         cancel=cancel)
        if binding is None or (cancel is not None and cancel()):
            if not network_was_prepared:
                self.network.reset()
            return None
        self.session = AgentSession(binding, self.events)
        if not self.session.start():
            closed = self.session.close()
            if closed:
                self.session = None
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
        self.events.emit('agent.stopped', {})
        return True
