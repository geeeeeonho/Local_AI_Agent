"""What the idle program costs, and what it must not do on a timer.

The desktop polls service status while it sits there. Each pass shells out to
Docker three times and, on Windows, runs PowerShell twice to identify who owns
the port - about five process launches, every poll, forever, to paint one status
line. Store agreement used to walk every blob in the model store on the same
timer. These pin the cheaper shapes.
"""
import time
import types

import pytest


def backend(importer, tmp_path):
    from integrations.legacy.desktop import LegacyBackend
    return LegacyBackend(tmp_path / 'env', tmp_path / 'models', tmp_path, importer=importer)


def counting_importer(counter):
    real = __import__('importlib').import_module

    class Docker:
        @staticmethod
        def daemon_alive():
            counter.append('docker'); return True
        @staticmethod
        def container_running(name):
            counter.append('docker'); return True

    class Ollama:
        def __init__(self, *a, **k):
            pass
        def is_managed_running(self):
            counter.append('ollama'); return True

    def importer(name):
        if name == 'launcher.services.docker':
            return types.SimpleNamespace(DockerService=Docker)
        if name == 'launcher.services.ollama':
            return types.SimpleNamespace(OllamaService=Ollama)
        if name == 'launcher.anythingllm_runtime':
            return types.SimpleNamespace(is_running=lambda: counter.append('chat') or True)
        return real(name)
    return importer


def test_a_repeated_poll_does_not_reprobe_every_service(tmp_path):
    calls = []
    back = backend(counting_importer(calls), tmp_path)
    back.health()
    first = len(calls)
    assert first >= 4, 'a real pass touches every service'
    for _ in range(5):
        back.health()
    assert len(calls) == first, 'a poll inside the window reuses the last answer'


def test_the_answer_is_reprobed_once_it_is_stale(tmp_path, monkeypatch):
    from integrations.legacy import desktop
    calls = []
    back = backend(counting_importer(calls), tmp_path)
    clock = [0.0]
    monkeypatch.setattr(desktop, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    back.health()
    first = len(calls)
    clock[0] = back.HEALTH_MAX_AGE + 1
    back.health()
    assert len(calls) > first


def test_asking_for_a_fresh_answer_always_probes(tmp_path):
    calls = []
    back = backend(counting_importer(calls), tmp_path)
    back.health()
    first = len(calls)
    back.health(max_age=0)
    assert len(calls) > first, 'pressing refresh must actually refresh'


def test_the_cached_answer_cannot_be_mutated_by_a_caller(tmp_path):
    back = backend(counting_importer([]), tmp_path)
    back.health()['ollama'] = 'tampered'
    assert back.health()['ollama'] is True


def test_the_service_layer_passes_a_refresh_request_through(tmp_path):
    from services.system.desktop import SystemService
    asked = []
    service = SystemService(types.SimpleNamespace(
        health=lambda max_age=None: asked.append(max_age) or {}))
    service.health()
    service.health(fresh=True)
    assert asked == [None, 0]


def test_store_agreement_does_not_walk_the_blob_store(tmp_path, monkeypatch):
    """It runs on the health poll, so its cost must track models, not blobs."""
    import json
    from launcher.services import ollama as module
    from launcher.services.ollama import OllamaService

    service = OllamaService(tmp_path, model_dir=tmp_path / 'models')

    class Response:
        def read(self, n=None):
            return json.dumps({'models': [{'name': 'a:1'}]}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: Response())
    walked = []
    monkeypatch.setattr('launcher.models.model_index.build_index',
                        lambda path: walked.append(path) or {'models': []})
    monkeypatch.setattr('launcher.models.model_index.read_manifests',
                        lambda path: {'a:1': {}})
    assert service.store_agrees() is True
    assert walked == []


def test_reading_manifests_is_cheaper_than_indexing_the_whole_store(tmp_path):
    """Not a timing assertion: the work itself has to be smaller."""
    import hashlib
    import json
    from launcher.models import model_index

    store = tmp_path / 'models'
    (store / 'blobs').mkdir(parents=True)
    digests = []
    for i in range(60):
        payload = str(i).encode() * 8
        digest = hashlib.sha256(payload).hexdigest()
        (store / 'blobs' / ('sha256-' + digest)).write_bytes(payload)
        digests.append(('sha256:' + digest, len(payload)))
    folder = store / 'manifests' / 'registry.ollama.ai' / 'library' / 'one'
    folder.mkdir(parents=True)
    (folder / 'latest').write_text(json.dumps({
        'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
        'config': {'mediaType': 'application/vnd.docker.container.image.v1+json',
                   'digest': digests[0][0], 'size': digests[0][1]},
        'layers': [{'mediaType': 'application/vnd.ollama.image.model',
                    'digest': d, 'size': s} for d, s in digests[1:]]}))

    assert set(model_index.read_manifests(store)) == {'one:latest'}
    assert {m['name'] for m in model_index.build_index(store)['models']} == {'one:latest'}
    # The cheap read must not need the blob directory at all.
    import shutil
    shutil.rmtree(store / 'blobs')
    assert set(model_index.read_manifests(store)) == {'one:latest'}


# ── what survives the window closing ─────────────────────────────────────
# WARP and Tor run as Docker containers and hand their teardown to
# lifelog.register_cleanup. Nothing in DesktopServices.close() owns them, so
# the only thing that stops them is the atexit/signal pass in lifelog. The
# desktop shell has to install it, or the containers outlive the program.

def test_the_desktop_shell_installs_the_hooks_that_stop_containers(monkeypatch, tmp_path):
    from apps.shared import entry
    from services.system import bootstrap
    order = []
    monkeypatch.setattr(bootstrap, 'install_exit_hooks',
                        lambda root: order.append(('install', root)))
    monkeypatch.setattr(bootstrap, 'run_exit_cleanups', lambda: order.append(('cleanup',)))
    monkeypatch.setattr(bootstrap, 'initialize_language', lambda root, lang: None)
    services = types.SimpleNamespace(project_root=tmp_path,
                                     close=lambda: order.append(('close',)))
    monkeypatch.setattr('services.desktop.create_services',
                        lambda: order.append(('services',)) or services)
    pytest.importorskip('tkinter')
    monkeypatch.setattr('apps.shared.window.DesktopWindow',
                        lambda app, svc: types.SimpleNamespace(run=lambda: None))
    assert entry.main('studio', []) == 0
    steps = [step[0] for step in order]
    assert steps.index('install') < steps.index('services'), \
        'hooks must exist before anything can start a container'
    assert steps[-2:] == ['close', 'cleanup'], \
        'teardown the services do not own still has to run'


def test_containers_are_stopped_even_when_startup_fails(monkeypatch, tmp_path):
    """A crash after WARP is up must not be the one path that leaks it."""
    from apps.shared import entry
    from services.system import bootstrap
    order = []
    monkeypatch.setattr(bootstrap, 'install_exit_hooks', lambda root: order.append('install'))
    monkeypatch.setattr(bootstrap, 'run_exit_cleanups', lambda: order.append('cleanup'))
    monkeypatch.setattr(bootstrap, 'initialize_language', lambda root, lang: None)

    def explode():
        raise RuntimeError('model store unreadable')
    monkeypatch.setattr('services.desktop.create_services', explode)
    monkeypatch.setattr(entry, 'sys', types.SimpleNamespace(stderr=None))
    # The failure path opens a modal; a test must never wait on one.
    pytest.importorskip('tkinter')
    import tkinter.messagebox
    monkeypatch.setattr(tkinter.messagebox, 'showerror', lambda *a, **k: None)
    assert entry.main('studio', []) == 3
    assert order == ['install', 'cleanup']


def test_hook_installation_never_takes_the_program_down_with_it(monkeypatch, tmp_path):
    """A logging directory that cannot be created is not a reason not to start."""
    from launcher.core import lifelog
    from services.system import bootstrap
    seen = []
    monkeypatch.setattr(lifelog, 'install_global_hooks', lambda root: seen.append(root))
    assert bootstrap.install_exit_hooks(tmp_path) is True
    assert seen == [tmp_path]

    def refuse(root):
        raise OSError('read-only filesystem')
    monkeypatch.setattr(lifelog, 'install_global_hooks', refuse)
    assert bootstrap.install_exit_hooks(tmp_path) is False


def test_a_shell_that_never_loaded_the_legacy_runtime_still_exits(monkeypatch):
    """run_exit_cleanups must not import the world just to find nothing to do."""
    import sys
    from services.system import bootstrap
    monkeypatch.delitem(sys.modules, 'launcher.core.lifelog', raising=False)
    assert bootstrap.run_exit_cleanups() is False


# ── one screen, one source of truth ──────────────────────────────────────

def test_the_stack_view_does_not_ask_ollama_once_per_role(monkeypatch, tmp_path):
    """Five roles used to mean five /api/tags calls to paint one page."""
    from launcher.models import model_roles
    from services.models.service import ModelService
    asked = []
    monkeypatch.setattr(model_roles, 'installed_models',
                        lambda *a, **k: asked.append(1) or set())
    service = ModelService(types.SimpleNamespace(
        model_dir=tmp_path / 'models', client=object()))
    service.current_stack(free_gb=32.0, installed=set())
    assert asked == [], 'the caller already read the store'


def test_the_stack_names_a_model_that_is_actually_on_disk(monkeypatch, tmp_path):
    """on_disk read the store while chosen asked HTTP, so the two disagreed.

    With only the lightest rung downloaded and memory to spare, preferring
    what is installed and taking the heaviest that fits give different
    answers. Whether Ollama happens to be up must not decide which one the
    screen shows.
    """
    from launcher.models import model_roles
    from services.models.service import ModelService
    service = ModelService(types.SimpleNamespace(
        model_dir=tmp_path / 'models', client=object()))
    lightest = {min(ladder, key=lambda rung: rung[1])[0]
                for ladder in model_roles.LADDERS.values() if ladder}

    monkeypatch.setattr(model_roles, 'installed_models', lambda *a, **k: set(lightest))
    running = service.current_stack(free_gb=512.0, installed=lightest)
    # A stopped server answers None, which used to mean "ignore what is installed".
    monkeypatch.setattr(model_roles, 'installed_models', lambda *a, **k: None)
    stopped = service.current_stack(free_gb=512.0, installed=lightest)

    assert running == stopped
    for row in stopped['roles']:
        assert row['on_disk'], row['name'] + ' points at a model that is not here'
        assert row['chosen'] in lightest
