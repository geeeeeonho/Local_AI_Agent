"""OS-owned session lock; never delete a lock file or trust a saved PID.

This serializes *managed runtime mutations* across LocalAI windows and Windows
accounts that share the machine-wide runtime. It does not reserve port 11434 or prevent external Ollama clients.
The same window can share a prepared network among its Chat and Agent views.
"""
from pathlib import Path
import os
import threading


class RuntimeOwner:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None
        self._lock = threading.RLock()

    @property
    def owned(self):
        return self._file is not None

    def acquire(self):
        with self._lock:
            if self._file is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
            try:
                fd = os.open(self.path, flags, 0o600)
                handle = os.fdopen(fd, 'r+b')
            except OSError as exc:
                raise RuntimeError(
                    'Shared LocalAI runtime lock is not writable: %s. '
                    'Run RUN.bat --install once from an administrator/installer account '
                    'to repair shared runtime permissions.' % self.path
                ) from exc
            try:
                if os.fstat(fd).st_size == 0:
                    handle.write(b'\0'); handle.flush()
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise RuntimeError('Managed runtime is busy in another LocalAI window. '
                                   'Close its session before changing runtimes here.') from exc
            self._file = handle
            try:
                from launcher.core import lifelog
                lifelog.rearm_exit_cleanups()
            except Exception:
                pass

    def release(self):
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
