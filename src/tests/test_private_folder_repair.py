"""When the signed-in account cannot lock its own records folder.

Setup stopped with "Windows ACL을 읽거나 확인할 수 없습니다" and told the user
to go and ask an administrator, with nothing they could run. These tests hold
the three things that replace that: reading the ACL in-process with a reason
when Windows refuses, one UAC prompt that hands the folder back to this
account's SID, and an error that names the cause and the exact commands.
"""
import os
import types
from pathlib import Path

import pytest

from integrations.windows import acl, privacy

LOCKED = 'D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-7-8-9-1001)'
INHERITED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;0x1200a9;;;BU)'
SID = 'S-1-5-21-7-8-9-1001'


@pytest.fixture(autouse=True)
def forget_sid(monkeypatch):
    monkeypatch.setattr(acl, '_known_sid', None)
    monkeypatch.delenv(privacy.NO_ELEVATION_VARIABLE, raising=False)


def result(code=0, stdout=''):
    return types.SimpleNamespace(returncode=code, stdout=stdout, stderr='')


# ── reading: in-process first, then two independent tools ────────────────

def test_the_native_reader_answers_without_a_temp_file_or_a_child(monkeypatch, tmp_path):
    monkeypatch.setattr(acl, '_native_sddl', lambda path, info: (LOCKED, None))
    monkeypatch.setattr(acl.subprocess, 'run',
                        lambda *a, **k: pytest.fail('no child process needed'))
    assert acl.saved_sddl(tmp_path) == LOCKED
    assert privacy.is_private(tmp_path, windows=True) is True


def test_icacls_is_the_fallback_when_the_api_is_not_there(monkeypatch, tmp_path):
    monkeypatch.setattr(acl, '_native_sddl', lambda path, info: (None, None))

    def run(command, **kwargs):
        if '/save' in command:
            Path(command[command.index('/save') + 1]).write_text(
                'folder\n' + INHERITED + '\n', encoding='utf-16')
        return result()

    monkeypatch.setattr(acl.subprocess, 'run', run)
    assert privacy.is_private(tmp_path, windows=True) is False


def test_powershell_is_the_last_reader_when_icacls_save_fails(monkeypatch, tmp_path):
    """A Store Python's private TEMP copy or an antivirus can break /save."""
    monkeypatch.setattr(acl, '_native_sddl', lambda path, info: (None, None))
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    seen = []

    def run(command, **kwargs):
        seen.append(command[0])
        if command[0] == 'icacls':
            return result(5)
        return result(0, 'O:BAG:SY' + LOCKED)

    monkeypatch.setattr(acl.subprocess, 'run', run)
    assert privacy.is_private(tmp_path, windows=True) is True
    assert seen == ['icacls', 'powershell.exe']
    assert acl.owner_sid(tmp_path) == 'BA'


def test_a_refusal_is_reported_with_its_windows_error_code(monkeypatch):
    assert '5' in acl.describe_error(5) and '액세스 거부' in acl.describe_error(5)
    assert '1223' in acl.describe_error(1223)
    assert acl.describe_error(None)


def test_the_sid_comes_from_whoami_when_the_token_cannot_be_read(monkeypatch):
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, '_native_user_sid', lambda: None)
    answers = iter([result(1), result(0, '"pc\\tester","%s"\r\n' % SID)])
    monkeypatch.setattr(acl.subprocess, 'run', lambda *a, **k: next(answers))
    assert acl.current_user_sid() is None, 'a failed lookup is not remembered'
    assert acl.current_user_sid() == SID
    monkeypatch.setattr(acl.subprocess, 'run', lambda *a, **k: pytest.fail('cached'))
    assert acl.current_user_sid() == SID


# ── the elevated repair ──────────────────────────────────────────────────

def test_the_admin_repair_gives_ownership_back_before_locking(tmp_path):
    commands = privacy.admin_repair_commands(tmp_path, SID)
    assert commands[0][2:4] == ['/setowner', '*' + SID] and '/T' in commands[0]
    assert '/inheritance:r' in commands[1]
    assert '*%s:(OI)(CI)F' % SID in commands[1]
    assert not any('BU' in part or 'S-1-5-32-545' in part
                   for command in commands for part in command)
    assert commands[2][2] == '/reset'


def test_one_uac_prompt_runs_every_step_through_cmd(monkeypatch, tmp_path):
    folder = tmp_path / 'users' / 'Tester'
    folder.mkdir(parents=True)
    monkeypatch.setattr(acl, 'current_user_sid', lambda: SID)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    elevated = []
    monkeypatch.setattr(acl, 'run_elevated',
                        lambda exe, params, **kw: elevated.append((exe, params)) or (0, None))
    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: True)
    said = []
    assert privacy.repair_as_admin(folder, windows=True, log=said.append) is True
    assert len(elevated) == 1, 'one prompt, not one per command'
    exe, params = elevated[0]
    assert exe.lower().endswith('cmd.exe')
    assert params.startswith('/d /s /c "') and params.endswith('"')
    assert params.count('icacls.exe') == 3 and ' & ' in params
    assert '"%s"' % folder in params and SID in params
    assert any('UAC' in line for line in said)


def test_an_already_elevated_setup_repairs_without_a_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: SID)
    monkeypatch.setattr(acl, 'is_elevated', lambda: True)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: pytest.fail('no prompt'))
    ran = []
    monkeypatch.setattr(acl, 'run', lambda command, **kw: ran.append(command) or result())
    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: True)
    assert privacy.repair_as_admin(tmp_path, windows=True) is True
    assert [command[2] for command in ran] == ['/setowner', '/inheritance:r', '/reset']


def test_declining_the_prompt_is_an_answer_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: SID)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: (None, acl.ERROR_CANCELLED))
    monkeypatch.setattr(privacy, 'ensure_private', lambda *a, **k: pytest.fail('nothing ran'))
    said = []
    assert privacy.repair_as_admin(tmp_path, windows=True, log=said.append) is None
    assert any('취소' in line for line in said)


def test_automation_can_forbid_the_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv(privacy.NO_ELEVATION_VARIABLE, '1')
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: pytest.fail('opted out'))
    assert privacy.repair_as_admin(tmp_path, windows=True) is None


def test_a_path_cmd_would_reinterpret_is_never_run_as_administrator(monkeypatch, tmp_path):
    folder = tmp_path / 'a&calc'
    folder.mkdir()
    monkeypatch.setattr(acl, 'current_user_sid', lambda: SID)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: pytest.fail('unsafe'))
    assert privacy.repair_as_admin(folder, windows=True) is None


def test_no_sid_means_no_elevated_guess(monkeypatch, tmp_path):
    monkeypatch.setattr(acl, 'current_user_sid', lambda: None)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: pytest.fail('no target'))
    assert privacy.repair_as_admin(tmp_path, windows=True) is None


# ── Setup: escalate once, then say exactly what is wrong ─────────────────

def test_setup_continues_after_the_admin_repair_worked(monkeypatch, tmp_path):
    from installer.core import filesystem
    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: None)
    repaired = []
    monkeypatch.setattr(privacy, 'repair_as_admin',
                        lambda path, **kw: repaired.append(Path(path)) or True)
    account = tmp_path / 'users' / 'Tester'
    paths = filesystem.create_environment(tmp_path / 'env', model_dir=tmp_path / 'models',
                                          account_root=account)
    assert repaired == [account]
    assert (paths['user_data']).is_dir()
    assert (account / filesystem.ACCOUNT_MARKER).is_file()


def test_the_setup_error_names_the_cause_and_the_commands_that_fix_it(monkeypatch, tmp_path):
    from installer.core import filesystem
    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: None)
    monkeypatch.setattr(privacy, 'repair_as_admin', lambda path, **kw: None)
    monkeypatch.setattr(privacy, 'diagnose', lambda path, **kw: {
        'path': str(path), 'exists': True, 'private': None, 'writable': True,
        'user_sid': SID, 'owner': 'BA', 'owner_is_user': False,
        'elevated': False, 'read_error': 5})
    account = tmp_path / 'users' / 'Tester'
    with pytest.raises(RuntimeError) as raised:
        filesystem.create_environment(tmp_path / 'env', model_dir=tmp_path / 'models',
                                      account_root=account)
    message = str(raised.value)
    assert 'Windows ACL을 읽거나 확인할 수 없습니다' in message
    assert SID in message and 'Administrators' in message
    assert 'Windows 오류 5' in message
    assert '/setowner' in message and '/inheritance:r' in message and '/reset' in message
    assert not (account / 'user_data').exists()


def test_the_diagnosis_reads_as_one_line_of_plain_words():
    text = privacy.describe_diagnosis({
        'private': True, 'writable': False, 'user_sid': SID, 'owner': SID,
        'owner_is_user': True, 'elevated': None, 'read_error': None})
    assert '현재 계정' in text and '쓰기: 불가' in text and 'ACL 읽기: 정상' in text


# ── a stale file inside a folder that is itself fine ─────────────────────

def test_a_file_this_account_cannot_append_to_is_found(monkeypatch, tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'ok.log').write_text('', encoding='utf-8')
    (logs / 'ollama_run.log').write_text('', encoding='utf-8')
    real = os.open

    def guarded(path, flags, *args):
        if path.endswith('ollama_run.log'):
            raise PermissionError(13, 'Permission denied')
        return real(path, flags, *args)

    monkeypatch.setattr(privacy.os, 'open', guarded)
    assert privacy.unwritable_files(logs) == [logs / 'ollama_run.log']
    assert (logs / 'ok.log').read_text(encoding='utf-8') == '', 'checking writes nothing'


def test_refusals_no_permission_repair_can_fix_are_not_reported(monkeypatch, tmp_path):
    """A file held open elsewhere, or marked read-only, is not a stale ACL.

    Counting them would show a UAC prompt for a repair that cannot help.
    """
    logs = tmp_path / 'logs'
    logs.mkdir()
    held = logs / 'held.log'
    held.write_text('', encoding='utf-8')
    readonly = logs / 'readonly.log'
    readonly.write_text('', encoding='utf-8')
    readonly.chmod(0o444)
    real = os.open

    def guarded(path, flags, *args):
        if path.endswith('held.log'):
            error = PermissionError(13, 'in use')
            error.winerror = 32
            raise error
        if path.endswith('readonly.log'):
            raise PermissionError(13, 'read-only')
        return real(path, flags, *args)

    monkeypatch.setattr(privacy.os, 'open', guarded)
    try:
        assert privacy.unwritable_files(logs) == []
    finally:
        readonly.chmod(0o644)


def test_setup_resets_only_the_state_folder_holding_a_stale_file(monkeypatch, tmp_path):
    from installer.core import filesystem
    account = tmp_path / 'users' / 'Tester'
    logs = account / 'logs'
    logs.mkdir(parents=True)
    stale = logs / 'ollama_run.log'
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    fixed = []
    answers = {logs: [[stale], []]}
    monkeypatch.setattr(privacy, 'unwritable_files',
                        lambda folder, **kw: answers.get(folder, [[]]).pop(0)
                        if answers.get(folder) else [])
    monkeypatch.setattr(privacy, 'reset_tree', lambda folder, **kw: fixed.append(folder) or True)
    monkeypatch.setattr(privacy, 'repair_as_admin', lambda *a, **k: pytest.fail('not needed'))
    assert filesystem.repair_stale_children(account) == []
    assert fixed == [logs], 'workspace and the rest of the account are left alone'


def test_setup_escalates_when_a_stale_file_survives_the_reset(monkeypatch, tmp_path):
    from installer.core import filesystem
    account = tmp_path / 'users' / 'Tester'
    logs = account / 'logs'
    logs.mkdir(parents=True)
    stale = logs / 'ollama_run.log'
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    remaining = [[stale], [stale], []]
    monkeypatch.setattr(privacy, 'unwritable_files',
                        lambda folder, **kw: remaining.pop(0) if folder == logs else [])
    monkeypatch.setattr(privacy, 'reset_tree', lambda folder, **kw: True)
    escalated = []
    monkeypatch.setattr(privacy, 'repair_as_admin',
                        lambda path, **kw: escalated.append(path) or True)
    assert filesystem.repair_stale_children(account) == []
    assert escalated == [account]
