"""Full model discovery and explicit standalone Ollama path connection."""
from pathlib import Path
from types import SimpleNamespace

from services.models.service import ModelService


def test_installed_summary_includes_unknown_tags_and_server_only():
    from launcher.models import model_catalog
    known = next(iter(model_catalog.catalog_tags()))
    service = object.__new__(ModelService)
    service.inventory_view = lambda **kwargs: SimpleNamespace(
        on_disk=frozenset({known, 'my-gguf:latest', 'QWEN3-VL:8B'}),
        served=frozenset({known, 'MY-GGUF:latest', 'other-tool:7b',
                          'gpt-oss:20b-cloud'}),
        source='router', store_path='C:/LocalAI/models',
        router_reachable=True, on_disk_complete=True)
    summary = service.installed_summary()
    rows = {r['tag'].casefold(): r for r in summary['models']}
    assert rows[known.casefold()]['catalogued']
    assert rows['my-gguf:latest']['on_disk'] is True
    assert rows['my-gguf:latest']['served'] is True
    assert rows['qwen3-vl:8b']['on_disk'] is True
    assert rows['other-tool:7b']['on_disk'] is False
    assert rows['other-tool:7b']['served'] is True
    assert '읽기 전용' in rows['other-tool:7b']['status']
    assert 'gpt-oss:20b-cloud' not in rows


def test_stopped_server_preserves_disk_models():
    service = object.__new__(ModelService)
    service.inventory_view = lambda **kwargs: SimpleNamespace(
        on_disk=frozenset({'handmade:latest'}), served=None, source='store',
        store_path='C:/LocalAI/models', router_reachable=False,
        on_disk_complete=True)
    model = service.installed_summary()['models'][0]
    assert model['tag'] == 'handmade:latest'
    assert model['served'] is None
    assert '서버 미확인' in model['status']


def test_explicit_link_fixes_conflicting_user_override(monkeypatch):
    from integrations.ollama import sharing
    state = {'machine': '', 'user': 'D:/OldOllama'}
    operations = []

    def status(path, *, windows=None):
        active = state['user'] or state['machine']
        return {'supported': True, 'connected': active == str(path),
                'user_conflict': bool(state['user'] and state['user'] != str(path)),
                'path': str(path), 'user': state['user'], 'machine': state['machine'],
                'effective': active}

    def machine(path, *, windows=None):
        operations.append('machine')
        state['machine'] = str(path)
        return True

    def user(path, *, windows=None):
        operations.append('user')
        state['user'] = str(path)
        return True

    monkeypatch.setattr(sharing, 'external_store_settings', status)
    monkeypatch.setattr(sharing, 'publish_machine_variable', machine)
    monkeypatch.setattr(sharing, 'publish_user_variable', user)
    result = sharing.connect_external_store(Path('C:/LocalAI/models'), windows=True)
    assert result['ok']
    assert operations == ['machine', 'user']
    assert result['after']['connected']


def test_user_scope_fallback_when_machine_scope_denied(monkeypatch):
    from integrations.ollama import sharing
    target = Path('C:/LocalAI/models')
    state = {'user': '', 'machine': ''}

    def status(path, *, windows=None):
        effective = state['user'] or state['machine']
        return {'supported': True, 'connected': effective == str(path),
                'user_conflict': False, 'path': str(path),
                'user': state['user'], 'machine': state['machine'],
                'effective': effective}
    monkeypatch.setattr(sharing, 'external_store_settings', status)
    monkeypatch.setattr(sharing, 'publish_machine_variable', lambda *a, **k: False)
    monkeypatch.setattr(sharing, 'publish_user_variable',
                        lambda path, **kw: state.__setitem__('user', str(path)) or True)
    result = sharing.connect_external_store(target, windows=True)
    assert result['ok'] and result['scope'] == 'user'


def test_model_service_rejects_external_broker_for_download(tmp_path):
    import pytest
    calls = []
    class Client:
        def pull(self, name, **kwargs):
            calls.append(name)

    class Runtime:
        def validate_mutation_store(self):
            raise RuntimeError('externally owned Ollama')

    class Inference:
        model_dir = tmp_path / 'models'
        client = Client()
        runtime = Runtime()
        def ensure_ready(self):
            return 'http://127.0.0.1:11434'

    service = ModelService(Inference())
    with pytest.raises(RuntimeError, match='externally owned'):
        service.install_model('test:latest')
    assert calls == []
