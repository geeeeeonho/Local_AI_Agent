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
from core.network.policy import NetworkMode, NetworkPolicy
from integrations.ollama.client import OllamaClient
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
        if not cls(self.env, model_dir=self.model_dir).ensure_running():
            raise RuntimeError('Ollama ownership/store validation failed. Open Setup / Repair.')
        return self.endpoint


class LegacyBackend:
    def __init__(self, env, model_dir, project_root, *, importer=importlib.import_module):
        self.env, self.model_dir, self.root = map(Path, (env, model_dir, project_root))
        self.load = importer
        self.inference = ManagedInference(self.env, self.model_dir, self.load)
        self._chat_owned_id = None
        self._chat_probe_failed = False
        self._search_runtime = None

    def current_mode(self):
        return self.load('launcher.network_policy').current_mode().value

    def health(self):
        # None is unknown/error, not a falsely reported stopped or ready service.
        checks = {
            'ollama': lambda: self.load('launcher.services.ollama').OllamaService(
                self.env, model_dir=self.model_dir).is_managed_running(),
            'docker': lambda: self.load('launcher.services.docker').DockerService.daemon_alive(),
            'chat': lambda: self.load('launcher.anythingllm_runtime').is_running(),
            'search': lambda: self.load('launcher.services.docker').DockerService.container_running(
                self.load('launcher.config').SEARXNG_CONTAINER),
        }
        result = {}
        for name, check in checks.items():
            try:
                result[name] = bool(check())
            except Exception:
                result[name] = None
        return result

    def prepare_network(self, mode, log):
        selected = NetworkMode(mode)
        policy = self.load('launcher.network_policy')
        policy.set_mode(selected.value)
        if selected is NetworkMode.DIRECT:
            return True
        docker = self.load('launcher.services.docker').DockerService
        if not docker.ensure_daemon(timeout=90):
            return False
        if selected is NetworkMode.BLOCK:
            return bool(policy.ensure_block_network(log=log))
        runtime = self.load('launcher.' + selected.value + '_runtime')
        if not runtime.image_exists():
            log('Network runtime image is missing. Use Setup / Repair.')
            return False
        if selected is NetworkMode.WARP:
            return bool(runtime.start(env=self.env))
        return bool(runtime.start(env=self.env, log=log))

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

    def chat_image_exists(self):
        return bool(self.load('launcher.anythingllm_runtime').image_exists())

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
    _DEFAULT_CHAT_CONTEXT = 4096

    def _chat_context(self, cfg):
        """Token limit for AnythingLLM, from whichever source is actually present."""
        roles = None
        try:
            roles = self.load('launcher.models.model_roles')
        except Exception:
            roles = None
        for value in (getattr(roles, 'chat_context_window', None),
                      getattr(cfg, 'MODEL_CONTEXT', None),
                      getattr(cfg, 'CHAT_CONTEXT_WINDOW', None)):
            try:
                resolved = int(value() if callable(value) else value)
            except Exception:
                continue
            if resolved > 0:
                return resolved
        return self._DEFAULT_CHAT_CONTEXT

    def chat_start(self, model, log, cancel):
        runtime = self.load('launcher.anythingllm_runtime')
        cfg = self.load('launcher.config')
        if not self.load('launcher.services.docker').DockerService.ensure_daemon(
                timeout=90, cancel_check=cancel):
            raise RuntimeError('Docker is unavailable. Open Setup / Repair.')
        before = self._chat_id()
        self._chat_probe_failed = False
        context = self._chat_context(cfg)
        try:
            if not runtime.start(log=log, model_tag=model or cfg.MODEL_TAG,
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

    # launcher.actions re-exports `searxng`/`settings` under *_action names as
    # package attributes. They are not submodules, so import_module cannot find
    # them; the operation key is mapped to the real module name here instead.
    MAINTENANCE_MODULES = {
        'docker_image': 'docker_image',
        'docker_clean': 'docker_clean',
        'searxng_action': 'searxng',
        'settings_action': 'settings',
        'ollama_action': 'ollama',
    }

    def maintenance(self, key, presenter):
        module = self.MAINTENANCE_MODULES.get(key)
        if module is None:
            raise ValueError('unknown maintenance operation: ' + str(key))
        return self.load('launcher.actions.' + module).run(self.env, presenter)

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
