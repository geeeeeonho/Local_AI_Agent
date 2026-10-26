"""Bounded JSON, atomic replacement and OS-backed cross-process update locks.

The lock file is permanent; the OS releases its byte/flock lock after crashes.
Deleting 'stale' lock files would let different processes lock different inodes.
Readers see a previous or next whole document, never a partially written file.
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable

from core import vault

_MAX_BYTES = 4 * 1024 * 1024
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def file_lock(path: Path, timeout: float = 10):
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError('lock timeout must be finite and non-negative')
    deadline = time.monotonic() + timeout
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(key, threading.RLock())
    if not mutex.acquire(timeout=timeout):
        raise TimeoutError(f'LocalAI state file is busy: {path}')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'\0')
                handle.flush()
            while True:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'LocalAI state file is busy: {path}')
                    time.sleep(0.025)
            try:
                yield
            finally:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    finally:
        mutex.release()


class JsonStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> dict:
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(_MAX_BYTES + 1)
        except FileNotFoundError:
            return {}
        if len(raw) > _MAX_BYTES:
            raise ValueError(f'LocalAI state exceeds size limit: {self.path}')
        # Inside this account's folder the document is DPAPI-protected;
        # plaintext from before that is still read.
        try:
            raw = vault.open_bytes(raw)
        except vault.Undecryptable:
            # Protected for a key this account no longer has (an administrator
            # reset its password): the content is gone either way. Keep the
            # file aside and start empty instead of refusing to start at all.
            try:
                vault.set_aside(self.path)
            except OSError:
                pass
            return {}
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError(f'LocalAI state must be an object: {self.path}')
        return data

    def update(self, change: Callable[[dict], dict]) -> dict:
        with file_lock(self.path.with_name(self.path.name + '.lock')):
            result = change(self.read())
            if not isinstance(result, dict):
                raise ValueError('state update must return an object')
            payload = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            if len(payload) > _MAX_BYTES:
                raise ValueError('LocalAI state exceeds size limit')
            payload = vault.encode_for(self.path, payload)
            fd, name = tempfile.mkstemp(prefix='.' + self.path.name + '.', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
            return result


def schema_one(document: dict) -> dict:
    version = document.get('schema_version', 1)
    if type(version) is not int or version != 1:
        raise ValueError(f'unsupported LocalAI schema_version: {version!r}')
    document['schema_version'] = 1
    return document
