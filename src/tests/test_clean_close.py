"""Closing the window with X must not wait on work nobody needs any more.

Two things used to keep a closed window on screen: a model download running
to the end (gigabytes) and the Docker leftover sweep running five CLI calls
even with the engine stopped. Both are bounded here; the verified-shutdown
contract itself (window kept if teardown cannot be verified) is unchanged.
"""
import threading
import types

import pytest

from apps.shared.tasks import TaskRunner
from integrations.ollama import client as ollama_client
from launcher.core import docker_maint


class _Lines:
    def __init__(self, lines, on_read=None):
        self.lines = list(lines)
        self.on_read = on_read
        self.reads = 0

    def readline(self, limit=-1):
        self.reads += 1
        if self.on_read:
            self.on_read(self.reads)
        return self.lines.pop(0) if self.lines else b''

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(monkeypatch, response):
    api = ollama_client.OllamaClient.__new__(ollama_client.OllamaClient)
    api.timeout = 5
    monkeypatch.setattr(api, '_request', lambda path, body: (path, body), raising=False)
    monkeypatch.setattr(api, '_open', lambda request, timeout: response, raising=False)
    return api


def test_a_download_stops_at_the_next_progress_line_when_closing(monkeypatch):
    cancel = threading.Event()
    progress = [b'{"status":"pulling","completed":%d}\n' % i for i in range(1000)]
    response = _Lines(progress, on_read=lambda n: n == 3 and cancel.set())
    api = _client(monkeypatch, response)
    with pytest.raises(ollama_client.PullCancelled):
        api.pull('qwen3:8b', cancel=cancel)
    assert response.reads == 3, 'not one more line after the cancel'


def test_a_download_without_cancel_still_completes(monkeypatch):
    response = _Lines([b'{"status":"pulling"}\n', b'{"status":"success"}\n'])
    api = _client(monkeypatch, response)
    api.pull('qwen3:8b')   # reaching "success" without raising is the assertion


def test_the_model_service_hands_the_cancel_to_the_download(monkeypatch, tmp_path):
    from services.models.service import ModelService
    seen = {}
    inference = types.SimpleNamespace(
        model_dir=tmp_path,
        client=types.SimpleNamespace(pull=lambda name, progress=None, **kw: seen.update(kw)),
        ensure_ready=lambda: None)
    service = ModelService(inference, lock_path=tmp_path / 'lock')
    monkeypatch.setattr(service, 'require_management', lambda name=None: None)
    monkeypatch.setattr(service, 'refresh_index', lambda: None)
    cancel = threading.Event()
    service.install_model('qwen3:8b', cancel=cancel)
    assert seen == {'cancel': cancel}
    seen.clear()
    service.install_model('qwen3:8b')
    assert seen == {}, 'older clients without the keyword keep working'


def test_closing_sweep_skips_docker_when_the_engine_is_not_answering(monkeypatch):
    calls = []
    monkeypatch.setattr(docker_maint, '_run', lambda cmd, timeout=60: calls.append(cmd)
                        or types.SimpleNamespace(returncode=1, stdout='', stderr='down'))
    assert docker_maint.daemon_reachable() is False
    assert calls == [['docker', 'version', '--format', '{{.Server.Version}}']]


def test_leftovers_are_listed_with_one_docker_call(monkeypatch):
    calls = []
    out = 'llm_searxng\tsearxng/searxng\nsomeone_else\tnginx\n'
    monkeypatch.setattr(docker_maint, '_run', lambda cmd, timeout=60: calls.append(cmd)
                        or types.SimpleNamespace(returncode=0, stdout=out, stderr=''))
    monkeypatch.setattr(docker_maint, '_is_owned_container', lambda name: name.startswith('llm_'))
    assert docker_maint.list_our_leftovers() == ['llm_searxng']
    assert len(calls) == 1
    assert calls[0].count('--filter') == len(docker_maint.LEFTOVER_STATES)


def test_the_runner_names_what_closing_is_waiting_for():
    runner = TaskRunner()
    gate = threading.Event()
    try:
        runner.submit('models.apply', gate.wait, lambda _: None, lambda _: None)
        runner.submit('quick', lambda: None, lambda _: None, lambda _: None, mutate=False)
        for _ in range(100):
            if runner.pending() == ['models.apply']:
                break
            threading.Event().wait(0.01)
        assert runner.pending() == ['models.apply']
    finally:
        gate.set()
        runner.shutdown()
