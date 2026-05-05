"""i18n — installer.i18n 의 launcher 측 래퍼.

별도 사전을 두지 않고 같은 사전을 재사용한다.
"""
from installer.i18n import t, set_language, get_language, SUPPORTED_LANGUAGES

__all__ = ["t", "set_language", "get_language", "SUPPORTED_LANGUAGES"]
