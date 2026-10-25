"""Read-only diagnostics and explicit Setup/Repair operations."""
from core.network.policy import NetworkMode


# The operations this shell is willing to hand to the retained launcher. The
# backend maps each key onto a real module; a stub backend keeps the same keys.
MAINTENANCE_OPERATIONS = ('docker_image', 'docker_clean',
                          'searxng_action', 'settings_action', 'ollama_action')


class SystemService:
    def __init__(self, backend):
        self.backend = backend

    def health(self, *, fresh=False):
        """Service status. ``fresh`` forces a new probe instead of a recent one."""
        return self.backend.health(max_age=0) if fresh else self.backend.health()

    def create_presenter(self, window):
        return self.backend.create_presenter(window)


    def create_agent_panel(self, parent, metadata, callbacks):
        """Presentation compatibility factory; caller is the UI thread."""
        return self.backend.create_agent_panel(parent, metadata, callbacks)


class SetupService:
    # Explicit allowlist. A key never becomes an import path or a command on its
    # own; the backend maps these to the retained implementation modules.
    # One tuple, referenced by both spellings, so the two cannot drift.
    MAINTENANCE_KEYS = MAINTENANCE_OPERATIONS

    def __init__(self, backend, models, network, settings, *, active=None, events=None):
        self.backend, self.models = backend, models
        self.network, self.settings = network, settings
        self.active = active if active is not None else lambda: False
        self.events = events

    def require_idle(self):
        if self.active():
            raise RuntimeError("Stop active sessions before maintenance or model changes.")

    def ensure_model_runtime(self, *, download=False):
        """Prepare Ollama once before an explicit model mutation."""
        self.require_idle()
        if download:
            selected = self.settings.network_mode(app='setup')
            if selected is NetworkMode.BLOCK or self.network.mode is NetworkMode.BLOCK:
                raise RuntimeError('Downloads are disabled in Block. Change Setup network intent explicitly.')
        self.network.owner.acquire()
        return self.backend.prepare_model_runtime()

    def _models_log(self, message):
        if self.events is not None:
            self.events.emit('runtime.progress', {'message': str(message)})

    def check_ollama(self):
        """Start/verify the managed Ollama for the Models page. Never waits on a click."""
        self.require_idle()
        self.network.owner.acquire()
        return self.backend.check_ollama(log=self._models_log)

    def restart_ollama_for_store(self):
        """Restart Ollama on the resolved store, after the user said yes."""
        self.require_idle()
        self.network.owner.acquire()
        return self.backend.restart_ollama_for_store(log=self._models_log)

    def install_model(self, name):
        self.ensure_model_runtime(download=True)
        return self.models.install_model(name)

    def remove_model(self, name):
        self.ensure_model_runtime(download=False)
        return self.models.remove_model(name)

    def repair(self, options=None, *, cancel=None):
        """Run installer/repair from the desktop without spawning a UI/console."""
        self.require_idle()
        acquired_here = not self.network.owner.owned
        self.network.owner.acquire()

        def log(message):
            if self.events is not None:
                self.events.emit('runtime.progress', {
                    'service': 'setup',
                    'message': str(message),
                })

        try:
            return self.backend.run_setup(options or {}, log=log, cancel=cancel)
        finally:
            if acquired_here:
                try:
                    from launcher.core import lifelog
                    lifelog.suppress_exit_cleanups()
                except Exception:
                    pass
                self.network.owner.release()

    def maintenance(self, key, presenter):
        self.require_idle()
        if key not in MAINTENANCE_OPERATIONS:
            raise ValueError('unknown maintenance operation')
        self.network.owner.acquire()
        return self.backend.maintenance(key, presenter)
