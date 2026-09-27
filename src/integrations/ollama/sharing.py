"""Read and repair the LocalAI machine-shared model store.

``core.models.sharing`` decides whether LocalAI accounts can manage the shared
library. The LocalAI broker receives its store path explicitly. Publishing
``OLLAMA_MODELS`` remains a separate best-effort convenience for standalone
Ollama CLI/Tray processes.
"""
from __future__ import annotations

from pathlib import Path

from core.models import sharing as policy
from core.models.sharing import Sharing, VARIABLE
from integrations.windows import acl

__all__ = ['read', 'repair', 'Sharing', 'VARIABLE',
           'ensure_readable', 'ensure_manageable',
           'publish_machine_variable', 'publish_user_variable',
           'publish_variable', 'describe']

# The local Users group, by SID so it works on a non-English Windows.
BUILTIN_USERS_SID = policy.USERS_SID
# One copy of the console plumbing: the private records folder under the same
# root asks the opposite question of the same tool.
_run = acl.run


def _users_access(model_dir: Path) -> tuple[bool | None, bool | None]:
    """Return (readable, manageable) for BUILTIN\\Users from one ACL read."""
    if not model_dir.exists():
        return None, None
    text = acl.saved_sddl(model_dir)
    if text is None:
        return None, None
    for line in text.splitlines():
        descriptor = line.strip()
        readable = policy.readable_from_sddl(descriptor)
        manageable = policy.manageable_from_sddl(descriptor)
        if readable is not None or manageable is not None:
            return readable, manageable
    return None, None


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
    readable, manageable = _users_access(model_dir)
    return Sharing(
        path=str(model_dir),
        intended_shared=model_dir == ollama_paths.SHARED_MODELS_DIR,
        readable_by_users=readable,
        manageable_by_users=manageable,
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


def ensure_manageable(model_dir: Path, *, windows=None) -> bool:
    """Grant BUILTIN\\Users inheritable Modify rights on the model store only.

    Model files, manifests, the shared registry and the mutation lock are
    machine-wide mutable state. Standard Windows accounts therefore need
    to create, replace and delete children here. This stays separate from
    ensure_readable because environment/ollama must remain RX-only.
    """
    if not acl.on_windows(windows):
        return True
    result = _run(['icacls', str(model_dir), '/grant',
                   '*%s:(OI)(CI)(M)' % BUILTIN_USERS_SID, '/T', '/Q'])
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
    """Repair LocalAI cross-account model management and report what is left.

    Safe to run at any time and safe to run twice; Modify includes the read
    access required by the sharing check and the ACL step is idempotent.
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
        ('manageable', lambda: ensure_manageable(model_dir, windows=windows)),
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
    policy.NOT_READABLE:
        '다른 계정에 읽기 권한이 없습니다.',
    policy.NOT_MANAGEABLE:
        '다른 계정에 모델 설치·삭제를 위한 수정 권한이 없습니다. 설치 / 복구에서 권한을 갱신하세요.',
}


def describe(state: Sharing) -> tuple:
    """One sentence per blocker, in the order the policy reports them."""
    return tuple(_MESSAGES[key] for key in state.blockers if key in _MESSAGES)
