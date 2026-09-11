"""Application contracts tested with real state files and injected runtime I/O."""
from pathlib import Path
from types import SimpleNamespace
import threading
import pytest


class Backend:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.ready = True
        self.images = True
        self.mode = 'warp'
        self.inference = SimpleNamespace(model_dir=root / 'models',
            client=SimpleNamespace(list_models=lambda: [], pull=self.pull, remove=self.remove),
            ensure_running=lambda: 'http://127.0.0.1:11434')
        self.inference.model_dir.mkdir(exist_ok=True)
    def pull(self, name, progress=None): self.calls.append(('pull', name))
    def remove(self, name): self.calls.append(('remove', name))
    def health(self): return {'ollama': True, 'docker': False, 'chat': False, 'search': False}
    def prepare_network(self, mode, log):
        self.calls.append(('prepare', mode)); self.mode = mode; return self.ready
    def current_mode(self): return self.mode
    def search_start(self, mode, log): self.calls.append(('search', mode)); return True
    def search_stop(self): self.calls.append(('search_stop',)); return True
    def chat_image_exists(self): return self.images
    def chat_start(self, model, log, cancel): self.calls.append(('chat', model)); return 'http://127.0.0.1:3001'
    def agent_open(self, presenter, network, project):
        from test_desktop_session import binding
        self.calls.append(('agent', network, project))
        return binding()[0]
    def agent_stop(self): self.calls.append(('agent_stop',)); return True
    def chat_stop(self): self.calls.append(('chat_stop',)); return True
    def maintenance(self, key, presenter): self.calls.append(('maintenance', key))
    def create_presenter(self, window): return SimpleNamespace(_window=window)
    def setup_command(self): return ['python', '-m', 'installer', '--install']


def make(tmp_path):
    from services.desktop import DesktopServices
    backend = Backend(tmp_path)
    env = tmp_path / 'llm_environment'
    env.mkdir(exist_ok=True)
    svc = DesktopServices(project_root=tmp_path, env=env,
        model_dir=backend.inference.model_dir, backend=backend)
    return svc, backend


def test_composition_is_side_effect_free_until_requested(tmp_path):
    svc, backend = make(tmp_path)
    assert backend.calls == []
    assert not (tmp_path / 'user_data').exists()
    assert svc.model_dir == backend.inference.model_dir


def test_health_does_not_start_or_repair_services(tmp_path):
    svc, backend = make(tmp_path)
    assert svc.system.health()['docker'] is False
    assert not backend.calls


@pytest.mark.parametrize('value', ['', 'off', 'garbage', 'DIRECT ', None])
def test_invalid_mode_is_not_silently_used(tmp_path, value):
    svc, backend = make(tmp_path)
    with pytest.raises(ValueError): svc.network.prepare(value)
    assert backend.calls == []
    svc.close()


def test_block_prepare_failure_prevents_chat_start(tmp_path):
    svc, backend = make(tmp_path); backend.ready = False
    with pytest.raises(RuntimeError): svc.chat.start('block')
    assert backend.calls == [('prepare', 'block')]
    svc.close()


def test_chat_requires_installed_image_not_implicit_download(tmp_path):
    svc, backend = make(tmp_path); backend.images = False
    with pytest.raises(RuntimeError, match='Setup'):
        svc.chat.start('direct')
    assert not any(call[0] in ('chat', 'pull') for call in backend.calls)
    svc.close()


def test_block_chat_never_starts_search(tmp_path):
    svc, backend = make(tmp_path)
    assert svc.chat.start('block') == 'http://127.0.0.1:3001'
    assert ('prepare', 'block') in backend.calls
    assert not any(call[0] == 'search' for call in backend.calls)
    svc.close()


def test_search_disabled_in_block_even_when_called_directly(tmp_path):
    svc, backend = make(tmp_path)
    with pytest.raises(RuntimeError): svc.search.start('block')
    assert not backend.calls
    svc.close()


def test_runtime_owner_prevents_other_window_from_changing_network(tmp_path):
    first, _ = make(tmp_path); second, backend = make(tmp_path)
    first.chat.start('warp')
    with pytest.raises(RuntimeError, match='window|busy'):
        second.chat.start('block')
    assert not backend.calls
    first.close()
    assert second.chat.start('block')
    second.close()


def test_same_window_cannot_switch_live_network(tmp_path):
    svc, backend = make(tmp_path); svc.chat.start('warp')
    with pytest.raises(RuntimeError, match='active|session'):
        svc.network.prepare('block')
    assert ('prepare', 'block') not in backend.calls
    svc.close()


def test_setup_is_only_entry_for_explicit_model_downloads(tmp_path):
    svc, backend = make(tmp_path)
    svc.settings.set_network_mode('block')
    with pytest.raises(RuntimeError): svc.setup.install_model('test:latest')
    assert not backend.calls
    svc.settings.set_network_mode('direct')
    result = svc.setup.install_model('test:latest')
    assert ('pull', 'test:latest') in backend.calls
    assert result['model'] == 'test:latest'
    svc.close()


def test_failed_shutdown_keeps_runtime_owner_until_success(tmp_path):
    first, backend = make(tmp_path); second, _ = make(tmp_path)
    first.chat.start('warp')
    backend.chat_stop = lambda: False
    assert first.close() is False
    with pytest.raises(RuntimeError): second.chat.start('block')
    backend.chat_stop = lambda: True
    assert first.close() is True
    assert second.chat.start('block')
    second.close()


def test_settings_and_projects_shared_by_all_app_instances(tmp_path):
    from core.projects.model import Project
    first, _ = make(tmp_path); second, _ = make(tmp_path)
    first.settings.set_network_mode('tor', app='chat')
    first.projects.save(Project('demo', 'Demo', str(tmp_path), network_mode='block'))
    assert second.settings.network_mode(app='chat').value == 'tor'
    project = second.projects.get('demo')
    assert second.resolve_mode('chat', project=project).value == 'block'
    assert second.resolve_mode('chat', project=project, session='direct').value == 'direct'
    assert not (tmp_path / 'anythingllm').exists()
    first.close(); second.close()


def test_agent_launch_uses_same_backend_and_network_guard(tmp_path):
    svc, backend = make(tmp_path)
    p = object()
    assert svc.agent.open(p, 'tor')
    assert ('agent', 'tor', None) in backend.calls
    assert ('prepare', 'tor') in backend.calls
    svc.close()


def test_inspection_allowed_while_another_app_has_active_session(tmp_path):
    one, _ = make(tmp_path); two, _ = make(tmp_path)
    one.chat.start('block')
    assert two.system.health()['ollama']
    assert two.models.disk_usage()['models'] == 0
    one.close(); two.close()
