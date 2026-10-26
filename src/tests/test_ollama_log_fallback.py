"""A log file must never be the reason Ollama does not start.

Seen on a real machine: ``C:\\LocalAI\\users\\<account>\\logs\\ollama_run.log``
refused this account (``[Errno 13] Permission denied``) while the folder
around it was fine, and every model install failed at "prepare Ollama".
"""
import builtins
from pathlib import Path

from launcher.services import ollama as module
from launcher.services.ollama import OllamaService


def service(tmp_path):
    said = []

    class Log:
        def info(self, m): said.append(str(m))
        def ok(self, m): said.append(str(m))
        def warn(self, m): said.append(str(m))
        def error(self, m): said.append(str(m))

    root = tmp_path / 'LocalAI'
    svc = OllamaService(root / 'environment', logger=Log(), model_dir=root / 'models',
                        state_dir=root / 'users' / 'Tester' / 'logs')
    svc.said = said
    return svc


def refuse(monkeypatch, *refused):
    """Make ``open`` refuse exactly these paths, the way a stale ACL does."""
    blocked = {str(Path(p)) for p in refused}
    real = builtins.open

    def guarded(file, *args, **kwargs):
        if str(Path(file)) in blocked:
            raise PermissionError(13, 'Permission denied', str(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(module, 'open', guarded, raising=False)


def test_a_writable_log_is_used_as_it_is(tmp_path):
    svc = service(tmp_path)
    stream = svc._open_log()
    try:
        assert stream is not None
        assert svc.log_file.name == 'ollama_run.log'
    finally:
        stream.close()
    assert not any('쓸 수 없' in line for line in svc.said)


def test_a_refused_log_is_moved_aside_and_recreated(tmp_path, monkeypatch):
    svc = service(tmp_path)
    original = svc.log_file
    original.parent.mkdir(parents=True)
    original.write_text('old server output', encoding='utf-8')
    # Refuse only the first open of the original file.
    real = builtins.open
    calls = []

    def first_refused(file, *args, **kwargs):
        if Path(file) == original and not calls:
            calls.append(file)
            raise PermissionError(13, 'Permission denied', str(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(module, 'open', first_refused, raising=False)
    stream = svc._open_log()
    stream.close()
    assert svc.log_file == original, 'the usual name is kept when it can be'
    aside = list(original.parent.glob('ollama_run.blocked-*.log'))
    assert len(aside) == 1 and aside[0].read_text(encoding='utf-8') == 'old server output'
    assert any('옆으로 옮기고' in line for line in svc.said)


def test_a_log_that_cannot_be_moved_gets_a_fresh_file_beside_it(tmp_path, monkeypatch):
    svc = service(tmp_path)
    original = svc.log_file
    original.parent.mkdir(parents=True)
    original.write_text('held by another process', encoding='utf-8')
    refuse(monkeypatch, original)
    monkeypatch.setattr(module.os, 'replace',
                        lambda *a: (_ for _ in ()).throw(PermissionError(32, 'in use')))
    stream = svc._open_log()
    stream.close()
    assert svc.log_file != original and svc.log_file.parent == original.parent
    assert svc.log_file.name.startswith('ollama_run-')
    assert any(str(svc.log_file) in line for line in svc.said), 'say where it went'


def test_with_no_writable_place_ollama_still_starts_without_a_log(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(module, 'open',
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, 'denied')),
                        raising=False)
    monkeypatch.setattr(module.os, 'replace',
                        lambda *a: (_ for _ in ()).throw(PermissionError(13, 'denied')))
    assert svc._open_log() is None

    launched = {}

    class Process:
        pid = 4242

    def popen(command, **kwargs):
        launched.update(kwargs)
        return Process()

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    assert svc._launch() == 4242
    assert launched['stdout'] is module.subprocess.DEVNULL
    assert any('로그 없이 시작' in line for line in svc.said)


def test_a_refused_state_file_does_not_turn_a_running_server_into_a_failure(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(svc, '_store_runtime_state',
                        lambda pid: (_ for _ in ()).throw(PermissionError(13, 'denied')))
    svc._write_runtime_state(4242)
    assert any('실행 기록을 저장하지 못했습니다' in line for line in svc.said)


# ── the broker's log is shared and write-only ────────────────────────────

def test_on_windows_the_broker_logs_to_the_shared_folder(tmp_path, monkeypatch):
    import project_paths
    monkeypatch.setattr(module, '_shared_log', lambda: True)
    svc = OllamaService(tmp_path / 'environment', model_dir=tmp_path / 'models')
    assert svc.log_file == project_paths.ollama_log_dir() / 'server.log'
    assert svc.private_log.name == 'ollama_run.log'


def test_a_shared_log_this_account_cannot_open_falls_back_to_its_own(tmp_path, monkeypatch):
    svc = service(tmp_path)
    shared = tmp_path / 'LocalAI' / 'ollama' / 'logs' / 'server.log'
    svc.log_file = shared
    refuse(monkeypatch, shared)
    stream = svc._open_log()
    stream.close()
    assert svc.log_file == svc.private_log
    assert not list(shared.parent.glob('*.blocked-*')), 'never rename the shared log'


def test_prompts_never_reach_the_shared_log(tmp_path):
    svc = service(tmp_path)
    env = svc.env_vars({'OLLAMA_DEBUG': '1', 'PATH': 'x'})
    assert 'OLLAMA_DEBUG' not in env


def test_setup_makes_the_log_folder_append_only_for_accounts(tmp_path, monkeypatch):
    import types
    from installer.core import filesystem
    from integrations.windows import acl, privacy
    ran = []
    monkeypatch.setattr(acl, 'run', lambda command, **kw: ran.append(command)
                        or types.SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(privacy, 'reset_children', lambda path, **kw: ran.append(['reset', str(path)]))
    assert filesystem.ensure_shared_log_access(tmp_path / 'logs', windows=True)
    command = ran[0]
    assert '/inheritance:r' in command
    assert '*S-1-5-32-545:(OI)(CI)W' in command, 'append, not read'
    assert '*S-1-3-4:(OI)(CI)W' in command, 'the creator cannot grant itself read'
    assert not any('RX' in part or ':(OI)(CI)R' in part for part in command if 'S-1-5-32-545' in part)
    assert ran[1] == ['reset', str(tmp_path / 'logs')]
