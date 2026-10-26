"""Chat history and agent sessions, sealed whenever no session uses them.

AnythingLLM and Open Interpreter need their files in plaintext while they
run; between sessions they are this account's alone. The order is the safety
these tests hold: open before the runtime starts, seal only after it has
verifiably stopped, never seal under a runtime that may still be running.
"""
import pytest

from core import vault
from services.records import SessionStores
from test_vault import Key


@pytest.fixture
def account(tmp_path, monkeypatch):
    root = tmp_path / 'users' / 'Tester'
    (root / 'user_data').mkdir(parents=True)
    monkeypatch.setattr('project_paths.account_dir', lambda: root)
    with vault.using(Key()):
        yield root


def chat_store(data):
    store = data / 'anythingllm'
    (store / 'documents').mkdir(parents=True)
    (store / 'documents' / 'diary.json').write_text('dear diary', encoding='utf-8')
    (store / 'anythingllm.db').write_bytes(b'chats')
    (store / 'models').mkdir()
    (store / 'models' / 'embedder.onnx').write_bytes(b'public')
    return store


def services_for(tmp_path, account):
    from services.desktop import DesktopServices
    from test_desktop_services import Backend
    backend = Backend(tmp_path)
    env = tmp_path / 'environment'
    env.mkdir(exist_ok=True)
    svc = DesktopServices(project_root=tmp_path, env=env,
                          model_dir=backend.inference.model_dir,
                          data=account / 'user_data', backend=backend)
    return svc, backend


def test_chat_store_is_open_while_chat_runs_and_sealed_after(tmp_path, account):
    svc, backend = services_for(tmp_path, account)
    store = chat_store(account / 'user_data')
    svc.records.close('chat')                    # as a previous stop would
    assert not (store / 'anythingllm.db').exists()
    seen = {}
    original = backend.chat_start

    def start(model, log, cancel):
        seen['db'] = (store / 'anythingllm.db').read_bytes()
        return original(model, log, cancel)

    backend.chat_start = start
    svc.chat.start('direct')
    assert seen['db'] == b'chats', 'the container must find its files'
    assert svc.chat.stop()
    assert not (store / 'anythingllm.db').exists()
    assert (store / 'models' / 'embedder.onnx').exists(), 'public weights stay'
    assert (account / 'user_data' / 'anythingllm.vault').is_file()
    svc.close()


def test_a_chat_that_did_not_stop_is_not_sealed(tmp_path, account):
    svc, backend = services_for(tmp_path, account)
    store = chat_store(account / 'user_data')
    svc.chat.start('direct')
    backend.chat_stop = lambda: False
    assert svc.chat.stop() is False
    assert (store / 'anythingllm.db').read_bytes() == b'chats'


def test_agent_stores_follow_the_agent_session(tmp_path, account):
    svc, backend = services_for(tmp_path, account)
    host = account / 'user_data' / 'interpreter' / 'host'
    (host / 'packages').mkdir(parents=True)
    (host / 'packages' / 'big.whl').write_bytes(b'pkg')
    (host / 'sessions').mkdir()
    (host / 'sessions' / 'rollout.jsonl').write_text('{"prompt": "secret"}', encoding='utf-8')
    assert svc.agent.open(object(), 'tor')
    assert (host / 'sessions' / 'rollout.jsonl').exists()
    assert svc.agent.stop()
    assert not (host / 'sessions').exists()
    assert (host / 'packages' / 'big.whl').exists()
    assert svc.agent.open(object(), 'tor')
    assert (host / 'sessions' / 'rollout.jsonl').read_text(encoding='utf-8') == '{"prompt": "secret"}'
    svc.close()
    assert not (host / 'sessions').exists(), 'closing the window seals too'


def test_a_failed_agent_open_does_not_leave_the_store_held(tmp_path, account):
    svc, backend = services_for(tmp_path, account)
    host = account / 'user_data' / 'interpreter' / 'host'
    (host / 'sessions').mkdir(parents=True)
    (host / 'sessions' / 'a.jsonl').write_text('x', encoding='utf-8')
    backend.agent_open = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('docker'))
    with pytest.raises(RuntimeError):
        svc.agent.open(object(), 'tor')
    assert not vault.in_use(host)
    assert not (host / 'sessions').exists()


def test_recovery_seals_only_when_the_runtime_is_proven_stopped(tmp_path, account):
    data = account / 'user_data'
    store = chat_store(data)
    stores = SessionStores(data)
    assert stores.recover(lambda kind: False) == []
    assert (store / 'anythingllm.db').exists()
    assert stores.recover(lambda kind: (_ for _ in ()).throw(RuntimeError())) == []
    assert stores.recover(lambda kind: kind == 'chat') == ['chat']
    assert not (store / 'anythingllm.db').exists()


def test_recovery_skips_a_store_this_window_is_using(tmp_path, account):
    data = account / 'user_data'
    store = chat_store(data)
    stores = SessionStores(data)
    stores.open('chat')
    assert stores.recover(lambda kind: True) == []
    assert (store / 'anythingllm.db').exists()
    stores.close('chat')


def test_without_protection_nothing_is_sealed_or_held(tmp_path, monkeypatch):
    root = tmp_path / 'users' / 'Tester'
    monkeypatch.setattr('project_paths.account_dir', lambda: root)
    data = root / 'user_data'
    store = chat_store(data)
    with vault.using(None):
        stores = SessionStores(data)
        stores.open('chat')
        assert stores.close('chat') is True
        assert stores.recover(lambda kind: True) == []
    assert (store / 'anythingllm.db').exists()
    assert not list(data.glob('.anythingllm.inuse-*'))
