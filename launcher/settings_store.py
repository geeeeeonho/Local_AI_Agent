# -*- coding: utf-8 -*-
"""사용자 설정 저장소.

모든 영속 설정의 정본은 프로젝트 루트의
``user_data/settings/user_config.json`` 이다.

과거 버전이 사용하던 ``launcher/settings`` 와
``launcher/agent/settings`` 는 실행 시 정본 디렉터리를 가리키는 호환 링크로
전환한다. 기존 ``user_config.json`` 이 있으면 먼저 병합한 뒤 링크를 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
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


def _merged_data(project_root: Path | None = None) -> dict[str, Any]:
    """레거시 설정을 먼저 읽고 정본 설정으로 덮어쓴 병합 결과."""
    root = _root(project_root)
    merged: dict[str, Any] = {}
    for rel in _LEGACY_DIRS:
        legacy = root / rel / "user_config.json"
        if legacy.exists():
            merged.update(_read_dict(legacy))

    canonical = path(root)
    canonical_data = _read_dict(canonical) if canonical.exists() else {}
    merged.update(canonical_data)

    if merged and canonical_data != merged:
        _write_dict(canonical, merged)
    return merged


def _remove_known_legacy_file(directory: Path) -> None:
    cfg = directory / "user_config.json"
    try:
        if cfg.is_file() or cfg.is_symlink():
            cfg.unlink()
    except OSError:
        pass


def _same_target(link: Path, target: Path) -> bool:
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _bridge_directory(link: Path, target: Path) -> bool:
    """link 디렉터리를 target 으로 연결한다. 알 수 없는 파일은 삭제하지 않는다."""
    if link.exists() or link.is_symlink():
        if _same_target(link, target):
            return True
        if link.is_symlink():
            try:
                link.unlink()
            except OSError:
                return False
        elif link.is_dir():
            _remove_known_legacy_file(link)
            try:
                if any(link.iterdir()):
                    return False
                link.rmdir()
            except OSError:
                return False
        else:
            return False

    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)

    try:
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=creationflags,
            )
            return result.returncode == 0 and _same_target(link, target)
        link.symlink_to(target, target_is_directory=True)
        return _same_target(link, target)
    except OSError:
        return False


def ensure_legacy_bridges(project_root: Path | None = None) -> bool:
    """레거시 설정을 정본으로 이전하고 과거 경로를 호환 링크로 만든다."""
    root = _root(project_root)
    _merged_data(root)
    target = path(root).parent
    results = [_bridge_directory(root / rel, target) for rel in _LEGACY_DIRS]
    return all(results)


def load(project_root: Path | None = None) -> Settings:
    data = _merged_data(project_root)
    ensure_legacy_bridges(project_root)
    known = {k: v for k, v in data.items() if k in _KNOWN_FIELDS}
    extra = {k: v for k, v in data.items() if k not in _KNOWN_FIELDS}
    try:
        cfg = Settings(**known)
    except TypeError:
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
    ok = _write_dict(path(project_root), data)
    if ok:
        ensure_legacy_bridges(project_root)
    return ok


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
