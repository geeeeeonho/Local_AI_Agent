"""Desktop integration boundary to the launcher runtimes; never import apps.

The application services use this module as the single adapter to the mature
launcher/container implementations. It contains active runtime code, not a
compatibility or migration layer.
"""
from pathlib import Path
import importlib
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from core.calls import invoke
from core.network.policy import NetworkMode, NetworkPolicy
from core.progress import LogAdapter
from integrations.ollama.client import OllamaClient, is_cloud_tag
from core.urls import local_url
from core.agent import AgentBinding


class ManagedInference:
    def __init__(self, env, model_dir, importer):
        self.env, self.model_dir, self.load = env, model_dir, importer
        cfg = self.load('launcher.config')
        self.endpoint = 'http://127.0.0.1:' + str(int(cfg.OLLAMA_PORT))
        self.client = OllamaClient(self.endpoint)

    def local_models(self):
        """Delegate to the Ollama service so there is one way of asking."""
        cls = self.load('launcher.services.ollama').OllamaService
        return cls(self.env, model_dir=self.model_dir).local_models()

    def describe_models(self):
        """Why nothing is runnable, distinguishing absent from invisible."""
        cls = self.load('launcher.services.ollama').OllamaService
        service = cls(self.env, model_dir=self.model_dir)
        situation, detail = service.inspect_store()
        if situation != service.STORE_NOT_READ:
            return None
        held = detail.get('on_disk') or ()
        return ('설치된 모델 %d개가 %s 에 있는데 실행 중인 Ollama 가 그 경로를 읽지 '
                '않습니다. 모델 화면의 [Ollama 시작 / 확인] 에서 이 경로로 다시 시작하세요. '
                '(%s)' % (len(held), self.model_dir, ', '.join(list(held)[:4])))

    def ensure_running(self, log=None):
        cls = self.load('launcher.services.ollama').OllamaService
        # 로거를 주지 않으면 최대 30초의 기동이 통째로 침묵한다. Chat 준비창이
        # [2/5] 에서 멈춘 것처럼 보이던 원인이다.
        service = cls(self.env, logger=LogAdapter(log) if log else None,
                      model_dir=self.model_dir)
        if not service.ensure_running():
            detail = getattr(service, 'last_error', '') or 'Ollama ownership/store validation failed.'
            raise RuntimeError(detail + ' Open Setup / Repair.')
        return self.endpoint


class DesktopBackend:
    def __init__(self, env, model_dir, project_root, *, data=None,
                 importer=importlib.import_module):
        self.env, self.model_dir, self.root = map(Path, (env, model_dir, project_root))
        # Where this product writes. DesktopServices hands over the runtime
        # root's user_data; a caller that names only a project root means the
        # whole install lives there, which is how portable runs and tests
        # express themselves.
        self.data = Path(data) if data is not None else self.root / 'user_data'
        self.load = importer
        self.inference = ManagedInference(self.env, self.model_dir, self.load)
        self._chat_owned_id = None
        self._chat_before_id = None
        self._chat_probe_failed = False
        self._search_runtime = None
        self._health = None          # (monotonic, result)

    def describe_records_privacy(self):
        """Report when this account's private record tree has a bad ACL.

        The model store is deliberately shared, but users/<account> is a
        separate sibling subtree and must remain private to that account,
        SYSTEM and Administrators.
        """
        paths = self.load('project_paths')
        privacy = self.load('integrations.windows.privacy')
        if privacy.is_private(paths.ACCOUNT_ROOT) is not False:
            return None
        return ('이 PC 의 다른 Windows 계정이 내 기록(%s)을 읽을 수 있습니다 · '
                '[설치 / 복구] 를 한 번 실행하면 이 계정 전용으로 잠급니다'
                % paths.ACCOUNT_ROOT)

    def current_mode(self):
        return self.load('launcher.network_policy').current_mode().value

    # A status line is not worth a process storm. Each health pass shells out to
    # Docker three times and, on Windows, runs PowerShell twice to identify the
    # port's owner; the desktop polls it on a timer. Answers this coarse do not
    # change within a few seconds, so a repeat inside the window reuses the last
    # one. Anything that acts on the result - ensure_running before a real
    # operation, or the user pressing refresh - asks for a fresh pass.
    HEALTH_MAX_AGE = 30.0

    def health(self, max_age=None):
        max_age = self.HEALTH_MAX_AGE if max_age is None else max_age
        cached = self._health
        if cached is not None and max_age > 0:
            age = time.monotonic() - cached[0]
            if 0 <= age < max_age:
                return dict(cached[1])
        result = self._probe_health()
        self._health = (time.monotonic(), dict(result))
        return result

    def _probe_health(self):
        # None is unknown/error, not a falsely reported stopped or ready service.
        # These probes are independent and several shell out to Docker/PowerShell.
        # Running them serially made a harmless status refresh look like a stalled
        # connection on Windows.
        checks = {
            'ollama': lambda: self.load('launcher.services.ollama').OllamaService(
                self.env, model_dir=self.model_dir).is_managed_running(),
            # Where the running Ollama keeps its models is the thing the status
            # line could not say, so a server that was serving perfectly well
            # from its own default directory read as "not recognised".
            'ollama_store': lambda: self.load('launcher.services.ollama').OllamaService(
                self.env, model_dir=self.model_dir).describe_store(),
            'docker': lambda: self.load('launcher.services.docker').DockerService.daemon_alive(),
            'chat_image': lambda: self.load('launcher.anythingllm_runtime').image_exists(),
            'chat': lambda: self.load('launcher.anythingllm_runtime').is_ready(),
            'search': lambda: self.load('launcher.services.docker').DockerService.container_running(
                self.load('launcher.config').SEARXNG_CONTAINER),
            # Personal records sharing a folder with the machine's other
            # accounts is not a smaller problem than a missing install.
            'records_private': self.describe_records_privacy,
        }
        started = time.monotonic()

        def run(check):
            try:
                value = check()
            except Exception:
                return None
            # One of these answers in words rather than yes/no.
            return value if isinstance(value, str) else bool(value)

        with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix='health') as pool:
            futures = {name: pool.submit(run, check) for name, check in checks.items()}
            result = {name: future.result() for name, future in futures.items()}
        result['probe_seconds'] = round(time.monotonic() - started, 3)
        return result

    def prepare_network(self, mode, log, cancel=None):
        selected = NetworkMode(mode)
        policy = self.load('launcher.network_policy')
        if selected is NetworkMode.DIRECT:
            policy.set_mode(selected.value)
            return True
        docker = self.load('launcher.services.docker').DockerService
        # 로거 없이 부르면 Docker Desktop 자동 시작이 최대 90초 동안 아무 말도
        # 하지 않고, 취소도 되지 않는다. 사용자가 보던 것은 멈춘 창뿐이었다.
        if not docker.ensure_daemon(logger=LogAdapter(log), timeout=90,
                                    cancel_check=cancel):
            return False
        if selected is NetworkMode.BLOCK:
            ok = bool(policy.ensure_block_network(log=log))
        else:
            runtime = self.load('launcher.' + selected.value + '_runtime')
            if not runtime.image_exists():
                log('Network runtime image is missing. Use Setup / Repair.')
                return False
            # Both runtimes take a progress callback now. WARP not taking one
            # was why the default network mode prepared in total silence.
            ok = bool(invoke(runtime.start, env=self.env, log=log, cancel_check=cancel))
        # Do not publish a mode that failed to prepare. AnythingLLM reads the
        # canonical mode later, so a failed WARP/Tor/Block attempt must not poison
        # the next retry.
        if ok:
            policy.set_mode(selected.value)
        return ok

    def search_start(self, mode, log):
        if NetworkMode(mode) is NetworkMode.BLOCK:
            raise ValueError('Search is disabled in Block')
        from integrations.searxng.runtime import SearchRuntime
        cfg = self.load('launcher.config')
        policy = self.load('launcher.network_policy')
        self._search_runtime = SearchRuntime(
            self.env / 'searxng' / 'config' / 'settings.yml',
            self.data / 'cache' / 'search',
            self.load('launcher.services.docker').DockerService,
            image=cfg.SEARXNG_IMAGE, container=cfg.SEARXNG_CONTAINER,
            network=cfg.LLM_NETWORK, host_port=cfg.SEARXNG_HOST_PORT,
            container_port=cfg.SEARXNG_CONTAINER_PORT)
        proxy = policy.container_proxy_env(mode).get('ALL_PROXY', '')
        return self._search_runtime.start(mode, proxy)

    def search_stop(self):
        return self._search_runtime is None or self._search_runtime.stop()

    def chat_prepare(self, log, cancel=None):
        """Ensure Docker is actually usable before treating image state as fact."""
        docker = self.load('launcher.services.docker').DockerService
        if docker.daemon_alive():
            return True
        log('Docker Desktop 준비 중...')
        if not docker.ensure_daemon(logger=LogAdapter(log), timeout=90, cancel_check=cancel):
            raise RuntimeError('Docker is unavailable. Start Docker Desktop or use Setup / Repair.')
        log('Docker Desktop 준비 완료')
        return True

    def chat_image_exists(self):
        return bool(self.load('launcher.anythingllm_runtime').image_exists())

    def chat_active_model(self):
        return str(self.load('launcher.anythingllm_runtime').configured_model() or '')

    def _resolve_chat_model(self, requested='', log=None):
        """Return an actually installed local Ollama tag for AnythingLLM.

        Project Chat model is optional. Falling back to config.MODEL_TAG made
        Chat fail on machines that correctly installed a lighter model. Ollama
        can also return the same tag with different casing, so preserve the
        spelling reported by /api/tags instead of comparing case-sensitively.
        """
        try:
            rows = self.inference.client.list_models()
        except Exception as exc:
            raise RuntimeError('Ollama model list could not be read: ' + str(exc)) from exc

        installed = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or row.get('model') or '').strip()
            if name and not is_cloud_tag(name):
                installed.append(name)

        wanted = str(requested or '').strip()
        if wanted:
            if is_cloud_tag(wanted):
                raise RuntimeError('Chat cannot use an Ollama cloud tag under the local network policy: ' + wanted)
            wanted_lower = wanted.lower()
            for name in installed:
                if name.lower() == wanted_lower:
                    if log and name != wanted:
                        log('Chat 모델 태그 정규화: ' + wanted + ' -> ' + name)
                    return name
            shown = ', '.join(installed[:8]) if installed else '(없음)'
            raise RuntimeError(
                '선택한 Chat 모델이 Ollama에 설치되어 있지 않습니다: ' + wanted +
                ' · 설치된 로컬 모델: ' + shown
            )

        if not installed:
            raise RuntimeError(
                'Chat에 사용할 로컬 Ollama 모델이 없습니다. 모델 화면에서 모델을 먼저 설치하세요.'
            )

        # Prefer the existing balanced role ladder, but only if that candidate is
        # truly installed. If the user installed a custom local model, keep Chat
        # usable by selecting the first real local tag instead of a static default.
        try:
            roles = self.load('launcher.models.model_roles')
            catalog = self.load('launcher.models.model_catalog')
            chosen = roles.resolve_ladder('balanced', installed=set(installed))
            matched = catalog.find_installed(chosen, installed) if chosen else None
            if matched:
                if log:
                    log('Chat 모델 자동 선택: ' + str(matched))
                return str(matched)
        except Exception:
            pass

        chosen = installed[0]
        if log:
            log('Chat 모델 자동 선택: ' + chosen)
        return chosen

    def _chat_id(self):
        runtime = self.load('launcher.anythingllm_runtime')
        result = self.load('launcher.services.docker').DockerService.run(
            ['ps', '--filter', 'name=^/' + runtime.CONTAINER + '$',
             '--no-trunc', '--format', '{{.ID}}'], timeout=10)
        if result is None or result.returncode != 0:
            raise RuntimeError('Unable to verify the Chat container identity.')
        identifiers = (result.stdout or '').split()
        if len(identifiers) > 1:
            raise RuntimeError('Ambiguous Chat container ownership.')
        return identifiers[0] if identifiers else None

    # The launcher reads this through getattr with a default; copying
    # the lookup without the default turned a missing constant into a crash.
    def chat_start(self, model, log, cancel):
        runtime = self.load('launcher.anythingllm_runtime')
        cfg = self.load('launcher.config')
        if not self.load('launcher.services.docker').DockerService.ensure_daemon(
                logger=LogAdapter(log), timeout=90, cancel_check=cancel):
            raise RuntimeError('Docker is unavailable. Open Setup / Repair.')
        self._chat_before_id = None
        before = self._chat_id()
        self._chat_before_id = before
        self._chat_probe_failed = False
        # Resolve against the live Ollama inventory before writing AnythingLLM
        # settings. This avoids both a missing static default and case-only tag
        # mismatches between the catalogue and Ollama /api/tags.
        model = self._resolve_chat_model(model, log=log)

        # launcher.config.CHAT_CONTEXT_WINDOW (TOKEN_LIMITS_v1) is the one context
        # source. The previous pair named two attributes that never existed, so the
        # fallback raised AttributeError and Chat could not start at all.
        context = int(cfg.CHAT_CONTEXT_WINDOW)
        try:
            if not runtime.start(log=log, model_tag=model,
                                 token_limit=context, cancel_check=cancel):
                raise RuntimeError('AnythingLLM failed to start with the selected network policy.')
        finally:
            try:
                after = self._chat_id()
                self._chat_owned_id = after if after != before else None
            except Exception:
                self._chat_probe_failed = True
                raise
        return local_url(runtime.URL)

    def chat_stop(self):
        # A container cannot outlive its daemon. If Docker Desktop was stopped
        # or crashed while this window was open, asking it to identify our
        # container raised out of close() and the window could never be closed
        # again - for a container that had already died with the daemon.
        if self._chat_probe_failed or self._chat_owned_id is not None:
            if not self._daemon_alive():
                self._chat_probe_failed = False
                self._chat_owned_id = None
                return True
        # Reused containers belong to their original owner. A container recreated
        # by start() has a new ID and must not escape this window's cleanup.
        if self._chat_probe_failed:
            # A Docker hiccup during start used to latch this flag forever, and
            # nothing cleared it but another successful start. Shutdown then
            # reported "could not be verified" on every attempt and the window
            # could not be closed at all. Ask Docker again instead of refusing.
            try:
                recovered = self._chat_id()
            except Exception:
                return False
            self._chat_probe_failed = False
            if self._chat_owned_id is None and recovered is not None \
                    and recovered != self._chat_before_id:
                # The probe failed exactly when start() had already created the
                # container, so ownership was never recorded. Claim it now
                # instead of leaking it past the window that made it.
                self._chat_owned_id = recovered
        if self._chat_owned_id is None:
            return True
        try:
            current = self._chat_id()
        except Exception:
            # Unverified is not stopped, but it is also not a reason to raise
            # out of shutdown: report it and let the user retry.
            return False
        if current is None:
            self._chat_owned_id = None
            return True
        if current != self._chat_owned_id:
            return False
        docker = self.load('launcher.services.docker').DockerService
        # Use the immutable ID, not a name that an external process can replace.
        if not docker.stop_container(self._chat_owned_id, timeout=3):
            return False
        try:
            if self._chat_id() is not None:
                return False
        except Exception:
            return False
        self._chat_owned_id = None
        return True

    def _daemon_alive(self):
        """``False`` only when Docker provably is not there. Errors are unknown."""
        try:
            return bool(self.load('launcher.services.docker').DockerService.daemon_alive())
        except Exception:
            return True

    def agent_open(self, presenter, network, project, cancel=None):
        agent_ui = self.load('launcher.actions.agent_chat')
        if not agent_ui._ensure_gui(presenter):
            return None
        # The original selector owns profile, folder policy and Host confirmation.
        # A project path is a dialog default, never an automatic permission grant.
        presenter.workspace_default = getattr(project, 'workspace_path', '')
        selected = agent_ui._select_setup(self.env, presenter)
        if selected is None:
            return None
        profile, workspace, mode, model_selection, chosen_network = selected
        NetworkPolicy(NetworkMode(chosen_network.value), execution=mode)
        if chosen_network.value != network:
            self.load('launcher.network_policy').set_mode(network)
            presenter.error('The active network is pinned to ' + network + '. '
                            'Choose the same mode in the Agent wizard, or close active sessions first.')
            return None
        coordinator = self.load('launcher.agent.runtime_coordinator')
        if not invoke(coordinator.prepare_runtime, self.env, presenter, mode,
                      chosen_network, cancel=cancel):
            return None
        cfg = self.load('launcher.config')
        tag = agent_ui._match_installed_model(str(model_selection.get('tag') or cfg.MODEL_TAG), presenter)
        if not tag:
            return None
        runtime_config = self.load('launcher.agent.runtime_config')
        memory, cpus = runtime_config.resolve_resource_limits(self.env)
        name = cfg.SANDBOX_CONTAINER_PREFIX + 'chat_' + secrets.token_hex(4)
        command, is_host = runtime_config.build_cmd_for_mode(
            mode, self.env, profile, Path(workspace), name, memory, cpus, model_tag=tag)
        if command is None:
            raise RuntimeError('Agent runtime unavailable. Open Setup / Repair.')
        instance = coordinator.RuntimeCoordinator(env=self.env, profile=profile,
            workspace=Path(workspace), mode=mode, selected_network=chosen_network,
            model_tag=tag, run_mem=memory, run_cpus=cpus, command=list(command))
        factory = self.load('launcher.agent.chat_session_controller').ChatSessionController
        risk = self.load('launcher.presenter.base').RISK_HIGH
        def approve(event):
            return presenter.confirm_dangerous(label='Open Interpreter approval',
                description=agent_ui._approval_description(event, Path(workspace)), risk=risk)
        return AgentBinding(instance, factory, approve, {
            'workspace': str(workspace), 'mode': mode, 'network': chosen_network.value,
            'model': tag, 'memory': memory, 'cpus': cpus,
            'profile': str(getattr(profile, 'label', None) or getattr(profile, 'name', 'Agent'))})

    def create_presenter(self, window):
        base = self.load('launcher.presenter.gui').TkPresenter

        class DesktopPresenter(base):
            def prompt_path(self, title, default, last_used=None, must_exist=True):
                preferred = getattr(self, 'workspace_default', '')
                return super().prompt_path(title, Path(preferred) if preferred else default,
                    last_used=Path(preferred) if preferred else last_used, must_exist=must_exist)

        presenter = DesktopPresenter()
        presenter._window = window
        return presenter

    def create_agent_panel(self, parent, metadata, callbacks):
        panel_type = self.load('launcher.presenter.gui.chat_panel').ChatPanel
        panel = panel_type(parent, title='Open Interpreter - ' + metadata['profile'],
            subtitle=metadata['mode'] + ' | ' + metadata['network'] + ' | ' + metadata['workspace'],
            workspace=Path(metadata['workspace']))
        panel.set_input_callback(callbacks['input'])
        panel.set_stop_callback(callbacks['stop'])
        panel.set_restart_callback(callbacks['restart'])
        panel.set_current_model(metadata['model'])
        panel.set_status('Mode: ' + metadata['mode'] + '\nNetwork: ' + metadata['network'] +
                         '\nMemory: ' + metadata['memory'] + '\nCPU: ' + metadata['cpus'])
        panel.refresh_files(Path(metadata['workspace']))
        panel.set_open_folder_callback(lambda: self.load('launcher.actions.agent_chat')._open_folder(
            Path(metadata['workspace'])))
        # Lifetime is owned by AgentSession and DesktopWindow, not panel destruction.
        return panel

    # The launcher package re-exports two of these under *_action aliases, so a
    # module path built from the key alone raised ModuleNotFoundError the first
    # time a user pressed those buttons. Name the real modules here instead.
    def prepare_model_runtime(self):
        """Start the shared Ollama broker without re-installing private account data.

        The Models page changes C:/LocalAI/models, not users/<account>. A
        failed Ollama start previously invoked create_environment(), which
        unconditionally tried to rewrite the private account ACL and could
        abort a model-only action for an unrelated account-permission issue.
        Privacy enforcement stays mandatory for full Setup and personal data.
        """
        service_cls = self.load('launcher.services.ollama').OllamaService
        service = service_cls(self.env, model_dir=self.model_dir)
        if service.ensure_running():
            return self.inference.endpoint

        # A present broker that failed to start (or is serving another store)
        # is not an "uninstalled" broker. Do not conceal its original error by
        # attempting full Setup, changing private ACLs, or overwriting binaries.
        if service.is_installed():
            # Match explicit Setup's safe store-repair path, without invoking
            # the full installer. restart_for_store() refuses unknown processes
            # and a broker that is actively serving models.
            if service.is_running() and service.restart_for_store():
                return self.inference.endpoint
            detail = (getattr(service, 'last_error', '') or
                      '설치된 Ollama를 시작하거나 공용 모델 저장소에 연결하지 못했습니다.')
            raise RuntimeError(
                detail + '\n모델 변경 중 전체 설치/개인 폴더 권한 복구는 실행하지 않았습니다. '
                '모델 화면의 [Ollama 시작 / 확인]에서 상태를 확인하세요.'
            )

        # The broker is genuinely missing. Only prepare its shared locations:
        # installing a model must never create or relax users/<account> ACLs.
        ollama = self.load('installer.steps.ollama')
        project_paths = self.load('project_paths')
        model_store = Path(self.model_dir)
        broker = Path(project_paths.OLLAMA_INSTALL_DIR)
        ollama.prepare_install(self.env, model_store)
        try:
            broker.mkdir(parents=True, exist_ok=True)
            model_store.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                '공용 Ollama/모델 폴더에 쓸 수 없습니다: %s 또는 %s. '
                '기존 설치 계정에서 공용 설치 경로의 권한을 확인하세요. (%s)'
                % (broker, model_store, exc)
            ) from exc
        shared_paths = {'env': Path(self.env), 'ollama': broker, 'models': model_store}
        ollama.install(shared_paths)
        ollama.start_service(shared_paths)
        return self.inference.endpoint

    MAINTENANCE_MODULES = {
        'docker_image': 'launcher.actions.docker_image',
        'docker_clean': 'launcher.actions.docker_clean',
        'settings_action': 'launcher.actions.settings',
        'searxng_action': 'launcher.actions.searxng',
        'ollama_action': 'launcher.actions.ollama',
    }

    def maintenance(self, key, presenter):
        module = self.MAINTENANCE_MODULES.get(key)
        if module is None:
            raise ValueError('unknown maintenance operation: ' + str(key))
        return self.load(module).run(self.env, presenter)

    @staticmethod
    def setup_exit_message(code) -> str:
        """Turn Windows process exit codes into a useful Setup failure message."""
        raw = int(code)
        unsigned = raw & 0xFFFFFFFF
        hex_code = "0x%08X" % unsigned
        if unsigned == 0xC000013A:
            return (
                "설치 / 복구 창이 닫혔거나 작업이 취소되었습니다 "
                "(종료 코드 %s / %s)." % (raw, hex_code)
            )
        return "설치 / 복구가 종료 코드 %s (%s)로 실패했습니다." % (raw, hex_code)


    def setup_command(self, options=None):
        """Build the hidden installer command from choices already made in UI."""
        options = dict(options or {})
        executable = Path(sys.executable)
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        command = [str(executable), '-m', 'installer', '--install', '--embedded']
        language = str(options.get('lang') or '').strip().lower()
        if language not in ('ko', 'en'):
            try:
                from installer.i18n import get_language
                language = str(get_language()).strip().lower()
            except Exception:
                language = ''
        if language in ('ko', 'en'):
            command += ['--lang', language]
        if not options.get('sandbox', True):
            command.append('--skip-sandbox')
        if not options.get('build', True):
            command.append('--skip-build')
        if not options.get('search', True):
            command.append('--skip-search')
        return command

    @staticmethod
    def _stop_setup_process(process):
        if process.poll() is not None:
            return
        if os.name == 'nt':
            try:
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                    timeout=10,
                    check=False,
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass

    def run_setup(self, options=None, log=None, cancel=None):
        """Run Setup invisibly and stream every line into the desktop UI.

        The installer stays a separate process so a broken dependency install
        cannot corrupt the Tk process, but it owns no console/window. Its stdout
        and every child command inheriting stdout are piped back to the one
        LocalAI activity log.
        """
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(self.root / 'src')
        environment['PYTHONUTF8'] = '1'
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['PYTHONUNBUFFERED'] = '1'
        kwargs = {
            'cwd': self.root,
            'env': environment,
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
            'text': True,
            'encoding': 'utf-8',
            'errors': 'replace',
            'bufsize': 1,
        }
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

        process = subprocess.Popen(self.setup_command(options), **kwargs)
        lines = queue.Queue()
        finished = object()

        def read_output():
            # Install/download tools use both newline logs and carriage-return
            # progress bars. Treat either delimiter as a UI update so a 1.5GB
            # download does not look frozen until its final newline.
            buffer = []
            try:
                stream = process.stdout
                if stream is not None:
                    while True:
                        char = stream.read(1)
                        if not char:
                            break
                        if char in ('\r', '\n'):
                            if buffer:
                                lines.put(''.join(buffer))
                                buffer.clear()
                        else:
                            buffer.append(char)
                            if len(buffer) >= 4096:
                                lines.put(''.join(buffer))
                                buffer.clear()
                    if buffer:
                        lines.put(''.join(buffer))
            finally:
                lines.put(finished)

        threading.Thread(
            target=read_output, daemon=True, name='localai-setup-output'
        ).start()

        reader_done = False
        while True:
            if cancel is not None and cancel():
                if log:
                    log('설치 / 복구 취소 요청 — 실행 중인 설치 프로세스를 종료합니다.')
                self._stop_setup_process(process)
                raise RuntimeError('설치 / 복구가 취소되었습니다.')

            try:
                item = lines.get(timeout=0.1)
            except queue.Empty:
                item = None
            if item is finished:
                reader_done = True
            elif item and log:
                log(str(item))

            code = process.poll()
            if code is not None and reader_done:
                break

        code = int(process.returncode or 0)
        if code:
            raise RuntimeError(self.setup_exit_message(code))
        return code
