"""Application-facing inference readiness with shared observations and events."""
from core.calls import invoke
from core.events import EventBus
from core.runtime_state import RuntimeState


class InferenceService:
    def __init__(self, *, runtime=None, events=None, state=None):
        if runtime is None:
            import importlib
            from project_paths import ENV_DIR, MODEL_STORAGE_DIR
            from integrations.desktop import ManagedInference
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

    def ensure_ready(self, log=None) -> str:
        self._observe('starting')
        try:
            endpoint = self._start(log)
        except Exception as exc:
            self._observe('error', str(exc))
            self.events.emit('runtime.error', {'service': 'inference', 'detail': str(exc)})
            raise
        self._observe('ready')
        return endpoint

    def local_models(self):
        """Tags the running server can serve from this machine, or None.

        ``None`` means the question could not be asked, which is not the same
        as "none installed" and must not be reported as one.
        """
        reader = getattr(self.runtime, 'local_models', None)
        if callable(reader):
            return reader()
        try:
            from core.models.registry import local_only
            rows = self.client.list_models() or ()
        except Exception:
            return None
        names = {str(row.get('name') or row.get('model') or '').strip()
                 for row in rows if isinstance(row, dict)}
        return sorted(local_only(name for name in names if name))

    def describe_models(self):
        """Why there is nothing to run, in the runtime's own words, or None."""
        explain = getattr(self.runtime, 'describe_models', None)
        if not callable(explain):
            return None
        try:
            return explain()
        except Exception:
            return None

    def _start(self, log):
        """Forward the progress callback only to a runtime that accepts one.

        A thirty-second Ollama boot with no output is indistinguishable from a
        hang, and not every runtime entrypoint accepts a callback.
        """
        return invoke(self.runtime.ensure_running, log=log)
