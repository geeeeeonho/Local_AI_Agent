"""installer.core.filesystem — 환경 폴더 구조와 설치 식별 정보 관리."""
from __future__ import annotations

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
_BUILTIN_USERS_SID = "S-1-5-32-545"


def ensure_shared_model_access(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 로컬 사용자도 공용 모델을 읽을 수 있도록 최소 권한을 보장한다.

    모델 저장소는 AI 동작에 영향을 주는 신뢰 자산이므로 모든 사용자에게 쓰기
    권한을 열지는 않는다. ``BUILTIN\\Users`` 에 읽기/실행만 상속시키고, 모델
    추가/삭제는 폴더 소유자나 관리자 권한으로 수행한다.
    """
    use_windows = (os.name == "nt") if windows is None else bool(windows)
    if not use_windows:
        return True

    command = [
        "icacls",
        str(model_dir),
        "/grant",
        f"*{_BUILTIN_USERS_SID}:(OI)(CI)(RX)",
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


def _migrate_legacy_models(env: Path, models: Path) -> None:
    """과거 ``llm_environment/llm_models`` 를 공용 저장소로 안전하게 옮긴다.

    프로젝트가 다른 드라이브에 있으면 ``shutil.move`` 는 내부적으로 복사 후
    원본 삭제가 된다. 중간 종료 시 최종 ``LLM_Models`` 가 부분 상태로 보이지
    않도록 같은 대상 드라이브의 ``.migrating`` 폴더를 staging 으로 사용한다.
    """
    legacy = env / "llm_models"
    staging = models.with_name(models.name + ".migrating")
    if legacy == models:
        return

    models.parent.mkdir(parents=True, exist_ok=True)

    # 이전 실행에서 staging 이동까지 끝났지만 최종 이름 승격 직전에 중단된 경우.
    if staging.exists() and not legacy.exists() and not models.exists():
        staging.replace(models)
        ok(f"  staged models       → {models}")
        return

    # 복사 도중 중단되면 shutil.move 는 원본을 남긴다. 이 경우 부분 staging 만
    # 버리고 원본에서 다시 시작한다.
    if staging.exists() and legacy.exists() and not models.exists():
        _remove_migration_staging(staging)

    if not legacy.exists():
        return

    # create_environment 의 이전 실행 등이 빈 최종 폴더만 만든 경우에는 제거하고
    # staging 마이그레이션을 계속할 수 있다.
    if models.exists() and models.is_dir() and not any(models.iterdir()):
        models.rmdir()

    if models.exists():
        # 최종 저장소가 이미 사용 중이면 사용자의 두 데이터 세트를 임의 병합하지
        # 않는다. staging 이 있고 legacy 도 남아 있다면 staging 은 부분 복사본으로
        # 확정할 수 있으므로 그것만 정리한다.
        if staging.exists() and legacy.exists():
            _remove_migration_staging(staging)
        warn(
            f"기존 모델 폴더가 남아 있습니다: {legacy} / "
            f"공용 저장소가 이미 사용 중이므로 자동 병합하지 않습니다: {models}"
        )
        return

    if staging.exists():
        # 여기까지 왔는데 staging 이 남아 있으면 원본이 유일한 기준이므로 안전하게
        # 지우고 다시 이동한다.
        _remove_migration_staging(staging)

    shutil.move(str(legacy), str(staging))
    staging.replace(models)
    ok(f"  legacy models       → {models}")


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
        "model_storage_access": "local-users-read; owner/admin-manage",
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
