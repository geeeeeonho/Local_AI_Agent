"""Composition shared by Studio, Chat, Interpreter and Setup."""
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
from services.tools.translation import TranslationService
from services.tools.calendar import CalendarService
from services.tools.reminder_worker import ReminderManager
from services.system.desktop import SetupService, SystemService
from services.records import SessionStores


class DesktopServices:
    @staticmethod
    def _prepare_private_state(data: Path) -> None:
        """Prepare each account's private state before any personal storage opens.

        In Windows, ACL validation and the account-bound DPAPI key must be
        available. A failure is fatal, never a silent plaintext fallback.
        """
        import os

        data = Path(data)
        account = data.parent
        try:
            account.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise RuntimeError(
                "이 Windows 계정의 LocalAI 폴더를 만들 권한이 없습니다: %s. "
                "관리자 또는 기존 설치 계정에서 Setup을 한 번 실행해 "
                "C:\\LocalAI\\users 공용 부모 권한을 갱신하세요." % account
            ) from exc

        # Test/developer platforms do not use Windows ACL or DPAPI.
        if os.name != 'nt':
            data.mkdir(parents=True, exist_ok=True)
            for name in ('runtime', 'settings', 'projects'):
                (data / name).mkdir(parents=True, exist_ok=True)
            return

        from integrations.windows import privacy
        from core import vault

        if privacy.ensure_private(account) is not True:
            raise RuntimeError(
                '현재 Windows 계정의 개인 폴더 접근 권한을 확인하지 못했습니다. '
                'Setup / Repair에서 계정별 ACL을 복구하세요: %s' % account)

        try:
            data.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            if not privacy.make_private(account):
                raise RuntimeError('계정 폴더 권한 복구 실패: %s' % account)
            data.mkdir(parents=True, exist_ok=True)

        # Both user_data and logs are private; logs live alongside user_data,
        # never in a machine-shared top-level log folder.
        personal_logs = account / 'logs'
        personal_logs.mkdir(parents=True, exist_ok=True)
        for folder in (data, personal_logs):
            if privacy.ensure_private(folder) is not True:
                raise RuntimeError(
                    '개인 데이터/로그 폴더의 ACL 검증 실패: %s. '
                    'Setup / Repair를 실행하세요.' % folder)

        vault.require_private_record_encryption(data)
        vault.require_private_record_encryption(personal_logs)

        for name in ('runtime', 'settings', 'projects'):
            folder = data / name
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                if not privacy.make_private(data):
                    raise RuntimeError('상태 폴더 권한 복구 실패: %s' % data)
                folder.mkdir(parents=True, exist_ok=True)
            if privacy.ensure_private(folder) is not True:
                raise RuntimeError(
                    '개인 상태 폴더 보안 검증 실패: %s. '
                    'Setup / Repair를 실행하세요.' % folder)

    def __init__(self, *, project_root, env, model_dir, data=None, backend=None):
        self.project_root, self.env, self.model_dir = map(Path, (project_root, env, model_dir))
        # ``create_services`` passes the runtime root's user_data, because the
        # source checkout and the folder this product writes to are two
        # different places now. A caller that names only a project root means
        # "this whole install lives here", which is how tests and portable
        # runs express themselves, so that root keeps its own user_data.
        self.data = Path(data) if data is not None else self.project_root / 'user_data'
        if backend is None:
            from integrations.desktop import DesktopBackend
            backend = DesktopBackend(self.env, self.model_dir, self.project_root,
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
        )
        self.search = SearchService(backend, self.network, self.events)
        self.records = SessionStores(self.data, self.events)
        self.chat = ChatService(backend, self.inference, self.network, self.search,
                                self.events, stores=self.records)
        self.agent = AgentLauncher(backend, self.network, self.events, stores=self.records)
        self.translator = TranslationService(
            self.inference, checkpoint_dir=self.data / 'tools' / 'translation')
        self.calendar = CalendarService(self.data / 'tools' / 'calendar' / 'items.json')
        self.reminders = ReminderManager()
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
        # Some Agent sessions explicitly start SearXNG via the legacy runner.
        # Release that owned container only AFTER both Chat and Agent finish.
        search_release = getattr(self.backend, 'agent_search_stop', None)
        if callable(search_release):
            try:
                if not search_release():
                    return False
            except Exception as exc:
                self.events.emit('runtime.error',
                                 {'service': 'agent.search', 'detail': str(exc)})
                return False
        self.network.mode = None
        return True

    def recover_records(self):
        """Seal Chat/Agent stores a crashed session left in plaintext.

        Only where the backend can prove the runtime that used them is not
        running; otherwise they wait for the next verified session stop.
        """
        idle = getattr(self.backend, 'session_runtime_idle', None)
        if not callable(idle):
            return []
        return self.records.recover(idle)

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
    DesktopServices._prepare_private_state(USER_DATA_DIR)
    return DesktopServices(project_root=PROJECT_ROOT, env=ENV_DIR,
                           model_dir=MODEL_STORAGE_DIR, data=USER_DATA_DIR)
