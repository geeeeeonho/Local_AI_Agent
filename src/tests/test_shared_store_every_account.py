"""C:\\Ollama\\models only serves the whole machine if the machine says so.

Putting the store outside a profile is half of it. Another account's Ollama
reads OLLAMA_MODELS from its own environment; with no machine-scope value it
falls back to that account's %USERPROFILE%\\.ollama\\models and re-downloads
the library. Publishing that value needs administrator rights, so setup can
simply have failed - and the program used to report "모든 계정 공용" from the
shape of the path alone, telling those users something false.
"""
import types
from pathlib import Path

import pytest

from core.models import sharing as policy
from core.models.sharing import Sharing

STORE = r'C:\Ollama\models'


def state(**kw):
    base = dict(path=STORE, intended_shared=True, machine_value=STORE,
                user_value='', readable_by_users=True, windows=True)
    base.update(kw)
    return Sharing(**base)


# ── what the facts mean ──────────────────────────────────────────────────

def test_a_fully_set_up_machine_shares_the_store():
    assert state().every_account is True
    assert state().blockers == ()


def test_setup_without_admin_is_not_reported_as_shared():
    """setx /M failed, so every other account looks in its own profile."""
    found = state(machine_value='')
    assert found.every_account is False
    assert found.blockers == (policy.VARIABLE_MISSING,)
    assert found.repairable is True


def test_a_machine_value_naming_another_store_is_a_blocker():
    found = state(machine_value=r'D:\somewhere\else')
    assert found.blockers == (policy.VARIABLE_ELSEWHERE,)


def test_a_user_scope_value_hides_the_machine_one():
    """That is this account's own setting, so the program must not overwrite it."""
    found = state(user_value=r'E:\my\models')
    assert found.blockers == (policy.USER_OVERRIDE,)
    assert found.repairable is False, 'a personal setting is not ours to delete'


def test_a_store_inside_a_profile_is_never_machine_wide():
    found = state(path=r'C:\Users\a\.ollama\models', intended_shared=False,
                  per_user_path=True, machine_value=r'C:\Users\a\.ollama\models')
    assert policy.PER_USER_PATH in found.blockers
    assert found.every_account is False


def test_unreadable_files_block_it_even_with_the_variable_set():
    assert state(readable_by_users=False).blockers == (policy.NOT_READABLE,)


def test_a_fact_we_could_not_read_is_unknown_not_success():
    """A wrong "yes" costs a second account the whole library again."""
    assert state(machine_value=None).every_account is None
    assert state(readable_by_users=None).every_account is None


def test_trailing_quotes_and_slashes_are_not_a_disagreement():
    """Windows dialogs and batch files hand back quoted, trailing-slash paths."""
    assert state(machine_value='"' + STORE + '\\"').blockers == ()


@pytest.mark.parametrize('value', [STORE.lower(), STORE.upper(),
                                   'C:\\Ollama\\.\\models', 'C:/Ollama/models',
                                   STORE + '\\'])
def test_the_same_path_written_differently_still_matches(value):
    """Windows rules, checked on whatever platform the tests run on."""
    assert state(machine_value=value).blockers == ()


def test_off_windows_the_question_does_not_arise():
    found = Sharing(path='/srv/models', intended_shared=True, windows=False)
    assert found.every_account is True and found.blockers == ()


# ── reading and repairing the real machine ───────────────────────────────

class FakeWinreg:
    """Just enough registry to exercise the Windows-only read off Windows."""
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = 1, 2

    REG_SZ, REG_EXPAND_SZ = 1, 2

    def __init__(self, machine=None, user=None):
        self.values = {self.HKEY_LOCAL_MACHINE: machine, self.HKEY_CURRENT_USER: user}
        self.kinds = {}

    def OpenKey(self, root, key):
        store = self
        class Handle:
            def __enter__(self): return root
            def __exit__(self, *exc): return False
        if self.values.get(root) is None:
            raise FileNotFoundError(key)
        return Handle()

    def QueryValueEx(self, root, name):
        return self.values[root], self.kinds.get(root, self.REG_SZ)


# What `icacls <dir> /save` writes: the name, then the DACL in SDDL. Our own
# repair produces the second line; BU is BUILTIN\Users in every language.
GRANTED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
NOT_GRANTED = 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)'


def install_fake_windows(monkeypatch, store, *, machine=None, user=None,
                         sddl=GRANTED, returncode=0):
    """A machine whose shared store is ``store``, with a stub registry and ACL."""
    import sys
    from core import ollama_paths
    from integrations.ollama import sharing
    # This tmp directory stands in for C:\Ollama\models, so the reads under
    # test are about the machine's settings rather than the path's shape.
    monkeypatch.setattr(ollama_paths, 'SHARED_MODELS_DIR', store)
    monkeypatch.setitem(sys.modules, 'winreg', FakeWinreg(machine, user))
    ran = []

    def fake_run(command, **kw):
        ran.append(command)
        if returncode == 0 and '/save' in command and sddl is not None:
            # icacls writes UTF-16; the reader has to decode it as such.
            target = Path(command[command.index('/save') + 1])
            target.write_text('models\n' + sddl + '\n', encoding='utf-16')
        return types.SimpleNamespace(returncode=returncode, stdout='', stderr='')
    monkeypatch.setattr(sharing.subprocess, 'run', fake_run)
    return ran


def test_a_machine_set_up_by_an_admin_reads_as_shared(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=str(store))
    found = sharing.read(store, windows=True)
    assert found.machine_value == str(store)
    assert found.readable_by_users is True
    assert found.blockers == ()


def test_a_machine_set_up_without_admin_names_the_missing_variable(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=None)
    found = sharing.read(store, windows=True)
    assert found.machine_value == '', 'unset, not unreadable'
    assert found.blockers == (policy.VARIABLE_MISSING,)
    assert sharing.describe(found) and '관리자' in sharing.describe(found)[0]


def test_repair_grants_read_and_publishes_the_variable(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    ran = install_fake_windows(monkeypatch, store, machine=str(store))
    result = sharing.repair(store, windows=True)
    commands = [c[0] for c in ran]
    assert 'icacls' in commands and 'setx' in commands
    grant = next(c for c in ran if c[0] == 'icacls' and '/grant' in c)
    assert '*S-1-5-32-545:(OI)(CI)(RX)' in grant, 'read and execute only'
    assert '/T' in grant
    publish = next(c for c in ran if c[0] == 'setx')
    assert publish == ['setx', 'OLLAMA_MODELS', str(store), '/M']
    assert result['failed'] == ()


def test_models_pulled_later_are_covered_by_the_grant(monkeypatch, tmp_path):
    """(OI)(CI) is inheritable, so tomorrow's blobs are readable too."""
    from integrations.ollama import sharing
    ran = install_fake_windows(monkeypatch, tmp_path, machine=str(tmp_path))
    sharing.ensure_readable(tmp_path, windows=True)
    grant = ran[0]
    assert '(OI)(CI)(RX)' in ' '.join(grant), grant
    assert not any('(F)' in part or ':(M)' in part for part in grant), \
        'other accounts read the models; they do not get to replace them'


def test_a_failed_repair_says_so_rather_than_claiming_success(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    install_fake_windows(monkeypatch, tmp_path, machine=None, returncode=1)
    result = sharing.repair(tmp_path, windows=True)
    assert set(result['failed']) == {'readable', 'machine_variable'}
    assert result['every_account'] is not True


def test_the_environment_this_process_injected_is_not_mistaken_for_the_machine(monkeypatch, tmp_path):
    """We set OLLAMA_MODELS for our own child Ollama; that is not a machine setting."""
    from integrations.ollama import sharing
    monkeypatch.setenv('OLLAMA_MODELS', str(tmp_path))
    install_fake_windows(monkeypatch, tmp_path, machine=None)
    assert sharing.read(tmp_path, windows=True).machine_value == ''


# ── and the screen says what is true ─────────────────────────────────────

def test_the_screen_stops_claiming_shared_when_it_is_not(monkeypatch, tmp_path):
    from services.models.service import ModelService
    from integrations.ollama import sharing
    service = ModelService(types.SimpleNamespace(model_dir=tmp_path, client=object()))
    monkeypatch.setattr(sharing, 'read',
                        lambda path, **k: state(machine_value=''))
    report = service.sharing()
    assert report['every_account'] is False and report['repairable'] is True
    assert report['blockers'] == [policy.VARIABLE_MISSING]
    assert report['reasons'], 'a blocker the user cannot read is not a warning'


# ── reading an ACL without depending on the display language ─────────────
# icacls prints account names in the language Windows is installed in, so on
# a Korean install the store's ACL lists BUILTIN\사용자. Matching the English
# name reported every Korean machine as unreadable - permanently, including
# right after a repair that had worked.

@pytest.mark.parametrize('sddl,expected', [
    (GRANTED, True),
    ('D:AI(A;OICI;0x1200a9;;;S-1-5-32-545)', True),   # raw SID
    ('D:AI(A;OICIID;FR;;;BU)', True),                 # inherited read
    ('D:AI(A;OICI;FA;;;BU)', True),                   # full control
    ('D:AI(D;OICI;FA;;;BU)(A;OICI;0x1200a9;;;BU)', False),  # deny wins
    ('D:AI(A;OICI;FX;;;BU)', False),                  # execute is not read
    (NOT_GRANTED, False),
    ('not an sddl at all', None),
    ('', None),
])
def test_the_acl_is_read_from_sddl_not_a_localized_name(sddl, expected):
    assert policy.readable_from_sddl(sddl) is expected


def test_a_korean_windows_reads_the_same_as_an_english_one(monkeypatch, tmp_path):
    """The localized display name never reaches the parser now."""
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=str(store), sddl=GRANTED)
    assert sharing.read(store, windows=True).readable_by_users is True


def test_an_explicit_deny_is_not_read_as_permission(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=str(store),
                         sddl='D:AI(D;OICI;FA;;;BU)(A;OICI;FA;;;BA)')
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is False
    assert policy.NOT_READABLE in found.blockers


def test_an_acl_that_cannot_be_read_is_unknown(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=str(store), returncode=1)
    found = sharing.read(store, windows=True)
    assert found.readable_by_users is None
    assert found.every_account is None
    assert found.repairable is True, 'unknown must still offer the idempotent fix'


def test_the_save_file_is_never_left_behind(monkeypatch, tmp_path):
    """icacls refuses to overwrite one, so a leftover would break every later read."""
    import glob
    import tempfile
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    install_fake_windows(monkeypatch, store, machine=str(store))
    sharing.read(store, windows=True)
    sharing.read(store, windows=True)
    assert glob.glob(str(Path(tempfile.gettempdir()) / 'localai-acl-*')) == []


# ── a registry value written with %SystemDrive% is the same store ────────

def test_an_expandable_registry_value_is_expanded_before_comparing(monkeypatch, tmp_path):
    from integrations.ollama import sharing
    store = tmp_path / 'models'
    store.mkdir()
    fake = FakeWinreg(r'%LOCALAI_TEST_ROOT%\models', '')
    fake.REG_EXPAND_SZ = 2
    fake.kinds = {fake.HKEY_LOCAL_MACHINE: 2, fake.HKEY_CURRENT_USER: 1}
    monkeypatch.setenv('LOCALAI_TEST_ROOT', str(tmp_path))
    install_fake_windows(monkeypatch, store, machine=str(store))
    import sys
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    found = sharing.read(store, windows=True)
    assert '%' not in found.machine_value, 'the variable was expanded'
    # Separators differ because the stored value is Windows-shaped; the policy
    # compares by Windows rules, so this is the same store.
    assert found.blockers == ()
    assert found.every_account is True
