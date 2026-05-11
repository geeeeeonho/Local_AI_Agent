"""ui — 호환 shim.

신규 코드는 launcher.presenter.tui 또는 Presenter 인터페이스 사용 권장.
기존 코드를 깨지 않기 위해 함수/상수만 re-export.
"""
from .presenter.tui import (
    C, clear, hr, header,
    info, ok, warn, err,
    prompt, pause,
)

__all__ = [
    "C", "clear", "hr", "header",
    "info", "ok", "warn", "err",
    "prompt", "pause",
]
