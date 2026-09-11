"""Application-facing inference readiness with shared observations and events."""
from core.events import EventBus
from core.runtime_state import RuntimeState


class InferenceService:
    def __init__(self, *, runtime=None, events=None, state=None):
        if runtime is None:
            import importlib
            from project_paths import ENV_DIR, MODEL_STORAGE_DIR
            from integrations.legacy.desktop import ManagedInference
            runtime = ManagedInference(ENV_DIR, MODEL_STORAGE_DIR, importlib.import_module)
        self.runtime = runtime
        self.client, self.model_dir = runtime.client, runtime.model_dir
        self.events = events if events is not None else EventBus()
        self.state = state if state is not None else RuntimeState()

    def _observe(self, status, detail=''):
        try:
            self.state.set_status('inference', status, detail=detail)
        except (OSError, ValueError) as exc:
            self.events.emit('runtime.error', {'service': 'observations', 'detail': str(exc)})
        self.events.emit('runtime.status', {'service': 'inference', 'status': status, 'detail': detail})

    def ensure_ready(self) -> str:
        self._observe('starting')
        try:
            endpoint = self.runtime.ensure_running()
        except Exception as exc:
            self._observe('error', str(exc))
            self.events.emit('runtime.error', {'service': 'inference', 'detail': str(exc)})
            raise
        self._observe('ready')
        return endpoint
