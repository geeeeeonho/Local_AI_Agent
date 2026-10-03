"""Models shared by the machine; what a person does with them, theirs alone.

Those two live one folder apart under the same root, and they want opposite
permissions. The model store deliberately grants ``BUILTIN\\Users`` Modify so a
second Windows account can install/remove the same models instead of maintaining
its own copy. A folder created underneath inherits that grant - so the records
folder is not private by being in the right place, and the household's other
account could open the chat history, the project list and every agent trace.

Two signed-in accounts sharing one ``user_data`` is worse than a leak, too:
they write the same settings file and the same session state and corrupt each
other.

These tests hold both halves at once - the store readable, the records not -
and hold the check to saying "unknown" when it cannot read an ACL, rather than
reassuring anyone.
"""
import types
from pathlib import Path

import pytest

from core import accounts, sddl
from integrations.windows import acl, privacy


# What ``icacls <dir> /save`` writes. BU is BUILTIN\Users in every language,
# which is the point of reading SDDL rather than icacls' own output.
INHERITED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;0x1200a9;;;BU)'
LOCKED = 'D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-7-8-9-1001)'
EVERYONE = 'D:PAI(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;WD)'
DENIED = 'D:PAI(D;OICI;FA;;;BU)(A;OICI;0x1200a9;;;BU)(A;OICI;FA;;;SY)'


def fake_icacls(monkeypatch, descriptor=LOCKED, returncode=0, after_lock=None):
    """A machine where icacls answers with ``descriptor``. Records every call.

    ``after_lock`` is what a folder reads back once ``/inheritance:r`` has run
    on it, so a test can follow a real lock from inherited to private.
    """
    ran = []
    locked = set()

    def run(command, **kwargs):
        ran.append(list(command))
        if returncode == 0 and '/inheritance:r' in command:
            locked.add(str(command[1]))
        if returncode == 0 and '/save' in command and descriptor is not None:
            target = Path(command[command.index('/save') + 1])
            current = (after_lock if after_lock is not None and str(command[1]) in locked
                       else descriptor)
            target.write_text('folder\n' + current + '\n', encoding='utf-16')
        return types.SimpleNamespace(returncode=returncode, stdout='', stderr='')

    monkeypatch.setattr(acl.subprocess, 'run', run)
    return ran


# ── naming one account's folder ───────────────────────────────────────────

def test_a_plain_account_name_is_kept_so_the_owner_recognises_the_folder():
    assert accounts.slug('Geonho') == 'Geonho'
    assert accounts.slug('dev_user-1') == 'dev_user-1'


def test_two_accounts_that_clean_up_the_same_never_share_a_folder():
    """``Hong Gil-dong`` and ``HongGil-dong`` are two Windows accounts.

    Strip the space and they are one folder - which is the exact failure this
    split exists to prevent, arriving through the back door.
    """
    assert accounts.slug('Hong Gil-dong') != accounts.slug('HongGil-dong')
    assert accounts.slug('홍길동') != accounts.slug('김철수')


def test_a_folder_name_is_safe_to_hand_to_docker_and_to_windows():
    """It ends up in a ``docker -v`` argument and in a path under C:.

    A space or a Korean character is not cosmetic there: Docker Desktop
    refuses the mount and the sandbox never starts.
    """
    for name in ('홍길동', 'Hong Gil-dong', 'CON', '', 'a' * 90, 'x/y\\z:w'):
        value = accounts.slug(name)
        assert value and value.isascii()
        assert not any(c in value for c in ' /\\:*?"<>|')
        assert value.upper() not in ('CON', 'PRN', 'AUX', 'NUL')
        assert len(value) <= 48


def test_the_account_is_read_from_the_machine_and_can_be_overridden():
    assert accounts.current_name({'USERNAME': 'Geonho'}) == 'Geonho'
    assert accounts.current_name({'USER': 'geonho'}) == 'geonho'
    assert accounts.current_name({'USERNAME': 'Geonho',
                                  accounts.ACCOUNT_VARIABLE: 'Other'}) == 'Other'
    assert accounts.current_name({}) == 'user'


# ── reading what the ACL actually says ────────────────────────────────────

def test_an_inherited_grant_from_the_shared_store_is_not_private():
    """This is the state a new folder starts in, and why the work is needed."""
    assert accounts.private_from_sddl(INHERITED) is False


def test_the_locked_folder_reads_as_private():
    assert accounts.private_from_sddl(LOCKED) is True


def test_everyone_counts_as_somebody_else():
    assert accounts.private_from_sddl(EVERYONE) is False


def test_a_deny_wins_over_an_allow_the_way_windows_evaluates_it():
    assert accounts.private_from_sddl(DENIED) is True


def test_an_unreadable_acl_is_unknown_rather_than_reassuring():
    assert accounts.private_from_sddl('not a descriptor') is None
    assert accounts.private_from_sddl('') is None


def test_the_same_parser_answers_the_stores_question_the_other_way():
    """One descriptor, two questions - and they must not disagree."""
    from core.models import sharing
    assert sharing.readable_from_sddl(INHERITED) is True
    assert accounts.private_from_sddl(INHERITED) is False
    assert sharing.readable_from_sddl(LOCKED) is False
    assert accounts.private_from_sddl(LOCKED) is True


# ── putting it right on the real machine ──────────────────────────────────

def test_locking_a_folder_breaks_inheritance_in_the_same_call(monkeypatch, tmp_path):
    """``/inheritance:r`` alone copies the inherited entries in and keeps them.

    Removing the link without replacing the list leaves the very grant being
    removed, so the folder reads as private to nobody and stays open.
    """
    folder = tmp_path / 'users' / 'Tester'
    folder.mkdir(parents=True)
    ran = fake_icacls(monkeypatch)

    assert privacy.make_private(folder, windows=True,
                                environ={'USERNAME': 'Tester', 'USERDOMAIN': 'PC'})

    command = ran[-1]
    assert command[:2] == ['icacls', str(folder)]
    assert '/inheritance:r' in command
    assert 'PC\\Tester:(OI)(CI)F' in command
    assert '*%s:(OI)(CI)F' % privacy.SYSTEM_SID in command
    assert '*%s:(OI)(CI)F' % privacy.ADMINISTRATORS_SID in command
    assert '/T' in command, 'files already inside have to be covered too'
    assert command.count('/grant:r') == 3
    assert not any('BU' in part or sddl.USERS_SID in part for part in command)


def test_administrators_keep_access_so_a_broken_acl_can_be_repaired(monkeypatch):
    entries = privacy.grants({'USERNAME': 'Tester'})
    assert any(privacy.ADMINISTRATORS_SID in entry for entry in entries)
    assert any(privacy.SYSTEM_SID in entry for entry in entries)


def test_a_folder_that_is_already_private_is_not_rewritten(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    ran = fake_icacls(monkeypatch, LOCKED)
    assert privacy.ensure_private(folder, windows=True) is True
    assert not any('/inheritance:r' in command for command in ran)


def test_private_but_unwritable_folder_is_repaired(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    ran = fake_icacls(monkeypatch, LOCKED)
    writable = iter([False, True])
    monkeypatch.setattr(
        privacy,
        'current_user_can_write',
        lambda path: next(writable),
    )

    assert privacy.ensure_private(
        folder,
        windows=True,
        environ={'USERNAME': 'Tester'},
    ) is True
    assert any('/inheritance:r' in command for command in ran), ran


def test_a_folder_open_to_everyone_is_locked_and_checked_again(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    states = iter([INHERITED, LOCKED])
    ran = []

    def run(command, **kwargs):
        ran.append(list(command))
        if '/save' in command:
            target = Path(command[command.index('/save') + 1])
            target.write_text('folder\n' + next(states) + '\n', encoding='utf-16')
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(acl.subprocess, 'run', run)
    assert privacy.ensure_private(folder, windows=True,
                                  environ={'USERNAME': 'Tester'}) is True
    assert any('/inheritance:r' in command for command in ran)


def test_a_failed_lock_says_so_instead_of_claiming_privacy(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    fake_icacls(monkeypatch, INHERITED, returncode=1)
    assert privacy.make_private(folder, windows=True) is False
    assert privacy.ensure_private(folder, windows=True) is not True


def test_an_acl_that_cannot_be_read_is_unknown(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    fake_icacls(monkeypatch, descriptor=None)
    assert privacy.is_private(folder, windows=True) is None
    assert '확인하지 못했습니다' in privacy.describe(folder, windows=True)


def test_the_words_for_each_state_say_what_the_user_needs_to_do(monkeypatch, tmp_path):
    folder = tmp_path / 'account'
    folder.mkdir()
    fake_icacls(monkeypatch, LOCKED)
    assert '이 계정 전용' in privacy.describe(folder, windows=True)
    fake_icacls(monkeypatch, INHERITED)
    exposed = privacy.describe(folder, windows=True)
    assert '다른 Windows 계정' in exposed and '설치 / 복구' in exposed


# ── setup does it, and the window says when it did not ────────────────────

def test_setup_locks_the_account_folder_it_creates(monkeypatch, tmp_path):
    from installer.core import filesystem
    locked = []
    monkeypatch.setattr(privacy, 'ensure_private',
                        lambda path, **kw: locked.append(Path(path)) or True)
    account = tmp_path / 'users' / 'Tester'
    paths = filesystem.create_environment(tmp_path / 'env',
                                          model_dir=tmp_path / 'models',
                                          account_root=account)
    assert paths['account'] == account
    assert paths['user_data'] == account / 'user_data'
    assert locked == [account]


def test_setup_refuses_to_create_personal_state_when_privacy_cannot_be_enforced(monkeypatch, tmp_path):
    from installer.core import filesystem

    monkeypatch.setattr(privacy, 'ensure_private', lambda path, **kw: False)
    monkeypatch.setattr('integrations.windows.acl.on_windows', lambda windows=None: True)
    fake_icacls(monkeypatch)
    account = tmp_path / 'users' / 'Tester'

    with pytest.raises(RuntimeError, match='개인 폴더를 안전하게 잠그지 못했습니다'):
        filesystem.create_environment(
            tmp_path / 'env',
            model_dir=tmp_path / 'models',
            account_root=account,
        )

    assert not (account / 'user_data').exists()
    assert not (account / 'logs').exists()



def test_off_windows_the_account_folder_is_owner_only_instead_of_refused(monkeypatch, tmp_path):
    """No Windows ACL exists to read back off Windows, so the answer is always
    "unknown". Failing closed on that aborted every setup and model install on
    a development machine; owner-only permissions are the equivalent there."""
    import os
    import stat
    from installer.core import filesystem
    monkeypatch.setattr('integrations.windows.acl.on_windows', lambda windows=None: False)
    account = tmp_path / 'users' / 'Tester'
    paths = filesystem.create_environment(tmp_path / 'env',
                                          model_dir=tmp_path / 'models',
                                          account_root=account)
    assert paths['user_data'].is_dir()
    if os.name != 'nt':
        assert stat.S_IMODE(account.stat().st_mode) == 0o700


def test_the_store_stays_readable_while_the_records_do_not(monkeypatch, tmp_path):
    """Both halves in one pass: the grants must not undo each other.

    Setup asks for exactly two things on the same root - let every account read
    the models, let no other account read this one's records - and a change to
    either one has to leave the other standing.
    """
    from installer.core import filesystem
    models = tmp_path / 'models'
    account = tmp_path / 'users' / 'Tester'
    # Starts in the state a new folder is really in: inheriting the store's
    # grant, so the lock has to actually run.
    ran = fake_icacls(monkeypatch, INHERITED, after_lock=LOCKED)
    monkeypatch.setattr(filesystem, 'publish_shared_model_dir', lambda *a, **k: True)
    monkeypatch.setattr('core.accounts.current_slug', lambda environ=None: 'Tester')
    monkeypatch.setattr('project_paths.ACCOUNT_ROOT', account)
    monkeypatch.setattr('project_paths.MODEL_STORAGE_DIR', models)
    monkeypatch.setattr(filesystem, 'MODEL_STORAGE_DIR', models)
    monkeypatch.setattr(filesystem, 'ACCOUNT_ROOT', account)
    monkeypatch.setattr('integrations.windows.acl.on_windows', lambda windows=None: True)

    filesystem.create_environment(tmp_path / 'env')

    grants_to_users = [c for c in ran
                       if '/grant' in c and any(sddl.USERS_SID in p for p in c)]
    assert grants_to_users, 'shared assets must remain usable by standard accounts'

    model_grants = [c for c in grants_to_users if str(models) in c]
    users_parent_grants = [c for c in grants_to_users if str(account.parent) in c]

    assert model_grants, 'every account still has to be able to manage the models'
    assert any('(OI)(CI)(M)' in part for command in model_grants for part in command)

    assert users_parent_grants, 'a standard account must be able to create users/<itself>'
    assert all('(OI)' not in part and '(CI)' not in part
               for command in users_parent_grants for part in command), \
        'the parent creation grant must never inherit into private account data'

    assert not any(str(account) in command and '/grant' in command
                   and any(sddl.USERS_SID in p for p in command)
                   for command in ran), \
        'BUILTIN Users must never receive a grant on users/<account> itself'

    locked = [c for c in ran if '/inheritance:r' in c]
    assert locked and all(str(account) in command for command in locked)


def test_the_window_is_told_when_the_records_are_readable_by_others(tmp_path, monkeypatch):
    from integrations import desktop
    import project_paths
    account = tmp_path / 'users' / 'Tester'
    account.mkdir(parents=True)
    monkeypatch.setattr(project_paths, 'ACCOUNT_ROOT', account)
    monkeypatch.setattr(privacy, 'is_private', lambda path, **kw: False)
    backend = desktop.DesktopBackend(tmp_path / 'env', tmp_path / 'models', tmp_path)
    message = backend.describe_records_privacy()
    assert message and str(account) in message and '설치 / 복구' in message

    monkeypatch.setattr(privacy, 'is_private', lambda path, **kw: True)
    assert backend.describe_records_privacy() is None
    monkeypatch.setattr(privacy, 'is_private', lambda path, **kw: None)
    assert backend.describe_records_privacy() is None, 'unknown is not an alarm'
