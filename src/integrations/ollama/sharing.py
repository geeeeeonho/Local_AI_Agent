"""Read and repair the machine-shared model store. One place, any time.

``core.models.sharing`` decides what the facts mean; this reads them off the
real machine and can put them right. Both halves used to live in the
installer, where they ran exactly once - during setup, only for the default
path, and only if that setup happened to have administrator rights. A user
whose setup ran without admin had no way to find that out and no way to fix
it short of reinstalling.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from core.models import sharing as policy
from core.models.sharing import Sharing, VARIABLE

__all__ = ['read', 'repair', 'Sharing', 'VARIABLE',
           'ensure_readable', 'publish_machine_variable', 'publish_user_variable',
           'publish_variable', 'describe']

# The local Users group, by SID so it works on a non-English Windows.
BUILTIN_USERS_SID = policy.USERS_SID
_MACHINE_KEY = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
_USER_KEY = 'Environment'
_NO_WINDOW = 0x08000000


def _run(command, timeout=20):
    """Run one console tool without flashing a window. None if it cannot run."""
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, check=False,
                              creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return None


def _registry_value(root, key) -> Optional[str]:
    """A stored environment value: '' when unset, None when unreadable.

    Read from the registry rather than os.environ because this process
    inherited its environment at launch: a value written by a setup that ran
    after it would not be visible, and a value this process injected for its
    own child Ollama would look like a machine-wide setting.
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(root, key) as handle:
            value, kind = winreg.QueryValueEx(handle, VARIABLE)
        value = str(value)
        # REG_EXPAND_SZ comes back with %SystemDrive% and friends still in it.
        # That is the same store written differently, and comparing the raw
        # text reported it as pointing somewhere else.
        if kind == getattr(winreg, 'REG_EXPAND_SZ', 2):
            # ntpath, not os.path: this value came out of the Windows registry
            # and uses %VAR% syntax, which posixpath.expandvars leaves alone.
            # Naming the platform makes the rule checkable off Windows too.
            import ntpath
            value = ntpath.expandvars(value)
        return value
    except FileNotFoundError:
        return ''
    except OSError:
        return None


def _saved_sddl(model_dir: Path) -> Optional[str]:
    """The store's DACL in SDDL form, via ``icacls /save``. None if unavailable.

    ``icacls`` on its own prints account names in the language Windows is
    installed in, so reading its normal output meant matching "BUILTIN\\Users"
    against "BUILTIN\\사용자" on a Korean machine and concluding, permanently,
    that nobody could read the store - including right after a repair that had
    worked. SDDL names that group "BU" in every language.
    """
    handle, name = tempfile.mkstemp(prefix='localai-acl-', suffix='.txt')
    os.close(handle)
    saved = Path(name)
    try:
        # icacls will not overwrite an existing save file.
        saved.unlink(missing_ok=True)
        result = _run(['icacls', str(model_dir), '/save', str(saved), '/Q'])
        if result is None or result.returncode != 0 or not saved.is_file():
            return None
        return saved.read_text(encoding='utf-16', errors='replace')
    except (OSError, UnicodeError):
        return None
    finally:
        try:
            saved.unlink(missing_ok=True)
        except OSError:
            pass


def _readable_by_users(model_dir: Path) -> Optional[bool]:
    """Can BUILTIN\\Users read the store? None when the answer is unavailable."""
    if not model_dir.exists():
        return None
    text = _saved_sddl(model_dir)
    if text is None:
        return None
    for line in text.splitlines():
        answer = policy.readable_from_sddl(line.strip())
        if answer is not None:
            return answer
    return None


def read(model_dir=None, *, windows=None) -> Sharing:
    """What is actually true about this store on this machine."""
    from core import ollama_paths
    if model_dir is None:
        from project_paths import MODEL_STORAGE_DIR
        model_dir = MODEL_STORAGE_DIR
    model_dir = Path(model_dir)
    on_windows = (os.name == 'nt') if windows is None else bool(windows)
    if not on_windows:
        return Sharing(path=str(model_dir),
                       intended_shared=model_dir == ollama_paths.SHARED_MODELS_DIR,
                       per_user_path=ollama_paths.is_per_user_store(model_dir),
                       windows=False)
    import winreg
    return Sharing(
        path=str(model_dir),
        intended_shared=model_dir == ollama_paths.SHARED_MODELS_DIR,
        machine_value=_registry_value(winreg.HKEY_LOCAL_MACHINE, _MACHINE_KEY),
        user_value=_registry_value(winreg.HKEY_CURRENT_USER, _USER_KEY),
        readable_by_users=_readable_by_users(model_dir),
        per_user_path=ollama_paths.is_per_user_store(model_dir),
        windows=True,
    )


def ensure_readable(model_dir: Path, *, windows=None) -> bool:
    """Grant BUILTIN\\Users read and execute, inheritable, keeping existing ACLs.

    Read only. The store is a trust asset - it decides what the models on this
    machine actually are - so the other accounts get to use the models, not to
    replace them. (OI)(CI) makes the grant apply to models pulled later, not
    just the ones present when this runs.
    """
    if not ((os.name == 'nt') if windows is None else bool(windows)):
        return True
    result = _run(['icacls', str(model_dir), '/grant',
                   '*%s:(OI)(CI)(RX)' % BUILTIN_USERS_SID, '/T', '/Q'])
    return result is not None and result.returncode == 0


def publish_machine_variable(model_dir: Path, *, windows=None) -> bool:
    """Point every account's Ollama here, machine-wide. Needs administrator.

    Without this, another account's Ollama reads no OLLAMA_MODELS, falls back
    to that account's own profile, and re-downloads the whole library.
    """
    if not ((os.name == 'nt') if windows is None else bool(windows)):
        return True
    result = _run(['setx', VARIABLE, str(model_dir), '/M'])
    return result is not None and result.returncode == 0


def publish_user_variable(model_dir: Path, *, windows=None) -> bool:
    """Point this account's Ollama here. No administrator needed."""
    if not ((os.name == 'nt') if windows is None else bool(windows)):
        return True
    result = _run(['setx', VARIABLE, str(model_dir)])
    return result is not None and result.returncode == 0


def publish_variable(model_dir: Path, *, windows=None) -> str:
    """Make the store stick for every future Ollama start. Returns the scope.

    ``'machine'``, ``'user'`` or ``''`` for neither. This is the step that was
    missing everywhere: the installer only ever passed OLLAMA_MODELS to the
    server it launched itself, as a child-process variable. Nothing else that
    starts Ollama - the Startup entry Windows runs at login, the tray app, the
    user typing ``ollama serve`` - inherits that, so after the first reboot the
    server reads its own empty default and the whole library disappears from
    view. Machine scope needs administrator; user scope does not and is enough
    for the account actually using the program.
    """
    if not ((os.name == 'nt') if windows is None else bool(windows)):
        return 'machine'
    if publish_machine_variable(model_dir, windows=windows):
        return 'machine'
    if publish_user_variable(model_dir, windows=windows):
        return 'user'
    return ''


def repair(model_dir=None, *, windows=None) -> dict:
    """Put right what can be put right, and report what is left.

    Safe to run at any time and safe to run twice; both steps are idempotent.
    Returns the state afterwards so a caller can tell the user whether it
    worked without guessing.
    """
    if model_dir is None:
        from project_paths import MODEL_STORAGE_DIR
        model_dir = MODEL_STORAGE_DIR
    model_dir = Path(model_dir)
    before = read(model_dir, windows=windows)
    done, failed = [], []
    for name, action in (
        ('readable', lambda: ensure_readable(model_dir, windows=windows)),
        ('machine_variable', lambda: publish_machine_variable(model_dir, windows=windows)),
    ):
        (done if action() else failed).append(name)
    after = read(model_dir, windows=windows)
    return {'path': str(model_dir), 'repaired': tuple(done), 'failed': tuple(failed),
            'before': before, 'after': after,
            'every_account': after.every_account,
            'blockers': after.blockers}


# Sentences for the screen, keyed by what the policy found.
_MESSAGES = {
    policy.PER_USER_PATH:
        '이 저장소는 한 계정의 프로필 안에 있습니다. 다른 Windows 계정은 같은 '
        '모델을 보지 못하고 각자 다시 받습니다.',
    policy.NOT_SHARED_PATH:
        '이 저장소는 기계 공용 위치가 아닙니다. 직접 지정한 경로라면 그대로 '
        '두어도 됩니다.',
    policy.VARIABLE_MISSING:
        '시스템 범위 ' + VARIABLE + ' 가 없습니다. 다른 Windows 계정의 Ollama 는 '
        '자기 프로필을 보고 모델을 처음부터 다시 받습니다. 관리자 권한이 필요합니다.',
    policy.VARIABLE_ELSEWHERE:
        '시스템 범위 ' + VARIABLE + ' 가 다른 경로를 가리킵니다.',
    policy.USER_OVERRIDE:
        '이 계정의 사용자 범위 ' + VARIABLE + ' 가 시스템 값을 가립니다. '
        '개인 설정이므로 프로그램이 지우지 않습니다.',
    policy.NOT_READABLE:
        '다른 계정에 읽기 권한이 없습니다.',
}


def describe(state: Sharing) -> tuple:
    """One sentence per blocker, in the order the policy reports them."""
    return tuple(_MESSAGES[key] for key in state.blockers if key in _MESSAGES)
