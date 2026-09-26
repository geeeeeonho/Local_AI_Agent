"""Read and repair the LocalAI machine-shared model store.

``core.models.sharing`` decides whether LocalAI accounts can read the shared
library. Registry OLLAMA_MODELS values are still exposed here for external
Ollama compatibility, but the LocalAI-managed broker receives its store path
explicitly and does not depend on those registry values.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.models import sharing as policy
from core.models.sharing import Sharing, VARIABLE
from integrations.windows import acl

__all__ = ['read', 'repair', 'Sharing', 'VARIABLE',
           'ensure_readable', 'publish_machine_variable', 'publish_user_variable',
           'publish_variable', 'describe']

# The local Users group, by SID so it works on a non-English Windows.
BUILTIN_USERS_SID = policy.USERS_SID
_MACHINE_KEY = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
_USER_KEY = 'Environment'

# One copy of the console plumbing: the private records folder under the same
# root asks the opposite question of the same tool.
_run = acl.run


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


def _readable_by_users(model_dir: Path) -> Optional[bool]:
    """Can BUILTIN\\Users read the store? None when the answer is unavailable."""
    if not model_dir.exists():
        return None
    text = acl.saved_sddl(model_dir)
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
    if not acl.on_windows(windows):
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
    if not acl.on_windows(windows):
        return True
    result = _run(['icacls', str(model_dir), '/grant',
                   '*%s:(OI)(CI)(RX)' % BUILTIN_USERS_SID, '/T', '/Q'])
    return result is not None and result.returncode == 0


def publish_machine_variable(model_dir: Path, *, windows=None) -> bool:
    """Best-effort compatibility for Ollama launched outside LocalAI.

    The LocalAI-managed broker does not require this value because its child
    environment always receives the canonical model store. Machine scope still
    helps a user who opens the standalone Ollama CLI/Tray directly.
    """
    if not acl.on_windows(windows):
        return True
    result = _run(['setx', VARIABLE, str(model_dir), '/M'])
    return result is not None and result.returncode == 0


def publish_user_variable(model_dir: Path, *, windows=None) -> bool:
    """Point this account's Ollama here. No administrator needed."""
    if not acl.on_windows(windows):
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
    if not acl.on_windows(windows):
        return 'machine'
    if publish_machine_variable(model_dir, windows=windows):
        return 'machine'
    if publish_user_variable(model_dir, windows=windows):
        return 'user'
    return ''


def repair(model_dir=None, *, windows=None) -> dict:
    """Repair LocalAI cross-account readability and report what is left.

    Safe to run at any time and safe to run twice; the ACL step is idempotent.
    Machine-scope OLLAMA_MODELS is an external-Ollama compatibility setting,
    not a LocalAI sharing requirement.
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
