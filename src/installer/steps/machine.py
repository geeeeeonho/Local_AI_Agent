"""installer.steps.machine — who administers LocalAI on this PC.

The first account to install becomes the LocalAI administrator: one UAC
prompt creates the ``LocalAI-Admins`` / ``LocalAI-Users`` groups, adds this
account to the first, locks the shared root so only administrators can
change the program and runtimes, and puts a LocalAI shortcut on every
account's desktop and Start menu. Later Setup runs by an administrator keep
the program current; any other account's Setup prepares only its own private
folder and leaves the shared parts alone.
"""
from __future__ import annotations

from pathlib import Path

from ..core.console import info, ok, section, warn
from . import app as app_step


def _write_policy(path: Path, policy) -> bool:
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(policy.to_json(), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as exc:
        warn("관리 정책 파일을 쓰지 못했습니다: %s (%s)" % (path, exc))
        return False


def current_role(root: Path) -> str:
    """``admin``, ``user`` or ``dev`` for this account - without changing anything."""
    from core import machine
    from integrations.windows import acl
    from integrations.windows import machine as windows

    if not acl.on_windows():
        return "dev"
    sid = acl.current_user_sid()
    policy = machine.load(Path(root) / machine.POLICY_FILENAME)
    if policy is None:
        return "admin" if machine.first_admin_candidate(acl.owner_sid(Path(root)), sid) else "user"
    if policy.is_admin(sid, windows.token_group_sids()) or acl.is_elevated():
        return "admin"
    return "user"


def ensure(root: Path, app_dir: Path, project_root: Path) -> str:
    """Return this account's role: ``admin``, ``user`` or ``dev`` (not Windows)."""
    from core import machine
    from integrations.windows import acl
    from integrations.windows import machine as windows

    if not acl.on_windows():
        return "dev"
    root, app_dir = Path(root), Path(app_dir)
    policy_path = root / machine.POLICY_FILENAME
    policy = machine.load(policy_path)
    sid = acl.current_user_sid()
    if not sid:
        warn("현재 계정의 SID를 확인하지 못해 LocalAI 관리자 설정을 건너뜁니다.")
        return "user"

    if policy is None:
        owner = acl.owner_sid(root)
        if not machine.first_admin_candidate(owner, sid):
            info("LocalAI를 처음 설치한 계정(%s)에서 Setup을 실행하면 관리자 설정이 "
                 "완료됩니다. 이 계정은 개인 폴더만 준비합니다." % owner)
            return "user"
        section("LocalAI 관리자 설정 (처음 설치)")
        info("이 계정을 LocalAI 관리자로 지정하고, 공용 프로그램을 %s 에 설치합니다." % app_dir)
        app_step.deploy(project_root, app_dir)
        script = windows.first_install_script(sid, root, app_dir)
        elevated = bool(script) and windows.run_as_admin(script, log=info)
        policy = machine.new_policy(
            sid,
            admins_group_sid=windows.group_sid(machine.ADMINS_GROUP),
            users_group_sid=windows.group_sid(machine.USERS_GROUP))
        if not elevated:
            warn("Windows 관리자 승인 없이 진행합니다. 그룹과 공용 바로가기는 만들지 못했고, "
                 "이 계정만 LocalAI 관리자로 기록합니다. 나중에 Setup을 다시 실행하면 "
                 "다시 시도합니다.")
            policy.notes["groups_pending"] = True
            if windows.lockable_root(root) and not acl.succeeded(
                    acl.run(windows.lock_root_command(root, policy), timeout=600)):
                warn("공용 폴더 권한을 잠그지 못했습니다: %s" % root)
        _write_policy(policy_path, policy)
        ok("LocalAI 관리자: 이 계정 (%s)" % sid)
        return "admin"

    if policy.is_admin(sid, windows.token_group_sids()) or acl.is_elevated():
        if policy.notes.get("groups_pending"):
            script = windows.first_install_script(sid, root, app_dir)
            if script and windows.run_as_admin(script, log=info):
                policy.admins_group_sid = windows.group_sid(machine.ADMINS_GROUP)
                policy.users_group_sid = windows.group_sid(machine.USERS_GROUP)
                policy.notes.pop("groups_pending", None)
                _write_policy(policy_path, policy)
        if windows.lockable_root(root) and not acl.succeeded(
                acl.run(windows.lock_root_command(root, policy), timeout=600)):
            warn("공용 폴더 권한을 다시 맞추지 못했습니다: %s" % root)
        app_step.deploy(project_root, app_dir)
        return "admin"

    info("공용 프로그램과 실행환경은 LocalAI 관리자가 관리합니다. "
         "이 계정의 개인 폴더와 Docker 이미지만 준비합니다.")
    return "user"


__all__ = ["current_role", "ensure"]
