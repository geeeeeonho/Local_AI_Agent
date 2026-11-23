"""Machine-wide model-store sharing is a path + ACL contract.

Every allowed account reads the shared store; only LocalAI administrators
change it. A store ordinary accounts can modify is a tampering risk, not
"better sharing".
"""
import types
from pathlib import Path

import pytest

from core.models import sharing as policy
from core.models.sharing import Sharing

STORE = r'C:\LocalAI\models'


def state(**kw):
    base = dict(
        path=STORE,
        intended_shared=True,
        readable_by_users=True,
        manageable_by_users=False,
        windows=True,
    )
    base.update(kw)
    return Sharing(**base)


def test_a_fully_set_up_machine_shares_the_store():
    assert state().every_account is True
    assert state().blockers == ()


def test_a_store_inside_a_profile_is_never_machine_wide():
    found = state(
        path=r'C:\Users\a\.ollama\models',
        intended_shared=False,
        per_user_path=True,
    )
    assert found.blockers == (policy.PER_USER_PATH,)
    assert found.every_account is False


def test_a_noncanonical_custom_store_is_not_machine_wide():
    found = state(path=r'D:\models', intended_shared=False)
    assert found.blockers == (policy.NOT_SHARED_PATH,)
    assert found.every_account is False


def test_unreadable_files_block_sharing():
    assert state(readable_by_users=False).blockers == (policy.NOT_READABLE,)


def test_a_store_ordinary_accounts_can_modify_is_a_finding():
    found = state(manageable_by_users=True)
    assert found.blockers == (policy.USERS_CAN_MODIFY,)
    assert found.every_account is False
    assert found.repairable is True


def test_unknown_acl_state_is_unknown_and_repairable():
    found = state(readable_by_users=None, manageable_by_users=None)
    assert found.every_account is None
    assert found.repairable is True


def test_off_windows_acl_question_does_not_arise():
    found = Sharing(path='/srv/models', intended_shared=True, windows=False)
    assert found.every_account is True
    assert found.blockers == ()


GRANTED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICI;0x1301bf;;;BU)'
READ_ONLY = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
NOT_GRANTED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)'


def install_fake_windows(monkeypatch, store, *, sddl=READ_ONLY, returncode=0):
    import sys
    from core import ollama_paths
    from integrations.windows import acl

    monkeypatch.setattr(ollama_paths, 'SHARED_MODELS_DIR', store)
    ran = []

    def fake_run(command, **kw):
        ran.append(command)
        if returncode == 0 and '/save' in command and sddl is not None:
            target = Path(command[command.index('/save') + 1])
            target.write_text('models\n' + sddl + '\n', encoding='utf-16')
        return types.SimpleNamespace(returncode=returncode, stdout='', stderr='')

    monkeypatch.setattr(acl.subprocess, 'run', fake_run)
    return ran


def test_read_only_store_acl_reads_as_shared(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store)
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is True
    assert found.manageable_by_users is False
    assert found.blockers == ()
    assert found.every_account is True


def test_old_modify_grant_is_detected_as_tampering_risk(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, sddl=GRANTED)
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is True
    assert found.manageable_by_users is True
    assert found.blockers == (policy.USERS_CAN_MODIFY,)
    assert found.repairable is True
    assert any('변조' in line for line in sharing.describe(found))


def test_repair_removes_modify_and_leaves_read_only(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    ran = install_fake_windows(monkeypatch, store)
    result = sharing.repair(store, windows=True)
    icacls = [cmd for cmd in ran if cmd[0] == 'icacls' and '/save' not in cmd]
    remove = next(cmd for cmd in icacls if '/remove:g' in cmd)
    assert remove[3] == '*S-1-5-32-545' and '/T' in remove
    grant = next(cmd for cmd in icacls if '/grant' in cmd)
    assert '*S-1-5-32-545:(OI)(CI)(RX)' in grant
    assert '*S-1-3-4:(OI)(CI)(RX)' in grant, "a blob's owner cannot re-grant itself write"
    assert not any('(M)' in part or ':F' in part or '(F)' in part
                   for cmd in icacls for part in cmd)
    assert icacls.index(remove) < icacls.index(grant)
    assert not any(cmd[0] == 'setx' for cmd in ran)
    assert result['failed'] == ()


def test_failed_repair_never_claims_success(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    install_fake_windows(monkeypatch, tmp_path, returncode=1)
    result = sharing.repair(tmp_path, windows=True)
    assert result['failed'] == ('read_only',)
    assert result['every_account'] is not True


def test_model_service_reports_only_the_localai_sharing_contract(monkeypatch, tmp_path):
    from services.models.service import ModelService
    from integrations.ollama import sharing
    from integrations import model_access
    service = ModelService(types.SimpleNamespace(model_dir=tmp_path, client=object()))
    monkeypatch.setattr(sharing, 'read', lambda path, **k: state())
    monkeypatch.setattr(model_access, 'management_access',
                        lambda path, **k: {'allowed': False, 'admin': False, 'reason': 'no'})
    report = service.sharing()
    assert report['every_account'] is True
    assert report['readable_by_users'] is True
    assert report['manageable_by_users'] is False
    assert report['blockers'] == []
    assert report['reasons'] == []
    assert report['can_manage'] is False and report['manage_reason'] == 'no'
    assert report['repairable'] is False, 'only an administrator is offered the repair'


@pytest.mark.parametrize('sddl,expected', [
    (GRANTED, True),
    ('D:AI(A;OICI;0x1200a9;;;S-1-5-32-545)', True),
    ('D:AI(A;OICIID;FR;;;BU)', True),
    ('D:AI(A;OICI;FA;;;BU)', True),
    ('D:AI(D;OICI;FA;;;BU)(A;OICI;0x1200a9;;;BU)', False),
    ('D:AI(A;OICI;FX;;;BU)', False),
    (NOT_GRANTED, False),
    ('not an sddl at all', None),
    ('', None),
])
def test_read_access_is_language_independent(sddl, expected):
    assert policy.readable_from_sddl(sddl) is expected


@pytest.mark.parametrize('sddl,expected', [
    (GRANTED, True),
    (READ_ONLY, False),
    ('D:AI(A;OICI;FA;;;BU)', True),
    ('D:AI(A;OICI;FW;;;BU)', False),
    ('D:AI(D;OICI;FA;;;BU)(A;OICI;0x1301bf;;;BU)', False),
    (NOT_GRANTED, False),
    ('not an sddl at all', None),
])
def test_modify_access_is_language_independent(sddl, expected):
    assert policy.manageable_from_sddl(sddl) is expected


def test_explicit_deny_is_not_read_as_permission(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(
        monkeypatch, store,
        sddl='D:AI(D;OICI;FA;;;BU)(A;OICI;FA;;;BA)',
    )
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is False
    assert policy.NOT_READABLE in found.blockers


def test_unreadable_acl_is_unknown_but_offers_repair(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, returncode=1)
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is None
    assert found.every_account is None
    assert found.repairable is True


def test_acl_save_file_is_never_left_behind(monkeypatch, tmp_path):
    import glob
    import tempfile
    from integrations.ollama import sharing

    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store)
    sharing.read(store, windows=True)
    sharing.read(store, windows=True)
    assert glob.glob(str(Path(tempfile.gettempdir()) / 'localai-acl-*')) == []
