"""gui — 호환 shim.

신규 코드는 launcher.presenter.gui.TkPresenter 사용.
기존 `from launcher import gui; gui.main_menu(...)` 와
`python -m launcher.gui` 데모 진입점을 보존.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

from .presenter.base import MenuItem, Option, RISK_SAFE, RISK_MEDIUM, RISK_HIGH
from .presenter.gui import TkPresenter, Theme

# 호환 alias
SAFE = RISK_SAFE
MEDIUM = RISK_MEDIUM
HIGH = RISK_HIGH


def _wrap_with_temp_window(call_with_presenter):
    """단일 윈도우 모드 TkPresenter 가 _window 없이 동작 못 하므로,
    잠깐 메인 윈도우를 띄워 단발성 호출을 처리하는 helper.

    main_menu / run_checkbox 같은 일회성 호출용.
    """
    p = TkPresenter()
    result = {"value": None}

    def runner(_key: str):
        result["value"] = call_with_presenter(p)
        p._window.quit()  # 결과 받자마자 윈도우 종료

    # 사이드바 없이 단일 패널만 표시: items=[] 로 호출
    # 하지만 sidebar 가 빈 메뉴는 어색하므로 더미 메뉴 추가 후 자동 트리거
    dummy_items = [MenuItem(key="_run", title="자동 실행")]
    # 윈도우 시작 직후 액션 자동 호출
    import threading
    def auto_trigger():
        # 약간의 지연 후 사이드바 자동 클릭
        p._window.root.after(50, lambda: runner("_run"))
    threading.Thread(target=auto_trigger, daemon=True).start()

    try:
        p.run_app(items=dummy_items, action_runner=runner,
                  env_path_str="", pollers={})
    except Exception:
        pass
    return result["value"]


def main_menu(
    title: str,
    subtitle: str,
    items: List[MenuItem],
    last_choice: Optional[str] = None,
) -> str:
    """이전 gui.main_menu 호환.

    일회성 호출. 새 단일 윈도우 모드 안에서 메뉴 패널을 띄우고 결과 반환.
    """
    return _wrap_with_temp_window(
        lambda p: p.show_menu(title, subtitle, items, last_choice)
    ) or "q"


def run_checkbox(
    title: str,
    subtitle: str = "",
    options: Optional[List[Option]] = None,
    extra_lines: Optional[List[str]] = None,
    override_defaults: Optional[Set[str]] = None,
) -> Optional[Set[str]]:
    """이전 gui.run_checkbox 호환."""
    return _wrap_with_temp_window(
        lambda p: p.show_checkbox(
            title, subtitle, options or [], extra_lines, override_defaults,
        )
    )


def _demo():
    """단독 실행 데모 — `python -m launcher.gui`.

    새 단일 윈도우 GUI 데모. 사이드바 클릭 시 액션 대신 print 만 수행.
    """
    from .app import _build_menu_items
    from .presenter import create_presenter

    p = create_presenter("gui")
    items = _build_menu_items()

    def fake_action(key: str):
        p.section(f"메뉴 [{key.upper()}] 선택됨")
        p.info(f"실제 환경에서는 launcher.actions 모듈의 액션이 실행됩니다.")
        p.info(f"이 데모는 단일 윈도우 GUI 동작 확인용입니다.")
        p.ok("데모: 액션 실행 완료")
        p.pause()

    p.run_app(
        items=items,
        action_runner=fake_action,
        env_path_str="(데모 모드)",
        pollers={},  # 폴링 없음
    )


# 호환: launcher.checkbox 패턴으로 import 한 코드를 위한 별칭
class checkbox:  # noqa: N801
    SAFE = SAFE
    MEDIUM = MEDIUM
    HIGH = HIGH
    Option = Option


__all__ = [
    "MenuItem", "Option", "Theme",
    "SAFE", "MEDIUM", "HIGH",
    "main_menu", "run_checkbox",
    "checkbox",
]


if __name__ == "__main__":
    _demo()
