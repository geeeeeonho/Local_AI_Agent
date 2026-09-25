"""Chat cannot run without a model this machine can serve, and says so early.

The log from the field reads: WARP comes up (45 seconds), Docker is checked,
SearXNG starts, AnythingLLM is reached - and only then, at [5/5], Chat reports
that there is no local model. Twice in a row, because nothing about the first
attempt told the user what to fix. Step [2/5] had even said "모델 저장소 일치
확인됨" on the way past, which is what an empty store and an empty router look
like to a check that only compares the two against each other.
"""
from types import SimpleNamespace as NS

import pytest


def services(tmp_path, installed):
    from test_desktop_services import make
    svc, backend = make(tmp_path)
    backend.installed = list(installed)
    return svc, backend


def test_nothing_is_prepared_when_there_is_nothing_to_run(tmp_path):
    """The network step alone is most of the wait; it must not be paid first."""
    svc, backend = services(tmp_path, [])
    with pytest.raises(RuntimeError, match='모델'):
        svc.chat.start('warp')
    assert backend.calls == [], 'not even the network was touched'
    svc.close()


def test_the_message_names_the_screen_that_fixes_it(tmp_path):
    svc, backend = services(tmp_path, [])
    with pytest.raises(RuntimeError) as failure:
        svc.chat.start('direct')
    assert '모델 화면' in str(failure.value)
    svc.close()


def test_cloud_models_do_not_count_as_something_to_run(tmp_path):
    """Ollama proxies these to its own servers, outside the chosen policy."""
    svc, backend = services(tmp_path, ['gemma4:cloud', 'gpt-oss:20b-cloud'])
    backend.inference.local_models = lambda: []
    with pytest.raises(RuntimeError, match='모델'):
        svc.chat.start('block')
    svc.close()


def test_a_question_that_could_not_be_asked_is_not_an_answer(tmp_path):
    """Ollama may simply not be running yet; starting it is step 2's job."""
    svc, backend = services(tmp_path, [])
    backend.inference.local_models = lambda: None
    assert svc.chat.start('direct', search=False)
    svc.close()


def test_one_local_model_is_enough_to_proceed(tmp_path):
    svc, backend = services(tmp_path, ['qwen3:8b'])
    assert svc.chat.start('direct', search=False)
    svc.close()


def test_the_count_is_reported_where_the_check_happens(tmp_path):
    svc, backend = services(tmp_path, ['qwen3:8b', 'bge-m3:567m'])
    seen = []
    svc.events.subscribe('runtime.progress', lambda event: seen.append(event.payload['message']))
    svc.chat.start('direct', search=False)
    assert any('로컬 모델 2개' in message for message in seen), seen
    svc.close()


# ── one definition of a cloud tag ────────────────────────────────────────

def test_the_two_cloud_tag_rules_are_one_rule():
    """They drifted apart inside a single release and disagreed about
    ``gemma4:cloud`` - the shorter of the two forms Ollama actually emits."""
    from core.models.registry import is_cloud_tag as rule
    from integrations.ollama.client import is_cloud_tag as transport
    assert transport is rule
    for tag in ('gemma4:cloud', 'gpt-oss:20b-cloud', 'deepseek-v3.1:671b-cloud'):
        assert rule(tag) is True, tag
    for tag in ('qwen3:8b', 'foo:cloudy', 'cloud:7b', ''):
        assert rule(tag) is False, tag


def test_an_inventory_of_only_cloud_tags_holds_nothing_local(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ['gemma4:cloud'])
    router.store(monkeypatch, [])
    read = inventory.read(tmp_path)
    assert read.tags == frozenset({'gemma4:cloud'})
    assert read.local_tags == frozenset()
    assert read.agreement is True, 'a cloud tag contradicts no store'


# ── what the service says about it ───────────────────────────────────────

def test_an_empty_library_is_not_reported_as_a_healthy_match(tmp_path, monkeypatch):
    """"모델 저장소 일치 확인됨" is what it said on the way to failing."""
    from launcher.services.ollama import OllamaService
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('x', encoding='utf-8')
    service = OllamaService(env, model_dir=tmp_path / 'models')
    monkeypatch.setattr(service, 'inspect_store',
                        lambda timeout=5: (service.NOTHING_INSTALLED, {'served': []}))
    described = service.describe_store()
    assert '로컬 모델이 없습니다' in described
    assert '일치' not in described


def test_a_library_that_is_there_is_counted(tmp_path, monkeypatch):
    from launcher.services.ollama import OllamaService
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('x', encoding='utf-8')
    service = OllamaService(env, model_dir=tmp_path / 'models')
    monkeypatch.setattr(service, 'inspect_store',
                        lambda timeout=5: (service.READY, {'served': ['qwen3:8b']}))
    assert '로컬 모델 1개' in service.describe_store()


# ── the installer's exit code ────────────────────────────────────────────

def test_a_closed_installer_window_is_not_a_hex_number(tmp_path):
    """3221225786 is 0xC000013A, STATUS_CONTROL_C_EXIT: the console was closed.
    Printing the number was the entire diagnosis the user got."""
    from integrations.legacy.desktop import LegacyBackend
    message = LegacyBackend.setup_exit_message(3221225786)
    assert '창이 닫혔' in message
    assert '3221225786' in message


def test_an_unknown_code_is_shown_in_a_form_that_can_be_looked_up(tmp_path):
    from integrations.legacy.desktop import LegacyBackend
    assert '0xC0000005' in LegacyBackend.setup_exit_message(0xC0000005)


# ── installed, but the server is not reading them ────────────────────────
# The opposite mistake to "nothing installed", and the one that was being
# reported. Ollama reads OLLAMA_MODELS once, at startup; when Windows relaunches
# it from its own startup entry the variable the installer set is not there, so
# it serves out of its empty per-user default while every model the user has
# sits in the store this program manages. Three models on disk, zero served -
# and the program said "모델 저장소 일치 확인됨" on its way to telling the user
# to go and download one.

import hashlib as _hashlib
import json as _json


def store_with(root, tags):
    payload = b'weights'
    digest = _hashlib.sha256(payload).hexdigest()
    (root / 'blobs').mkdir(parents=True, exist_ok=True)
    (root / 'blobs' / ('sha256-' + digest)).write_bytes(payload)
    for tag in tags:
        name, _, version = tag.partition(':')
        folder = root / 'manifests' / 'registry.ollama.ai' / 'library' / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / version).write_text(_json.dumps({
            'schemaVersion': 2,
            'config': {'digest': 'sha256:' + digest, 'size': len(payload)},
            'layers': [{'digest': 'sha256:' + digest, 'size': len(payload),
                        'mediaType': 'application/vnd.ollama.image.model'}]}))
    return root


def blind_service(tmp_path, monkeypatch, held=('qwen3:8b', 'gemma4:12b-it-qat')):
    """A store holding models and a router that lists none of them."""
    import model_router_stub as router
    from launcher.services.ollama import OllamaService
    store = store_with(tmp_path / 'Ollama' / 'models', held)
    router.serve(monkeypatch, [])
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('x', encoding='utf-8')
    return OllamaService(env, model_dir=store), store


def test_a_router_that_lists_none_of_the_store_is_not_agreement(tmp_path, monkeypatch):
    service, store = blind_service(tmp_path, monkeypatch)
    assert service.store_agrees() is False
    situation, detail = service.inspect_store()
    assert situation == service.STORE_NOT_READ
    assert len(detail['on_disk']) == 2


def test_the_reading_names_the_models_that_are_there(tmp_path, monkeypatch):
    service, store = blind_service(tmp_path, monkeypatch)
    described = service.describe_store()
    assert str(store) in described
    assert '2개' in described
    assert '받으세요' not in described, 'they already have them'


def test_the_remedy_is_the_one_that_can_work(tmp_path, monkeypatch):
    """Ollama reads OLLAMA_MODELS at startup only, so restarting is the fix."""
    service, store = blind_service(tmp_path, monkeypatch)
    assert str(store) in service.store_fix_command()
    assert 'OLLAMA_MODELS' in service.store_fix_command()


def test_a_server_that_is_serving_something_is_never_restarted(tmp_path, monkeypatch):
    """Only a server doing nothing is a server we offer to end."""
    service, store = blind_service(tmp_path, monkeypatch)
    monkeypatch.setattr(service, 'inspect_store',
                        lambda timeout=5: (service.READY, {'served': ['qwen3:8b']}))
    monkeypatch.setattr(service, '_kill',
                        lambda pid: pytest.fail('a working server must not be ended'))
    assert service.restart_for_store() is True


def test_an_unknown_binary_is_not_restarted_either(tmp_path, monkeypatch):
    service, store = blind_service(tmp_path, monkeypatch)
    stranger = tmp_path / 'somewhere' / 'ollama.exe'
    stranger.parent.mkdir(parents=True)
    stranger.write_text('?', encoding='utf-8')
    monkeypatch.setattr(service, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(service, '_process_executable', lambda _pid: stranger)
    monkeypatch.setattr(service, '_kill',
                        lambda pid: pytest.fail('not ours to end'))
    assert service.restart_for_store() is False


def test_chat_says_the_models_are_here_not_that_they_are_missing(tmp_path):
    """The sentence that sent a user with three models to the download screen."""
    from test_desktop_services import make
    svc, backend = make(tmp_path)
    backend.installed = []
    backend.inference.local_models = lambda: []
    backend.inference.describe_models = lambda: (
        '설치된 모델 3개가 C:/Ollama/models 에 있는데 실행 중인 Ollama 가 '
        '그 경로를 읽지 않습니다.')
    with pytest.raises(RuntimeError) as failure:
        svc.chat.start('warp')
    assert '읽지 않습니다' in str(failure.value)
    assert '받으세요' not in str(failure.value)
    assert backend.calls == [], 'and still nothing was prepared'
    svc.close()


def test_chat_keeps_the_plain_message_when_there_really_is_nothing(tmp_path):
    from test_desktop_services import make
    svc, backend = make(tmp_path)
    backend.installed = []
    backend.inference.local_models = lambda: []
    backend.inference.describe_models = lambda: None
    with pytest.raises(RuntimeError, match='모델 화면'):
        svc.chat.start('direct')
    svc.close()
