"""installer.core.filesystem — 환경 폴더 구조와 설치 식별 정보 관리."""
from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from project_paths import MODEL_STORAGE_DIR

from .console import section, ok, warn


INSTALL_MANIFEST = "LOCAL_AI_AGENT_INSTALL.json"
_MIGRATION_COMPLETE_MARKER = ".LOCAL_AI_MIGRATION_COMPLETE"
_BUILTIN_USERS_SID = "S-1-5-32-545"


def ensure_shared_model_access(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 로컬 사용자도 공용 모델을 읽을 수 있도록 최소 권한을 보장한다.

    모델 저장소는 AI 동작에 영향을 주는 신뢰 자산이므로 모든 사용자에게 쓰기
    권한을 열지는 않는다. ``BUILTIN\\Users`` 에 읽기/실행 권한을 재귀적으로
    추가하고 기존 ACL은 보존한다.
    """
    use_windows = (os.name == "nt") if windows is None else bool(windows)
    if not use_windows:
        return True

    command = [
        "icacls",
        str(model_dir),
        "/grant",
        f"*{_BUILTIN_USERS_SID}:(OI)(CI)(RX)",
        "/T",
        "/Q",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"공용 모델 폴더 읽기 권한 설정 실패: {exc}")
        return False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        warn(f"공용 모델 폴더 읽기 권한 설정 실패: {detail or 'icacls error'}")
        return False
    return True


def _remove_migration_staging(staging: Path) -> None:
    if staging.is_dir():
        shutil.rmtree(staging)
    elif staging.exists():
        staging.unlink()


def _promote_staging(staging: Path, models: Path) -> None:
    marker = staging / _MIGRATION_COMPLETE_MARKER
    marker.unlink(missing_ok=True)
    staging.replace(models)
    ok(f"  staged models       → {models}")


def _migrate_legacy_models(env: Path, models: Path) -> None:
    """과거 ``llm_environment/llm_models`` 를 공용 저장소로 안전하게 옮긴다.

    같은 볼륨에서는 rename 으로 이동한다. 다른 볼륨에서는 staging 에 전체 복사한
    뒤 완료 marker 를 기록하고 원본을 지운다. 따라서 복사·원본 정리·최종 승격 중
    어느 지점에서 중단돼도 다음 실행이 완성본과 부분 복사본을 구분할 수 있다.
    """
    legacy = env / "llm_models"
    staging = models.with_name(models.name + ".migrating")
    marker = staging / _MIGRATION_COMPLETE_MARKER
    if legacy == models:
        return

    models.parent.mkdir(parents=True, exist_ok=True)

    # 이전 실행이 빈 최종 폴더만 만든 경우에는 복구/마이그레이션을 계속할 수 있다.
    if models.exists() and models.is_dir() and not any(models.iterdir()):
        models.rmdir()

    # 사용 중인 최종 저장소와 레거시/스테이징을 임의 병합하지 않는다.
    if models.exists():
        if legacy.exists() or staging.exists():
            warn(
                f"기존 모델 데이터가 남아 있습니다: {legacy} / {staging} / "
                f"공용 저장소가 이미 사용 중이므로 자동 병합하지 않습니다: {models}"
            )
        return

    if staging.exists():
        if marker.is_file():
            # 복사는 완전히 끝났고 원본 삭제 중 중단된 상태일 수 있다. marker가
            # staging 완전성을 증명하므로 남은 원본보다 staging을 정본으로 삼는다.
            if legacy.exists():
                shutil.rmtree(legacy)
            _promote_staging(staging, models)
            return

        if not legacy.exists():
            # 같은 볼륨 rename 뒤 최종 승격 직전에 중단됐거나, 이전 버전이 만든
            # 유일한 staging이다. 원본이 없으므로 staging을 보존한다.
            _promote_staging(staging, models)
            return

        # marker 없이 원본도 남아 있으면 복사 도중 중단된 부분 staging으로 본다.
        _remove_migration_staging(staging)

    if not legacy.exists():
        return

    try:
        # 같은 볼륨은 원본 삭제와 복사를 분리할 필요 없이 atomic rename 가능.
        legacy.replace(staging)
    except OSError as exc:
        cross_volume = exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17
        if not cross_volume:
            raise

        # 다른 볼륨은 명시적으로 copy → marker → source cleanup 순서를 지킨다.
        # copytree가 실패하면 원본은 그대로 남고 marker가 없으므로 다음 실행에서
        # 부분 staging을 폐기하고 다시 시작한다.
        shutil.copytree(legacy, staging, copy_function=shutil.copy2, symlinks=True)
        marker.write_text("complete\n", encoding="utf-8")
        shutil.rmtree(legacy)

    _promote_staging(staging, models)


def create_environment(env: Path, model_dir: Optional[Path] = None) -> Dict[str, Path]:
    """관리 환경 트리와 공용 모델 저장소를 생성해 경로 dict를 반환한다.

    모델은 프로젝트 체크아웃과 분리된 ``C:\\LLM_Models`` 를 기본으로 사용한다.
    테스트나 관리형 배포에서는 ``model_dir`` 로 명시적으로 재정의할 수 있다.
    """
    try:
        from ..i18n import t
        section(t("install.create_dirs"))
    except Exception:
        section("Creating environment folders")

    env = Path(env)
    models = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
    _migrate_legacy_models(env, models)

    paths = {
        "env":                   env,
        "ollama":                env / "ollama_runtime",
        "models":                models,
        "chat":                  env / "chat_ui",
        "agent":                 env / "agent",
        "sandbox":               env / "agent" / "sandbox",
        "workspace":             env / "agent" / "workspace",
        "open_interpreter":      env / "open_interpreter",
        "open_interpreter_bin":  env / "open_interpreter" / "bin",
        "open_interpreter_home": env / "open_interpreter" / "home",
        "searxng":               env / "searxng",
        "scripts":               env / "scripts",
        "logs":                  env / "logs",
    }
    for name, p in paths.items():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            if name == "models":
                raise RuntimeError(
                    f"공용 모델 저장소를 만들 권한이 없습니다: {p}. "
                    "관리자 계정에서 SETUP.bat을 한 번 실행하거나 폴더 권한을 확인하세요."
                ) from exc
            raise
        ok(f"  {name:<20} → {p}")

    # 기본 머신 공용 경로에서만 Windows 로컬 사용자 읽기 권한을 보장한다.
    if model_dir is None:
        ensure_shared_model_access(models)
    return paths


def write_install_manifest(
    paths: Dict[str, Path],
    project_root: Path,
    status: str,
    components: Iterable[str] = (),
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
        "product": "Local AI Agent",
        "repository": "geeeeeonho/Local_AI_Agent",
        "managed_environment": True,
        "status": status,
        "project_root": str(Path(project_root).resolve()),
        "environment_path": str(paths["env"].resolve()),
        "model_storage": str(paths["models"].resolve()),
        "model_storage_access": (
            "builtin-users-read-execute-requested; existing-acl-preserved"
        ),
        "components": list(components),
        "installed_at": installed_at,
        "updated_at": now,
        "note": "This directory is managed by Local AI Agent SETUP.bat.",
    }
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
