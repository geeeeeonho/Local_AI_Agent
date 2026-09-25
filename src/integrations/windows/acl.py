"""Run ``icacls`` and read back what it did, in a language-neutral way.

Two callers need exactly this: the model store has to be *readable* by every
account on the machine, and each account's records folder has to be readable
by *no one else*. Both questions are answered by the same descriptor, and both
are asked by running the same tool, so the plumbing lives here once.

``core.sddl`` decides what a descriptor means. Nothing here interprets one.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

#: Do not flash a console window out of a GUI process.
NO_WINDOW = 0x08000000


def on_windows(windows=None) -> bool:
    return (os.name == 'nt') if windows is None else bool(windows)


def run(command, timeout=20):
    """Run one console tool without flashing a window. None if it cannot run."""
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, check=False,
                              creationflags=NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return None


def succeeded(result) -> bool:
    return result is not None and result.returncode == 0


def saved_sddl(path: Path) -> Optional[str]:
    """A folder's DACL in SDDL form, via ``icacls /save``. None if unavailable.

    ``icacls`` on its own prints account names in the language Windows is
    installed in, so reading its normal output meant matching "BUILTIN\\Users"
    against "BUILTIN\\사용자" on a Korean machine. SDDL names that group "BU" in
    every language.
    """
    handle, name = tempfile.mkstemp(prefix='localai-acl-', suffix='.txt')
    os.close(handle)
    saved = Path(name)
    try:
        # icacls will not overwrite an existing save file.
        saved.unlink(missing_ok=True)
        result = run(['icacls', str(path), '/save', str(saved), '/Q'])
        if not succeeded(result) or not saved.is_file():
            return None
        return saved.read_text(encoding='utf-16', errors='replace')
    except (OSError, UnicodeError):
        return None
    finally:
        try:
            saved.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ['NO_WINDOW', 'on_windows', 'run', 'succeeded', 'saved_sddl']
