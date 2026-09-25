"""Whether this program can tell that Ollama is there, and use it.

The store this project resolves - ``OLLAMA_MODELS`` if set, otherwise the
machine-shared ``C:\\Ollama\\models`` - answers "where would models go". It was
also being used to answer "is that running server one we can use", and those
are different questions. Install Ollama the official way, never set
OLLAMA_MODELS, and it serves from ``<home>/.ollama/models``: the two disagree,
and the disagreement was fatal. Health said stopped, Chat and Agent refused,
against a server that was answering and serving models the whole time.
"""
import hashlib
import json
from pathlib import Path

import pytest

from launcher.services.ollama import OllamaService


def make_store(root, tags):
    """A real Ollama store on disk: manifests plus the blob they reference."""
    payload = b'weights'
    digest = hashlib.sha256(payload).hexdigest()
    (root / 'blobs').mkdir(parents=True, exist_ok=True)
    (root / 'blobs' / ('sha256-' + digest)).write_bytes(payload)
    for tag in tags:
        name, _, version = tag.partition(':')
        folder = root / 'manifests' / 'registry.ollama.ai' / 'library' / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / version).write_text(json.dumps({
            'schemaVersion': 2,
            'config': {'digest': 'sha256:' + digest, 'size': len(payload)},
            'layers': [{'digest': 'sha256:' + digest, 'size': len(payload),
                        'mediaType': 'application/vnd.ollama.image.model'}]}))
    return root


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """An official Ollama, running, serving from Ollama's own default store."""
    import model_router_stub as router
    from core import ollama_paths

    home = tmp_path / 'home'
    real_store = make_store(home / '.ollama' / 'models', ['qwen3:8b', 'bge-m3:567m'])
    resolved = tmp_path / 'Ollama' / 'models'        # what this project picks
    exe = tmp_path / 'Programs' / 'Ollama' / 'ollama.exe'
    exe.parent.mkdir(parents=True)
    exe.write_text('official', encoding='utf-8')

    monkeypatch.setattr(ollama_paths, 'install_candidates', lambda environ=None: (exe.parent,))
    monkeypatch.setattr(ollama_paths, 'store_candidates', lambda environ=None: (resolved, real_store))
    router.serve(monkeypatch, ['qwen3:8b', 'bge-m3:567m'])

    env = tmp_path / 'llm_environment'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('portable', encoding='utf-8')

    said = []

    class Log:
        def info(self, m): said.append(str(m))
        def ok(self, m): said.append(str(m))
        def warn(self, m): said.append(str(m))
        def error(self, m): said.append(str(m))

    service = OllamaService(env, logger=Log(), model_dir=resolved)
    monkeypatch.setattr(service, 'is_running', lambda: True)
    monkeypatch.setattr(service, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(service, '_process_executable', lambda _pid: exe)
    monkeypatch.setattr(service, '_state_matches', lambda _pid: False)
    monkeypatch.setattr(service, '_terminate_listener',
                        lambda pid: pytest.fail('someone else\'s server must not be killed'))
    return type('Machine', (), {'service': service, 'said': said, 'real_store': real_store,
                                'resolved': resolved, 'exe': exe})


def test_an_ollama_keeping_its_models_where_ollama_puts_them_is_recognised(machine):
    assert machine.service.is_managed_running() is True
    assert machine.service.ensure_running(boot_timeout=1) is True


def test_the_store_the_server_really_serves_from_is_found(machine):
    assert machine.service.locate_store() == machine.real_store


def test_the_difference_is_said_out_loud_rather_than_being_fatal(machine):
    machine.service.ensure_running(boot_timeout=1)
    assert any(str(machine.real_store) in message for message in machine.said), machine.said
    assert any(str(machine.resolved) in message for message in machine.said), machine.said


def test_the_status_line_can_put_it_in_words(machine):
    described = machine.service.describe_store()
    assert str(machine.real_store) in described


def test_the_matching_case_still_reads_as_a_match(tmp_path, monkeypatch):
    import model_router_stub as router
    store = make_store(tmp_path / 'models', ['qwen3:8b'])
    router.serve(monkeypatch, ['qwen3:8b'])
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('portable', encoding='utf-8')
    service = OllamaService(env, model_dir=store)
    assert service.store_agrees() is True
    assert service.describe_store().startswith('모델 저장소 일치')


def test_an_ollama_from_nowhere_known_is_still_refused(tmp_path, monkeypatch):
    """Relaxing the store check must not relax the ownership check."""
    from core import ollama_paths
    monkeypatch.setattr(ollama_paths, 'install_candidates', lambda environ=None: ())
    env = tmp_path / 'env'
    (env / 'ollama_runtime').mkdir(parents=True)
    (env / 'ollama_runtime' / 'ollama.exe').write_text('portable', encoding='utf-8')
    stranger = tmp_path / 'somewhere' / 'ollama.exe'
    stranger.parent.mkdir(parents=True)
    stranger.write_text('?', encoding='utf-8')
    service = OllamaService(env, model_dir=tmp_path / 'models')
    monkeypatch.setattr(service, 'is_running', lambda: True)
    monkeypatch.setattr(service, '_listener_pid', lambda: 99)
    monkeypatch.setattr(service, '_process_executable', lambda _pid: stranger)
    assert service.ensure_running(boot_timeout=1) is False
    assert service.is_managed_running() is False


# ── what "not on disk" is allowed to prove ───────────────────────────────

def test_a_manifest_the_scan_cannot_read_is_not_evidence_of_anything(tmp_path, monkeypatch):
    """A half-finished download used to read as "that server is pointed
    somewhere else" - and, before this, as a reason to refuse it."""
    import model_router_stub as router
    from integrations.ollama import inventory
    (tmp_path / 'manifests').mkdir()      # the store exists; one file in it does not read
    router.serve(monkeypatch, ['qwen3:8b'])
    router.store(monkeypatch, [], unreadable=['manifests/library/qwen3/8b'])
    assert inventory.read(tmp_path).agreement is None


def test_a_store_that_does_not_exist_yet_holds_nothing_and_says_so(tmp_path, monkeypatch):
    """A fresh install has no store directory. That is "empty", not "unknown";
    reporting it as unreadable would hide a real disagreement behind a shrug."""
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ['qwen3:8b'])
    read = inventory.read(tmp_path / 'not-created-yet')
    assert read.on_disk == frozenset()
    assert read.agreement is False


def test_a_cloud_tag_is_served_without_ever_being_on_this_disk(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ['gpt-oss:120b-cloud'])
    router.store(monkeypatch, [])
    assert inventory.read(tmp_path).agreement is True


def test_a_model_that_really_is_missing_still_disagrees(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ['qwen3:8b'])
    router.store(monkeypatch, [])
    assert inventory.read(tmp_path).agreement is False


def test_the_health_probe_says_where_the_models_are(tmp_path):
    """"Ollama: stopped" with no further word was the whole diagnosis."""
    from test_desktop_integration import fixture
    from types import SimpleNamespace as NS
    backend, modules, calls = fixture(tmp_path)
    modules['launcher.services.ollama'] = NS(OllamaService=lambda *a, **k: NS(
        is_managed_running=lambda: True,
        describe_store=lambda: '실행 중인 Ollama 는 C:/Users/me/.ollama/models 를 씁니다'))
    assert 'C:/Users/me/.ollama/models' in backend.health(max_age=0)['ollama_store']
