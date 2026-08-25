"""window — 메인 윈도우 (싱글 윈도우 컨테이너).

구조:
  ┌─────────────────────────────────────┐
  │ ≡  LLM Launcher                     │  헤더 + 토글
  ├──────┬──────────────────────────────┤
  │ Side │  PanelHost (메인 영역)        │
  │ bar  │                              │
  │      │                              │
  ├──────┴──────────────────────────────┤
  │ ●Ollama  ●Docker  ●SearXNG    msg   │  상태바
  └─────────────────────────────────────┘
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional

from ..base import MenuItem
from .sidebar import Sidebar
from .statusbar import StatusBar
from .theme import Theme
from .widgets import create_dark_root


class PanelHost:
    """메인 영역 — 패널을 갈아끼우는 컨테이너."""

    def __init__(self, parent: tk.Widget):
        self.frame = tk.Frame(parent, bg=Theme.BG)
        self._current = None

    def replace(self, build_panel: Callable[[tk.Widget], object]):
        """기존 패널 제거하고 새 패널을 만들어 표시.

        build_panel: parent_frame 을 받아 panel 객체 반환.
                     panel 객체는 .pack(...) 와 .destroy() 메서드 보유.
        """
        if self._current is not None:
            # v4_lifecycle: 기존 패널에 on_destroy hook 있으면 먼저 호출
            _on_destroy = getattr(self._current, 'on_destroy', None)
            if callable(_on_destroy):
                try:
                    _on_destroy()
                except Exception:
                    pass
            try:
                self._current.destroy()
            except Exception:
                pass
            self._current = None
        panel = build_panel(self.frame)
        panel.pack(fill="both", expand=True)
        self._current = panel
        return panel


class MainWindow:
    """메인 윈도우 — 모든 GUI 흐름의 컨테이너."""

    def __init__(
        self, items: List[MenuItem],
        on_select: Callable[[str], None],
        env_path_str: str = "",
    ):
        self.root = create_dark_root("LLM Environment Launcher")

        # ── 메인 컨테이너 ──
        main = tk.Frame(self.root, bg=Theme.BG)
        main.pack(fill="both", expand=True)

        # ── 상태바 (먼저 만들어야 메인 영역이 위로 가고 상태바는 아래로) ──
        self.statusbar = StatusBar(main)
        self.statusbar._wrap.pack(side="bottom", fill="x")

        # ── 사이드바 ──
        self.sidebar = Sidebar(
            main, items=items,
            on_select=on_select,
            on_toggle=self._on_sidebar_toggle,
            env_path_str=env_path_str,
        )
        self.sidebar.frame.pack(side="left", fill="y")

        # 사이드바와 본문 사이 구분선
        tk.Frame(main, bg=Theme.BORDER, width=1).pack(side="left", fill="y")

        # ── 메인 영역 ──
        self.host = PanelHost(main)
        self.host.frame.pack(side="left", fill="both", expand=True)

        # 단축키
        self.root.bind("<Control-b>", lambda e: self.sidebar.toggle())
        self.root.bind("<Control-B>", lambda e: self.sidebar.toggle())

    def _on_sidebar_toggle(self, _collapsed: bool):
        # 필요 시 추가 처리 (현재는 폭만 변경)
        pass

    def set_message(self, msg: str, level: str = "info"):
        self.statusbar.set_message(msg, level)

    def set_pollers(self, **kw):
        self.statusbar.set_pollers(**kw)

    def start(self):
        self.statusbar.start_polling(self.root)

        # v6_lifelog: GUI 창 X 클릭 시 cleanup hook 호출
        try:
            from .. import lifelog as _ll

            def _on_window_close():
                _ll.log('CLEANUP', 'GUI WM_DELETE_WINDOW 트리거')
                try:
                    _ll.shutdown_then_exit()
                except Exception:
                    pass
                try:
                    self.quit()
                except Exception:
                    pass

            self.root.protocol('WM_DELETE_WINDOW', _on_window_close)
        except Exception as _e:
            pass

        try:
            self.root.mainloop()
        finally:
            # mainloop 가 어떤 식으로 끝나든 폴러 정리
            self.statusbar.stop_polling(self.root)

    def quit(self):
        if getattr(self, "_quitted", False):
            return
        self._quitted = True
        # v4_lifecycle: 활성 에이전트 일괄 종료
        try:
            from .. import agent_lifecycle as _lc
            _n = _lc.cleanup_all(timeout=3.0)
            if _n > 0:
                print(f'[v4_lifecycle] 활성 에이전트 {_n}개 정리됨', flush=True)
        except Exception:
            pass
        self.statusbar.stop_polling(self.root)
        # destroy 만 호출 — destroy 가 mainloop 도 함께 깨움
        try:
            self.root.destroy()
        except tk.TclError:
            pass
