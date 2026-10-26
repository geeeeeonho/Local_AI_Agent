"""The first installer administers LocalAI; Windows enforces it.

One copy of the program for the whole PC, writable only by LocalAI
administrators; two local groups carrying the roles; one UAC prompt to set
it up. These tests hold the decisions (``core.machine``), the scripts that
carry them out, and Setup's choice of what each account may touch.
"""
import base64
import types
from pathlib import Path, PureWindowsPath

import pytest

from core import machine
from integrations.windows import acl
from integrations.windows import machine as windows

ME = 'S-1-5-21-111-222-333-1001'
OTHER = 'S-1-5-21-111-222-333-1002'
GROUP = 'S-1-5-21-111-222-333-1010'


# ── the decisions ────────────────────────────────────────────────────────

def test_the_policy_round_trips_and_ignores_what_is_not_a_sid():
    policy = machine.new_policy(ME, admins_group_sid=GROUP)
    again = machine.parse(policy.to_json())
    assert again.admins == (ME,) and again.admins_group_sid == GROUP
    assert machine.parse('{"schema": 1, "admins": ["ghwork", "%s"]}' % ME).admins == (ME,)
    assert machine.parse('not json') is None
    assert machine.parse('{"schema": 99}') is None


def test_an_administrator_is_listed_or_in_the_group_by_sid():
    policy = machine.new_policy(ME, admins_group_sid=GROUP)
    assert policy.is_admin(ME)
    assert not policy.is_admin(OTHER)
    assert policy.is_admin(OTHER, token_groups=[GROUP.lower()])
    assert policy.with_admin(OTHER).is_admin(OTHER)
    assert not policy.with_admin(ME, present=False).is_admin(ME)


def test_everyone_may_use_it_until_access_is_limited_to_members():
    policy = machine.new_policy(ME, users_group_sid=GROUP)
    assert policy.principal() == 'S-1-5-32-545'
    policy.access = machine.ACCESS_MEMBERS
    assert policy.principal() == GROUP
    policy.users_group_sid = None
    assert policy.principal() == 'S-1-5-32-545', 'never lock everyone out'


def test_the_account_that_created_the_folder_is_the_first_installer():
    assert machine.first_admin_candidate(ME, ME)
    assert not machine.first_admin_candidate(OTHER, ME)
    # An elevated install leaves Administrators as owner: whoever runs Setup
    # first, through the UAC prompt, takes the role.
    assert machine.first_admin_candidate('BA', ME)
    assert machine.first_admin_candidate(None, ME)
    assert not machine.first_admin_candidate(ME, None)


# ── the scripts ──────────────────────────────────────────────────────────

ROOT = PureWindowsPath(r'C:\LocalAI')
APP = PureWindowsPath(r'C:\LocalAI\app')


def test_first_install_creates_groups_adds_me_by_sid_and_locks_the_root():
    script = windows.first_install_script(ME, ROOT, APP)
    assert script.count(".Create('group'") == 2
    assert "'WinNT://%s'" % ME in script, 'membership by SID, not a localized name'
    assert "/inheritance:r" in script and "'*S-1-5-32-545:(OI)(CI)RX'" in script
    assert "'*%s:(OI)(CI)F'" % ME in script
    assert '(OI)(CI)M' not in script, 'no account other than admins may change the program'
    assert 'CommonDesktopDirectory' in script and 'CommonPrograms' in script
    assert script.rstrip().endswith('exit $failed')
    assert windows.first_install_script('ghwork', ROOT, APP) is None


def test_a_single_quote_in_a_path_cannot_break_out_of_the_script():
    assert windows.quote("C:\\it's") == "'C:\\it''s'"


def test_deleting_records_targets_only_a_folder_directly_in_users():
    users = PureWindowsPath(r'C:\LocalAI\users')
    script = windows.delete_records_script(users / 'bob', users)
    assert "Remove-Item -LiteralPath $target" in script
    assert '/setowner' in script and 'takeown' not in script, 'takeown /D Y is localized'
    assert windows.delete_records_script(users, users) is None
    assert windows.delete_records_script(users / 'bob' / 'logs', users) is None
    assert windows.delete_records_script(PureWindowsPath(r'C:\Windows'), users) is None


def test_membership_changes_take_a_sid_and_a_known_group():
    assert "Invoke('Remove'" in windows.membership_script(machine.USERS_GROUP, OTHER, False)
    assert windows.membership_script('Administrators', OTHER, True) is None
    assert windows.membership_script(machine.ADMINS_GROUP, 'bob', True) is None


def test_an_admin_script_runs_through_one_uac_prompt(monkeypatch):
    monkeypatch.delenv('LOCAL_AI_NO_ELEVATION', raising=False)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    seen = []
    monkeypatch.setattr(acl, 'run_elevated',
                        lambda exe, params, **kw: seen.append((exe, params)) or (0, None))
    assert windows.run_as_admin('Write-Output 1') is True
    exe, params = seen[0]
    assert exe.lower().endswith('powershell.exe')
    encoded = params.split('-EncodedCommand ')[1]
    assert base64.b64decode(encoded).decode('utf-16-le') == 'Write-Output 1'


def test_declining_uac_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv('LOCAL_AI_NO_ELEVATION', raising=False)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: (None, acl.ERROR_CANCELLED))
    said = []
    assert windows.run_as_admin('x', log=said.append) is False
    assert any('취소' in line for line in said)


def test_an_elevated_setup_needs_no_prompt(monkeypatch):
    monkeypatch.delenv('LOCAL_AI_NO_ELEVATION', raising=False)
    monkeypatch.setattr(acl, 'is_elevated', lambda: True)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **k: pytest.fail('no prompt'))
    monkeypatch.setattr(windows, 'run_script',
                        lambda script, **kw: types.SimpleNamespace(returncode=0))
    assert windows.run_as_admin('x') is True


def test_root_lock_for_an_existing_admin_needs_no_prompt():
    policy = machine.new_policy(ME, admins_group_sid=GROUP)
    command = windows.lock_root_command(ROOT, policy)
    assert command[:3] == ['icacls', str(ROOT), '/inheritance:r']
    assert '*%s:(OI)(CI)F' % ME in command and '*%s:(OI)(CI)F' % GROUP in command
    assert '*S-1-5-32-545:(OI)(CI)RX' in command
    assert '/T' not in command, 'inheritance carries it down; one object, one answer'


# ── Setup decides what this account may touch ────────────────────────────

@pytest.fixture
def setup(tmp_path, monkeypatch):
    from installer.steps import machine as step
    root = tmp_path / 'LocalAI'
    root.mkdir()
    calls = []
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, 'current_user_sid', lambda: ME)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(acl, 'owner_sid', lambda path: ME)
    monkeypatch.setattr(acl, 'run', lambda command, **kw: calls.append(('acl', command[:3]))
                        or types.SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(windows, 'token_group_sids', lambda: set())
    monkeypatch.setattr(windows, 'group_sid', lambda name: GROUP if name == machine.ADMINS_GROUP else None)
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: calls.append(('uac', script)) or True)
    monkeypatch.setattr(step.app_step, 'deploy', lambda source, target: calls.append(('deploy', target)) or True)
    return step, root, calls


def test_the_first_installer_becomes_administrator_with_one_prompt(setup):
    step, root, calls = setup
    assert step.current_role(root) == 'admin'
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    kinds = [call[0] for call in calls]
    assert kinds == ['deploy', 'uac'], 'the program is in place before the shortcut points at it'
    policy = machine.load(root / machine.POLICY_FILENAME)
    assert policy.admins == (ME,) and policy.admins_group_sid == GROUP


def test_declining_the_prompt_still_records_the_admin_and_locks_what_it_can(setup, monkeypatch):
    step, root, calls = setup
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: False)
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    policy = machine.load(root / machine.POLICY_FILENAME)
    assert policy.notes.get('groups_pending') is True
    assert ('acl', ['icacls', str(root), '/inheritance:r']) in calls


def test_another_account_is_an_ordinary_user_and_changes_nothing_shared(setup, monkeypatch):
    step, root, calls = setup
    (root / machine.POLICY_FILENAME).write_text(machine.new_policy(OTHER).to_json(), encoding='utf-8')
    assert step.current_role(root) == 'user'
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'user'
    assert calls == []


def test_a_later_admin_setup_keeps_the_program_current_without_a_prompt(setup):
    step, root, calls = setup
    (root / machine.POLICY_FILENAME).write_text(
        machine.new_policy(ME, admins_group_sid=GROUP).to_json(), encoding='utf-8')
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    assert [call[0] for call in calls] == ['acl', 'deploy']


def test_a_group_member_is_an_administrator_too(setup, monkeypatch):
    step, root, calls = setup
    (root / machine.POLICY_FILENAME).write_text(
        machine.new_policy(OTHER, admins_group_sid=GROUP).to_json(), encoding='utf-8')
    monkeypatch.setattr(windows, 'token_group_sids', lambda: {GROUP})
    assert step.current_role(root) == 'admin'


def test_not_windows_is_a_development_checkout(tmp_path, monkeypatch):
    from installer.steps import machine as step
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: False)
    assert step.current_role(tmp_path) == 'dev'
    assert step.ensure(tmp_path, tmp_path / 'app', tmp_path) == 'dev'


# ── the program copy ─────────────────────────────────────────────────────

def checkout(tmp_path):
    source = tmp_path / 'checkout'
    (source / 'src' / 'core').mkdir(parents=True)
    (source / 'src' / 'core' / 'x.py').write_text('VALUE = 1\n', encoding='utf-8')
    (source / 'src' / 'tests').mkdir()
    (source / 'src' / 'tests' / 'test_x.py').write_text('', encoding='utf-8')
    (source / 'src' / '__pycache__').mkdir()
    (source / 'RUN.bat').write_text('@echo off\n', encoding='utf-8')
    (source / 'README.md').write_text('readme', encoding='utf-8')
    (source / 'users').mkdir()
    return source


def test_the_program_is_copied_without_tests_or_state(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    assert (target / 'src' / 'core' / 'x.py').is_file()
    assert (target / 'RUN.bat').is_file() and (target / app.VERSION_FILE).is_file()
    assert not (target / 'src' / 'tests').exists()
    assert not (target / 'users').exists(), 'records never travel with the program'
    assert list((target / 'src' / 'core').glob('__pycache__/*.pyc')), 'precompiled for read-only use'


def test_an_update_replaces_the_copy_whole(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    app.deploy(source, target)
    (source / 'src' / 'core' / 'x.py').write_text('VALUE = 2\n', encoding='utf-8')
    (target / 'stale.txt').write_text('old', encoding='utf-8')
    assert app.deploy(source, target)
    assert 'VALUE = 2' in (target / 'src' / 'core' / 'x.py').read_text(encoding='utf-8')
    assert not (target / 'stale.txt').exists()
    assert not target.with_name('app.old').exists()


def test_a_failed_swap_keeps_the_running_copy(tmp_path, monkeypatch):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    app.deploy(source, target)
    real = app.os.replace
    calls = []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise PermissionError(32, 'in use')
        return real(src, dst)

    monkeypatch.setattr(app.os, 'replace', flaky)
    assert app.deploy(source, target) is False
    assert (target / 'src' / 'core' / 'x.py').is_file()
    assert not target.with_name('app.new').exists()


def test_setup_run_from_the_shared_copy_does_not_copy_onto_itself(tmp_path):
    from installer.steps import app
    target = tmp_path / 'app'
    target.mkdir()
    assert app.deploy(target, target) is True


def test_an_ordinary_accounts_setup_leaves_shared_permissions_alone(tmp_path, monkeypatch):
    from installer.core import filesystem
    from integrations.windows import privacy
    ran = []
    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: True)
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, 'run', lambda command, **kw: ran.append(command)
                        or types.SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr('integrations.ollama.sharing._run', lambda command, **kw: ran.append(command)
                        or types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(filesystem, 'repair_stale_children', lambda account: [])
    filesystem.create_environment(tmp_path / 'env', model_dir=tmp_path / 'models',
                                  account_root=tmp_path / 'users' / 'T', manage_shared=False)
    assert not any('/grant' in command for command in ran), ran
