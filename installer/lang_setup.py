"""lang_setup — 설치 시작 시 언어 결정 로직.

순서:
  1. CLI 인자 --lang 가 있으면 그대로 사용
  2. 저장된 user_data/settings/user_config.json 의 language 가 있으면 사용
  3. 둘 다 없으면 사용자에게 묻고 저장
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .i18n import set_language, t, SUPPORTED_LANGUAGES, ENV_VAR


def _settings_store():
    from launcher import settings_store
    return settings_store


def _config_path(here: Path) -> Path:
    return _settings_store().path(here)


def _load_saved_language(here: Path) -> Optional[str]:
    try:
        lang = _settings_store().load(here).language
        if lang in SUPPORTED_LANGUAGES:
            return lang
    except Exception:
        pass
    return None


def _save_language(here: Path, lang: str):
    """통합 설정 파일의 language 필드만 갱신하고 다른 설정은 보존."""
    try:
        store = _settings_store()
        cfg = store.load(here)
        store.update_language(cfg, lang)
        store.save(cfg, here)
    except Exception:
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
    # 설정 저장소 초기화는 레거시 경로의 기존 설정도 user_data 로 이전한다.
    try:
        _settings_store().ensure_legacy_bridges(here)
    except Exception:
        pass

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

    name_map = {"en": "English", "ko": "한국어"}
    print()
    print(f"  {t('lang.saved', lang=name_map[chosen])}")
    print()
    return chosen
