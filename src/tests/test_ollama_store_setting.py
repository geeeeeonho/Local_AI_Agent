"""Managed Ollama store persistence and explicit repair behavior.

LocalAI owns one machine-wide broker and does not stop it merely because one
window closes. These tests cover the remaining explicit maintenance behavior:
persisting compatibility settings, stopping the tray supervisor before an
explicit store repair, and never stopping a broker this process did not start.
"""
from pathlib import Path

import pytest

from launcher.services.ollama import OllamaService


def service(tmp_path, monkeypatch, *, held=(), served=()):
    from core import ollama_paths
    root = tmp_path / 'LocalAI'
    exe = root / 'ollama' / 'ollama.exe'
    exe.parent.mkdir(parents=True)
    exe.write_text('managed', encoding='utf-8')
    env = root / 'environment'
    env.mkdir(parents=True)
    said = []

    class Log:
        def info(self, m): said.append(str(m))
        def ok(self, m): said.append(str(m))
        def warn(self, m): said.append(str(m))
        def error(self, m): said.append(str(m))

    svc = OllamaService(env, logger=Log(), model_dir=root / 'models')
    svc.exe = exe
    svc.said = said
    return svc


# ── the value has to outlive the process we hand it to ───────────────────

def test_machine_scope_first_then_the_account_that_needs_no_administrator():
    from integrations.ollama import sharing
    calls = []

    def run(command, timeout=20):
        calls.append(list(command))
        class Result:
            returncode = 0 if '/M' not in command else 1
        return Result()

    original = sharing._run
    sharing._run = run
    try:
        assert sharing.publish_variable(Path('C:/LocalAI/models'), windows=True) == 'user'
    finally:
        sharing._run = original
    assert ['/M' in call for call in calls] == [True, False], calls


def test_nothing_written_is_reported_as_nothing_written():
    from integrations.ollama import sharing
    original = sharing._run
    sharing._run = lambda command, timeout=20: None
    try:
        assert sharing.publish_variable(Path('C:/Ollama/models'), windows=True) == ''
    finally:
        sharing._run = original


def test_installing_writes_the_path_where_windows_keeps_it(tmp_path, monkeypatch):
    """The installer used to pass it to one child and stop there."""
    from installer.steps import ollama as step
    written = []
    monkeypatch.setattr(step, '_service', lambda env, models: type('S', (), {
        'persist_store_setting': lambda self: written.append(str(models)) or 'user',
        'ensure_running': lambda self, boot_timeout=30: True,
        'last_error': '',
    })())
    step.start_service({'env': tmp_path / 'env', 'models': tmp_path / 'models'})
    assert written == [str(tmp_path / 'models')]


def test_a_server_we_launch_also_writes_the_setting(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    running = iter([False, True])
    monkeypatch.setattr(svc, 'is_running', lambda: next(running))
    monkeypatch.setattr(svc, '_launch', lambda: 4242)
    monkeypatch.setattr(svc, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: svc.exe)
    monkeypatch.setattr(svc, '_write_runtime_state', lambda pid: None)
    monkeypatch.setattr(svc, 'register_exit_cleanup', lambda: True)
    persisted = []
    monkeypatch.setattr(svc, 'persist_store_setting', lambda: persisted.append(1) or 'user')
    assert svc.ensure_running(boot_timeout=2) is True
    assert persisted == [1]


# ── the tray application is what actually owns the server ────────────────

def test_only_a_tray_application_beside_an_ollama_we_know_is_ours(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    beside = str(svc.exe.parent / 'ollama app.exe')
    stranger = str(tmp_path / 'elsewhere' / 'ollama app.exe')
    monkeypatch.setattr(svc, '_powershell',
                        lambda script: '111|%s\n222|%s' % (beside, stranger))
    assert svc.supervisor_pids() == [111]


def test_the_tray_goes_first_or_the_restart_is_undone(tmp_path, monkeypatch):
    """Kill the server with its supervisor alive and a replacement arrives
    within milliseconds, reading exactly the directory we were trying to change."""
    svc = service(tmp_path, monkeypatch)
    order = []
    stores = iter([
        (svc.STORE_NOT_READ, {'on_disk': ['a:1']}),
        (svc.READY, {'served': ['a:1'], 'on_disk': ['a:1']}),
    ])
    monkeypatch.setattr(svc, 'inspect_store', lambda timeout=5: next(stores))
    monkeypatch.setattr(svc, 'persist_store_setting',
                        lambda: order.append('persist') or 'user')
    monkeypatch.setattr(svc, 'supervisor_pids', lambda: [222])
    monkeypatch.setattr(svc, '_listener_pid', lambda: 111)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: svc.exe)
    monkeypatch.setattr(svc, '_kill', lambda pid: order.append('kill %d' % pid) or True)
    monkeypatch.setattr(svc, 'is_running', lambda: False)
    monkeypatch.setattr(svc, 'ensure_running',
                        lambda *a, **k: order.append('start') or True)
    assert svc.restart_for_store(stop_timeout=1) is True
    assert order == ['persist', 'kill 222', 'kill 111', 'start'], order


def test_a_restart_that_changed_nothing_is_not_reported_as_done(tmp_path, monkeypatch):
    """"다시 시작 완료 · 로컬 모델 0개" was the message. Nothing was completed."""
    svc = service(tmp_path, monkeypatch)
    stores = iter([
        (svc.STORE_NOT_READ, {'on_disk': ['a:1']}),
        (svc.STORE_NOT_READ, {'on_disk': ['a:1']}),
    ])
    monkeypatch.setattr(svc, 'inspect_store', lambda timeout=5: next(stores))
    monkeypatch.setattr(svc, 'persist_store_setting', lambda: 'user')
    monkeypatch.setattr(svc, 'supervisor_pids', lambda: [])
    monkeypatch.setattr(svc, '_listener_pid', lambda: 111)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: svc.exe)
    monkeypatch.setattr(svc, '_kill', lambda pid: True)
    monkeypatch.setattr(svc, 'is_running', lambda: False)
    monkeypatch.setattr(svc, 'ensure_running', lambda *a, **k: True)
    assert svc.restart_for_store(stop_timeout=1) is False


# ── explicit managed stop behavior ───────────────────────────────────────

def test_closing_stops_the_tray_before_the_server_it_would_restart(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    svc._write_runtime_state(4242)
    order = []
    monkeypatch.setattr(svc, 'is_running', lambda: len(order) < 2)
    monkeypatch.setattr(svc, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(svc, 'supervisor_pids', lambda: [222] if 'kill 222' not in order else [])
    monkeypatch.setattr(svc, '_kill', lambda pid: order.append('kill %d' % pid) or True)
    assert svc.stop_managed(stop_timeout=1) is True
    assert order == ['kill 222', 'kill 4242'], order


def test_a_server_we_did_not_start_keeps_its_tray(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    monkeypatch.setattr(svc, 'supervisor_pids',
                        lambda: pytest.fail('not ours to look at, let alone end'))
    monkeypatch.setattr(svc, '_kill', lambda pid: pytest.fail('not ours to end'))
    assert svc.stop_managed(stop_timeout=1) is True
