"""Account administration rules: only administrators act, nobody reads.

Every Windows call is replaced; what is held here is which call is made,
when it is refused, and that the policy file and the shared ACL move
together.
"""
import types

import pytest

from core import machine
from integrations import accounts as admin_module
from integrations.accounts import AccountAdmin
from integrations.windows import acl
from integrations.windows import machine as windows

ME = 'S-1-5-21-9-9-9-1001'
BOB = 'S-1-5-21-9-9-9-1002'
ADMINS = 'S-1-5-21-9-9-9-1010'
USERS = 'S-1-5-21-9-9-9-1011'


@pytest.fixture
def machine_root(tmp_path, monkeypatch):
    root = tmp_path / 'LocalAI'
    (root / 'users' / 'ghwork').mkdir(parents=True)
    (root / 'users' / 'bob').mkdir()
    policy = machine.new_policy(ME, admins_group_sid=ADMINS, users_group_sid=USERS)
    (root / machine.POLICY_FILENAME).write_text(policy.to_json(), encoding='utf-8')
    state = {'admins': {ME.upper()}, 'members': set(), 'calls': []}
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, 'current_user_sid', lambda: ME)
    monkeypatch.setattr(windows, 'token_group_sids', lambda: set())
    monkeypatch.setattr(windows, 'list_accounts', lambda: {
        'users': [{'name': 'ghwork', 'sid': ME, 'disabled': False},
                  {'name': 'bob', 'sid': BOB, 'disabled': False}],
        'admins': set(state['admins']), 'members': set(state['members']),
        'administrators': set()})
    monkeypatch.setattr(windows, 'run_as_admin',
                        lambda script, **kw: state['calls'].append(('uac', script)) or True)
    monkeypatch.setattr(acl, 'run', lambda command, **kw: state['calls'].append(('acl', command))
                        or types.SimpleNamespace(returncode=0, stdout='', stderr=''))
    return root, state


def test_the_overview_lists_roles_without_opening_anyones_folder(machine_root):
    root, state = machine_root
    overview = AccountAdmin(root).overview()
    assert overview['available'] and overview['is_admin']
    rows = {row['name']: row for row in overview['rows']}
    assert rows['ghwork']['me'] and rows['ghwork']['admin']
    assert rows['bob']['allowed'] and rows['bob']['records'] and not rows['bob']['admin']
    assert overview['rows'][0]['name'] == 'ghwork', 'me first'


def test_a_non_administrator_cannot_change_anything(machine_root, monkeypatch):
    root, state = machine_root
    monkeypatch.setattr(acl, 'current_user_sid', lambda: BOB)
    for action in (lambda a: a.set_admin(ME, False), lambda a: a.delete_records(ME),
                   lambda a: a.set_allowed(ME, False), lambda a: a.set_access('members')):
        with pytest.raises(RuntimeError, match='관리자만'):
            action(AccountAdmin(root))
    assert state['calls'] == []


def test_making_an_administrator_changes_the_group_the_policy_and_the_acl(machine_root):
    root, state = machine_root
    message = AccountAdmin(root).set_admin(BOB, True)
    assert '다시 로그인' in message
    assert state['calls'][0][0] == 'uac' and ("WinNT://%s" % BOB) in state['calls'][0][1]
    assert machine.load(root / machine.POLICY_FILENAME).is_admin(BOB)
    lock = state['calls'][-1][1]
    assert lock[:3] == ['icacls', str(root), '/inheritance:r'] and '*%s:(OI)(CI)F' % BOB in lock


def test_removing_an_administrator_also_removes_their_explicit_grant(machine_root):
    root, state = machine_root
    AccountAdmin(root).set_admin(BOB, True)
    state['admins'].add(BOB.upper())
    state['calls'].clear()
    AccountAdmin(root).set_admin(BOB, False)
    commands = [call[1] for call in state['calls'] if call[0] == 'acl']
    assert ['icacls', str(root), '/remove:g', '*' + BOB, '/Q'] in commands
    assert not machine.load(root / machine.POLICY_FILENAME).is_admin(BOB)


def test_the_last_administrator_cannot_be_removed(machine_root):
    root, state = machine_root
    with pytest.raises(RuntimeError, match='마지막'):
        AccountAdmin(root).set_admin(ME, False)
    assert state['calls'] == []


def test_deleting_records_never_reads_them_and_never_targets_myself(machine_root):
    root, state = machine_root
    with pytest.raises(RuntimeError, match='지울 수 없습니다'):
        AccountAdmin(root).delete_records(ME)
    message = AccountAdmin(root).delete_records(BOB)
    assert '열어 보지 않았습니다' in message
    script = state['calls'][-1][1]
    assert str(root / 'users' / 'bob') in script and 'Remove-Item' in script
    assert 'Get-Content' not in script and 'type ' not in script


def test_a_declined_prompt_is_an_error_and_the_policy_stays(machine_root, monkeypatch):
    root, state = machine_root
    monkeypatch.setattr(windows, 'run_as_admin', lambda script, **kw: False)
    with pytest.raises(RuntimeError):
        AccountAdmin(root).set_admin(BOB, True)
    assert not machine.load(root / machine.POLICY_FILENAME).is_admin(BOB)


def test_limiting_access_moves_every_shared_grant_to_the_group(machine_root):
    root, state = machine_root
    message = AccountAdmin(root).set_access(machine.ACCESS_MEMBERS)
    assert '허용된 계정만' in message
    commands = [call[1] for call in state['calls'] if call[0] == 'acl']
    removed = [c for c in commands if '/remove:g' in c]
    granted = ' '.join(' '.join(c) for c in commands)
    assert all(c[3] == '*S-1-5-32-545' for c in removed) and len(removed) == 6
    for place, rights in (('models', '(OI)(CI)(M)'), ('environment', '(OI)(CI)(RX)'),
                          ('users', '(RD,X,AD,RA,REA)')):
        assert '*%s:%s' % (USERS, rights) in granted, place
    assert machine.load(root / machine.POLICY_FILENAME).principal() == USERS
    # And back.
    state['calls'].clear()
    AccountAdmin(root).set_access(machine.ACCESS_EVERYONE)
    assert any(c[3] == '*' + USERS for c in (call[1] for call in state['calls']) if '/remove:g' in c)


def test_without_the_users_group_access_cannot_be_limited(machine_root):
    root, state = machine_root
    policy = machine.load(root / machine.POLICY_FILENAME)
    policy.users_group_sid = None
    (root / machine.POLICY_FILENAME).write_text(policy.to_json(), encoding='utf-8')
    with pytest.raises(RuntimeError, match='LocalAI-Users'):
        AccountAdmin(root).set_access(machine.ACCESS_MEMBERS)


def test_no_policy_yet_says_who_should_run_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(acl, 'on_windows', lambda windows=None: True)
    monkeypatch.setattr(acl, 'current_user_sid', lambda: ME)
    monkeypatch.setattr(windows, 'token_group_sids', lambda: set())
    overview = AccountAdmin(tmp_path).overview()
    assert not overview['available'] and '처음 설치한 계정' in overview['reason']


def test_records_folder_matches_the_accounts_own_folder_name():
    from core import accounts
    from pathlib import Path
    assert admin_module.folder_for(Path('/r'), '홍길동') == Path('/r') / 'users' / accounts.slug('홍길동')
