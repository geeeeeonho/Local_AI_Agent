"""Only a LocalAI administrator installs or removes shared models.

Every allowed account reads and runs the shared model library. Changing it -
pulling, deleting, rewriting the shared index - is refused for anyone Windows
does not confirm as a LocalAI administrator, before any broker start or
download. The ACL is the real boundary; these tests hold the early refusal and
the protection that backs it.
"""
import types
from pathlib import Path

import pytest

from core import machine
from integrations import model_access
from integrations.windows import acl
from integrations.windows import machine as windows

ME = 'S-1-5-21-7-7-7-1001'
OTHER = 'S-1-5-21-7-7-7-1002'
ADMINS = 'S-1-5-21-7-7-7-1010'


@pytest.fixture
def shared_store(tmp_path, monkeypatch):
    root = tmp_path / 'LocalAI'
    store = root / 'models'
    store.mkdir(parents=True)
    (root / machine.POLICY_FILENAME).write_text(
        machine.new_policy(ME, admins_group_sid=ADMINS).to_json(), encoding='utf-8')
    monkeypatch.setenv('LOCAL_AI_ROOT', str(root))
    monkeypatch.delenv('LLM_MODEL_DIR', raising=False)
    monkeypatch.setattr('project_paths.runtime_dir', lambda: root)
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(windows, 'token_group_sids', lambda: set())
    monkeypatch.setattr(windows, 'group_sid',
                        lambda name: ADMINS if name == machine.ADMINS_GROUP else None)
    monkeypatch.setattr(windows, 'group_member_sids', lambda name: {ME})
    model_access.clear_cache()
    yield store
    model_access.clear_cache()


def test_the_installing_administrator_may_manage_models(shared_store, monkeypatch):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: ME)
    answer = model_access.management_access(shared_store)
    assert answer['allowed'] and answer['admin']


def test_an_ordinary_account_may_not(shared_store, monkeypatch):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: OTHER)
    answer = model_access.management_access(shared_store)
    assert not answer['allowed'] and answer['reason'] == model_access.DENIED
    with pytest.raises(PermissionError):
        model_access.require_management(shared_store)


def test_a_sid_only_machine_json_lists_may_not(shared_store, monkeypatch):
    root = shared_store.parent
    tampered = machine.load(root / machine.POLICY_FILENAME).with_admin(OTHER)
    (root / machine.POLICY_FILENAME).write_text(tampered.to_json(), encoding='utf-8')
    monkeypatch.setattr(acl, 'current_user_sid', lambda: OTHER)
    assert not model_access.management_access(shared_store, refresh=True)['allowed']


def test_without_a_readable_policy_nobody_but_elevated_may(shared_store, monkeypatch):
    (shared_store.parent / machine.POLICY_FILENAME).unlink()
    monkeypatch.setattr(acl, 'current_user_sid', lambda: ME)
    assert model_access.management_access(shared_store, refresh=True)['reason'] == \
        model_access.UNVERIFIED
    monkeypatch.setattr(acl, 'is_elevated', lambda: True)
    assert model_access.management_access(shared_store, refresh=True)['allowed']


def test_an_explicit_private_store_is_left_to_its_own_acl(shared_store, tmp_path, monkeypatch):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: OTHER)
    own = tmp_path / 'my-models'
    own.mkdir()
    assert model_access.management_access(own)['allowed']


def test_model_service_refuses_before_the_broker_or_a_download(shared_store, monkeypatch):
    from services.models.service import ModelService
    monkeypatch.setattr(acl, 'current_user_sid', lambda: OTHER)
    touched = []
    inference = types.SimpleNamespace(
        model_dir=shared_store,
        client=types.SimpleNamespace(pull=lambda *a, **k: touched.append('pull'),
                                     remove=lambda *a, **k: touched.append('remove')),
        ensure_ready=lambda: touched.append('broker'))
    events = []
    service = ModelService(inference)
    monkeypatch.setattr(service.events, 'emit', lambda kind, payload: events.append((kind, payload)))
    for action in (service.install_model, service.remove_model):
        with pytest.raises(RuntimeError, match='LocalAI 관리자'):
            action('qwen3:8b')
    assert touched == [], 'no broker start, pull or delete for an ordinary account'
    assert all(kind == 'runtime.error' for kind, _ in events)
    assert not (shared_store / '.localai').exists(), 'not even the mutation lock'
    assert service.refresh_index() is None, 'the shared index is not rewritten either'


def test_desktop_setup_refuses_before_preparing_the_runtime(monkeypatch):
    from services.system.desktop import SetupService
    calls = []

    class Models:
        def require_management(self, name=None):
            calls.append(('check', name))
            raise RuntimeError(model_access.DENIED)

        def install_model(self, name):
            calls.append(('install', name))

    service = SetupService.__new__(SetupService)
    service.models = Models()
    service.ensure_model_runtime = lambda **k: calls.append(('runtime',))
    with pytest.raises(RuntimeError):
        service.install_model('qwen3:8b')
    with pytest.raises(RuntimeError):
        service.remove_model('qwen3:8b')
    assert calls == [('check', 'qwen3:8b'), ('check', 'qwen3:8b')]


def test_the_protection_repair_covers_the_model_library():
    from integrations.windows import program_security
    policy = machine.new_policy(ME, admins_group_sid=ADMINS)
    script = program_security.protection_script(Path('C:/LocalAI'), policy)
    assert "LocalAI/models'" in script.replace('\\', '/')
    assert 'users' not in script


def test_verify_rejects_a_writable_model_store(tmp_path, monkeypatch):
    from integrations.windows import program_security
    root = tmp_path / 'LocalAI'
    (root / 'models').mkdir(parents=True)
    policy = machine.new_policy(ME, admins_group_sid=ADMINS)
    safe = 'O:BAD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
    monkeypatch.setattr(acl, 'owner_sid', lambda path: 'BA')
    monkeypatch.setattr(acl, 'saved_sddl', lambda path: (
        'O:BAD:AI(A;OICIID;FA;;;BA)(A;OICI;0x1301bf;;;BU)' if path.name == 'models' else safe))
    reasons = program_security.verify(root, policy)
    assert any('models' in reason for reason in reasons)


def test_the_broker_never_prunes_the_read_only_store(tmp_path):
    from launcher.services.ollama import OllamaService
    service = OllamaService(tmp_path / 'env', model_dir=tmp_path / 'models')
    env = service.env_vars({'PATH': ''})
    assert env['OLLAMA_NOPRUNE'] == '1'
    assert service.env_vars({'OLLAMA_NOPRUNE': ''})['OLLAMA_NOPRUNE'] == '1'
