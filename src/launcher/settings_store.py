# -*- coding: utf-8 -*-
"""사용자 설정 저장소.

모든 영속 설정의 정본은 프로젝트 루트의
``user_data/settings/user_config.json`` 이다.

과거 버전의 설정 파일은 정본으로 병합한다. 이 저장소는 junction/symlink 를 만들지
않는다. 예전에는 레거시 경로를 직접 읽는 agent_runner 를 위해 소스 트리 안으로
junction 을 걸었지만, 그 런타임이 사라져 호환 연결도 함께 제거했다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
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
        # Preserve an explicitly supplied root exactly as the caller expressed
        # it. On Windows, Path.resolve() can expand an 8.3 short path such as
        # RUNNER~1 to its long form, which changes the canonical path object's
        # representation even though it points at the same directory.
        # Target-comparison helpers below resolve paths explicitly when actual
        # filesystem identity is required.
        return Path(project_root)
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


def _points_to_canonical(candidate: Path, canonical: Path) -> bool:
    """레거시 경로가 링크/junction을 통해 정본 자체를 가리키는지 확인."""
    try:
        return candidate.resolve() == canonical.resolve()
    except OSError:
        return False


def _cleanup_legacy_files(root: Path, canonical: Path) -> None:
    """마이그레이션된 알려진 설정 파일만 제거하고 정본은 절대 지우지 않는다."""
    for legacy in _legacy_files(root):
        if _points_to_canonical(legacy, canonical):
            continue
        try:
            if legacy.is_file() or legacy.is_symlink():
                legacy.unlink()
        except OSError:
            pass


def migrate_legacy_settings(project_root: Path | None = None) -> bool:
    """레거시 설정을 정본으로 병합한다. 링크나 junction 은 만들지 않는다."""
    root = _root(project_root)
    canonical = path(root)
    canonical_data = _read_dict(canonical) if canonical.exists() else {}

    merged: dict[str, Any] = {}
    found_legacy = False
    for legacy in _legacy_files(root):
        if not legacy.exists() or _points_to_canonical(legacy, canonical):
            continue
        found_legacy = True
        merged.update(_read_dict(legacy))
    merged.update(canonical_data)

    if merged and canonical_data != merged:
        if not _write_dict(canonical, merged):
            return False

    if found_legacy and canonical.exists():
        _cleanup_legacy_files(root, canonical)
    return True


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


def logging_enabled(project_root: Path | None = None) -> bool:
    """Detailed agent input/output logging switch (settings menu [5])."""
    try:
        return bool(load(project_root).logging_enabled)
    except Exception:
        return True


def set_logging_enabled(enabled: bool, project_root: Path | None = None) -> bool:
    cfg = load(project_root)
    cfg.logging_enabled = bool(enabled)
    return save(cfg, project_root)
