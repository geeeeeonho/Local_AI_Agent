"""lang_setup — 설치 시작 시 언어 결정 로직.

순서:
  1. CLI 인자 --lang 가 있으면 그대로 사용
  2. 저장된 user_data/settings/user_config.json 의 language 가 있으면 사용
  3. 둘 다 없으면 사용자에게 묻고 저장
"""
from __future__ import annotations

import os
import sys
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


def _can_ask() -> bool:
    """콘솔이 있어야 물어볼 수 있다.

    RUN.bat 은 창 모드에서 pythonw.exe 를 쓴다. 그 프로세스에는 콘솔이
    없어 sys.stdin 이 None 이고, input() 은 EOFError 가 아니라
    RuntimeError("input(): lost sys.stdin") 를 던진다. 예전에는 그것이
    그대로 올라가 첫 실행에서 창 대신 오류 상자가 떴다.
    """
    stream = getattr(sys, "stdin", None)
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _system_language() -> str:
    """물어볼 수 없을 때의 차선책 — OS 가 이미 답을 알고 있다."""
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(key) or ""
        if value[:2].lower() == "ko":
            return "ko"
    try:
        import locale
        name = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
    except (ValueError, TypeError, AttributeError):
        name = ""
    if "ko" in str(name).lower() or "korea" in str(name).lower():
        return "ko"
    if os.name == "nt":
        try:
            import ctypes
            # 0x0412 == ko-KR. 한국어 Windows 에서 영어로 떨어지지 않게.
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x12:
                return "ko"
        except Exception:
            pass
    return "en"


def _ask_language() -> Optional[str]:
    """언어 선택 메뉴 (양 언어 병기). 물어볼 수 없으면 None."""
    if not _can_ask():
        return None
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
        except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
            return None

        if choice in ("", "1"):
            return "en"
        if choice == "2":
            return "ko"
        print("  Invalid input. Please type 1 or 2.")


def initialize_language(here: Path, override: Optional[str] = None) -> str:
    """언어 결정 + 적용 + (필요시) 저장.

    Returns: 결정된 언어 코드
    """
    # load/save 단계에서 기존 설정이 있으면 user_data 정본으로 자동 마이그레이션된다.

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
    if chosen is None:
        # 물어볼 수 없었다. 짐작한 값은 저장하지도, 환경변수로 넘기지도 않는다.
        # 저장하면 그 짐작이 영구 설정이 되고, 환경변수로 넘기면 같은 프로세스
        # 안에서 이어 도는 설치 화면과 자식 프로세스가 -- 콘솔이 있어서 물어볼
        # 수 있는데도 -- 위의 2단계에서 그 값을 집어 그냥 써 버린다.
        guess = _system_language()
        set_language(guess)
        return guess

    set_language(chosen)
    _save_language(here, chosen)
    os.environ[ENV_VAR] = chosen

    name_map = {"en": "English", "ko": "한국어"}
    print()
    print(f"  {t('lang.saved', lang=name_map[chosen])}")
    print()
    return chosen
