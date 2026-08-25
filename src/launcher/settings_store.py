# -*- coding: utf-8 -*-
"""사용자 설정 저장소.

모든 영속 설정의 정본은 프로젝트 루트의
``user_data/settings/user_config.json`` 이다.

과거 버전의 설정 파일은 정본으로 병합한다. 일반적인 load/save/import 경로에서는
junction/symlink 를 만들지 않는다. 아직 레거시 경로를 직접 읽는 agent_runner 를
위한 호환 연결만 런처 시작 시 명시적으로 한 번 구성할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Optional

from project_paths import PROJECT_ROOT, SRC_ROOT
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
_AGENT_LEGACY_DIR = Path("launcher") / "agent" / "settings"
_AGENT_SRC_RUNTIME_DIR = Path("launcher") / "agent" / "settings"


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


def _same_target(link: Path, target: Path) -> bool:
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _remove_compat_path(link: Path) -> bool:
    """비어 있는 디렉터리나 기존 호환 링크만 안전하게 제거한다."""
    try:
        if link.is_symlink():
            link.unlink()
            return True
        if link.is_dir():
            if any(link.iterdir()):
                return False
            link.rmdir()
            return True
    except OSError:
        pass

    # Windows의 끊어진 junction은 Path.exists()가 False일 수 있다.
    if os.name == "nt" and os.path.lexists(str(link)):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["cmd", "/c", "rmdir", str(link)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creationflags,
        )
        return result.returncode == 0
    return not os.path.lexists(str(link))


def _agent_runtime_compat_dir(root: Path) -> Path:
    """agent_runner가 실제로 읽는 설정 호환 디렉터리를 반환한다.

    현재 애플리케이션은 ``src/launcher/agent`` 에서 실행되므로 정본 프로젝트
    루트에 대해서는 그 실제 소스 위치를 사용한다. 임의의 외부 프로젝트 루트를
    넘기는 마이그레이션/테스트 호출은 과거 레이아웃을 그대로 유지한다.
    """
    candidate = Path(root)
    try:
        if candidate.resolve() == PROJECT_ROOT.resolve():
            return SRC_ROOT / _AGENT_SRC_RUNTIME_DIR
    except OSError:
        pass
    return candidate / _AGENT_LEGACY_DIR


def ensure_agent_settings_compat(project_root: Path | None = None) -> bool:
    """agent_runner의 직접 설정 경로 하나만 정본 디렉터리로 연결한다.

    일반 설정 API에서는 호출하지 않는다. 런처 시작 시 한 번만 호출하도록 분리해
    import 부작용과 반복적인 파일시스템 점검을 피한다.
    """
    root = _root(project_root)
    if not migrate_legacy_settings(root):
        return False

    link = _agent_runtime_compat_dir(root)
    target = path(root).parent
    if _same_target(link, target):
        return True

    if os.path.lexists(str(link)) and not _remove_compat_path(link):
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
    """이전 API 호환 별칭. agent_runner 호환 연결 하나만 구성한다."""
    return ensure_agent_settings_compat(project_root)


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
