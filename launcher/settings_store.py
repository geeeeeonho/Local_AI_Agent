"""settings — 사용자 설정 영속화 (JSON).

설계 원칙:
  - 안전 정보만 저장 (경로, 일반 옵션, 마지막 선택)
  - 위험 옵션 (privileged, allow_internet 등) 은 저장하지 않거나
    로드 시 강제로 False — 매 실행 시 명시적 확인을 다시 거치도록
  - 손상된 JSON 은 무시하고 기본값 사용 (방어적)
  - 스키마 버전 관리로 향후 호환성 유지
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Set

from . import ui

SCHEMA_VERSION = 1

# ─── 파일 위치 ───
# launcher/ 폴더 밑의 settings/user_config.json
_SETTINGS_DIR = Path(__file__).resolve().parent / "settings"
_CONFIG_FILE  = _SETTINGS_DIR / "user_config.json"

# ─── 위험 옵션 ID 목록 ───
# 이들은 저장하더라도 로드 시 항상 False 로 강제됨
DANGEROUS_OPTION_IDS = frozenset({
    "allow_internet",
    "no_resource_limit",
    "privileged",
})


@dataclass
class UserConfig:
    """저장 가능한 사용자 설정."""
    schema_version: int = SCHEMA_VERSION

    # 언어 코드 ('en', 'ko' 등)
    language: Optional[str] = None

    # 마지막 워크스페이스 경로 (절대 경로 문자열)
    last_workspace: Optional[str] = None

    # 마지막 메뉴 선택 (편의용)
    last_menu_choice: Optional[str] = None

    # 마지막 사용 모델 태그 (참조용, 강제 적용 X)
    last_model_tag: Optional[str] = None

    # 안전한 샌드박스 옵션 체크 상태
    # 위험 옵션은 여기 들어가도 로드 시 무시됨
    sandbox_safe_options: list = field(default_factory=lambda: [
        "isolation",
        "block_internet",
        "cpu_limit",
        "memory_limit",
        "auto_run",
    ])


# ───────── 직렬화 / 역직렬화 ─────────

def _ensure_dir():
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> UserConfig:
    """디스크에서 설정 로드. 실패하면 기본값."""
    if not _CONFIG_FILE.exists():
        return UserConfig()

    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        ui.warn(f"설정 파일 손상 — 기본값 사용 ({e})")
        return UserConfig()

    # 스키마 버전 호환성
    version = data.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        ui.warn(f"설정 파일이 더 새 버전 ({version}) — 기본값 사용")
        return UserConfig()

    # 모르는 키는 무시, 알려진 키만 채택 (방어적 역직렬화)
    return UserConfig(
        schema_version=SCHEMA_VERSION,
        language=data.get("language"),
        last_workspace=data.get("last_workspace"),
        last_menu_choice=data.get("last_menu_choice"),
        last_model_tag=data.get("last_model_tag"),
        sandbox_safe_options=data.get("sandbox_safe_options",
                                      UserConfig().sandbox_safe_options),
    )


def save(cfg: UserConfig):
    """설정을 디스크에 저장."""
    _ensure_dir()
    cfg.schema_version = SCHEMA_VERSION
    try:
        _CONFIG_FILE.write_text(
            json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        ui.warn(f"설정 저장 실패: {e}")


# ───────── 샌드박스 옵션 영속화 헬퍼 ─────────

def get_sandbox_defaults(cfg: UserConfig, all_safe_ids: Set[str]) -> Set[str]:
    """저장된 옵션을 기본값으로 변환.

    - 저장된 옵션 중 위험 옵션은 제외 (보안)
    - 저장된 옵션 중 더 이상 존재하지 않는 ID 는 제외
    - 결과는 'safe id 와 교집합 빼기 위험 id' 만 남음
    """
    saved = set(cfg.sandbox_safe_options or [])
    # 안전 옵션 ID 와의 교집합만 살림 (위험 옵션 차단)
    return saved & all_safe_ids


def update_sandbox_options(cfg: UserConfig, selected: Set[str]):
    """체크박스 메뉴에서 선택된 옵션 중 안전한 것만 저장.

    위험 옵션이 선택돼 있더라도 저장에선 제거됨.
    이렇게 해야 다음 실행 때 위험 옵션이 자동 활성화되지 않음.
    """
    safe_only = [oid for oid in selected if oid not in DANGEROUS_OPTION_IDS]
    cfg.sandbox_safe_options = sorted(safe_only)


# ───────── 메뉴용 ─────────

def update_last_workspace(cfg: UserConfig, path: Path):
    cfg.last_workspace = str(path.resolve())


def update_last_menu_choice(cfg: UserConfig, choice: str):
    cfg.last_menu_choice = choice


def update_last_model_tag(cfg: UserConfig, tag: str):
    cfg.last_model_tag = tag


def update_language(cfg: UserConfig, lang: str):
    cfg.language = lang


# ───────── 디버그 / 사용자 표시용 ─────────

def file_location() -> Path:
    return _CONFIG_FILE


def reset():
    """설정 초기화 (파일 삭제)."""
    if _CONFIG_FILE.exists():
        _CONFIG_FILE.unlink()
        ui.ok(f"설정 초기화: {_CONFIG_FILE}")
