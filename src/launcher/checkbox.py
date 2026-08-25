"""checkbox — 호환 shim.

신규 코드는 Presenter.show_checkbox 사용.
기존 `from launcher import checkbox; checkbox.run(...)` 보존.
"""
from __future__ import annotations

from typing import List, Optional, Set

from .presenter.base import Option, RISK_SAFE, RISK_MEDIUM, RISK_HIGH
from .presenter.tui import TerminalPresenter

# 위험도 상수 (기존 코드는 checkbox.SAFE 등으로 참조)
SAFE = RISK_SAFE
MEDIUM = RISK_MEDIUM
HIGH = RISK_HIGH


def run(
    title: str,
    subtitle: str = "",
    options: Optional[List[Option]] = None,
    extra_lines: Optional[List[str]] = None,
    override_defaults: Optional[Set[str]] = None,
) -> Optional[Set[str]]:
    """기존 checkbox.run() 호환 진입점.

    내부적으로 TerminalPresenter 인스턴스를 만들어 사용.
    """
    return TerminalPresenter().show_checkbox(
        title=title,
        subtitle=subtitle,
        options=options or [],
        extra_lines=extra_lines,
        override_defaults=override_defaults,
    )


__all__ = ["Option", "SAFE", "MEDIUM", "HIGH", "run"]
