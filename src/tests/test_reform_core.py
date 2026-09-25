"""Core contracts stay usable without importing a UI or external runtime."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


def _isolated_paths():
    """Load the one path module fresh so environment overrides are observable."""
    import importlib.util
    path = Path(__file__).parents[1] / 'project_paths.py'
    spec = importlib.util.spec_from_file_location('isolated_project_paths', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_runtime_path_sits_under_one_root(monkeypatch, tmp_path):
    """A portable run moves the whole product, not three quarters of it.

    Each module used to compose its own "<project root>/user_data" or
    "<project root>/llm_environment", so pointing one override at a new folder
    left the rest writing to the old one.
    """
    monkeypatch.setenv('LLM_PROJECT_ROOT', str(tmp_path))
    monkeypatch.delenv('LOCAL_AI_ROOT', raising=False)
    monkeypatch.delenv('LLM_MODEL_DIR', raising=False)
    monkeypatch.delenv('OLLAMA_MODELS', raising=False)
    paths = _isolated_paths()
    assert paths.RUNTIME_ROOT == tmp_path
    assert paths.USER_DATA_DIR == tmp_path / 'user_data'
    assert paths.ENV_DIR == tmp_path / 'environment'
    assert paths.LOGS_DIR == tmp_path / 'logs'
    assert paths.MODEL_STORAGE_DIR == tmp_path / 'models'
    # Reading a path still creates nothing.
    assert not paths.USER_DATA_DIR.exists()


def test_the_root_is_one_folder_directly_under_the_drive_on_windows():
    """C:\\LocalAI - short, ASCII, space-free, and not inside the checkout.

    A checkout lives wherever the user unzipped it: Desktop, Downloads, a
    OneDrive folder that syncs tens of gigabytes to the cloud, a path with
    spaces that Docker Desktop will not bind-mount.
    """
    # Built with / rather than a literal so the comparison means the same
    # thing on the Linux box that runs this suite as it does on Windows.
    from core import runtime_root
    drive_root = Path(r'C:\LocalAI')
    assert runtime_root.root({}, windows=True) == drive_root
    layout = runtime_root.layout({}, windows=True)
    assert layout['models'] == drive_root / 'models'
    assert layout['env'] == drive_root / 'environment'
    assert layout['user_data'] == drive_root / 'user_data'
    assert layout['logs'] == drive_root / 'logs'
    # "Directly under C:" is the point, so check it as Windows would.
    import ntpath
    drive, tail = ntpath.splitdrive(str(runtime_root.WINDOWS_ROOT))
    assert drive.upper() == 'C:'
    assert tail.strip('\\').count('\\') == 0, 'one level below the drive root'


def test_an_explicit_root_beats_the_portable_override(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_PROJECT_ROOT', str(tmp_path / 'checkout'))
    monkeypatch.setenv('LOCAL_AI_ROOT', str(tmp_path / 'elsewhere'))
    paths = _isolated_paths()
    assert paths.PROJECT_ROOT == tmp_path / 'checkout'
    assert paths.RUNTIME_ROOT == tmp_path / 'elsewhere'
    assert paths.ENV_DIR == tmp_path / 'elsewhere' / 'environment'


def test_model_and_runtime_paths_support_existing_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_OLLAMA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('LLM_MODEL_DIR', str(tmp_path / 'weights'))
    paths = _isolated_paths()
    assert paths.OLLAMA_INSTALL_DIR == tmp_path / 'runtime'
    assert paths.MODEL_STORAGE_DIR == tmp_path / 'weights'


@pytest.mark.parametrize('session,project,app,global_mode,expected', [
    ('direct','tor','block','warp','direct'),
    (None,'tor','block','warp','tor'),
    (None,None,'block','warp','block'),
    (None,None,None,'warp','warp'),
])
def test_network_precedence(session, project, app, global_mode, expected):
    from core.network.policy import resolve_mode
    assert resolve_mode(session=session, project=project, app=app,
                        global_mode=global_mode).value == expected


@pytest.mark.parametrize('value', ['', 'unknown', 'off', 'DIRECT ', False, 1])
def test_invalid_network_mode_never_becomes_direct(value):
    from core.network.policy import resolve_mode
    with pytest.raises(ValueError):
        resolve_mode(session=value)


def test_host_block_is_rejected_and_sandbox_block_is_distinct_from_direct():
    from core.network.policy import NetworkPolicy, NetworkMode
    with pytest.raises(ValueError, match='Host|host'):
        NetworkPolicy(NetworkMode.BLOCK, execution='host')
    blocked = NetworkPolicy(NetworkMode.BLOCK, execution='sandbox')
    direct = NetworkPolicy(NetworkMode.DIRECT, execution='sandbox')
    assert not blocked.public_egress
    assert direct.public_egress
    assert not blocked.search_available


def test_project_round_trip_only_manages_link_information(tmp_path):
    from core.projects.model import Project
    from core.projects.registry import ProjectRegistry
    workspace = tmp_path / 'real-workspace'
    project = Project(id='demo', name='Demo', anythingllm_workspace='knowledge',
                      workspace_path=str(workspace), network_mode='tor')
    registry = ProjectRegistry(tmp_path / 'projects.json')
    registry.save(project)
    assert registry.get('demo') == project
    assert registry.list() == [project]
    assert not workspace.exists()
    registry.delete('demo')
    assert registry.get('demo') is None


@pytest.mark.parametrize('identifier', ['../escape', '', 'a/b', '.', '..', '\\escape'])
def test_project_id_validation(identifier, tmp_path):
    from core.projects.model import Project
    with pytest.raises(ValueError):
        Project(id=identifier, name='bad', workspace_path=str(tmp_path))


def test_future_project_schema_is_not_silently_overwritten(tmp_path):
    from core.projects.registry import ProjectRegistry
    from core.projects.model import Project
    path = tmp_path / 'projects.json'
    original = json.dumps({'schema_version': 77, 'projects': {}})
    path.write_text(original)
    with pytest.raises(ValueError, match='schema'):
        ProjectRegistry(path).save(Project(id='x', name='X', workspace_path=str(tmp_path)))
    assert path.read_text() == original


def test_corrupt_settings_are_preserved(tmp_path):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    path.write_text('{incomplete')
    with pytest.raises(ValueError):
        SettingsStore(path).set_network_mode('tor')
    assert path.read_text() == '{incomplete'


def test_settings_scopes_and_unknown_fields_roundtrip(tmp_path):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'schema_version': 1, 'extra': {'kept': True}}))
    settings = SettingsStore(path)
    settings.set_network_mode('warp')
    settings.set_network_mode('block', app='interpreter')
    assert settings.network_mode(app='interpreter').value == 'block'
    assert settings.network_mode(app='interpreter', project='tor').value == 'tor'
    assert settings.network_mode(app='interpreter', project='tor', session='direct').value == 'direct'
    assert json.loads(path.read_text())['extra'] == {'kept': True}


def test_json_store_serializes_concurrent_read_modify_write(tmp_path):
    from core.persistence import JsonStore
    store = JsonStore(tmp_path / 'state.json')
    def increment(_):
        store.update(lambda data: dict(data, count=data.get('count', 0) + 1))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(60)))
    assert store.read()['count'] == 60


def test_json_store_serializes_multiple_processes(tmp_path):
    from core.persistence import JsonStore
    path = tmp_path / 'state.json'
    code = ('from core.persistence import JsonStore; import sys; '
            's=JsonStore(sys.argv[1]); '
            '[s.update(lambda d: dict(d,count=d.get("count",0)+1)) for _ in range(12)]')
    processes = [subprocess.Popen([sys.executable, '-c', code, str(path)]) for _ in range(3)]
    assert all(p.wait(timeout=10) == 0 for p in processes)
    assert JsonStore(path).read()['count'] == 36


def test_failed_atomic_replace_keeps_previous_json(tmp_path, monkeypatch):
    from core.persistence import JsonStore
    path = tmp_path / 'state.json'
    store = JsonStore(path)
    store.update(lambda d: {'old': True})
    before = path.read_bytes()
    def locked(*args, **kwargs):
        raise PermissionError('locked')
    monkeypatch.setattr(os, 'replace', locked)
    with pytest.raises(PermissionError):
        store.update(lambda d: {'new': True})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))


def test_events_are_immutable_and_one_bad_listener_does_not_break_others():
    from core.events import EventBus
    bus, received = EventBus(), []
    unsubscribe = bus.subscribe('model.changed', received.append)
    bus.subscribe('model.changed', lambda event: (_ for _ in ()).throw(ValueError('UI closed')))
    original = {'models': ['one']}
    bus.emit('model.changed', original)
    original['models'].append('two')
    event, = received
    assert tuple(event.payload['models']) == ('one',)
    with pytest.raises(TypeError):
        event.payload['key'] = 'mutation'
    unsubscribe()
    bus.emit('model.changed', {})
    assert len(received) == 1


def test_runtime_status_is_visible_to_a_second_store_instance(tmp_path):
    from core.runtime_state import RuntimeState
    path = tmp_path / 'runtime.json'
    one, two = RuntimeState(path), RuntimeState(path)
    one.set_status('inference', 'ready', detail='localhost')
    assert two.snapshot()['inference']['status'] == 'ready'
    two.set_status('search', 'unavailable', detail='block')
    assert one.snapshot()['search']['detail'] == 'block'


def test_core_has_no_reverse_import_dependencies():
    root = Path(__file__).parents[1] / 'core'
    assert root.is_dir()
    forbidden = {'apps', 'services', 'integrations', 'launcher', 'installer', 'tkinter'}
    for file in root.rglob('*.py'):
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            assert not any(name.split('.')[0] in forbidden for name in names), str(file)
