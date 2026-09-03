"""installer.core.filesystem — 환경 폴더 구조와 설치 식별 정보 관리."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from project_paths import MODEL_STORAGE_DIR

from .console import section, ok, warn


INSTALL_MANIFEST = "LOCAL_AI_AGENT_INSTALL.json"


def _migrate_legacy_models(env: Path, models: Path) -> None:
    """과거 ``llm_environment/llm_models`` 를 공용 저장소로 안전하게 옮긴다."""
    legacy = env / "llm_models"
    if not legacy.exists() or legacy == models:
        return

    models.parent.mkdir(parents=True, exist_ok=True)
    target_is_empty = models.exists() and not any(models.iterdir())
    if target_is_empty:
        models.rmdir()

    if not models.exists():
        shutil.move(str(legacy), str(models))
        ok(f"  legacy models       → {models}")
        return

    warn(
        f"기존 모델 폴더가 남아 있습니다: {legacy} / "
        f"공용 저장소가 이미 사용 중이므로 자동 병합하지 않습니다: {models}"
    )


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

    models = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
    _migrate_legacy_models(env, models)

    paths = {
        "env":                  env,
        "ollama":               env / "ollama_runtime",
        "models":               models,
        "chat":                 env / "chat_ui",
        "agent":                env / "agent",
        "sandbox":              env / "agent" / "sandbox",
        "workspace":            env / "agent" / "workspace",
        "open_interpreter":     env / "open_interpreter",
        "open_interpreter_bin": env / "open_interpreter" / "bin",
        "open_interpreter_home": env / "open_interpreter" / "home",
        "searxng":              env / "searxng",
        "scripts":              env / "scripts",
        "logs":                 env / "logs",
    }
    for name, p in paths.items():
        p.mkdir(parents=True, exist_ok=True)
        ok(f"  {name:<20} → {p}")
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
