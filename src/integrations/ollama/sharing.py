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

__all__ = ['read', 'repair', 'Sharing', 'VARIABLE', 'principal_sid',
           'ensure_readable', 'ensure_manageable',
           'publish_machine_variable', 'publish_user_variable',
           'publish_variable', 'describe']

# The local Users group, by SID so it works on a non-English Windows.
BUILTIN_USERS_SID = policy.USERS_SID
# One copy of the console plumbing: the private records folder under the same
# root asks the opposite question of the same tool.
_run = acl.run


def principal_sid() -> str:
    """Who "every account" is: BUILTIN\\Users, or LocalAI-Users when an
    administrator limited access to members (``core.machine``)."""
    try:
        import project_paths
        from core import machine
        policy = machine.load(project_paths.machine_policy_path())
    except Exception:
        policy = None
    return policy.principal() if policy is not None else BUILTIN_USERS_SID


def _users_access(model_dir: Path) -> tuple[bool | None, bool | None]:
    """Return (readable, manageable) for BUILTIN\\Users from one ACL read."""
    if not model_dir.exists():
        return None, None
    text = acl.saved_sddl(model_dir)
    if text is None:
        return None, None
    principal = principal_sid()
    for line in text.splitlines():
        descriptor = line.strip()
        readable = policy.readable_from_sddl(descriptor, principal)
        manageable = policy.manageable_from_sddl(descriptor, principal)
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
    """Grant BUILTIN\\Users inheritable read/execute, keeping existing ACLs.

    This helper is used for shared runtime/Ollama directories. The model store
    uses ensure_manageable instead because every account may install and remove
    shared models.
    """
    if not acl.on_windows(windows):
        return True
    result = _run(['icacls', str(model_dir), '/grant',
                   '*%s:(OI)(CI)(RX)' % principal_sid(), '/T', '/Q'])
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
                   '*%s:(OI)(CI)(M)' % principal_sid(), '/T', '/Q'])
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


def _published_variable(hive, subkey):
    """Registry setting seen by NEW Windows processes, not our child process."""
    try:
        import winreg
        with winreg.OpenKey(hive, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, VARIABLE)
            return value.strip().strip('"') if isinstance(value, str) else ''
    except FileNotFoundError:
        return ''
    except (OSError, ImportError):
        return None


def external_store_settings(model_dir=None, *, windows=None) -> dict:
    """The effective Windows Ollama store setting: HKCU overrides HKLM."""
    from core import ollama_paths
    path = Path(model_dir) if model_dir is not None else ollama_paths.SHARED_MODELS_DIR
    result = {'path': str(path), 'supported': False, 'connected': None,
              'machine': None, 'user': None, 'effective': None,
              'user_conflict': False}
    if not acl.on_windows(windows):
        return result
    try:
        import winreg
        user = _published_variable(winreg.HKEY_CURRENT_USER, 'Environment')
        machine = _published_variable(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')
    except ImportError:
        return result
    effective = (user or machine) if user is not None and machine is not None else None
    result.update(supported=True, user=user, machine=machine, effective=effective)
    if effective is not None:
        result['connected'] = bool(
            effective and ollama_paths._same_windows_path(effective, path))
    result['user_conflict'] = bool(
        user and not ollama_paths._same_windows_path(user, path))
    return result


def connect_external_store(model_dir=None, *, windows=None) -> dict:
    """Explicit opt-in for standalone CLI/tray to use the shared model store.

    Do not restart any server or move existing files. A conflicting user-scoped
    value must be fixed even if the machine-level write succeeded.
    """
    from core import ollama_paths
    path = Path(model_dir) if model_dir is not None else ollama_paths.SHARED_MODELS_DIR
    before = external_store_settings(path, windows=windows)
    if not before['supported']:
        return {'ok': False, 'scope': '', 'before': before, 'after': before,
                'message': 'Windows 환경변수 상태를 확인할 수 없습니다.'}
    if before['connected'] is True:
        return {'ok': True, 'scope': 'existing', 'before': before, 'after': before,
                'message': '일반 Ollama의 모델 경로가 이미 공용 저장소와 일치합니다.'}
    scope = ''
    if publish_machine_variable(path, windows=windows):
        scope = 'machine'
        if before['user_conflict'] and not publish_user_variable(path, windows=windows):
            after = external_store_settings(path, windows=windows)
            return {'ok': False, 'scope': scope, 'before': before, 'after': after,
                    'message': '시스템 경로는 저장했지만 사용자 계정의 충돌 설정을 고치지 못했습니다.'}
    elif publish_user_variable(path, windows=windows):
        scope = 'user'
    after = external_store_settings(path, windows=windows)
    ok = bool(scope) and after['connected'] is True
    if not scope:
        message = '환경변수를 저장하지 못했습니다. Windows 권한을 확인하세요.'
    elif not ok:
        message = '설정을 저장했지만 Windows 등록값이 일치하는지 확인하지 못했습니다.'
    else:
        message = ('일반 Ollama 모델 저장 경로 연결 완료 · 새 터미널 및 '
                   'Ollama 서버를 다시 시작해야 적용됩니다.')
    return {'ok': ok, 'scope': scope, 'before': before, 'after': after,
            'message': message}


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
