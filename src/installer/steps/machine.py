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
        # A folder's owner is only a *candidate* for first Setup, not a
        # verified program administrator. Until UAC + ACL protection succeeds
        # no caller may assume it is safe to mutate shared code.
        return "user"
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

    from integrations.windows import program_security

    if not windows.lockable_root(root):
        raise RuntimeError("공용 프로그램 경로에 안전한 ACL을 적용할 수 없습니다: " + str(root))
    program_security.reject_reparse_root(root)

    if policy is None:
        owner = acl.owner_sid(root)
        if not machine.first_admin_candidate(owner, sid):
            raise RuntimeError(
                "아직 LocalAI 관리자 설정이 완료되지 않았습니다. "
                "공유 폴더를 만든 첫 설치 계정으로 Setup을 실행해 "
                "Windows 관리자 승인과 ACL 보호를 완료하세요.")
        section("LocalAI 관리자 설정 (처음 설치)")
        info("먼저 Windows 권한을 잠근 뒤 공용 프로그램을 배포합니다.")
        # A per-attempt random file lets hidden UAC PowerShell report which
        # group/ACL stage failed, without weakening the security boundary.
        from uuid import uuid4
        report = root / ('.localai-admin-' + uuid4().hex + '.txt')
        script = windows.first_install_script(sid, root, app_dir, report_path=report)
        if not script or not windows.run_as_admin(
                script, log=info, report_path=report):
            try:
                details = report.read_text(encoding="utf-8-sig")[:1400].strip()
            except OSError:
                details = "UAC 취소 또는 권한 작업 실패(상세 기록 없음)"
            raise RuntimeError(
                "LocalAI 최초 관리자 자동 등록에 실패했습니다. "
                "프로그램 파일 보호를 건너뛰지 않습니다.\n"
                + "실패 단계: " + details + "\n"
                + "Windows 권한 오류라면 파일을 사용하는 다른 LocalAI/Ollama "
                  "프로세스를 종료한 뒤 다시 실행하세요.")
        admins_group_sid = windows.group_sid(machine.ADMINS_GROUP)
        users_group_sid = windows.group_sid(machine.USERS_GROUP)
        if not machine.is_sid(admins_group_sid) or not machine.is_sid(users_group_sid):
            raise RuntimeError(
                "Windows 그룹은 생성됐을 수 있지만 LocalAI-Admins / LocalAI-Users "
                "SID를 확인하지 못했습니다. 임의의 관리자 정책을 기록하지 않습니다.")
        policy = machine.new_policy(
            sid, admins_group_sid=admins_group_sid,
            users_group_sid=users_group_sid)
        reasons = program_security.verify(root, policy)
        if reasons:
            raise RuntimeError("프로그램 ACL 검증 실패: " + "; ".join(reasons[:4]))
        if not _write_policy(policy_path, policy):
            raise RuntimeError("관리 정책을 안전하게 저장하지 못했습니다.")
        if not app_step.deploy(project_root, app_dir):
            raise RuntimeError("보호된 공용 프로그램 배포에 실패했습니다.")
        # The deployed files inherit root RX for ordinary accounts. An
        # untrusted owner or explicit child grant must still abort setup.
        reasons = program_security.verify(root, policy)
        if reasons:
            raise RuntimeError("공용 프로그램 배포 후 ACL 검증 실패: " +
                               "; ".join(reasons[:4]))
        ok("LocalAI 관리자: 이 계정 (%s)" % sid)
        return "admin"

    if policy.is_admin(sid, windows.token_group_sids()) or acl.is_elevated():
        if policy.notes.get("groups_pending"):
            # Upgrade old installations, but never claim success until UAC
            # and the inherited permission repair have both completed.
            script = windows.first_install_script(sid, root, app_dir)
            if not script or not windows.run_as_admin(script, log=info):
                raise RuntimeError("LocalAI 관리자 그룹 복구를 승인하지 않았습니다.")
            policy.admins_group_sid = windows.group_sid(machine.ADMINS_GROUP)
            policy.users_group_sid = windows.group_sid(machine.USERS_GROUP)
            policy.notes.pop("groups_pending", None)
            if not _write_policy(policy_path, policy):
                raise RuntimeError("관리 정책 갱신에 실패했습니다.")
        # Reapply the same protection to pre-existing explicit child grants.
        program_security.ensure(root, policy, log=info, force=True)
        if not app_step.deploy(project_root, app_dir):
            raise RuntimeError("보호된 공용 프로그램 업데이트에 실패했습니다.")
        reasons = program_security.verify(root, policy)
        if reasons:
            raise RuntimeError("프로그램 업데이트 후 ACL 검증 실패: " +
                               "; ".join(reasons[:4]))
        return "admin"

    info("공용 프로그램과 실행환경은 LocalAI 관리자가 관리합니다. "
         "이 계정의 개인 폴더와 Docker 이미지만 준비합니다.")
    return "user"



def bootstrap_first_run(root, app_dir, project_root, env) -> bool:
    """First GUI launch automatically registers its initial LocalAI admin.

    Returns False for an existing installed policy. This never grants a Windows
    administrator token: actual directory ACL changes still require UAC.
    """
    from core import machine
    from integrations.windows import acl
    if not acl.on_windows():
        return False
    root = Path(root)
    policy_file = root / machine.POLICY_FILENAME
    if policy_file.exists():
        # A broken/unreadable policy is not a fresh installation and must
        # never let another user claim the existing LocalAI installation.
        if machine.load(policy_file) is None:
            raise RuntimeError(
                "LocalAI 관리자 정책 파일을 읽지 못했습니다. 최초 설치가 아니라 "
                "정책 복구가 필요하므로 자동 관리자 등록을 거부합니다.")
        return False
    root.mkdir(parents=True, exist_ok=True)
    if ensure(root, Path(app_dir), Path(project_root)) != "admin":
        raise RuntimeError("최초 LocalAI 관리자 등록이 완료되지 않았습니다.")

    # Make the private user folder + shared runtime skeleton before launching
    # Studio, so a new user may open the main UI without --install.
    from installer.core.filesystem import create_environment
    create_environment(Path(env), manage_shared=True)
    return True


__all__ = ["current_role", "ensure", "bootstrap_first_run"]
