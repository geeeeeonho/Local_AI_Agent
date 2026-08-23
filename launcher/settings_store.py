# -*- coding: utf-8 -*-
"""사용자 설정 저장소.

모든 영속 설정의 정본은 프로젝트 루트의
``user_data/settings/user_config.json`` 이다.

과거 버전의 ``launcher/settings`` 와 ``launcher/agent/settings`` 에 남은
``user_config.json`` 은 최초 로드 시 정본으로 병합한 뒤 제거한다. 디렉터리
junction/symlink 는 만들지 않으므로 프로젝트 이동과 권한 상태에 영향을 받지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Optional

from .core import user_data


@dataclass
class Settings:
    schema_version: int = 1
    language: Optional[str] = None
    last_workspace: Optional[str] = None
    last_menu_choice: Optional[str] = None
    logging_enabled: bool = True
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)


_KNOWN_FIELDS = {
    "schema_version", "language", "last_workspace",
    "last_menu_choice", "logging_enabled",
}
_LEGACY_DIRS = (
    Path("launcher") / "settings",
    Path("launcher") / "agent" / "settings",
)


def _root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return Path(project_root).resolve()
    return user_data.project_root()


def path(project_root: Path | None = None) -> Path:
    """정본 설정 파일 경로를 반환한다."""
    root = _root(project_root)
    p = root / "user_data" / "settings" / "user_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_dict(p: Path) -> dict[str, Any]:
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_dict(p: Path, data: dict[str, Any]) -> bool:
    return user_data.save_json(p, data)


def _legacy_files(root: Path) -> list[Path]:
    return [root / rel / "user_config.json" for rel in _LEGACY_DIRS]


def _cleanup_legacy_files(root: Path) -> None:
    """마이그레이션된 알려진 설정 파일만 제거하고 디렉터리는 보존한다."""
    for legacy in _legacy_files(root):
        try:
            if legacy.is_file() or legacy.is_symlink():
                legacy.unlink()
        except OSError:
            pass


def migrate_legacy_settings(project_root: Path | None = None) -> bool:
    """레거시 설정을 정본으로 병합한다. 링크나 junction 은 생성하지 않는다."""
    root = _root(project_root)
    canonical = path(root)
    canonical_data = _read_dict(canonical) if canonical.exists() else {}

    merged: dict[str, Any] = {}
    found_legacy = False
    for legacy in _legacy_files(root):
        if legacy.exists():
            found_legacy = True
            merged.update(_read_dict(legacy))
    merged.update(canonical_data)

    if merged and canonical_data != merged:
        if not _write_dict(canonical, merged):
            return False
    elif found_legacy and not canonical.exists():
        if not _write_dict(canonical, merged):
            return False

    if found_legacy and (canonical.exists() or not merged):
        _cleanup_legacy_files(root)
    return True


def ensure_legacy_bridges(project_root: Path | None = None) -> bool:
    """이전 API 호환 별칭. 이제 링크 대신 설정 마이그레이션만 수행한다."""
    return migrate_legacy_settings(project_root)


def _merged_data(project_root: Path | None = None) -> dict[str, Any]:
    root = _root(project_root)
    migrate_legacy_settings(root)
    canonical = path(root)
    return _read_dict(canonical) if canonical.exists() else {}


def load(project_root: Path | None = None) -> Settings:
    data = _merged_data(project_root)
    known = {k: v for k, v in data.items() if k in _KNOWN_FIELDS}
    extra = {k: v for k, v in data.items() if k not in _KNOWN_FIELDS}
    try:
        cfg = Settings(**known)
    except (TypeError, ValueError):
        cfg = Settings()
    cfg._extra = extra
    return cfg


def save(cfg: Settings, project_root: Path | None = None) -> bool:
    data = dict(cfg._extra)
    data.update({
        "schema_version": max(int(cfg.schema_version or 1), 1),
        "language": cfg.language,
        "last_workspace": cfg.last_workspace,
        "last_menu_choice": cfg.last_menu_choice,
        "logging_enabled": bool(cfg.logging_enabled),
    })
    return _write_dict(path(project_root), data)


def reset(project_root: Path | None = None) -> bool:
    """사용자 설정을 기본값으로 초기화한다."""
    return save(Settings(), project_root)


def update_language(cfg: Settings, lang: str) -> Settings:
    cfg.language = lang
    return cfg


def update_last_menu_choice(cfg: Settings, choice: str | None) -> Settings:
    cfg.last_menu_choice = choice
    return cfg


def update_last_workspace(cfg: Settings, workspace: str | Path | None) -> Settings:
    cfg.last_workspace = None if workspace is None else str(workspace)
    return cfg
