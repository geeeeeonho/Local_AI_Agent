"""Full model discovery and explicit external Ollama store integration."""
from pathlib import Path
from types import SimpleNamespace

from core.models.registry import ROUTER
from services.models.service import ModelService


def test_all_installed_models_include_uncatalogued_and_external_server_only():
    from launcher.models import model_catalog
    known = next(iter(model_catalog.catalog_tags()))
    service = object.__new__(ModelService)
    service.inventory_view = lambda **kwargs: SimpleNamespace(
        on_disk=frozenset({known, 'my-gguf:latest', 'QWEN3-VL:8B'}),
        served=frozenset({known, 'MY-GGUF:latest', 'other-tool:7b',
                          'gpt-oss:20b-cloud'}),
        source=ROUTER, store_path='C:/LocalAI/models',
        router_reachable=True, on_disk_complete=True)
    summary = service.installed_summary()
    by_tag = {m['tag'].casefold(): m for m in summary['models']}

    assert by_tag[known.casefold()]['catalogued']
    assert by_tag['my-gguf:latest']['on_disk'] is True
    assert by_tag['my-gguf:latest']['served'] is True
    assert by_tag['qwen3-vl:8b']['on_disk'] is True
    assert by_tag['other-tool:7b']['on_disk'] is False
    assert by_tag['other-tool:7b']['served'] is True
    assert '읽기 전용' in by_tag['other-tool:7b']['status']
    assert 'gpt-oss:20b-cloud' not in by_tag


def test_stopped_ollama_does_not_hide_shared_store_installs():
    service = object.__new__(ModelService)
    service.inventory_view = lambda **kwargs: SimpleNamespace(
        on_disk=frozenset({'handmade:latest'}), served=None, source='store',
        store_path='C:/LocalAI/models', router_reachable=False,
        on_disk_complete=True)
    summary = service.installed_summary()
    assert summary['models'][0]['tag'] == 'handmade:latest'
    assert summary['models'][0]['served'] is None
    assert '서버 미확인' in summary['models'][0]['status']


def test_explicit_link_fixes_conflicting_user_override(monkeypatch):
    from integrations.ollama import sharing
    setting = {'machine': '', 'user': 'D:/OldOllama'}
    operations = []

    def status(path, *, windows=None):
        active = setting['user'] or setting['machine']
        return {'path': str(path), 'supported': True,
                'user': setting['user'], 'machine': setting['machine'],
                'effective': active, 'connected': active == str(path),
                'user_conflict': bool(setting['user'] and setting['user'] != str(path))}

    def machine(path, *, windows=None):
        operations.append('machine')
        setting['machine'] = str(path)
        return True

    def user(path, *, windows=None):
        operations.append('user')
        setting['user'] = str(path)
        return True

    monkeypatch.setattr(sharing, 'external_store_settings', status)
    monkeypatch.setattr(sharing, 'publish_machine_variable', machine)
    monkeypatch.setattr(sharing, 'publish_user_variable', user)
    result = sharing.connect_external_store(Path('C:/LocalAI/models'), windows=True)
    assert result['ok']
    assert operations == ['machine', 'user']
    assert result['after']['connected']


def test_external_store_link_falls_back_to_user_scope(monkeypatch):
    from integrations.ollama import sharing
    target = Path('C:/LocalAI/models')
    state = {'user': '', 'machine': ''}

    def status(path, *, windows=None):
        effective = state['user'] or state['machine']
        return {'path': str(path), 'supported': True,
                'user': state['user'], 'machine': state['machine'],
                'effective': effective, 'connected': effective == str(path),
                'user_conflict': False}

    monkeypatch.setattr(sharing, 'external_store_settings', status)
    monkeypatch.setattr(sharing, 'publish_machine_variable', lambda *a, **k: False)
    monkeypatch.setattr(sharing, 'publish_user_variable',
                        lambda path, **kw: state.__setitem__('user', str(path)) or True)
    result = sharing.connect_external_store(target, windows=True)
    assert result['ok'] and result['scope'] == 'user'
