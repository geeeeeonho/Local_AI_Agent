"""Transition adapters to reviewed launcher runtimes; never import apps.

This file deliberately leaves existing security and container implementations
in place. Their eventual physical relocation is not required to use one shared
service boundary, and must not weaken their fail-closed behavior.
"""
from pathlib import Path
import importlib
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from core.network.policy import NetworkMode, NetworkPolicy
from integrations.ollama.client import OllamaClient, is_cloud_tag
from core.urls import local_url
from core.agent import AgentBinding


class ManagedInference:
    def __init__(self, env, model_dir, importer):
        self.env, self.model_dir, self.load = env, model_dir, importer
        cfg = self.load('launcher.config')
        self.endpoint = 'http://127.0.0.1:' + str(int(cfg.OLLAMA_PORT))
        self.client = OllamaClient(self.endpoint)

    def ensure_running(self):
        cls = self.load('launcher.services.ollama').OllamaService
        service = cls(self.env, model_dir=self.model_dir)
        if not service.ensure_running():
            detail = getattr(service, 'last_error', '') or 'Ollama ownership/store validation failed.'
            raise RuntimeError(detail + ' Open Setup / Repair.')
        return self.endpoint


class LegacyBackend:
    def __init__(self, env, model_dir, project_root, *, importer=importlib.import_module):
        self.env, self.model_dir, self.root = map(Path, (env, model_dir, project_root))
        self.load = importer
        self.inference = ManagedInference(self.env, self.model_dir, self.load)
        self._chat_owned_id = None
        self._chat_probe_failed = False
        self._search_runtime = None
        self._health = None          # (monotonic, result)

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
            'docker': lambda: self.load('launcher.services.docker').DockerService.daemon_alive(),
            'chat_image': lambda: self.load('launcher.anythingllm_runtime').image_exists(),
            'chat': lambda: self.load('launcher.anythingllm_runtime').is_ready(),
            'search': lambda: self.load('launcher.services.docker').DockerService.container_running(
                self.load('launcher.config').SEARXNG_CONTAINER),
        }
        started = time.monotonic()

        def run(check):
            try:
                return bool(check())
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix='health') as pool:
            futures = {name: pool.submit(run, check) for name, check in checks.items()}
            result = {name: future.result() for name, future in futures.items()}
        result['probe_seconds'] = round(time.monotonic() - started, 3)
        return result

    def prepare_network(self, mode, log):
        selected = NetworkMode(mode)
        policy = self.load('launcher.network_policy')
        if selected is NetworkMode.DIRECT:
            policy.set_mode(selected.value)
            return True
        docker = self.load('launcher.services.docker').DockerService
        if not docker.ensure_daemon(timeout=90):
            return False
        if selected is NetworkMode.BLOCK:
            ok = bool(policy.ensure_block_network(log=log))
        else:
            runtime = self.load('launcher.' + selected.value + '_runtime')
            if not runtime.image_exists():
                log('Network runtime image is missing. Use Setup / Repair.')
                return False
            if selected is NetworkMode.WARP:
                ok = bool(runtime.start(env=self.env))
            else:
                ok = bool(runtime.start(env=self.env, log=log))
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
            self.root / 'user_data' / 'cache' / 'search',
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
        if not docker.ensure_daemon(timeout=90, cancel_check=cancel):
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

    # The retained launcher reads this through getattr with a default; copying
    # the lookup without the default turned a missing constant into a crash.
    def chat_start(self, model, log, cancel):
        runtime = self.load('launcher.anythingllm_runtime')
        cfg = self.load('launcher.config')
        if not self.load('launcher.services.docker').DockerService.ensure_daemon(
                timeout=90, cancel_check=cancel):
            raise RuntimeError('Docker is unavailable. Open Setup / Repair.')
        before = self._chat_id()
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
        # Reused containers belong to their original owner. A container recreated
        # by start() has a new ID and must not escape this window's cleanup.
        if self._chat_probe_failed:
            return False
        if self._chat_owned_id is None:
            return True
        current = self._chat_id()
        if current is None:
            self._chat_owned_id = None
            return True
        if current != self._chat_owned_id:
            return False
        docker = self.load('launcher.services.docker').DockerService
        # Use the immutable ID, not a name that an external process can replace.
        if not docker.stop_container(self._chat_owned_id, timeout=3):
            return False
        if self._chat_id() is not None:
            return False
        self._chat_owned_id = None
        return True

    def agent_open(self, presenter, network, project):
        old = self.load('launcher.actions.agent_chat')
        if not old._ensure_gui(presenter):
            return None
        # The original selector owns profile, folder policy and Host confirmation.
        # A project path is a dialog default, never an automatic permission grant.
        presenter.workspace_default = getattr(project, 'workspace_path', '')
        selected = old._select_setup(self.env, presenter)
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
        if not coordinator.prepare_runtime(self.env, presenter, mode, chosen_network):
            return None
        cfg = self.load('launcher.config')
        tag = old._match_installed_model(str(model_selection.get('tag') or cfg.MODEL_TAG), presenter)
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
                description=old._approval_description(event, Path(workspace)), risk=risk)
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

    # The retained package re-exports two of these under *_action aliases, so a
    # module path built from the key alone raised ModuleNotFoundError the first
    # time a user pressed those buttons. Name the real modules here instead.
    def prepare_model_runtime(self):
        """Make Ollama usable for explicit model management.

        Model selection is itself an explicit install action, so it may acquire
        the Ollama binary when the machine has none. A healthy existing server
        is reused. Otherwise we stop only a recognized Ollama, migrate legacy
        model data through the installer's guarded filesystem path, install the
        official binary (portable fallback), and start it against the resolved
        store.
        """
        service_cls = self.load('launcher.services.ollama').OllamaService
        service = service_cls(self.env, model_dir=self.model_dir)
        if service.ensure_running():
            return self.inference.endpoint

        ollama = self.load('installer.steps.ollama')
        utils = self.load('installer.utils')
        project_paths = self.load('project_paths')

        ollama.prepare_install(self.env, self.model_dir)
        if Path(self.model_dir) == Path(project_paths.MODEL_STORAGE_DIR):
            paths = utils.create_environment(self.env)
        else:
            paths = utils.create_environment(self.env, model_dir=self.model_dir)
        ollama.install(paths)
        ollama.start_service(paths)
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

    def setup_command(self):
        executable = Path(sys.executable)
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        return [str(executable), '-m', 'installer', '--install']

    def run_setup(self):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(self.root / 'src')
        kwargs = {'cwd': self.root, 'env': environment}
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_CONSOLE
        # Explicit Setup action only. No shell and no detached untracked install.
        result = subprocess.run(self.setup_command(), **kwargs)
        if result.returncode:
            raise RuntimeError('Setup exited with code ' + str(result.returncode))
        return result.returncode
