"""lang_setup — 설치 시작 시 언어 결정 로직.

순서:
  1. CLI 인자 --lang 가 있으면 그대로 사용
  2. 저장된 user_config.json 의 language 가 있으면 사용
  3. 둘 다 없으면 사용자에게 묻고 저장
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .i18n import set_language, t, SUPPORTED_LANGUAGES, ENV_VAR


# launcher/settings/user_config.json 위치 (프로젝트 루트 기준)
def _config_path(here: Path) -> Path:
    return here / "launcher" / "settings" / "user_config.json"


def _load_saved_language(here: Path) -> Optional[str]:
    p = _config_path(here)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        lang = data.get("language")
        if lang in SUPPORTED_LANGUAGES:
            return lang
    except Exception:
        pass
    return None


def _save_language(here: Path, lang: str):
    """user_config.json 의 language 필드만 추가/갱신.

    파일이 없으면 새로 만들고, 있으면 다른 키는 보존.
    """
    p = _config_path(here)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["language"] = lang
    if "schema_version" not in data:
        data["schema_version"] = 1

    try:
        p.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _ask_language() -> str:
    """언어 선택 메뉴 (양 언어 병기)."""
    print()
    print("=" * 60)
    print("  Select language / 언어 선택")
    print("=" * 60)
    print()
    print("  [1] English")
    print("  [2] 한국어 (Korean)")
    print()
    while True:
        try:
            choice = input("  Choice [1/2] (default 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            return "en"

        if choice in ("", "1"):
            return "en"
        if choice == "2":
            return "ko"
        print("  Invalid input. Please type 1 or 2.")


def initialize_language(here: Path, override: Optional[str] = None) -> str:
    """언어 결정 + 적용 + (필요시) 저장.

    Returns: 결정된 언어 코드
    """
    # 1) CLI 인자
    if override and override in SUPPORTED_LANGUAGES:
        set_language(override)
        _save_language(here, override)
        os.environ[ENV_VAR] = override
        return override

    # 2) 환경변수 (RUN.bat 가 전달했을 수도)
    env_lang = os.environ.get(ENV_VAR)
    if env_lang in SUPPORTED_LANGUAGES:
        set_language(env_lang)
        return env_lang

    # 3) 저장된 값
    saved = _load_saved_language(here)
    if saved:
        set_language(saved)
        os.environ[ENV_VAR] = saved
        return saved

    # 4) 사용자에게 물어봄
    chosen = _ask_language()
    set_language(chosen)
    _save_language(here, chosen)
    os.environ[ENV_VAR] = chosen

    # 선택 직후 한 줄 안내
    name_map = {"en": "English", "ko": "한국어"}
    print()
    print(f"  {t('lang.saved', lang=name_map[chosen])}")
    print()
    return chosen
