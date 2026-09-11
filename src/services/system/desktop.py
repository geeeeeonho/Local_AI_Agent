"""Read-only diagnostics and explicit Setup/Repair operations."""
from core.network.policy import NetworkMode


class SystemService:
    def __init__(self, backend):
        self.backend = backend

    def health(self):
        return self.backend.health()

    def create_presenter(self, window):
        return self.backend.create_presenter(window)


    def create_agent_panel(self, parent, metadata, callbacks):
        """Presentation compatibility factory; caller is the UI thread."""
        return self.backend.create_agent_panel(parent, metadata, callbacks)


class SetupService:
    def __init__(self, backend, models, network, settings, *, active=None):
        self.backend, self.models = backend, models
        self.network, self.settings = network, settings
        self.active = active if active is not None else lambda: False

    def require_idle(self):
        if self.active():
            raise RuntimeError("Stop active sessions before maintenance or model changes.")

    def install_model(self, name):
        self.require_idle()
        selected = self.settings.network_mode(app='setup')
        if selected is NetworkMode.BLOCK or self.network.mode is NetworkMode.BLOCK:
            raise RuntimeError('Downloads are disabled in Block. Change Setup network intent explicitly.')
        self.network.owner.acquire()
        return self.models.install_model(name)

    def remove_model(self, name):
        self.require_idle()
        self.network.owner.acquire()
        return self.models.remove_model(name)

    def repair(self):
        self.require_idle()
        self.network.owner.acquire()
        return self.backend.run_setup()

    def maintenance(self, key, presenter):
        self.require_idle()
        if key not in {'docker_image', 'docker_clean', 'settings_action', 'searxng_action'}:
            raise ValueError('unknown maintenance operation')
        self.network.owner.acquire()
        return self.backend.maintenance(key, presenter)
