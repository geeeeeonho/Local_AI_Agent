"""Records an administrator can delete but not read.

DPAPI itself only exists on Windows, so these tests use a stand-in with the
same contract - only the key that protected a blob opens it, and a changed
blob fails - and hold every format to it: whole documents, logs written a
line at a time, and folders sealed between sessions.
"""
import hashlib
import hmac
import os
from pathlib import Path

import pytest

from core import vault


class Key:
    """Same contract as DPAPI: integrity-checked, bound to one key."""

    name = 'fake'

    def __init__(self, secret=b'account-a'):
        self.secret = secret
        self.calls = 0

    def _xor(self, nonce, data):
        stream = hashlib.shake_256(self.secret + nonce).digest(len(data))
        mixed = int.from_bytes(data, 'big') ^ int.from_bytes(stream, 'big')
        return mixed.to_bytes(len(data), 'big')

    def protect(self, data):
        self.calls += 1
        nonce = os.urandom(16)
        body = self._xor(nonce, data)
        tag = hmac.new(self.secret, nonce + body, 'sha256').digest()
        return nonce + tag + body

    def unprotect(self, blob):
        nonce, tag, body = blob[:16], blob[16:48], blob[48:]
        if not hmac.compare_digest(tag, hmac.new(self.secret, nonce + body, 'sha256').digest()):
            raise OSError(13, 'wrong account or modified data')
        return self._xor(nonce, body)


@pytest.fixture
def key():
    with vault.using(Key()) as k:
        yield k


@pytest.fixture
def account(tmp_path, monkeypatch):
    root = tmp_path / 'users' / 'Tester'
    root.mkdir(parents=True)
    monkeypatch.setattr('project_paths.account_dir', lambda: root)
    return root


# ── which files are protected ────────────────────────────────────────────

def test_only_this_accounts_folder_is_encrypted(key, account, tmp_path):
    """The shared model registry must stay readable by every account."""
    private = account / 'user_data' / 'projects' / 'registry.json'
    shared = tmp_path / 'models' / '.localai' / 'registry.json'
    vault.write_text_atomic(private, '{"a": 1}')
    vault.write_text_atomic(shared, '{"a": 1}')
    assert private.read_bytes().startswith(vault.MAGIC_FILE)
    assert b'"a"' not in private.read_bytes()
    assert shared.read_text(encoding='utf-8') == '{"a": 1}'
    assert vault.read_text(private) == '{"a": 1}'


def test_without_a_protector_records_stay_plaintext(account):
    with vault.using(None):
        path = account / 'settings.json'
        vault.write_text_atomic(path, '{}')
        assert path.read_text(encoding='utf-8') == '{}'


def test_plaintext_written_before_protection_is_still_read(key, account):
    path = account / 'old.json'
    path.write_text('{"legacy": true}', encoding='utf-8')
    assert vault.read_text(path) == '{"legacy": true}'


def test_another_accounts_key_cannot_read_it(account):
    path = account / 'secret.json'
    with vault.using(Key(b'account-a')):
        vault.write_text_atomic(path, '{"chat": "private"}')
    with vault.using(Key(b'administrator')):
        with pytest.raises(vault.VaultError):
            vault.read_text(path)


def test_a_modified_record_fails_instead_of_reading_wrong(key, account):
    path = account / 'secret.json'
    vault.write_text_atomic(path, '{"chat": "private"}')
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(vault.VaultError):
        vault.read_text(path)


def test_existing_plaintext_is_converted_once(key, account):
    doc = account / 'registry.json'
    doc.write_text('{"x": 1}', encoding='utf-8')
    assert vault.protect_file_in_place(doc) is True
    assert vault.protect_file_in_place(doc) is False
    assert vault.read_text(doc) == '{"x": 1}'


# ── logs, a line at a time ───────────────────────────────────────────────

def test_a_log_is_written_encrypted_line_by_line(key, account):
    path = account / 'logs' / 'launcher.log'
    path.parent.mkdir()
    stream = vault.open_log(path, 'w')
    stream.write('first line\nsecond ')
    stream.write('line\n')
    stream.flush()
    on_disk = path.read_text(encoding='utf-8')
    assert 'first line' not in on_disk and on_disk.count(vault.LINE_PREFIX) == 2
    stream.write('unfinished')
    stream.close()
    assert list(vault.iter_lines(path)) == ['first line\n', 'second line\n', 'unfinished\n']
    assert stream.name == str(path)


def test_a_log_outside_the_account_is_ordinary_text(key, tmp_path, account):
    path = tmp_path / 'shared.log'
    stream = vault.open_log(path, 'w')
    stream.write('visible\n')
    stream.close()
    assert path.read_text(encoding='utf-8') == 'visible\n'


def test_mixed_old_and_new_lines_read_in_order(key, account):
    path = account / 'trace.jsonl'
    path.write_text('{"old": 1}\n', encoding='utf-8')
    with vault.open_log(path, 'a') as stream:
        stream.write('{"new": 2}\n')
    assert list(vault.iter_lines(path)) == ['{"old": 1}\n', '{"new": 2}\n']
    assert vault.protect_lines_in_place(path) is True
    assert 'old' not in path.read_text(encoding='utf-8')
    assert list(vault.iter_lines(path)) == ['{"old": 1}\n', '{"new": 2}\n']


def test_an_unreadable_line_is_reported_not_fatal(account):
    path = account / 'trace.jsonl'
    with vault.using(Key(b'a')):
        with vault.open_log(path, 'w') as stream:
            stream.write('mine\n')
    with vault.using(Key(b'b')):
        lines = list(vault.iter_lines(path))
    assert len(lines) == 1 and '읽을 수 없는 줄' in lines[0]


# ── sealed trees ─────────────────────────────────────────────────────────

def make_store(root):
    (root / 'documents').mkdir(parents=True)
    (root / 'documents' / 'report.pdf.json').write_text('my medical report', encoding='utf-8')
    (root / 'anythingllm.db').write_bytes(os.urandom(3 * 1024 * 1024 + 17))
    (root / '.env').write_text('OLLAMA_MODEL_PREF=gemma', encoding='utf-8')
    (root / 'models').mkdir()
    (root / 'models' / 'embedder.onnx').write_bytes(b'public weights')


def snapshot(root, exclude=()):
    result = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = Path(folder) / name
            rel = path.relative_to(root).as_posix()
            if rel.split('/')[0] in exclude:
                continue
            result[rel] = path.read_bytes()
    return result


def test_a_store_is_sealed_and_restored_byte_for_byte(key, account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    before = snapshot(root)
    store = vault.Store('chat', root, exclude=('models',))
    assert store.seal_if_idle() is True
    assert store.sealed()
    # Names are hidden too: a document title is itself private.
    assert sorted(p.name for p in root.iterdir()) == ['models']
    assert b'medical' not in store.archive.read_bytes()
    hold = store.open()
    assert snapshot(root) == before
    assert not store.sealed()
    assert store.close(hold) is True
    assert store.sealed()


def test_nothing_is_deleted_when_the_archive_cannot_be_written(key, account, monkeypatch):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    before = snapshot(root)

    def broken(*args, **kwargs):
        raise vault.VaultError('read back differs')

    monkeypatch.setattr(vault, 'verify_archive', broken)
    said = []
    assert vault.seal_tree(root, root.with_name('x.vault'), log=said.append) is False
    assert snapshot(root) == before
    assert not root.with_name('x.vault').exists()
    assert not root.with_name('x.vault.tmp').exists()
    assert said and '평문을 그대로' in said[0]


def test_a_store_in_use_by_another_process_is_not_sealed(key, account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    store = vault.Store('chat', root)
    hold = store.open()
    assert store.seal_if_idle() is False, 'this process is still using it'
    hold.release()
    assert store.seal_if_idle() is True


def test_a_stale_hold_from_a_crashed_process_does_not_block_sealing(key, account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    stale = root.with_name('.anythingllm.inuse-999999')
    stale.write_bytes(b'\0')
    assert vault.in_use(root) is False
    assert not stale.exists()


def test_holds_are_counted_within_one_process(key, account):
    root = account / 'user_data' / 'anythingllm'
    root.mkdir(parents=True)
    first, second = vault.Hold(root), vault.Hold(root)
    first.release()
    assert vault.in_use(root)
    second.release()
    assert not vault.in_use(root)


def test_the_archive_wins_over_leftover_plaintext(key, account):
    """Plaintext beside an archive is a leftover or an empty folder made early."""
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    before = snapshot(root)
    store = vault.Store('chat', root, exclude=('models',))
    store.seal_if_idle()
    (root / '.env').write_text('written before the restore', encoding='utf-8')
    store.close(store.open())
    store.open().release()
    assert snapshot(root) == before


def test_a_damaged_archive_is_refused_and_kept(key, account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    store = vault.Store('chat', root, exclude=('models',))
    store.seal_if_idle()
    raw = bytearray(store.archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    store.archive.write_bytes(bytes(raw))
    with pytest.raises(vault.VaultError):
        store.open()
    assert store.archive.exists(), 'never delete the only copy'
    assert not vault.in_use(root), 'a failed open releases its hold'


def test_a_truncated_archive_is_refused(key, account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    store = vault.Store('chat', root, exclude=('models',))
    store.seal_if_idle()
    raw = store.archive.read_bytes()
    store.archive.write_bytes(raw[:len(raw) - 40])
    with pytest.raises(vault.VaultError):
        vault.verify_archive(store.archive)


def test_another_account_cannot_open_a_sealed_store(account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    with vault.using(Key(b'a')):
        vault.Store('chat', root, exclude=('models',)).seal_if_idle()
    with vault.using(Key(b'b')):
        with pytest.raises(vault.VaultError):
            vault.Store('chat', root, exclude=('models',)).open()


def test_a_sealed_store_without_a_protector_is_not_silently_replaced(account):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    with vault.using(Key()):
        vault.Store('chat', root, exclude=('models',)).seal_if_idle()
    with vault.using(None):
        with pytest.raises(vault.VaultError):
            vault.Store('chat', root, exclude=('models',)).open()


def test_short_of_disk_space_the_plaintext_stays(key, account, monkeypatch):
    root = account / 'user_data' / 'anythingllm'
    make_store(root)
    monkeypatch.setattr(vault.shutil, 'disk_usage',
                        lambda path: type('U', (), {'free': 1024})())
    said = []
    assert vault.seal_tree(root, root.with_name('a.vault'), log=said.append) is False
    assert (root / 'anythingllm.db').exists()
    assert said and '여유 공간' in said[0]


def test_an_empty_store_needs_no_archive(key, account):
    root = account / 'user_data' / 'anythingllm'
    (root / 'models').mkdir(parents=True)
    store = vault.Store('chat', root, exclude=('models',))
    assert store.seal_if_idle() is True
    assert not store.sealed()


# ── a key this account no longer has ─────────────────────────────────────

def test_a_document_this_key_cannot_open_is_kept_aside_and_the_app_starts(account):
    """An administrator reset the password: the record is gone, the app is not."""
    from core.persistence import JsonStore
    path = account / 'user_data' / 'settings' / 'localai.json'
    with vault.using(Key(b'before reset')):
        JsonStore(path).update(lambda data: {'schema_version': 1, 'theme': 'dark'})
    with vault.using(Key(b'after reset')):
        assert JsonStore(path).read() == {}
        kept = list(path.parent.glob('localai.json.undecryptable-*'))
        assert len(kept) == 1 and not path.exists()
        JsonStore(path).update(lambda data: {'schema_version': 1, 'theme': 'light'})
        assert JsonStore(path).read()['theme'] == 'light'


def test_a_sealed_store_this_key_cannot_open_is_kept_aside(account):
    from services.records import SessionStores
    data = account / 'user_data'
    make_store(data / 'anythingllm')
    with vault.using(Key(b'before reset')):
        SessionStores(data).close('chat')
    said = []
    events = type('E', (), {'emit': lambda self, topic, payload: said.append(payload['message'])})()
    with vault.using(Key(b'after reset')):
        stores = SessionStores(data, events)
        stores.open('chat')
        assert list(data.glob('anythingllm.vault.undecryptable-*'))
        assert any('풀 수 없는' in line for line in said)
        stores.close('chat')


def test_without_a_protector_a_sealed_store_is_refused_not_set_aside(account):
    from services.records import SessionStores
    data = account / 'user_data'
    make_store(data / 'anythingllm')
    with vault.using(Key()):
        SessionStores(data).close('chat')
    with vault.using(None):
        with pytest.raises(vault.VaultError):
            SessionStores(data).open('chat')
    assert (data / 'anythingllm.vault').is_file(), 'still openable with the real key'
