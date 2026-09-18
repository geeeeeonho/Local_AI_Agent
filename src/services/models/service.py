"""Single model-management boundary for the new application layer."""
from __future__ import annotations
from pathlib import Path
from core.events import EventBus
from core.persistence import file_lock
from integrations.ollama.client import is_cloud_tag, local_model_name, model_name
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
        name = model_name(name) if operation == 'remove' else local_model_name(name)
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

    # ── selection and stack views ──────────────────────────────────────────
    # These read the on-disk index rather than Ollama's HTTP API, so the model
    # screen still tells the truth while the server is stopped.

    def installed_tags(self):
        """Model names actually present in the store. Does not start Ollama."""
        return {model['name'] for model in index.build_index(self.model_dir)['models']}

    def catalog(self, *, installed=None, budget_gb=None):
        """Catalog rows for the selection view, each with its install state."""
        from launcher.models import model_catalog as catalog
        budget = catalog.MEMORY_BUDGET_GB if budget_gb is None else float(budget_gb)
        present = catalog.canonicalize_installed(
            self.installed_tags() if installed is None else installed)
        recommended = catalog.recommended_for(budget)
        models = []
        for entry in catalog.all_entries():
            level = catalog.level_of(entry.tag)
            models.append({
                'tag': entry.tag, 'role': entry.role, 'desc': entry.desc,
                'cloud': is_cloud_tag(entry.tag),
                'note': entry.note, 'group': entry.group, 'kind': entry.kind,
                'size_gb': float(entry.size_gb), 'memory_gb': float(entry.memory_gb),
                'level': level or '', 'level_label': catalog.level_label(level) if level else '',
                'installed': entry.tag in present,
                'recommended': entry.tag in recommended,
            })
        return {
            'budget_gb': budget, 'models': models,
            'recommended': sorted(recommended),
            # Models the user pulled themselves. Listed so unchecking one is a
            # deliberate removal rather than an invisible leftover.
            'extra_installed': sorted(present - catalog.catalog_tags()),
            # Remote tags occupy no disk, so the store never sees them; report
            # them separately rather than letting them look like local models.
            'cloud_installed': sorted(tag for tag in present if is_cloud_tag(tag)),
            'plan': {key: list(tags) for key, tags in catalog.plan_by_level(budget).items()},
            'levels': [(key, catalog.level_label(key)) for key in catalog.LEVEL_KEYS],
        }

    def current_stack(self, *, free_gb=None, installed=None):
        """What each role would actually load right now, and whether it is here.

        The choice comes from the retained ladder resolver, not a second copy of
        that policy; this only reports it alongside on-disk presence.
        """
        from launcher.models import model_catalog as catalog
        from launcher.models import model_roles as roles
        present = catalog.canonicalize_installed(
            self.installed_tags() if installed is None else installed)
        free = roles.detect_free_memory_gb() if free_gb is None else float(free_gb)
        rows = []
        for role in roles.ROLES:
            try:
                chosen = roles.resolve_ladder(role.name, free)
            except Exception:
                chosen = None
            ladder = [{'tag': tag, 'need_gb': float(need),
                       'on_disk': catalog.is_installed(tag, present)}
                      for tag, need in (roles.LADDERS.get(role.name) or ())]
            # The requirement that matters is the rung that will actually load,
            # not the role's top tier; showing the latter put "18.0 GB" beside a
            # 7.6 GB model.
            need = next((rung['need_gb'] for rung in ladder if rung['tag'] == chosen),
                        float(role.need_gb))
            rows.append({
                'name': role.name, 'label': role.label,
                'chosen': chosen or '', 'need_gb': need,
                'top_need_gb': float(role.need_gb),
                'on_disk': bool(chosen) and catalog.is_installed(chosen, present),
                'ladder': ladder,
            })
        return {'free_gb': free, 'budget_gb': catalog.MEMORY_BUDGET_GB, 'roles': rows}

    def storage(self):
        """Where models land, and whether there is room for more there.

        Reported against the nearest existing ancestor when the store itself has
        not been created yet, because a fresh machine has no C:\\LLM_Models but
        does have the drive it will live on.
        """
        import shutil
        path = Path(self.model_dir)
        probe, exists = path, path.is_dir()
        if not exists:
            for parent in path.parents:
                if parent.is_dir():
                    probe = parent
                    break
            else:
                probe = None
        usage = None
        if probe is not None:
            try:
                usage = shutil.disk_usage(probe)
            except OSError:
                usage = None
        from core import ollama_paths
        return {
            'path': str(path), 'exists': exists,
            'measured_at': None if probe is None else str(probe),
            'total_bytes': None if usage is None else usage.total,
            'free_bytes': None if usage is None else usage.free,
            # Ollama's own default sits in one account's profile. Saying which
            # kind of store this is tells the user whether the machine's other
            # Windows accounts will see the same models.
            'shared': ollama_paths.models_dir_is_shared(),
            'per_user': ollama_paths.is_per_user_store(path),
        }

    def plan_changes(self, desired, *, installed=None):
        """Checked means 'should exist': the difference is the work to do."""
        from launcher.models import model_catalog as catalog
        wanted = catalog.canonicalize_installed(desired)
        present = catalog.canonicalize_installed(
            self.installed_tags() if installed is None else installed)
        install = sorted(wanted - present)
        download_gb = catalog.download_gb(install)
        store = self.storage()
        free_gb = None if store['free_bytes'] is None else store['free_bytes'] / 1024 ** 3
        return {
            'install': install, 'remove': sorted(present - wanted),
            # Ollama shares blob layers between models, so a sum of catalogue
            # sizes is the ceiling, not the exact cost.
            'download_gb': download_gb, 'download_is_upper_bound': True,
            'free_gb': free_gb, 'storage': store,
            'fits': None if free_gb is None else download_gb <= free_gb,
        }
