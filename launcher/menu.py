"""menu — 호환 shim.

신규 코드는 launcher.app.Application 사용.
기존 `from launcher import menu; menu.main_loop(env)` 보존.
"""
from __future__ import annotations

from pathlib import Path

from .app import Application
from .presenter import create_presenter


def main_loop(env: Path, mode: str = "tui") -> None:
    """기존 진입점. mode 파라미터로 TUI/GUI 선택 가능 (선택적)."""
    presenter = create_presenter(mode)
    Application(env, presenter).run()


__all__ = ["main_loop"]
