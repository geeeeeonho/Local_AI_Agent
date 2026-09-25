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
    monkeypatch.setattr(service, 'local_models', lambda timeout=5: [])
    described = service.describe_store()
    assert '로컬 모델이 없습니다' in described
    assert '일치' not in described


def test_a_library_that_is_there_is_counted(tmp_path, monkeypatch):
    from launcher.services.ollama import OllamaService
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('x', encoding='utf-8')
    service = OllamaService(env, model_dir=tmp_path / 'models')
    monkeypatch.setattr(service, 'local_models', lambda timeout=5: ['qwen3:8b'])
    monkeypatch.setattr(service, 'store_agrees', lambda timeout=5: True)
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
