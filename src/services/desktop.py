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
    @staticmethod
    def _prepare_private_state(data: Path) -> None:
        """Repair small per-account state folders before any JsonStore opens.

        A stale lock created by an elevated/older run can deny the normal token
        even when the account root itself is correctly private. Runtime/settings/
        projects are small control-state trees, so recursively normalising their
        ACLs here is cheap. Ephemeral locks deliberately live in the fresh
        user_data/runtime tree instead of reusing legacy cache lock files.
        """
        data = Path(data)
        account = data.parent
        account.mkdir(parents=True, exist_ok=True)
        data.mkdir(parents=True, exist_ok=True)
        if __import__('os').name != 'nt':
            for name in ('runtime', 'settings', 'projects'):
                (data / name).mkdir(parents=True, exist_ok=True)
            return

        try:
            from integrations.windows import privacy
            privacy.ensure_private(account)
        except Exception:
            pass

        for name in ('runtime', 'settings', 'projects'):
            folder = data / name
            folder.mkdir(parents=True, exist_ok=True)
            try:
                # Always cover existing children too: the exact failure seen in
                # production is runtime-state.json.lock, not the directory.
                privacy.make_private(folder)
            except Exception:
                pass

    def __init__(self, *, project_root, env, model_dir, data=None, backend=None):
        self.project_root, self.env, self.model_dir = map(Path, (project_root, env, model_dir))
        # ``create_services`` passes the runtime root's user_data, because the
        # source checkout and the folder this product writes to are two
        # different places now. A caller that names only a project root means
        # "this whole install lives here", which is how tests and portable
        # runs express themselves, so that root keeps its own user_data.
        self.data = Path(data) if data is not None else self.project_root / 'user_data'
        self._prepare_private_state(self.data)
        if backend is None:
            from integrations.legacy.desktop import LegacyBackend
            backend = LegacyBackend(self.env, self.model_dir, self.project_root,
                                    data=self.data)
        self.backend = backend
        self.events = EventBus()
        self.settings = SettingsStore(self.data / 'settings' / 'localai.json')
        self.projects = ProjectRegistry(self.data / 'projects' / 'registry.json')
        self.owner = RuntimeOwner(self.env / "desktop-runtime.lock")
        self.network = NetworkManager(backend, self.owner, self.events)
        control = self.data / 'runtime'
        self.inference = InferenceService(
            runtime=backend.inference,
            events=self.events,
            state=RuntimeState(control / 'runtime-state.json'),
        )
        self.models = ModelService(
            self.inference,
            events=self.events,
            lock_path=control / 'model-mutation.lock',
        )
        self.search = SearchService(backend, self.network, self.events)
        self.chat = ChatService(backend, self.inference, self.network, self.search, self.events)
        self.agent = AgentLauncher(backend, self.network, self.events)
        self.system = SystemService(backend)
        self.setup = SetupService(
            backend, self.models, self.network, self.settings,
            active=lambda: self.chat.attempted or self.agent.opened,
            events=self.events,
        )
        self._close_lock = threading.RLock()
        self._finalized = False

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

    def _close_sessions(self):
        """Stop account-owned sessions without running process-global cleanup."""
        agent_ok = self._stop('agent', self.agent)
        chat_ok = self._stop('chat', self.chat)
        search_ok = self._stop('search', self.search)
        if not agent_ok or not chat_ok or not search_ok:
            return False
        self.network.mode = None
        return True

    def close(self):
        """Stop this account's sessions and release the machine runtime lease.

        The desktop remains usable after the Session stop button, so global
        atexit callbacks must not run here.
        """
        with self._close_lock:
            if not self._close_sessions():
                return False
            try:
                from launcher.core import lifelog
                lifelog.suppress_exit_cleanups()
            except Exception:
                pass
            self.owner.release()
            return True

    def finalize(self):
        """Final process teardown while holding the machine-wide runtime lock.

        Shared WARP/Tor/SearXNG/Docker callbacks use fixed machine-wide names.
        They must finish before another Windows account can acquire the runtime
        lease and start replacements with those same names.
        """
        with self._close_lock:
            if self._finalized:
                return True
            acquired_here = False
            if not self.owner.owned:
                try:
                    self.owner.acquire()
                    acquired_here = True
                except RuntimeError:
                    # Another account now owns the shared runtime. Never run
                    # stale callbacks from this process against its containers.
                    try:
                        from launcher.core import lifelog
                        lifelog.suppress_exit_cleanups()
                    except Exception:
                        pass
                    self._finalized = True
                    return True
            if not self._close_sessions():
                # Keep the lease on an unverified shutdown. Releasing it would
                # let another account reuse the same container names while this
                # process may still own live resources.
                return False
            try:
                from launcher.core import lifelog
                lifelog.shutdown_then_exit()
            finally:
                self.owner.release()
            self._finalized = True
            return True


def create_services():
    from project_paths import (PROJECT_ROOT, ENV_DIR, MODEL_STORAGE_DIR,
                               USER_DATA_DIR)
    return DesktopServices(project_root=PROJECT_ROOT, env=ENV_DIR,
                           model_dir=MODEL_STORAGE_DIR, data=USER_DATA_DIR)
