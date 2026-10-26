"""This account's records, unreadable to every other account - administrators too.

The ACL already keeps the machine's other standard accounts out of
``users\\<account>``. It cannot keep out an administrator: one can take
ownership of any folder. What an administrator cannot do is decrypt data that
Windows encrypted with *this* account's key (DPAPI), so the records LocalAI
keeps are stored that way. Administrators keep full ACL access on purpose:
they can still delete an account's records - they just cannot read them.

Three shapes of data, three formats, one key:

``protected file``
    A small document (settings, the project list) replaced whole on every
    write: ``MAGIC_FILE`` followed by one protected blob.

``protected lines``
    A log or trace that grows a line at a time: every line is written as
    ``LINE_PREFIX`` + base64 of its own protected blob, so a crash loses at
    most the line being written and the file never needs rewriting.

``sealed tree``
    A folder another program writes in plaintext while it runs - AnythingLLM's
    chat store, the agent's sessions. Between sessions it is packed into one
    archive of protected frames and the plaintext is removed. The archive is
    read back and checked before anything is deleted.

Plaintext written before this existed is still read, so turning protection on
loses nothing. Formats never depend on Windows; the key does. Off Windows - a
development checkout - there is no protector and files stay plaintext.

``core`` decides formats; ``integrations.windows.dpapi`` touches the machine.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import os
import shutil
import struct
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator, Optional

MAGIC_FILE = b'LOCALAI-VAULT1\n'
MAGIC_ARCHIVE = b'LOCALAI-VAULTA1\n'
LINE_PREFIX = '#LAV1 '

#: Plaintext per archive frame. Large enough that DPAPI's per-call cost does
#: not matter, small enough that memory stays flat on a gigabyte store.
FRAME_BYTES = 1024 * 1024
_FRAME_HEADER = struct.Struct('>16sQB')
_FINAL = 1

#: Opt-out for diagnosis and automation; records are then written plaintext.
DISABLE_VARIABLE = 'LOCAL_AI_VAULT'


class VaultError(RuntimeError):
    """A protected record could not be read or written."""


# ── the key ──────────────────────────────────────────────────────────────

_override = None
_overridden = False


def protector():
    """The account-bound protector, or None where records stay plaintext."""
    if _overridden:
        return _override
    if os.environ.get(DISABLE_VARIABLE, '').strip().lower() in ('0', 'off', 'false', 'no'):
        return None
    if os.name != 'nt':
        return None
    try:
        from integrations.windows import dpapi
    except ImportError:
        return None
    return dpapi.Protector() if dpapi.available() else None


@contextlib.contextmanager
def using(replacement):
    """Use ``replacement`` as the protector inside this block (tests, tools)."""
    global _override, _overridden
    previous = (_override, _overridden)
    _override, _overridden = replacement, True
    try:
        yield replacement
    finally:
        _override, _overridden = previous


def enabled() -> bool:
    return protector() is not None


def _account_root() -> Optional[Path]:
    try:
        import project_paths
        return Path(project_paths.account_dir()).resolve()
    except Exception:
        return None


def is_private_path(path) -> bool:
    """Is ``path`` inside this account's own folder?

    Only there. A shared file - the model registry, the machine-wide lock -
    must stay readable by the other accounts, and DPAPI would make it this
    account's alone.
    """
    root = _account_root()
    if root is None:
        return False
    try:
        target = Path(path).resolve()
    except OSError:
        target = Path(os.path.abspath(path))
    return target == root or root in target.parents


def should_protect(path) -> bool:
    return enabled() and is_private_path(path)


# ── protected files ──────────────────────────────────────────────────────

def is_protected_bytes(raw: bytes) -> bool:
    return raw.startswith(MAGIC_FILE)


def seal_bytes(payload: bytes, *, using_protector=None) -> bytes:
    shield = using_protector or protector()
    if shield is None:
        raise VaultError('no protector on this machine')
    return MAGIC_FILE + shield.protect(bytes(payload))


def open_bytes(raw: bytes, *, using_protector=None) -> bytes:
    """Plaintext for ``raw``, whether it was protected or not."""
    if not is_protected_bytes(raw):
        return raw
    shield = using_protector or protector()
    if shield is None:
        raise VaultError('this record is encrypted for a Windows account and '
                         'cannot be read here')
    try:
        return shield.unprotect(raw[len(MAGIC_FILE):])
    except Exception as exc:
        raise VaultError('this record cannot be decrypted by the signed-in '
                         'Windows account (%s)' % exc) from exc


def read_bytes(path, limit: Optional[int] = None) -> bytes:
    with Path(path).open('rb') as stream:
        raw = stream.read() if limit is None else stream.read(limit + 1)
    if limit is not None and len(raw) > limit:
        raise ValueError('LocalAI state exceeds size limit: %s' % path)
    return open_bytes(raw)


def read_text(path, encoding='utf-8') -> str:
    return read_bytes(path).decode(encoding)


def encode_for(path, payload: bytes) -> bytes:
    """What to write at ``path``: protected inside the account, else as is."""
    return seal_bytes(payload) if should_protect(path) else bytes(payload)


def write_bytes_atomic(path, payload: bytes) -> None:
    """Replace ``path`` whole; protected when it lies in this account's folder."""
    path = Path(path)
    data = encode_for(path, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp',
                                dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_text_atomic(path, text: str, encoding='utf-8') -> None:
    write_bytes_atomic(path, text.encode(encoding))


# ── protected lines ──────────────────────────────────────────────────────

def protect_line(text: str, *, using_protector=None) -> str:
    shield = using_protector or protector()
    blob = shield.protect(text.encode('utf-8'))
    return LINE_PREFIX + base64.b64encode(blob).decode('ascii') + '\n'


def open_line(line: str, *, using_protector=None) -> str:
    """One stored line back to text; plaintext lines pass through."""
    if not line.startswith(LINE_PREFIX):
        return line
    shield = using_protector or protector()
    if shield is None:
        raise VaultError('encrypted log line cannot be read on this machine')
    try:
        blob = base64.b64decode(line[len(LINE_PREFIX):].strip(), validate=True)
        return shield.unprotect(blob).decode('utf-8')
    except Exception as exc:
        raise VaultError('log line cannot be decrypted (%s)' % exc) from exc


def iter_lines(path) -> Iterator[str]:
    """Every line of a log or trace as text, decrypting protected ones."""
    with Path(path).open('r', encoding='utf-8', errors='replace') as stream:
        for line in stream:
            if line.startswith(LINE_PREFIX):
                try:
                    text = open_line(line)
                except VaultError as exc:
                    yield '[읽을 수 없는 줄: %s]\n' % exc
                    continue
                yield text if text.endswith('\n') else text + '\n'
            else:
                yield line


class ProtectedTextWriter(io.TextIOBase):
    """A text stream that stores each completed line encrypted.

    Drop-in for ``open(path, 'w'|'a', encoding='utf-8', buffering=1)`` in the
    places that write logs: ``write``, ``flush``, ``fileno``, ``close`` and
    ``name`` behave the same, and a line reaches the disk as soon as its
    newline is written.
    """

    def __init__(self, path, mode='a', *, using_protector=None):
        if mode not in ('a', 'w'):
            raise ValueError('mode must be "a" or "w"')
        self._shield = using_protector or protector()
        if self._shield is None:
            raise VaultError('no protector on this machine')
        self._raw = open(path, mode, encoding='utf-8', newline='\n')
        self._pending = ''
        self.name = str(path)

    def writable(self):
        return True

    def write(self, text):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        self._pending += str(text)
        while '\n' in self._pending:
            line, self._pending = self._pending.split('\n', 1)
            self._raw.write(protect_line(line, using_protector=self._shield))
        self._raw.flush()
        return len(text)

    def flush(self):
        if not self.closed:
            self._raw.flush()

    def fileno(self):
        return self._raw.fileno()

    def close(self):
        if self.closed:
            return
        try:
            if self._pending:
                self._raw.write(protect_line(self._pending, using_protector=self._shield))
                self._pending = ''
            # IOBase.close() flushes through self.flush(), so the file under it
            # has to still be open at that point.
            super().close()
        finally:
            self._raw.close()


def open_log(path, mode='a'):
    """A line-buffered text stream for a log; encrypted inside the account."""
    if should_protect(path):
        return ProtectedTextWriter(path, mode)
    return open(path, mode, encoding='utf-8', buffering=1)


def protect_lines_in_place(path) -> bool:
    """Encrypt an existing plaintext log/trace. True when it was rewritten."""
    path = Path(path)
    shield = protector()
    if shield is None or not path.is_file():
        return False
    with path.open('r', encoding='utf-8', errors='replace') as stream:
        lines = stream.readlines()
    if all(line.startswith(LINE_PREFIX) for line in lines):
        return False
    out = ''.join(line if line.startswith(LINE_PREFIX)
                  else protect_line(line.rstrip('\n'), using_protector=shield)
                  for line in lines)
    write_bytes_raw(path, out.encode('utf-8'))
    return True


def protect_file_in_place(path) -> bool:
    """Encrypt an existing plaintext document. True when it was rewritten."""
    path = Path(path)
    shield = protector()
    if shield is None or not path.is_file():
        return False
    raw = path.read_bytes()
    if is_protected_bytes(raw):
        return False
    write_bytes_raw(path, seal_bytes(raw, using_protector=shield))
    return True


def write_bytes_raw(path, data: bytes) -> None:
    """Atomic replace with exactly ``data`` (already encoded)."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp',
                                dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


# ── sealed trees ─────────────────────────────────────────────────────────

class _FrameWriter(io.RawIOBase):
    """File-like sink for ``tarfile``: plaintext in, protected frames out."""

    def __init__(self, stream, shield, archive_id: bytes):
        self._stream, self._shield, self._id = stream, shield, archive_id
        self._buffer = bytearray()
        self._index = 0
        self.digest = hashlib.sha256()
        self.size = 0

    def writable(self):
        return True

    def write(self, data):
        data = bytes(data)
        self.digest.update(data)
        self.size += len(data)
        self._buffer += data
        while len(self._buffer) >= FRAME_BYTES:
            self._emit(bytes(self._buffer[:FRAME_BYTES]), final=False)
            del self._buffer[:FRAME_BYTES]
        return len(data)

    def _emit(self, chunk: bytes, *, final: bool):
        header = _FRAME_HEADER.pack(self._id, self._index, _FINAL if final else 0)
        blob = self._shield.protect(header + chunk)
        self._stream.write(struct.pack('>I', len(blob)))
        self._stream.write(blob)
        self._index += 1

    def finish(self):
        self._emit(bytes(self._buffer), final=True)
        self._buffer.clear()


class _FrameReader(io.RawIOBase):
    """File-like source for ``tarfile``: protected frames in, plaintext out."""

    def __init__(self, stream, shield):
        self._stream, self._shield = stream, shield
        magic = stream.read(len(MAGIC_ARCHIVE))
        if magic != MAGIC_ARCHIVE:
            raise VaultError('not a LocalAI sealed archive')
        self._id = None
        self._index = 0
        self._pending = b''
        self._done = False
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self):
        return True

    def _next(self) -> bool:
        if self._done:
            return False
        size_raw = self._stream.read(4)
        if len(size_raw) != 4:
            raise VaultError('sealed archive is truncated')
        (size,) = struct.unpack('>I', size_raw)
        blob = self._stream.read(size)
        if len(blob) != size:
            raise VaultError('sealed archive is truncated')
        try:
            plain = self._shield.unprotect(blob)
        except Exception as exc:
            raise VaultError('sealed archive cannot be decrypted (%s)' % exc) from exc
        if len(plain) < _FRAME_HEADER.size:
            raise VaultError('sealed archive frame is malformed')
        archive_id, index, flags = _FRAME_HEADER.unpack(plain[:_FRAME_HEADER.size])
        if self._id is None:
            self._id = archive_id
        if archive_id != self._id or index != self._index:
            raise VaultError('sealed archive frames are out of order')
        self._index += 1
        chunk = plain[_FRAME_HEADER.size:]
        self.digest.update(chunk)
        self.size += len(chunk)
        self._pending += chunk
        if flags & _FINAL:
            self._done = True
            if self._stream.read(1):
                raise VaultError('sealed archive has data after its end')
        return True

    def readinto(self, target):
        while not self._pending and self._next():
            pass
        if not self._pending:
            return 0
        count = min(len(target), len(self._pending))
        target[:count] = self._pending[:count]
        self._pending = self._pending[count:]
        return count

    def drain(self):
        while self._next():
            self._pending = b''
        self._pending = b''


def _entries(root: Path, exclude: Iterable[str]) -> list:
    skip = {name.lower() for name in exclude}
    try:
        return sorted(child for child in root.iterdir()
                      if child.name.lower() not in skip)
    except FileNotFoundError:
        return []


def _tree_size(paths) -> int:
    total = 0
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
        elif path.is_dir():
            for folder, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        total += (Path(folder) / name).stat().st_size
                    except OSError:
                        pass
    return total


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def verify_archive(archive, *, using_protector=None) -> tuple:
    """(sha256 hex, plaintext size) of a sealed archive; raises if damaged."""
    shield = using_protector or protector()
    with Path(archive).open('rb') as stream:
        reader = _FrameReader(stream, shield)
        reader.drain()
        if not reader._done:
            raise VaultError('sealed archive is incomplete')
        return reader.digest.hexdigest(), reader.size


def seal_tree(root, archive, *, exclude=(), using_protector=None, log=None) -> bool:
    """Pack ``root`` (minus ``exclude``) into ``archive`` and remove the plaintext.

    Returns True when the plaintext is now sealed (or there was nothing to
    seal). The archive is written beside its final name, read back in full and
    compared before it replaces anything, and only then is plaintext deleted.
    Any failure leaves the plaintext where it was.
    """
    say = log or (lambda message: None)
    shield = using_protector or protector()
    root, archive = Path(root), Path(archive)
    if shield is None:
        return False
    entries = _entries(root, exclude)
    if not entries:
        return True
    need = _tree_size(entries)
    try:
        free = shutil.disk_usage(archive.parent).free
    except OSError:
        free = None
    if free is not None and free < need * 1.1 + 64 * 1024 * 1024:
        say('여유 공간이 부족해 %s 을(를) 잠그지 못했습니다 (필요 %.1f GB).'
            % (root, need / 1024 ** 3))
        return False
    temporary = archive.with_name(archive.name + '.tmp')
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open('wb') as stream:
            stream.write(MAGIC_ARCHIVE)
            writer = _FrameWriter(stream, shield, os.urandom(16))
            with tarfile.open(fileobj=writer, mode='w|', format=tarfile.PAX_FORMAT) as tar:
                for entry in entries:
                    tar.add(str(entry), arcname=entry.name)
            writer.finish()
            stream.flush()
            os.fsync(stream.fileno())
        digest, size = verify_archive(temporary, using_protector=shield)
        if digest != writer.digest.hexdigest() or size != writer.size:
            raise VaultError('sealed archive did not read back identically')
        os.replace(temporary, archive)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        say('잠그지 못해 평문을 그대로 둡니다: %s (%s)' % (root, exc))
        return False
    left = []
    for entry in entries:
        try:
            _remove(entry)
        except OSError:
            left.append(entry)
    if left:
        # The archive is complete; the next unseal overwrites these.
        say('잠금은 완료됐지만 일부 평문을 지우지 못했습니다: %s' % ', '.join(map(str, left[:3])))
    return True


def _safe_extract(tar, destination: Path) -> None:
    data_filter = getattr(tarfile, 'data_filter', None)
    if data_filter is not None:
        tar.extractall(destination, filter=data_filter)
        return
    base = destination.resolve()
    for member in tar:
        target = (destination / member.name).resolve()
        if base != target and base not in target.parents:
            raise VaultError('sealed archive entry escapes its folder: %s' % member.name)
        if member.issym() or member.islnk() or member.isdev():
            continue
        tar.extract(member, destination)


def unseal_tree(root, archive, *, using_protector=None, log=None) -> bool:
    """Restore ``root`` from ``archive`` and remove the archive.

    True when there was nothing sealed or it is now restored. The archive
    always wins over plaintext of the same name: plaintext beside a sealed
    archive is either a leftover the seal could not delete or something
    created empty before the restore.
    """
    say = log or (lambda message: None)
    root, archive = Path(root), Path(archive)
    if not archive.is_file():
        return True
    shield = using_protector or protector()
    if shield is None:
        raise VaultError('%s is sealed for a Windows account and cannot be '
                         'opened here' % root)
    staging = root.with_name(root.name + '.unseal-tmp')
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with archive.open('rb') as stream:
            reader = _FrameReader(stream, shield)
            with tarfile.open(fileobj=reader, mode='r|') as tar:
                _safe_extract(tar, staging)
            reader.drain()
            if not reader._done:
                raise VaultError('sealed archive is incomplete')
        root.mkdir(parents=True, exist_ok=True)
        for entry in sorted(staging.iterdir()):
            target = root / entry.name
            if target.exists() or target.is_symlink():
                _remove(target)
            os.replace(entry, target)
        archive.unlink()
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    say('%s 의 잠금을 풀었습니다.' % root)
    return True


# ── who is using a tree ──────────────────────────────────────────────────

def _hold_name(root: Path, pid: int) -> Path:
    return root.with_name('.%s.inuse-%d' % (root.name, pid))


def _try_lock(handle) -> bool:
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


_HOLDS: dict = {}
_HOLDS_GUARD = threading.Lock()


class Hold:
    """This process is using a tree; the OS drops the lock if it dies.

    One lock file per process, counted: Chat and the Agent in one window, or a
    Chat restarted without closing, share it instead of failing on a second
    lock of the same file.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.path = _hold_name(self.root, os.getpid())
        self._released = False
        key = os.path.normcase(os.path.abspath(self.path))
        with _HOLDS_GUARD:
            entry = _HOLDS.get(key)
            if entry is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open('a+b')
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b'\0')
                    handle.flush()
                if not _try_lock(handle):
                    handle.close()
                    raise VaultError('%s is locked by another handle' % self.root)
                entry = _HOLDS[key] = [handle, 0]
            entry[1] += 1
        self._key = key

    def release(self) -> None:
        with _HOLDS_GUARD:
            if self._released:
                return
            self._released = True
            entry = _HOLDS.get(self._key)
            if entry is None:
                return
            entry[1] -= 1
            if entry[1] > 0:
                return
            del _HOLDS[self._key]
            handle = entry[0]
        _unlock(handle)
        handle.close()
        try:
            self.path.unlink()
        except OSError:
            pass


def held_here(root) -> bool:
    key = os.path.normcase(os.path.abspath(_hold_name(Path(root), os.getpid())))
    with _HOLDS_GUARD:
        return key in _HOLDS


def in_use(root) -> bool:
    """Is any live process holding ``root``? Stale hold files are removed."""
    root = Path(root)
    if held_here(root):
        return True
    busy = False
    for hold in root.parent.glob('.%s.inuse-*' % root.name):
        try:
            handle = hold.open('a+b')
        except OSError:
            busy = True
            continue
        try:
            if _try_lock(handle):
                _unlock(handle)
                handle.close()
                try:
                    hold.unlink()
                except OSError:
                    pass
            else:
                handle.close()
                busy = True
        except OSError:
            handle.close()
            busy = True
    return busy


class Store:
    """One sealed tree: where it lives, where it is sealed, what stays out."""

    def __init__(self, name, root, *, exclude=()):
        self.name = str(name)
        self.root = Path(root)
        self.archive = self.root.with_name(self.root.name + '.vault')
        self.exclude = tuple(exclude)

    def sealed(self) -> bool:
        return self.archive.is_file()

    def has_plaintext(self) -> bool:
        return bool(_entries(self.root, self.exclude))

    def _operation(self):
        # Sealing and opening exclude each other across processes: a Chat
        # starting while another window seals would otherwise run on files
        # the seal is about to delete.
        from core.persistence import file_lock
        return file_lock(self.root.with_name('.%s.vault.lock' % self.root.name),
                         timeout=900)

    def open(self, *, log=None) -> Optional[Hold]:
        """Unseal for a session and hold it until ``close``.

        None when there is nothing to protect on this machine and nothing
        sealed - a development checkout, or protection switched off.
        """
        if not enabled() and not self.sealed():
            return None
        with self._operation():
            hold = Hold(self.root)
            try:
                unseal_tree(self.root, self.archive, log=log)
            except Exception:
                hold.release()
                raise
        return hold

    def close(self, hold: Optional[Hold], *, log=None) -> bool:
        """Release this process's hold and seal if nobody else is using it."""
        if hold is not None:
            hold.release()
        return self.seal_if_idle(log=log)

    def seal_if_idle(self, *, log=None) -> bool:
        if not enabled() or not is_private_path(self.root):
            return False
        with self._operation():
            if in_use(self.root):
                return False
            if not self.has_plaintext():
                return True
            return seal_tree(self.root, self.archive, exclude=self.exclude, log=log)


def wait_for(predicate, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


__all__ = ['MAGIC_FILE', 'MAGIC_ARCHIVE', 'LINE_PREFIX', 'DISABLE_VARIABLE',
           'VaultError', 'protector', 'using', 'enabled', 'is_private_path',
           'should_protect', 'is_protected_bytes', 'seal_bytes', 'open_bytes',
           'read_bytes', 'read_text', 'encode_for', 'write_bytes_atomic',
           'write_text_atomic', 'protect_line', 'open_line', 'iter_lines',
           'ProtectedTextWriter', 'open_log', 'protect_lines_in_place',
           'protect_file_in_place', 'write_bytes_raw', 'verify_archive',
           'seal_tree', 'unseal_tree', 'Hold', 'held_here', 'in_use', 'Store']
