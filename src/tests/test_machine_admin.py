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
# Imported before any test patches acl.run: sharing binds acl.run at import.
import integrations.ollama.sharing  # noqa: F401
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
    assert "$target = '%s'" % ME in script, 'membership by SID, not a localized name'
    assert "Test-LocalAISidMember" in script, 'SID membership verified by enumeration'
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
    script = windows.membership_script(machine.USERS_GROUP, OTHER, False)
    assert "Invoke('Remove'" in script
    assert windows.membership_script('Administrators', OTHER, True) is None
    assert windows.membership_script(machine.ADMINS_GROUP, 'bob', True) is None


def test_membership_verification_does_not_use_unsupported_winnt_sid_ismember():
    # Microsoft: WinNT Add/Remove accept a SID ADsPath, but IsMember on the
    # same SID path cannot verify membership and produced exit code 1.
    script = windows.first_install_script(ME, ROOT, APP)
    assert "Invoke('Members')" in script
    assert "InvokeMember('objectSid'" in script
    assert "SecurityIdentifier]::new([byte[]]$raw, 0)" in script
    assert "NTAccount]::new($localGroup)" in script
    assert "Test-LocalAISidMember" in script
    assert "psbase.Invoke('IsMember'" not in script
    assert "'WinNT://'" in script



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
    from integrations.windows import program_security
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
    monkeypatch.setattr(windows, 'group_sid', lambda name: GROUP if name == machine.ADMINS_GROUP else 'S-1-5-21-111-222-333-1011')
    # LocalAI-Admins as Windows lists it now (the first-install UAC adds ME).
    monkeypatch.setattr(windows, 'group_member_sids',
                        lambda name: {ME} if name == machine.ADMINS_GROUP else set())
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: calls.append(('uac', script)) or True)
    monkeypatch.setattr(step.app_step, 'deploy', lambda source, target: calls.append(('deploy', target)) or True)
    monkeypatch.setattr(program_security, 'verify', lambda root, policy: [])
    monkeypatch.setattr(program_security, 'ensure',
                        lambda root, policy, **kw: calls.append(('protect', root)) or True)
    return step, root, calls


def test_the_first_installer_becomes_administrator_with_one_prompt(setup):
    step, root, calls = setup
    assert step.current_role(root) == 'user', 'no administrator before UAC+ACL verification'
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    kinds = [call[0] for call in calls]
    assert kinds == ['uac', 'deploy'], 'executable files must not be deployed before UAC'
    policy = machine.load(root / machine.POLICY_FILENAME)
    assert policy.admins == (ME,) and policy.admins_group_sid == GROUP


def test_declining_the_prompt_aborts_without_deploying_or_recording_admin(setup, monkeypatch):
    step, root, calls = setup
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: False)
    with pytest.raises(RuntimeError, match='관리자 자동 등록'):
        step.ensure(root, root / 'app', Path('/checkout'))
    assert not (root / machine.POLICY_FILENAME).exists()
    assert all(call[0] != 'deploy' for call in calls)


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
    assert [call[0] for call in calls] == ['protect', 'deploy']


def test_unregistered_other_account_cannot_finish_an_unprotected_install(setup, monkeypatch):
    step, root, calls = setup
    monkeypatch.setattr(acl, 'owner_sid', lambda path: OTHER)
    with pytest.raises(RuntimeError, match='아직 LocalAI 관리자'):
        step.ensure(root, root / 'app', Path('/checkout'))
    assert not calls


def test_acl_inspection_failure_blocks_deployment(setup, monkeypatch):
    step, root, calls = setup
    from integrations.windows import program_security
    monkeypatch.setattr(program_security, 'verify',
                        lambda root, policy: ['DACL: unexpected Users Modify'])
    with pytest.raises(RuntimeError, match='ACL 검증'):
        step.ensure(root, root / 'app', Path('/checkout'))
    assert all(call[0] != 'deploy' for call in calls)


def test_existing_admin_acl_repair_failure_never_updates_program(setup, monkeypatch):
    step, root, calls = setup
    from integrations.windows import program_security
    (root / machine.POLICY_FILENAME).write_text(
        machine.new_policy(ME, admins_group_sid=GROUP).to_json(), encoding='utf-8')
    def fail(*args, **kwargs):
        raise RuntimeError('ACL repair failed')
    monkeypatch.setattr(program_security, 'ensure', fail)
    with pytest.raises(RuntimeError, match='ACL repair failed'):
        step.ensure(root, root / 'app', Path('/checkout'))
    assert all(call[0] != 'deploy' for call in calls)


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

def _git(repo, *args):
    import subprocess
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                    '-c', 'commit.gpgsign=false', '-C', str(repo), *args],
                   check=True, capture_output=True)


def commit_all(repo, message='c'):
    """Commit and mark it as present on a remote, as a pushed commit is."""
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', message)
    _git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


def checkout(tmp_path):
    source = tmp_path / 'checkout'
    (source / 'src' / 'core').mkdir(parents=True)
    (source / 'src' / 'core' / 'x.py').write_text('VALUE = 1\n', encoding='utf-8')
    (source / 'src' / 'tests').mkdir()
    (source / 'src' / 'tests' / 'test_x.py').write_text('', encoding='utf-8')
    # Bytes, not text: Windows text mode would already add the CRLF under test.
    (source / 'RUN.bat').write_bytes(b'@echo off\n:A\ngoto A\n')
    (source / 'README.md').write_text('readme', encoding='utf-8')
    (source / '.gitignore').write_text('__pycache__/\nusers/\n', encoding='utf-8')
    _git(source, 'init', '-q')
    _git(source, 'config', 'core.autocrlf', 'false')
    commit_all(source)
    (source / 'src' / '__pycache__').mkdir()
    (source / 'users').mkdir()
    return source


def test_the_program_is_copied_without_tests_or_state(tmp_path):
    from installer.steps import app
    from core import program_integrity
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    assert (target / 'src' / 'core' / 'x.py').is_file()
    assert (target / 'RUN.bat').is_file() and (target / app.VERSION_FILE).is_file()
    assert not (target / 'src' / 'tests').exists()
    assert not (target / 'users').exists(), 'records never travel with the program'
    assert not (target / '.gitignore').exists()
    assert list((target / 'src' / 'core').glob('__pycache__/*.pyc')), 'precompiled for read-only use'
    manifest = program_integrity.load(target)
    assert manifest['schema'] == program_integrity.SCHEMA
    assert len(manifest['commit']) == 40 and manifest['remote_branches'] == ['origin/main']
    assert program_integrity.verify(target) == []
    assert app.verify_deployed(target, source) == [], 'anchored to the checkout commit'


def test_batch_files_are_written_with_crlf_and_still_match_git(tmp_path):
    from installer.steps import app
    from core import program_integrity
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    data = (target / 'RUN.bat').read_bytes()
    assert data == b'@echo off\r\n:A\r\ngoto A\r\n', 'cmd.exe labels need CRLF'
    entry = program_integrity.load(target)['files']['RUN.bat']
    assert entry['eol'] == 'crlf'
    assert program_integrity.git_blob_id(
        program_integrity.to_blob('RUN.bat', data, entry['eol'])) == entry['git']


def test_an_update_replaces_the_copy_whole(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    app.deploy(source, target)
    (source / 'src' / 'core' / 'x.py').write_text('VALUE = 2\n', encoding='utf-8')
    commit_all(source, 'v2')
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


# ── only what Git vouches for is deployed ────────────────────────────────

def test_uncommitted_edits_are_never_deployed(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    (source / 'src' / 'core' / 'x.py').write_text('import os; os.system("evil")\n', encoding='utf-8')
    assert app.deploy(source, target) is False
    assert not target.exists()


def test_an_extra_untracked_program_is_never_deployed(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    (source / 'src' / 'sitecustomize.py').write_text('print("injected")\n', encoding='utf-8')
    assert app.deploy(source, target) is False
    assert not target.exists()


def test_a_git_ignored_extra_is_not_copied_either(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    (source / 'src' / '__pycache__' / 'json.cpython-313.pyc').write_bytes(b'planted')
    assert app.deploy(source, target)
    assert not (target / 'src' / '__pycache__' / 'json.cpython-313.pyc').exists()


def test_a_commit_no_remote_branch_contains_is_refused(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    (source / 'src' / 'core' / 'x.py').write_text('VALUE = 3\n', encoding='utf-8')
    _git(source, 'commit', '-q', '-am', 'local only')
    with pytest.raises(app.DeploySourceError, match='원격'):
        app.git_source(source)
    assert app.deploy(source, target) is False


def test_a_symlink_in_the_commit_is_refused(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    try:
        (source / 'src' / 'link.py').symlink_to(source / 'README.md')
    except (OSError, NotImplementedError):
        pytest.skip('this account may not create symlinks')
    commit_all(source, 'link')
    with pytest.raises(app.DeploySourceError, match='일반 파일'):
        app.git_source(source)


def test_a_subfolder_of_a_repository_is_not_a_source(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    with pytest.raises(app.DeploySourceError, match='최상위'):
        app.git_source(source / 'src')


def test_a_checkouts_own_git_config_cannot_run_a_program(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    marker = tmp_path / 'ran'
    hook = tmp_path / 'fsmonitor.sh'
    hook.write_text('#!/bin/sh\ntouch %s\n' % marker, encoding='utf-8')
    hook.chmod(0o755)
    _git(source, 'config', 'core.fsmonitor', str(hook))
    _git(source, 'config', 'core.hooksPath', str(tmp_path))
    app.git_source(source)
    assert not marker.exists(), 'core.fsmonitor must be forced off for Setup'


def test_borrowed_object_stores_are_refused(tmp_path):
    from installer.steps import app
    source = checkout(tmp_path)
    (source / '.git' / 'objects' / 'info' / 'alternates').write_text(
        str(tmp_path / 'elsewhere') + '\n', encoding='utf-8')
    with pytest.raises(app.DeploySourceError, match='alternates'):
        app.git_source(source)


def test_an_object_whose_content_does_not_match_its_id_is_refused(tmp_path, monkeypatch):
    from installer.steps import app
    oid = 'a' * 40
    monkeypatch.setattr(app, '_git', lambda source, *args, **kw:
                        ('%s blob 4\n' % oid).encode() + b'evil\n')
    with pytest.raises(app.DeploySourceError, match='해시'):
        app._read_blobs(tmp_path, {'src/x.py': oid})


# ── the deployed copy stays what the commit says ─────────────────────────

def test_drift_in_the_deployed_copy_is_detected(tmp_path):
    from installer.steps import app
    from core import program_integrity
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    (target / 'src' / 'core' / 'x.py').write_text('VALUE = "tampered"\n', encoding='utf-8')
    (target / 'src' / 'sitecustomize.py').write_text('', encoding='utf-8')
    pyc = next((target / 'src' / 'core' / '__pycache__').glob('*.pyc'))
    pyc.unlink()
    problems = program_integrity.verify(target)
    assert any('변경된 파일: src/core/x.py' in p for p in problems)
    assert any('추가된 파일: src/sitecustomize.py' in p for p in problems)
    assert any('없어진 파일' in p and '.pyc' in p for p in problems)
    with pytest.raises(program_integrity.IntegrityError, match='Git 커밋'):
        program_integrity.check_running_copy(target)
    assert app.deploy(target, target) is False, 'Setup run from a drifted copy refuses too'


def test_a_rewritten_manifest_does_not_pass_as_the_commit(tmp_path):
    """Tampering plus a recomputed manifest: drift check passes, Git does not."""
    import json
    from installer.steps import app
    from core import program_integrity
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    evil = b'VALUE = "tampered"\n'
    (target / 'src' / 'core' / 'x.py').write_bytes(evil)
    manifest = program_integrity.load(target)
    manifest['files']['src/core/x.py'] = {'git': program_integrity.git_blob_id(evil),
                                          'sha256': program_integrity.sha256(evil)}
    (target / app.VERSION_FILE).write_text(json.dumps(manifest), encoding='utf-8')
    assert program_integrity.verify(target) == []
    assert any('커밋과 다른 내용: src/core/x.py' in p
               for p in app.verify_deployed(target, source))


def test_development_checkouts_and_legacy_copies_are_not_blocked(tmp_path):
    from core import program_integrity
    assert program_integrity.check_running_copy(tmp_path) is None
    (tmp_path / program_integrity.VERSION_FILE).write_text(
        '{"revision": "abc1234", "deployed_at": "x"}', encoding='utf-8')
    assert '무결성 정보' in program_integrity.check_running_copy(tmp_path)


def test_the_verify_tool_reports_the_git_anchored_result(tmp_path, capsys):
    from installer.steps import app
    from tools import verify_app
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    assert verify_app.main(['--app', str(target), '--source', str(source)]) == 0
    assert 'Git ls-tree' in capsys.readouterr().out
    (target / 'README.md').write_text('changed', encoding='utf-8')
    assert verify_app.main(['--app', str(target), '--source', str(source)]) == 1


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
    (tmp_path / 'users').mkdir()   # the administrator's Setup made the parent
    filesystem.create_environment(tmp_path / 'env', model_dir=tmp_path / 'models',
                                  account_root=tmp_path / 'users' / 'T', manage_shared=False)
    assert not any('/grant' in command for command in ran), ran


def test_ordinary_account_setup_does_not_create_missing_shared_runtime_dirs(monkeypatch, tmp_path):
    from installer.core import filesystem as fs
    env = tmp_path / "environment"
    store = tmp_path / "models"
    account = tmp_path / "users" / "second"
    monkeypatch.setattr(fs, "ensure_private_account", lambda p: True)
    monkeypatch.setattr(fs, "repair_stale_children", lambda p: [])
    monkeypatch.setattr(fs, "protect_existing_records", lambda p: None)
    (tmp_path / "users").mkdir()
    store.mkdir()   # the administrator's store, read-only for this account
    fs.create_environment(env, model_dir=store, account_root=account,
                          manage_shared=False)
    assert account.is_dir()
    assert (account / "workspace").is_dir()
    assert not env.exists(), "no ordinary account can create the shared environment"
    assert not (env / "desktop-runtime.lock").exists()
    assert not (store / ".localai").exists(), "the shared model control plane is admin-only"
    assert list(store.iterdir()) == []


def test_ordinary_account_setup_needs_the_administrators_users_parent(monkeypatch, tmp_path):
    from installer.core import filesystem as fs
    monkeypatch.setattr(fs, "ensure_private_account", lambda p: True)
    with pytest.raises(RuntimeError, match="관리자"):
        fs.create_environment(tmp_path / "environment", model_dir=tmp_path / "models",
                              account_root=tmp_path / "users" / "second",
                              manage_shared=False)
    assert not (tmp_path / "users").exists()


def test_admins_only_the_file_lists_are_dropped_before_granting_full_control(setup, monkeypatch):
    step, root, calls = setup
    from integrations.windows import program_security
    seen = []
    monkeypatch.setattr(program_security, 'ensure',
                        lambda root, policy, **kw: seen.append(policy) or True)
    tampered = machine.new_policy(ME, admins_group_sid=GROUP).with_admin(OTHER)
    (root / machine.POLICY_FILENAME).write_text(tampered.to_json(), encoding='utf-8')
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    assert seen and OTHER not in seen[0].admin_sids()
    assert machine.load(root / machine.POLICY_FILENAME).admins == (ME,), 'file cleaned'


def test_a_listed_sid_outside_the_group_is_an_ordinary_user(setup, monkeypatch):
    step, root, calls = setup
    (root / machine.POLICY_FILENAME).write_text(
        machine.new_policy(OTHER, admins_group_sid=GROUP).with_admin(ME).to_json(), encoding='utf-8')
    monkeypatch.setattr(windows, 'group_member_sids', lambda name: {OTHER})
    assert step.current_role(root) == 'user'
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'user'
    assert calls == []


def test_a_legacy_install_is_repaired_only_through_uac_for_this_account(setup, monkeypatch):
    step, root, calls = setup
    legacy = machine.new_policy(ME).with_admin(OTHER)
    legacy.notes['groups_pending'] = True
    (root / machine.POLICY_FILENAME).write_text(legacy.to_json(), encoding='utf-8')
    assert step.ensure(root, root / 'app', Path('/checkout')) == 'admin'
    assert [call[0] for call in calls][:1] == ['uac']
    repaired = machine.load(root / machine.POLICY_FILENAME)
    assert repaired.admins == (ME,) and repaired.admins_group_sid == GROUP
    assert 'groups_pending' not in repaired.notes


def test_a_legacy_install_whose_uac_is_declined_changes_nothing(setup, monkeypatch):
    step, root, calls = setup
    legacy = machine.new_policy(ME)
    legacy.notes['groups_pending'] = True
    (root / machine.POLICY_FILENAME).write_text(legacy.to_json(), encoding='utf-8')
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: False)
    with pytest.raises(RuntimeError, match='승인'):
        step.ensure(root, root / 'app', Path('/checkout'))
    assert all(call[0] != 'deploy' for call in calls)


def test_reconcile_keeps_only_what_windows_vouches_for():
    policy = machine.new_policy(ME, admins_group_sid='S-1-5-32-545',
                                users_group_sid='S-1-5-32-545').with_admin(OTHER)
    policy.access = machine.ACCESS_MEMBERS
    trusted = machine.reconcile(policy, admins_group_sid=GROUP, users_group_sid=None,
                                admin_members={ME.lower()})
    assert trusted.admins == (ME,)
    assert trusted.admins_group_sid == GROUP
    assert trusted.principal() == 'S-1-5-32-545' and trusted.users_group_sid is None
    unknown = machine.reconcile(policy, admins_group_sid=GROUP, users_group_sid=None,
                                admin_members=None)
    assert unknown.admins == (), 'unknown membership keeps nobody'
    assert machine.reconcile(None, admins_group_sid=None, users_group_sid=None,
                             admin_members=None) is None


def test_a_drive_root_or_system_folder_is_never_locked(monkeypatch, tmp_path):
    """LOCAL_AI_ROOT can point anywhere; cutting inheritance there must not."""
    system = tmp_path / 'Windows'
    profile = tmp_path / 'Users' / 'ghwork'
    monkeypatch.setenv('SystemRoot', str(system))
    monkeypatch.setenv('USERPROFILE', str(profile))
    assert windows.lockable_root(tmp_path / 'LocalAI')
    assert not windows.lockable_root(Path('/'))
    assert not windows.lockable_root(system)
    assert not windows.lockable_root(tmp_path / 'Users'), 'holds every profile'
    assert not windows.lockable_root(tmp_path), 'would include the Windows folder'


def test_group_members_are_read_by_sid_and_unreadable_is_unknown(monkeypatch):
    out = types.SimpleNamespace(returncode=0, stdout='noise S-1-5-21-0-0-0-9\nmembers=%s,%s\n'
                                % (ME, OTHER), stderr='')
    monkeypatch.setattr(windows, 'run_script', lambda script, **kw: out)
    assert windows.group_member_sids(machine.ADMINS_GROUP) == {ME.upper(), OTHER.upper()}
    assert windows.group_member_sids('Administrators') is None, 'only the two LocalAI groups'
    monkeypatch.setattr(windows, 'run_script', lambda script, **kw:
                        types.SimpleNamespace(returncode=1, stdout='', stderr='x'))
    assert windows.group_member_sids(machine.ADMINS_GROUP) is None


def test_a_drifted_shared_copy_is_not_started(monkeypatch):
    from apps.shared import entry
    from core import program_integrity
    import services.system.bootstrap as bootstrap

    def drifted(root=None):
        raise program_integrity.IntegrityError('변경된 파일: src/core/x.py')

    monkeypatch.setattr(program_integrity, 'check_running_copy', drifted)
    monkeypatch.setattr(entry, '_report_startup_error', lambda exc, hint='': None)
    monkeypatch.setattr(bootstrap, 'install_exit_hooks',
                        lambda *a, **k: pytest.fail('nothing may start'))
    assert entry.main('studio', []) == 4
    assert entry.main('studio', ['--tui']) == 4
# ── first-run automatic registration and readable UAC errors ────────────
def test_first_run_bootstraps_admin_without_separate_install_flag(monkeypatch, tmp_path):
    from installer.steps import machine as step
    from installer.core import filesystem
    root=tmp_path / 'LocalAI'
    calls=[]
    monkeypatch.setattr(acl, 'on_windows', lambda: True)
    monkeypatch.setattr(step, 'ensure',
                        lambda *args: calls.append(('ensure', args)) or 'admin')
    monkeypatch.setattr(filesystem, 'create_environment',
                        lambda *args, **kw: calls.append(('env', args, kw)))
    assert step.bootstrap_first_run(root, root / 'app',
                                    tmp_path / 'checkout', root / 'environment') is True
    assert calls[0][0] == 'ensure'
    assert calls[1][0] == 'env'
    assert calls[1][2]['manage_shared'] is True


def test_existing_policy_never_attempts_first_run_claim(monkeypatch, tmp_path):
    from installer.steps import machine as step
    root=tmp_path / 'LocalAI'
    root.mkdir()
    (root / machine.POLICY_FILENAME).write_text(machine.new_policy(ME).to_json(),
                                                encoding='utf-8')
    monkeypatch.setattr(acl, 'on_windows', lambda: True)
    monkeypatch.setattr(step, 'ensure', lambda *a: pytest.fail('unexpected admin claim'))
    assert step.bootstrap_first_run(root, root / 'app', tmp_path,
                                    root / 'environment') is False


def test_corrupted_policy_is_not_treated_as_first_run(monkeypatch, tmp_path):
    from installer.steps import machine as step
    root=tmp_path / 'LocalAI'
    root.mkdir()
    (root / machine.POLICY_FILENAME).write_text('{broken json',encoding='utf-8')
    monkeypatch.setattr(acl, 'on_windows', lambda: True)
    with pytest.raises(RuntimeError, match='정책 복구'):
        step.bootstrap_first_run(root, root / 'app', tmp_path, root / 'environment')


def test_elevated_script_failure_reports_real_stage_not_uac_cancel(monkeypatch, tmp_path):
    monkeypatch.delenv('LOCAL_AI_NO_ELEVATION', raising=False)
    monkeypatch.setattr(acl, 'is_elevated', lambda: False)
    monkeypatch.setattr(acl, 'run_elevated', lambda *a, **kw: (1, None))
    report=tmp_path / '.localai-admin-123.txt'
    report.write_text('program ACL: Unable to reset ACLs: C:\\LocalAI\\app',
                      encoding='utf-8')
    events=[]
    assert windows.run_as_admin('x',log=events.append,report_path=report) is False
    assert any('실패 단계:' in e and 'program ACL' in e for e in events)
    assert not any('승인이 취소' in e for e in events)


def test_first_install_report_is_written_only_on_failure_and_cannot_overwrite(tmp_path):
    report=tmp_path / '.localai-admin-123.txt'
    script=windows.first_install_script(ME,tmp_path,tmp_path / 'app',
                                        report_path=report)
    assert '[System.IO.FileMode]::CreateNew' in script
    assert '$localaiIssues' in script
    assert 'create group LocalAI-Admins' in script
    assert 'root ACL' in script
    assert 'if ($failed -ne 0)' in script


def test_program_security_does_not_write_error_from_its_own_catch():
    from integrations.windows import program_security
    script=program_security.protection_script(Path('C:/LocalAI'),machine.new_policy(ME))
    assert 'Write-Error $_' not in script
    assert 'Write-Warning $detail' in script
    assert script.index('icacls.exe $folder /setowner') < script.index(
        'icacls.exe $folder /reset')


def test_bytecode_another_python_wrote_does_not_lock_everyone_out(tmp_path):
    import sys
    from installer.steps import app
    from core import program_integrity
    source = checkout(tmp_path)
    target = tmp_path / 'LocalAI' / 'app'
    assert app.deploy(source, target)
    cache = target / 'src' / 'core' / '__pycache__'
    (cache / 'x.cpython-39.pyc').write_bytes(b'other interpreter')
    assert program_integrity.verify(target) == []
    (cache / ('y.%s.pyc' % sys.implementation.cache_tag)).write_bytes(b'this interpreter')
    assert any('추가된 파일' in p for p in program_integrity.verify(target))
