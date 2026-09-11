"""Single model-management boundary for the new application layer."""
from __future__ import annotations
from pathlib import Path
from core.events import EventBus
from core.persistence import file_lock
from integrations.ollama.client import model_name
from . import index


class ModelService:
    def __init__(self, inference, *, events=None, lock_path=None):
        self.inference = inference
        self.model_dir, self.client = inference.model_dir, inference.client
        self.events = events if events is not None else EventBus()
        self.lock_path = Path(lock_path) if lock_path is not None else self.model_dir.parent / ".localai-ollama-setup.lock"

    def list_models(self):
        self.inference.ensure_ready()
        return self.client.list_models()

    def refresh_index(self):
        return index.refresh(self.model_dir, log=lambda message:
                             self.events.emit('runtime.progress', {'service': 'models', 'message': message}))

    def _change(self, name, operation):
        name = model_name(name)
        with file_lock(self.lock_path):
            self.inference.ensure_ready()
            try:
                if operation == 'install':
                    self.client.pull(name, progress=lambda value:
                        self.events.emit('runtime.progress', {**value, 'service': 'models', 'model': name}))
                else:
                    self.client.remove(name)
            except Exception as exc:
                self.events.emit('runtime.error', {'service': 'models', 'model': name, 'detail': str(exc)})
                raise
            finally:
                # A failed/interrupted pull may still have changed on-disk state.
                out = self.refresh_index()
            result = {'model': name, 'operation': operation, 'index_refreshed': out is not None}
            self.events.emit('model.changed', result)
            return result

    def install_model(self, name):
        """Explicit management download, not an agent/session network operation."""
        return self._change(name, 'install')

    def remove_model(self, name):
        return self._change(name, 'remove')

    def get_model_info(self, name):
        return next((model for model in index.build_index(self.model_dir)['models']
                     if model['name'] == name), None)

    def inventory(self):
        """Read a full on-disk snapshot without starting inference."""
        return index.build_index(self.model_dir)

    def disk_usage(self):
        return index.build_index(self.model_dir)['totals']

    def recommended_models(self, memory_gb=None):
        from launcher.models import model_catalog
        budget = model_catalog.MEMORY_BUDGET_GB if memory_gb is None else memory_gb
        return sorted(model_catalog.recommended_for(budget))
