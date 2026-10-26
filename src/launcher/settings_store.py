# -*- coding: utf-8 -*-
"""사용자 설정 저장소.

모든 영속 설정의 정본은 런타임 루트의
``user_data/settings/user_config.json`` 이다. 위치는 ``project_paths`` 한
곳에서 정하고 여기서는 물어보기만 한다 — "프로젝트 루트 + user_data" 를
모듈마다 따로 조립하던 것이 설치기와 데스크톱이 서로 다른 폴더에 쓰던
원인이었다.

설정 읽기/쓰기는 이 정본 한 곳만 사용한다. 이전 소스 트리의 설정 파일을
자동 검색·병합·삭제하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Optional

from core import vault

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
def _data_root(project_root: Path | None = None) -> Path:
    """설정이 실제로 놓이는 user_data 폴더.

    명시적으로 루트를 받으면 그 밑의 ``user_data`` 를 쓴다 — 테스트와 포터블
    실행이 프로젝트 하나를 통째로 옮기는 방식이라 그대로 유지한다.
    """
    if project_root is not None:
        return Path(project_root) / "user_data"
    return user_data.root()


def path(project_root: Path | None = None) -> Path:
    """정본 설정 파일 경로를 반환한다."""
    p = _data_root(project_root) / "settings" / "user_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_dict(p: Path) -> dict[str, Any]:
    try:
        value = json.loads(vault.read_text(p))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_dict(p: Path, data: dict[str, Any]) -> bool:
    return user_data.save_json(p, data)


def _merged_data(project_root: Path | None = None) -> dict[str, Any]:
    """Read only the canonical store; never import state from old layouts."""
    canonical = path(project_root)
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
