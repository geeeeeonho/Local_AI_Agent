"""launcher.presenter.gui — 단일 윈도우 Tk Presenter.

사용:
    from launcher.presenter.gui import TkPresenter, Theme
    p = TkPresenter()
    p.run_app(items, action_runner)

하위 모듈:
    theme       — 색상 / 폰트 / 위험도 정책
    widgets     — Tooltip, HoverCard, 버튼 헬퍼
    sidebar     — 토글 가능 사이드바
    statusbar   — 하단 상태바
    panels      — Home / Checkbox / Log
    menu_panel  — 메인 영역 메뉴 (사이드바와 별개의 sub-menu)
    dialogs     — 위험확인 / 텍스트입력 모달
    window      — 메인 윈도우 + PanelHost
    presenter   — TkPresenter 본체
"""
from .presenter import TkPresenter
from .theme import Theme

__all__ = ["TkPresenter", "Theme"]
