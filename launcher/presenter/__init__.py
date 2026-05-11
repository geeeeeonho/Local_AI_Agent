"""presenter — UI 추상화 레이어.

사용:
    from launcher.presenter import create_presenter
    p = create_presenter("tui")  # 또는 "gui"
    p.info("hello")
"""
from __future__ import annotations

from .base import (
    Presenter, MenuItem, Option,
    RISK_SAFE, RISK_MEDIUM, RISK_HIGH,
)


def create_presenter(mode: str = "tui") -> Presenter:
    """UI 모드별 Presenter 인스턴스 생성.

    Args:
        mode: "tui" | "gui"

    Raises:
        ValueError: 알 수 없는 모드
        ImportError: GUI 모드에서 tkinter 사용 불가
    """
    mode = (mode or "tui").lower()
    if mode == "tui":
        from .tui import TerminalPresenter
        return TerminalPresenter()
    elif mode == "gui":
        try:
            from .gui import TkPresenter
        except ImportError as e:
            raise ImportError(
                f"GUI 모드를 사용하려면 tkinter 가 필요합니다: {e}\n"
                "Windows Python 설치 시 'tcl/tk and IDLE' 옵션을 체크하세요."
            ) from e
        return TkPresenter()
    else:
        raise ValueError(f"알 수 없는 UI 모드: {mode!r} (tui/gui 중 선택)")


__all__ = [
    "Presenter", "MenuItem", "Option",
    "RISK_SAFE", "RISK_MEDIUM", "RISK_HIGH",
    "create_presenter",
]
