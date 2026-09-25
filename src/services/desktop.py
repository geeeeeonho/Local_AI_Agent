"""Composition shared by Studio, Chat, Interpreter and Setup.

Current project_paths are injected, so adding the UI cannot silently activate
staged official-Ollama migration defaults from the prior foundation patch.
"""
from pathlib import Path
import threading
from core.events import EventBus
from core.projects.registry import ProjectRegistry
from core.settings.store import SettingsStore
from core.runtime_state import RuntimeState
from services.inference.service import InferenceService
from services.models.service import ModelService
from services.network.manager import NetworkManager
from services.network.ownership import RuntimeOwner
from services.search.service import SearchService
from services.chat.service import ChatService
from services.agent.launcher import AgentLauncher
from services.system.desktop import SetupService, SystemService


class DesktopServices:
    def __init__(self, *, project_root, env, model_dir, data=None, backend=None):
        self.project_root, self.env, self.model_dir = map(Path, (project_root, env, model_dir))
        # ``create_services`` passes the runtime root's user_data, because the
        # source checkout and the folder this product writes to are two
        # different places now. A caller that names only a project root means
        # "this whole install lives here", which is how tests and portable
        # runs express themselves, so that root keeps its own user_data.
        self.data = Path(data) if data is not None else self.project_root / 'user_data'
        if backend is None:
            from integrations.legacy.desktop import LegacyBackend
            backend = LegacyBackend(self.env, self.model_dir, self.project_root,
                                    data=self.data)
        self.backend = backend
        self.events = EventBus()
        self.settings = SettingsStore(self.data / 'settings' / 'localai.json')
        self.projects = ProjectRegistry(self.data / 'projects' / 'registry.json')
        self.owner = RuntimeOwner(self.data / 'cache' / 'desktop-runtime.lock')
        self.network = NetworkManager(backend, self.owner, self.events)
        self.inference = InferenceService(runtime=backend.inference, events=self.events,
            state=RuntimeState(self.data / 'cache' / 'runtime-state.json'))
        self.models = ModelService(self.inference, events=self.events,
            lock_path=self.data / 'cache' / 'model-mutation.lock')
        self.search = SearchService(backend, self.network, self.events)
        self.chat = ChatService(backend, self.inference, self.network, self.search, self.events)
        self.agent = AgentLauncher(backend, self.network, self.events)
        self.system = SystemService(backend)
        self.setup = SetupService(backend, self.models, self.network, self.settings,
            active=lambda: self.chat.attempted or self.agent.opened)
        self._close_lock = threading.RLock()

    def resolve_mode(self, app, *, project=None, session=None):
        return self.settings.network_mode(app=app,
            project=getattr(project, 'network_mode', None), session=session,
            fallback=self.backend.current_mode())

    def _stop(self, name, service):
        """One service's teardown. An exception here is 'not verified', not a
        crash: raising out of close() left the window with no way to shut down
        and no way to say why."""
        try:
            return bool(service.stop())
        except Exception as exc:
            self.events.emit('runtime.error', {'service': name, 'detail': str(exc)})
            return False

    def account_label(self) -> str:
        """The account these records belong to, in its own name.

        The folder can be ``users\\user-9c6b9b1b`` when the Windows account name
        is Korean or has a space, because the path has to survive a
        ``docker -v`` argument. The person still gets to see their own name.
        """
        from core import accounts
        return accounts.current_name()

    def close(self):
        # Keep ownership if shutdown is not verified. The OS releases it if the
        # process terminates; no stale lock-file deletion or PID guessing.
        with self._close_lock:
            # Every service is asked, even after one refuses: a failure to stop
            # Chat is no reason to leave the Agent and search running too.
            agent_ok = self._stop('agent', self.agent)
            chat_ok = self._stop('chat', self.chat)
            search_ok = self._stop('search', self.search)
            if not agent_ok or not chat_ok or not search_ok:
                return False
            self.network.mode = None
            self.owner.release()
            return True


def create_services():
    from project_paths import (PROJECT_ROOT, ENV_DIR, MODEL_STORAGE_DIR,
                               USER_DATA_DIR)
    return DesktopServices(project_root=PROJECT_ROOT, env=ENV_DIR,
                           model_dir=MODEL_STORAGE_DIR, data=USER_DATA_DIR)
