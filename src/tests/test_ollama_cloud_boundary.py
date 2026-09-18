"""Ollama cloud tags must never be treated as local models.

A tag Ollama marks as cloud (``gpt-oss:20b-cloud``, ``gemma4:cloud``) is not
downloaded. The local daemon attaches the user's credentials and proxies the
request to Ollama's servers, and every OpenAI-compatible client - this project's
included - talks to it exactly like a local model. That silently voids all three
network promises: Block claims no public egress, WARP and Tor claim a specific
route, and none of them can see traffic the daemon makes on its own behalf.

So the refusal belongs at the name boundary, before a policy that cannot observe
it is asked to protect it.
"""
import pytest

from integrations.ollama.client import is_cloud_tag, local_model_name, model_name


CLOUD = (
    'gpt-oss:20b-cloud',
    'gpt-oss:120b-cloud',
    'deepseek-v3.1:671-cloud',
    'qwen3-coder:480b-cloud',
    'gemma4:cloud',
    'GEMMA4:CLOUD',
)
LOCAL = (
    'gemma4:26b',
    'qwen3.6:27b',
    'gpt-oss:20b',
    'prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S',
    'huihui_ai/qwen3-abliterated:8b',
    # Names that merely contain the word are not cloud tags.
    'cloudy-model:7b',
    'someone/cloud-model:8b',
    'thing:not-cloud-ish',
)


@pytest.mark.parametrize('tag', CLOUD)
def test_a_cloud_tag_is_recognised(tag):
    assert is_cloud_tag(tag)


@pytest.mark.parametrize('tag', LOCAL)
def test_a_local_tag_is_not_mistaken_for_one(tag):
    assert not is_cloud_tag(tag)


@pytest.mark.parametrize('tag', CLOUD)
def test_a_cloud_tag_is_refused_where_it_must_stay_local(tag):
    with pytest.raises(ValueError, match='cloud'):
        local_model_name(tag)


@pytest.mark.parametrize('tag', LOCAL)
def test_local_tags_still_pass(tag):
    assert local_model_name(tag) == tag


def test_the_refusal_says_why_rather_than_just_invalid():
    with pytest.raises(ValueError) as caught:
        local_model_name('gpt-oss:20b-cloud')
    message = str(caught.value)
    assert 'leave this machine' in message and 'network policy' in message


def test_an_invalid_name_is_still_invalid_before_the_cloud_check():
    for bad in ('', '../evil', 'a' * 300, 'has space:1b'):
        with pytest.raises(ValueError):
            local_model_name(bad)


def test_the_catalogue_offers_no_cloud_tag():
    """Nothing in the shipped list may route inference off the machine."""
    from launcher.models import model_catalog as catalog
    offenders = sorted(tag for tag in catalog.catalog_tags() if is_cloud_tag(tag))
    assert offenders == [], offenders


def test_no_ladder_rung_is_a_cloud_tag():
    from launcher.models import model_roles as roles
    offenders = sorted({tag for rungs in roles.LADDERS.values()
                        for tag, _need in rungs if is_cloud_tag(tag)})
    assert offenders == [], offenders


def test_installing_a_cloud_tag_is_refused_by_the_service(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    try:
        with pytest.raises(ValueError, match='cloud'):
            services.models.install_model('gpt-oss:20b-cloud')
        assert not any(call[0] == 'pull' for call in backend.calls)
    finally:
        services.close()


def test_removing_one_is_allowed_so_it_can_be_got_rid_of(tmp_path):
    """Refusing removal would strand a tag the user already pulled elsewhere."""
    from test_desktop_services import make
    services, backend = make(tmp_path)
    try:
        services.models.remove_model('gpt-oss:20b-cloud')
        assert ('remove', 'gpt-oss:20b-cloud') in backend.calls
    finally:
        services.close()


def test_the_catalogue_view_marks_any_remote_tag(tmp_path):
    from test_desktop_services import make
    services, _ = make(tmp_path)
    try:
        catalogue = services.models.catalog()
        assert all(model['cloud'] is False for model in catalogue['models'])
        assert catalogue['cloud_installed'] == []
    finally:
        services.close()


# ── configuring the relay itself ─────────────────────────────────────────
# Refusing cloud names at this project's own boundary only covers requests it
# originates. Ollama has an official switch, verified against a real binary:
# OLLAMA_NO_CLOUD=1 makes the server answer 403 "ollama cloud is disabled" on
# both /api/chat and /v1/chat/completions, while local models are unaffected.
# GET /api/status reports the decision, so a server this project did not launch
# can be asked rather than assumed.

def service(tmp_path):
    from launcher.services.ollama import OllamaService
    return OllamaService(tmp_path, model_dir=tmp_path / 'models')


def test_a_server_we_launch_is_told_to_have_no_cloud(tmp_path):
    assert service(tmp_path).env_vars({})['OLLAMA_NO_CLOUD'] == '1'


def test_the_switch_is_set_even_when_the_store_needs_no_override(tmp_path):
    from core import ollama_paths
    from launcher.services.ollama import OllamaService
    shared = ollama_paths.SHARED_MODELS_DIR
    env = OllamaService(tmp_path, model_dir=shared).env_vars(
        {'OLLAMA_MODELS': str(shared)})
    assert 'OLLAMA_MODELS' in env and env['OLLAMA_NO_CLOUD'] == '1'


def answer(monkeypatch, payload):
    """Stand in for GET /api/status on the running server."""
    import json
    from launcher.services import ollama as module

    class Response:
        def read(self, n=None):
            return json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: Response())


def test_cloud_status_reads_the_servers_own_answer(tmp_path, monkeypatch):
    svc = service(tmp_path)
    answer(monkeypatch, {'cloud': {'disabled': True, 'source': 'env'}})
    assert svc.cloud_status() is True
    answer(monkeypatch, {'cloud': {'disabled': False, 'source': 'none'}})
    assert svc.cloud_status() is False


def test_an_unreachable_or_odd_answer_is_unknown_not_a_verdict(tmp_path, monkeypatch):
    from launcher.services import ollama as module
    svc = service(tmp_path)
    def refuse(*a, **k):
        raise OSError('connection refused')
    monkeypatch.setattr(module.urllib.request, 'urlopen', refuse)
    assert svc.cloud_status() is None
    for payload in ({}, {'cloud': {}}, {'cloud': {'disabled': 'yes'}}, {'cloud': 1}):
        answer(monkeypatch, payload)
        assert svc.cloud_status() is None, payload


def test_attaching_to_a_relay_that_allows_cloud_says_so(tmp_path, monkeypatch):
    svc = service(tmp_path)
    warned = []
    monkeypatch.setattr(svc, '_warn', lambda m: warned.append(m))
    monkeypatch.setattr(svc, 'cloud_status', lambda timeout=5: False)
    svc._warn_if_cloud_enabled()
    assert any('cloud' in m.lower() or '클라우드' in m for m in warned)
    assert any('OLLAMA_NO_CLOUD' in m for m in warned), 'say how to fix it'


def test_a_relay_with_cloud_off_or_unknown_is_not_nagged_about(tmp_path, monkeypatch):
    svc = service(tmp_path)
    warned = []
    monkeypatch.setattr(svc, '_warn', lambda m: warned.append(m))
    for state in (True, None):
        monkeypatch.setattr(svc, 'cloud_status', lambda timeout=5, s=state: s)
        svc._warn_if_cloud_enabled()
    assert warned == []
