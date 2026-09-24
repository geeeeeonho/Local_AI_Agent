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

from project_paths import LEGACY_FORCED_MODEL_DIR, MODEL_STORAGE_DIR

from .console import section, ok, warn


INSTALL_MANIFEST = "LOCAL_AI_AGENT_INSTALL.json"
_MIGRATION_COMPLETE_MARKER = ".LOCAL_AI_MIGRATION_COMPLETE"
def ensure_shared_model_access(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 로컬 사용자도 공용 모델을 읽을 수 있도록 최소 권한을 보장한다.

    정본은 ``integrations.ollama.sharing`` 이다. 설치 때 한 번만이 아니라
    나중에도 확인·복구할 수 있어야 해서 그쪽으로 옮겼고, 여기서는 설치
    화면이 쓰는 이름만 유지한다.
    """
    from integrations.ollama import sharing
    if sharing.ensure_readable(model_dir, windows=windows):
        return True
    warn("공용 모델 폴더 읽기 권한 설정 실패")
    return False


def publish_shared_model_dir(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 Windows 계정도 같은 저장소를 보도록 시스템 환경변수에 기록한다.

    읽기 권한만으로는 부족하다. 다른 계정의 Ollama 는 자기 프로필 밑
    ``.ollama\\models`` 를 보므로, 시스템 범위 ``OLLAMA_MODELS`` 가 있어야
    같은 모델을 가리킨다.

    관리자 권한이 필요하다. 실패해도 설치를 중단하지 않는다 — 이 계정에서는
    실행 시 주입하는 값으로 계속 동작하고, 모델 화면에서 나중에 고칠 수 있다.
    """
    from integrations.ollama import sharing
    if sharing.publish_machine_variable(model_dir, windows=windows):
        return True
    warn("시스템 범위 OLLAMA_MODELS 설정 실패")
    warn("이 계정에서는 정상 동작하지만, 다른 Windows 계정은 같은 모델을 "
         "보지 못합니다. 모델 화면의 '모든 계정 공용으로 고치기' 를 "
         "관리자 권한으로 한 번 실행하세요.")
    return False


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


def legacy_model_stores(env: Path, models: Path) -> list:
    """이 프로젝트가 예전에 모델을 두던 위치들. 최근 것부터.

    ``C:\\LLM_Models`` 는 Ollama 가 위치를 갖기 전에 이 프로젝트가 강제하던
    저장소다. Ollama 를 따라가기 시작하면 그 폴더는 Ollama 눈에 안 보이므로,
    설치기가 찾아서 옮겨 줘야 수십 GB 가 사라진 것처럼 보이지 않는다.
    """
    out = []
    for candidate in (LEGACY_FORCED_MODEL_DIR, env / "llm_models"):
        candidate = Path(candidate)
        if candidate != models and candidate not in out:
            out.append(candidate)
    return out


def _staging_origin(marker: Path):
    """Which store a completed staging was copied from, if it recorded one."""
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return Path(lines[1]) if len(lines) > 1 and lines[1].strip() else None


def _resume_staging(staging: Path, marker: Path, models: Path, sources: list) -> bool:
    """이전 실행이 남긴 staging 을 정리한다. 승격했으면 True.

    marker 는 복사가 끝났다는 증거이고, 어느 원본에서 왔는지도 함께 적는다.
    출처가 적혀 있지 않은 구버전 marker 는 남아 있는 후보가 하나뿐일 때만 그것을
    출처로 본다. 후보가 여럿이면 아무것도 지우지 않는다 — 복사되지 않은 원본을
    지우는 것보다 중복이 남는 편이 낫다.
    """
    if not staging.exists():
        return False
    if not marker.is_file():
        if any(source.exists() for source in sources):
            # 원본이 남아 있으면 복사 도중 중단된 부분 staging 이다. 버리고 다시.
            _remove_migration_staging(staging)
            return False
        # 원본이 없다 = 같은 볼륨 rename 이 끝나고 승격 직전에 멈춘 상태다.
        # 여기서 staging 을 버리면 남은 유일한 사본을 지우는 것이 된다.
        _promote_staging(staging, models)
        return True
    origin = _staging_origin(marker)
    if origin is None:
        present = [s for s in sources if s.exists()]
        origin = present[0] if len(present) == 1 else None
    if origin is not None and origin.exists():
        shutil.rmtree(origin)
    _promote_staging(staging, models)
    return True


def _move_store(legacy: Path, staging: Path, marker: Path, models: Path) -> None:
    """한 저장소를 staging 을 거쳐 최종 위치로 옮긴다."""
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
        marker.write_text("complete\n%s\n" % legacy, encoding="utf-8")
        shutil.rmtree(legacy)

    _promote_staging(staging, models)


def _migrate_legacy_models(env: Path, models: Path) -> None:
    """예전 저장소들을 Ollama 가 보는 위치로 안전하게 옮긴다.

    같은 볼륨에서는 rename 으로 이동한다. 다른 볼륨에서는 staging 에 전체 복사한
    뒤 완료 marker 를 기록하고 원본을 지운다. 따라서 복사·원본 정리·최종 승격 중
    어느 지점에서 중단돼도 다음 실행이 완성본과 부분 복사본을 구분할 수 있다.

    저장소가 여러 곳일 수 있으므로 staging 은 루프 밖에서 한 번만 정리한다.
    staging 은 특정 원본 하나의 복사본이라, 각 원본마다 따로 다루면 A 를 옮기다
    B 의 staging 을 승격시키고 B 의 원본을 남기게 된다.
    """
    staging = models.with_name(models.name + ".migrating")
    marker = staging / _MIGRATION_COMPLETE_MARKER
    sources = [s for s in legacy_model_stores(env, models) if s != models]

    models.parent.mkdir(parents=True, exist_ok=True)

    # 이전 실행이 빈 최종 폴더만 만든 경우에는 복구/마이그레이션을 계속할 수 있다.
    if models.exists() and models.is_dir() and not any(models.iterdir()):
        models.rmdir()

    promoted = False
    if not models.exists():
        promoted = _resume_staging(staging, marker, models, sources)

    # 사용 중인 최종 저장소와 레거시를 임의 병합하지 않는다.
    if models.exists():
        leftovers = [s for s in sources if s.exists()] + ([staging] if staging.exists() else [])
        if leftovers and not promoted:
            warn(
                "기존 모델 데이터가 남아 있습니다: "
                + " / ".join(str(p) for p in leftovers)
                + f" / 공용 저장소가 이미 사용 중이므로 자동 병합하지 않습니다: {models}"
            )
        elif leftovers:
            warn(
                "옮기고 남은 예전 모델 데이터가 있습니다: "
                + " / ".join(str(p) for p in leftovers)
                + " / 내용을 확인한 뒤 직접 지우세요. 자동 병합하지 않습니다."
            )
        return

    for source in sources:
        if source.exists():
            _move_store(source, staging, marker, models)
            return


def create_environment(env: Path, model_dir: Optional[Path] = None) -> Dict[str, Path]:
    """관리 환경 트리와 공용 모델 저장소를 생성해 경로 dict를 반환한다.

    모델은 프로젝트 체크아웃과 분리된 Ollama 공용 저장소
    ``C:\\Ollama\\models`` 를 기본으로 사용한다. 예전 ``C:\\LLM_Models``
    저장소는 비어 있는 공용 저장소로 안전하게 이전한다. 테스트나 관리형
    배포에서는 ``model_dir`` 로 명시적으로 재정의할 수 있다.
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
                    "관리자 계정에서 RUN.bat --install을 한 번 실행하거나 폴더 권한을 확인하세요."
                ) from exc
            raise
        ok(f"  {name:<20} → {p}")

    # 기본 경로일 때만 기계 공용으로 만든다. 명시적으로 지정된 경로는
    # 호출자의 것이므로 권한이나 시스템 환경변수를 건드리지 않는다.
    if model_dir is None:
        ensure_shared_model_access(models)
        publish_shared_model_dir(models)
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
        "note": "This directory is managed by Local AI Agent RUN.bat --install.",
    }
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
