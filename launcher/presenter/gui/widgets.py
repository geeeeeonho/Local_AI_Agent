"""widgets — 공통 위젯 / 헬퍼.

- Tooltip:  마우스 hover 시 라벨 표시 (사이드바 접힌 상태용)
- HoverCard: 마우스 hover 시 배경색 변하는 프레임
- create_dark_root: 다크 테마 적용된 Tk 루트
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .theme import Theme


# ─────────────────────────────────────────────
#  Tooltip
# ─────────────────────────────────────────────
class Tooltip:
    """위젯에 마우스 hover 시 떠 있는 라벨.

    사이드바가 접힌 상태에서 아이콘 옆에 메뉴 이름을 보여주기 위함.
    Tkinter 기본 위젯에는 툴팁이 없어 직접 구현.
    """
    def __init__(
        self, widget: tk.Widget, text: str,
        delay_ms: int = 400,
        bg: str = None, fg: str = None,
    ):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.bg = bg or Theme.BG_TOOLTIP
        self.fg = fg or Theme.FG_BRIGHT
        self._tipwin: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Button>", self._on_leave, add="+")

    def update_text(self, text: str):
        self.text = text

    def _on_enter(self, _e=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _on_leave(self, _e=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tipwin or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
            y = self.widget.winfo_rooty() + (self.widget.winfo_height() // 2) - 10
        except tk.TclError:
            return

        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg=self.bg)
        tk.Label(
            tw, text=self.text, bg=self.bg, fg=self.fg,
            font=Theme.F_SMALL, padx=9, pady=4,
            relief="solid", bd=0,
            highlightbackground=Theme.BORDER, highlightthickness=1,
        ).pack()
        self._tipwin = tw

    def _hide(self):
        if self._tipwin:
            try:
                self._tipwin.destroy()
            except Exception:
                pass
            self._tipwin = None


# ─────────────────────────────────────────────
#  HoverCard — 호버 시 배경 변경
# ─────────────────────────────────────────────
class HoverCard(tk.Frame):
    """마우스가 들어오면 배경색이 BG_HOVER 로, 나가면 원래 색으로.

    Tk 의 <Enter>/<Leave> 이벤트는 자식 위젯에 마우스가 진입할 때마다
    부모의 <Leave> 가 발동되는 단점이 있다. 이 클래스는 두 가지로 해결:

    1. add_child_bindings() — 새 자식 위젯이 추가된 직후 호출하면
       그 위젯에도 동일한 hover 이벤트가 바인딩되어 깜빡임 방지.
    2. _on_leave 에서 winfo_containing() 으로 마우스가 실제로 카드 영역
       밖에 있는지 재확인 — 자식 진입은 leave 로 인식하지 않음.
    """

    def __init__(
        self, parent, normal_bg: str = None, hover_bg: str = None,
        on_click: Optional[Callable] = None, **kw,
    ):
        self._normal = normal_bg or Theme.BG_ALT
        self._hover = hover_bg or Theme.BG_HOVER
        kw.setdefault("bg", self._normal)
        kw.setdefault("cursor", "hand2")
        super().__init__(parent, **kw)

        self._selected = False
        self._on_click = on_click
        self._is_hovering = False

        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        if on_click:
            self.bind("<Button-1>", lambda e: on_click(), add="+")

    def add_child_bindings(self, widget=None):
        """자식 위젯에도 hover/click 이벤트를 전파.

        프레임에 라벨/서브프레임을 추가한 후 이 메서드를 호출하면
        자식 위로 마우스가 가도 hover 가 유지됨.

        widget=None 이면 현재 모든 자식에 자동 적용.
        """
        targets = [widget] if widget else self._iter_descendants()
        for w in targets:
            try:
                w.bind("<Enter>", self._on_enter, add="+")
                w.bind("<Leave>", self._on_leave, add="+")
                if self._on_click:
                    w.bind("<Button-1>", lambda e: self._on_click(), add="+")
            except tk.TclError:
                pass

    def _iter_descendants(self):
        """자기 자신을 제외한 모든 자손 위젯."""
        stack = list(self.winfo_children())
        while stack:
            w = stack.pop()
            yield w
            if isinstance(w, (tk.Frame, tk.LabelFrame)):
                stack.extend(w.winfo_children())

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_bg(self._normal if not selected else Theme.BG_SELECTED)

    def _on_enter(self, _e=None):
        if self._is_hovering:
            return
        self._is_hovering = True
        if not self._selected:
            self._apply_bg(self._hover)

    def _on_leave(self, _e=None):
        # 마우스가 이 카드 안의 다른 자식 위젯으로 이동한 경우엔
        # leave 로 처리하지 않음
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            under = self.winfo_containing(x, y)
            if under is not None and self._is_descendant_or_self(under):
                return  # 여전히 카드 영역 안
        except tk.TclError:
            pass

        self._is_hovering = False
        self._apply_bg(Theme.BG_SELECTED if self._selected else self._normal)

    def _is_descendant_or_self(self, widget) -> bool:
        """widget 이 self 또는 self 의 자손인지."""
        w = widget
        while w is not None:
            if w is self:
                return True
            try:
                w = w.master
            except Exception:
                return False
        return False

    def _apply_bg(self, color: str):
        try:
            self.configure(bg=color)
            for w in self.winfo_children():
                self._cascade_bg(w, color)
        except tk.TclError:
            pass

    @staticmethod
    def _cascade_bg(widget, color: str):
        try:
            if isinstance(widget, (tk.Frame, tk.Label)):
                widget.configure(bg=color)
            if isinstance(widget, tk.Frame):
                for sub in widget.winfo_children():
                    HoverCard._cascade_bg(sub, color)
        except tk.TclError:
            pass


# ─────────────────────────────────────────────
#  Tk 루트 / 스타일 헬퍼
# ─────────────────────────────────────────────
def create_dark_root(title: str = "LLM Environment Launcher",
                     size: str = "1024x680") -> tk.Tk:
    """다크 테마 적용된 Tk 루트."""
    root = tk.Tk()
    root.title(title)
    root.geometry(size)
    root.configure(bg=Theme.BG)
    root.minsize(820, 560)

    # ttk 스타일
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=Theme.BG)
    style.configure("Alt.TFrame", background=Theme.BG_ALT)
    style.configure(
        "TLabel", background=Theme.BG, foreground=Theme.FG,
        font=Theme.F_BASE,
    )
    return root


def make_button(parent, text: str, command,
                primary: bool = False, danger: bool = False,
                **kw) -> tk.Button:
    """일관된 스타일 버튼."""
    if danger:
        bg, fg = Theme.DANGER, Theme.FG_BRIGHT
        hover = "#d65f48"
    elif primary:
        bg, fg = Theme.ACCENT, Theme.FG_BRIGHT
        hover = Theme.ACCENT_HOVER
    else:
        bg, fg = Theme.BG_INPUT, Theme.FG
        hover = "#4a4a4a"

    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg,
        activebackground=hover, activeforeground=Theme.FG_BRIGHT,
        relief="flat", bd=0,
        font=Theme.F_BASE,
        padx=kw.pop("padx", 16), pady=kw.pop("pady", 6),
        cursor="hand2",
        **kw,
    )
    btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
    return btn


# ─────────────────────────────────────────────
#  Spinner — 진행 중임을 시각적으로 표시
# ─────────────────────────────────────────────
class Spinner:
    """텍스트 기반 회전 스피너 — root.after 로 자체 갱신.

    Tk 의 ttk.Progressbar(mode='indeterminate') 보다 가벼움.
    유니코드 점선 패턴 사용 — Tk 표준 폰트로 렌더 가능.
    """

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    INTERVAL_MS = 100

    def __init__(
        self, parent: tk.Widget,
        text: str = "진행 중...",
        fg: str = None, bg: str = None,
    ):
        self.frame = tk.Frame(
            parent, bg=bg or Theme.BG_ALT,
        )
        self._fg = fg or Theme.ACCENT
        self._spin_lbl = tk.Label(
            self.frame, text=self.FRAMES[0],
            bg=bg or Theme.BG_ALT, fg=self._fg,
            font=("Consolas", 13, "bold"),
        )
        self._spin_lbl.pack(side="left", padx=(0, 8))
        self._text_lbl = tk.Label(
            self.frame, text=text,
            bg=bg or Theme.BG_ALT, fg=Theme.FG,
            font=Theme.F_BASE,
        )
        self._text_lbl.pack(side="left")

        self._frame_idx = 0
        self._after_id = None
        self._stopped = False
        self._tick()

    def set_text(self, text: str):
        try:
            self._text_lbl.configure(text=text)
        except tk.TclError:
            pass

    def _tick(self):
        if self._stopped:
            return
        try:
            self._spin_lbl.configure(text=self.FRAMES[self._frame_idx])
            self._frame_idx = (self._frame_idx + 1) % len(self.FRAMES)
            self._after_id = self.frame.after(self.INTERVAL_MS, self._tick)
        except tk.TclError:
            self._stopped = True

    def stop(self, final_text: str = None, final_color: str = None):
        """스피너 정지. 정지 후 체크마크 등으로 변경 가능."""
        self._stopped = True
        if self._after_id:
            try:
                self.frame.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if final_text is not None:
            try:
                self._spin_lbl.configure(
                    text="✓", fg=final_color or Theme.OK,
                )
                self._text_lbl.configure(text=final_text)
            except tk.TclError:
                pass

    def pack(self, **kw):
        self.frame.pack(**kw)

    def destroy(self):
        self._stopped = True
        if self._after_id:
            try:
                self.frame.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self.frame.destroy()
        except tk.TclError:
            pass
