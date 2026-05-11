"""menu_panel — show_menu 가 메인 영역에 띄우는 카드 메뉴.

사이드바는 항상 보이는 상단 메뉴이고, MenuPanel 은 액션 내부에서
"하위 메뉴" 가 필요할 때 (예: SearXNG 액션의 시작/정지/로그보기)
메인 영역에 띄우는 패널.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional

from ..base import MenuItem
from .panels import _BasePanel
from .theme import Theme
from .widgets import HoverCard


class MenuPanel(_BasePanel):
    """사이드바와 별개의 메인 영역 메뉴.

    카드 형식으로 항목 나열 + 키보드 단축키 지원.
    """

    def __init__(
        self, parent: tk.Widget,
        title: str, subtitle: str,
        items: List[MenuItem],
        last_choice: Optional[str] = None,
        on_select: Optional[Callable[[str], None]] = None,
    ):
        self._on_select = on_select
        self._items = items

        self.frame = tk.Frame(parent, bg=Theme.BG)
        self.render_header(self.frame, title=title, subtitle=subtitle)

        body = tk.Frame(self.frame, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=18)

        for it in items:
            self._render_card(body, it, is_last=(it.key == last_choice))

        # 키보드 단축키 바인딩 (root 에)
        try:
            root = parent.winfo_toplevel()
            for it in items:
                k = it.key.lower()
                if k:
                    root.bind(
                        f"<KeyPress-{k}>" if k.isalnum() else None,
                        lambda e, kk=it.key: self._select(kk),
                        add="+",
                    )
        except Exception:
            pass

    def _select(self, key: str):
        if self._on_select:
            self._on_select(key)

    def _render_card(
        self, parent: tk.Widget, it: MenuItem, is_last: bool = False,
    ):
        if it.separator_above:
            tk.Frame(parent, bg=Theme.BORDER, height=1).pack(
                fill="x", pady=(6, 4)
            )

        card = HoverCard(
            parent,
            normal_bg=Theme.BG_ALT,
            hover_bg=Theme.BG_HOVER,
            on_click=lambda: self._select(it.key),
        )
        card.pack(fill="x", pady=2)

        inner = tk.Frame(card, bg=Theme.BG_ALT, padx=14, pady=10)
        inner.pack(fill="x")

        # 키 박스
        key_lbl = tk.Label(
            inner, text=f"[{it.key.upper()}]",
            bg=Theme.BG_ALT, fg=Theme.INFO,
            font=("Segoe UI", 11, "bold"),
            width=4, anchor="w",
        )
        key_lbl.pack(side="left")

        # 텍스트 컬럼
        text_col = tk.Frame(inner, bg=Theme.BG_ALT)
        text_col.pack(side="left", fill="x", expand=True, padx=(8, 0))

        title_row = tk.Frame(text_col, bg=Theme.BG_ALT)
        title_row.pack(fill="x", anchor="w")

        tk.Label(
            title_row, text=it.title,
            bg=Theme.BG_ALT, fg=Theme.FG_BRIGHT,
            font=Theme.F_BOLD, anchor="w",
        ).pack(side="left")

        # 뱃지
        if it.badge:
            color = {
                "good": Theme.OK,
                "danger": Theme.DANGER,
                "warn": Theme.FG_DIM,
            }.get(it.badge_kind, Theme.INFO)
            tk.Label(
                title_row, text=f"  ★ {it.badge}",
                bg=Theme.BG_ALT, fg=color, font=Theme.F_TINY,
            ).pack(side="left", padx=(6, 0))

        if is_last:
            tk.Label(
                title_row, text="  · 마지막 선택",
                bg=Theme.BG_ALT, fg=Theme.FG_DIM, font=Theme.F_TINY,
            ).pack(side="left")

        if it.description:
            tk.Label(
                text_col, text=it.description,
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_SMALL, anchor="w", justify="left",
            ).pack(fill="x", pady=(2, 0))

        # 자식 위젯 모두에 hover/click 전파 — 깜빡임 방지
        card.add_child_bindings()

    def pack(self, **kw):
        self.frame.pack(**kw)

    def destroy(self):
        self.frame.destroy()
