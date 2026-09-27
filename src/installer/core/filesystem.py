"""installer.core.filesystem — 환경 폴더 구조와 설치 식별 정보 관리."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from project_paths import (ACCOUNT_ROOT, ENV_DIRNAME, LOGS_DIRNAME,
                           MODEL_STORAGE_DIR, OLLAMA_INSTALL_DIR,
                           USER_DATA_DIRNAME, model_control_dir,
                           model_registry_path, model_mutation_lock_path)

from .console import section, ok, warn


INSTALL_MANIFEST = "LOCAL_AI_AGENT_INSTALL.json"
RUNTIME_LOCK_NAME = "desktop-runtime.lock"


def ensure_shared_model_access(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """모든 로컬 사용자가 공용 모델을 설치/삭제할 권한을 보장한다.

    environment/ollama는 RX 전용을 유지하고, 실제로 공유 변경되는 models에만
    BUILTIN\\Users Modify를 부여한다.
    """
    from integrations.ollama import sharing
    if sharing.ensure_manageable(model_dir, windows=windows):
        return True
    warn("공용 모델 폴더 수정 권한 설정 실패")
    return False


def publish_shared_model_dir(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """외부 Ollama CLI/Tray도 공용 저장소를 보기 쉽게 환경변수를 기록한다.

    LocalAI가 관리하는 broker는 실행할 때 모델 경로를 직접 주입하므로 이 값에
    의존하지 않는다. 시스템 범위 기록은 관리자 권한이 필요하며 실패해도 설치를
    중단하지 않는다.
    """
    from integrations.ollama import sharing
    # setx updates future processes only. Keep this setup process and every
    # child it starts on the same store immediately as well.
    os.environ["OLLAMA_MODELS"] = str(model_dir)
    if sharing.publish_machine_variable(model_dir, windows=windows):
        return True
    warn("시스템 범위 OLLAMA_MODELS 설정 실패")
    warn("LocalAI는 모든 계정에서 공용 모델 경로를 직접 주입하므로 계속 사용할 수 "
         "있습니다. 다만 LocalAI 밖에서 실행한 Ollama CLI/Tray는 자기 기본 경로를 "
         "볼 수 있습니다.")
    return False



def ensure_shared_runtime_access(paths, windows: Optional[bool] = None) -> bool:
    """Allow every local account to read/execute the shared runtime and broker.

    User-created state never lives in these folders; it belongs below
    users/<account>. Granting BUILTIN\\Users RX here makes a second Windows
    account able to use the installed environment and Ollama without giving it
    permission to replace those shared binaries.
    """
    from integrations.ollama import sharing
    ok_all = True
    for path in paths:
        if not sharing.ensure_readable(Path(path), windows=windows):
            warn("공용 실행환경 읽기 권한 설정 실패: %s" % path)
            ok_all = False
    return ok_all

def ensure_accounts_parent_access(users_root: Path, windows: Optional[bool] = None) -> bool:
    r"""Allow any local account to create its own child under C:\LocalAI\users.

    The grant is parent-only: it does not carry into account folders. Each
    users/<account> child immediately breaks inheritance and grants only that
    account, SYSTEM and Administrators full control.
    """
    from integrations.windows import acl
    from integrations.ollama.sharing import BUILTIN_USERS_SID
    if not acl.on_windows(windows):
        return True
    result = acl.run([
        "icacls", str(users_root), "/grant",
        "*%s:(RD,X,AD,RA,REA)" % BUILTIN_USERS_SID, "/Q",
    ])
    return result is not None and result.returncode == 0


def ensure_shared_runtime_lock_access(lock_path: Path, windows: Optional[bool] = None) -> bool:
    """Allow every local account to open the one machine-wide runtime lock.

    Shared binaries stay RX-only. The lock file itself needs read/write so an
    account can take an OS byte lock without gaining permission to modify the
    shared environment directory or replace binaries.
    """
    from integrations.windows import acl
    from integrations.ollama.sharing import BUILTIN_USERS_SID
    if not acl.on_windows(windows):
        return True
    result = acl.run([
        "icacls", str(lock_path), "/grant",
        "*%s:(R,W)" % BUILTIN_USERS_SID, "/Q",
    ])
    return result is not None and result.returncode == 0

def create_environment(env: Path, model_dir: Optional[Path] = None,
                       account_root: Optional[Path] = None) -> Dict[str, Path]:
    """새 설치용 공용 런타임과 이 계정의 개인 폴더를 생성한다.

    새 설치는 이전 경로를 검색하거나 옮기지 않는다. 공용 구성은 runtime root
    아래 environment/ollama/models 세 곳이고, 사용 기록은 users/<account> 아래다.
    """
    try:
        from ..i18n import t
        section(t("install.create_dirs"))
    except Exception:
        section("Creating environment folders")

    env = Path(env)
    models = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
    account = Path(account_root) if account_root is not None else ACCOUNT_ROOT

    # The shared parent must be creatable by a second standard Windows account,
    # otherwise only the installer/admin account can ever get its own private
    # users/<account> folder.
    users_root = account.parent
    users_root.mkdir(parents=True, exist_ok=True)
    if not ensure_accounts_parent_access(users_root):
        warn("다른 Windows 계정의 사용자 폴더 생성 권한을 설정하지 못했습니다: %s" % users_root)

    # A standard account may have permission to create users/<account> but no
    # inherited write grant inside it. As the creator/owner it can rewrite the
    # DACL, so do that immediately before making user_data/logs/workspace.
    try:
        account.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise RuntimeError(
            "이 Windows 계정의 개인 폴더를 만들 권한이 없습니다: %s. "
            "관리자 또는 기존 설치 계정에서 Setup을 실행해 "
            "C:\\LocalAI\\users 권한을 먼저 갱신하세요." % account
        ) from exc
    private_state = ensure_private_account(account)
    if private_state is not True:
        raise RuntimeError(
            "이 Windows 계정의 LocalAI 개인 폴더를 안전하게 잠그지 못했습니다: %s. "
            "설치를 중단합니다. 관리자 또는 기존 설치 계정에서 RUN.bat --install로 "
            "C:\\LocalAI\\users 권한을 복구한 뒤 다시 시도하세요." % account
        )

    paths = {
        "env":                   env,
        "ollama":                OLLAMA_INSTALL_DIR,
        "models":                models,
        "chat":                  env / "chat_ui",
        "agent":                 env / "agent",
        "sandbox":               env / "agent" / "sandbox",
        # The agent's default working folder holds the user's own files, so it
        # is theirs, not the machine's.
        "workspace":             account / "workspace",
        "open_interpreter":      env / "open_interpreter",
        "open_interpreter_bin":  env / "open_interpreter" / "bin",
        "open_interpreter_home": account / USER_DATA_DIRNAME / "interpreter" / "host",
        "searxng":               env / "searxng",
        "scripts":               env / "scripts",
        "logs":                  account / LOGS_DIRNAME,
        # Private to this Windows account. Settings, projects, chat history and
        # every agent trace are a record of what one person asked an AI to do.
        "account":               account,
        "user_data":             account / USER_DATA_DIRNAME,
        "session_logs":          account / LOGS_DIRNAME,
    }
    for name, p in paths.items():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            if name == "models":
                raise RuntimeError(
                    f"공용 모델 저장소를 만들 권한이 없습니다: {p}. "
                    "관리자 계정에서 RUN.bat --install을 한 번 실행하거나 폴더 권한을 확인하세요."
                ) from exc
            raise
        ok(f"  {name:<20} → {p}")

    # 공용 런타임/Ollama는 실행만 공유한다. models만 모든 계정이
    # 설치/삭제할 수 있는 machine-wide mutable state다.
    ensure_shared_runtime_access((env, paths["ollama"]))

    # Canonical LocalAI store: widen only this subtree before creating the
    # shared control files, so a standard second account can repair/use it.
    if model_dir is None:
        ensure_shared_model_access(models)

    model_control = model_control_dir(models)
    registry = model_registry_path(models)
    mutation_lock = model_mutation_lock_path(models)
    try:
        model_control.mkdir(parents=True, exist_ok=True)
        if not registry.exists():
            # Do not silently choose one account's per-account registry.
            registry.write_text("{}\n", encoding="utf-8")
        if not mutation_lock.exists():
            mutation_lock.write_bytes(b"\0")
    except OSError as exc:
        raise RuntimeError(
            "공용 모델 관리 폴더를 준비할 수 없습니다: %s (%s)" %
            (model_control, exc)
        ) from exc
    paths["model_control"] = model_control
    paths["model_registry"] = registry
    paths["model_mutation_lock"] = mutation_lock

    runtime_lock = env / RUNTIME_LOCK_NAME
    try:
        if not runtime_lock.exists():
            runtime_lock.write_bytes(b"\0")
        if not ensure_shared_runtime_lock_access(runtime_lock):
            warn("공용 런타임 잠금 파일 권한 설정 실패: %s" % runtime_lock)
    except OSError as exc:
        warn("공용 런타임 잠금 파일 준비 실패: %s (%s)" % (runtime_lock, exc))
    paths["runtime_lock"] = runtime_lock

    if model_dir is None:
        publish_shared_model_dir(models)
    return paths


ACCOUNT_MARKER = "ACCOUNT.txt"


def name_the_account(account: Path) -> None:
    """Record whose folder this is, in the account's real name.

    The folder name has to be ASCII and space-free - it ends up in a
    ``docker -v`` argument - so a Korean or spaced Windows account name is
    replaced by a fingerprint, and ``users\\user-9c6b9b1b`` tells nobody
    anything. The name itself goes inside, where no path rule applies.
    """
    from core import accounts
    marker = Path(account) / ACCOUNT_MARKER
    try:
        marker.write_text(
            "%s\n\n이 폴더는 위 Windows 계정 전용입니다.\n"
            "설정·프로젝트·대화·추적 기록·세션 로그가 들어 있고, 이 PC 의 다른\n"
            "계정은 읽을 수 없습니다. 모델은 공용이라 ..\\..\\models 에 한 벌만\n"
            "있습니다 — 계정마다 다시 받지 않습니다.\n" % accounts.current_name(),
            encoding="utf-8")
    except OSError:
        pass


def ensure_private_account(account: Path) -> Optional[bool]:
    """이 계정 폴더를 다른 Windows 계정이 못 읽게 잠근다.

    바로 옆 모델 저장소는 일부러 ``BUILTIN\\Users`` Modify를 허용한다 — 그래야
    두 번째 계정도 같은 모델을 쓰고 설치·삭제할 수 있다. 그 권한을 개인 기록이
    상속하면 안 되므로 계정 폴더에서 상속을 끊고 확인까지 한다.
    """
    from integrations.windows import privacy
    state = privacy.ensure_private(account)
    if state is True:
        # Write only after the creator's private/full-control ACL is in place.
        name_the_account(account)
        ok("  %-20s → %s (이 계정 전용)" % ("account", account))
    elif state is False:
        warn("개인 기록 폴더를 이 계정 전용으로 잠그지 못했습니다: %s" % account)
        warn("이 PC 의 다른 Windows 계정이 설정·대화·추적 기록을 읽을 수 있습니다.")
    return state


def write_install_manifest(
    paths: Dict[str, Path],
    project_root: Path,
    status: str,
    components: Iterable[str] = (),
    failed_components: Iterable[str] = (),
    skipped_components: Iterable[str] = (),
) -> Path:
    """설치 루트에 사람이 읽을 수 있는 설치 식별 JSON을 기록한다."""
    manifest = paths["env"] / INSTALL_MANIFEST
    now = datetime.now(timezone.utc).isoformat()

    installed_at = now
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            installed_at = previous.get("installed_at", now)
        except (OSError, ValueError, TypeError):
            pass

    data = {
        "schema_version": 3,
        "product": "Local AI Agent",
        "repository": "geeeeeonho/Local_AI_Agent",
        "managed_environment": True,
        "status": status,
        "project_root": str(Path(project_root).resolve()),
        "runtime_root": str(paths["env"].parent.resolve()),
        "environment_path": str(paths["env"].resolve()),
        "ollama_path": str(paths["ollama"].resolve()),
        "model_storage": str(paths["models"].resolve()),
        "account_path": str(paths["account"].resolve()),
        "model_storage_access": (
            "builtin-users-modify-requested; existing-acl-preserved"
        ),
        "components": list(components),
        "failed_components": list(failed_components),
        "skipped_components": list(skipped_components),
        "installed_at": installed_at,
        "updated_at": now,
        "note": "This directory is managed by Local AI Agent RUN.bat --install.",
    }
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
