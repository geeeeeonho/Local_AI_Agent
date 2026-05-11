"""sidebar — 토글 가능한 좌측 사이드바.

펼친 상태 (248px): 아이콘 + 라벨 + 한 줄 설명
접힌 상태 (56px):  아이콘만, 호버 시 툴팁
토글 버튼 좌상단 배치 + Ctrl+B 단축키.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional

from ..base import MenuItem
from .theme import Theme
from .widgets import HoverCard, Tooltip


SIDEBAR_EXPANDED_WIDTH = 248
SIDEBAR_COLLAPSED_WIDTH = 56


class SidebarItem:
    """메뉴 항목 + 그에 대응하는 카드 위젯.

    아이콘은 텍스트로 표현 (Tk 표준 폰트로 렌더링되는 유니코드 글리프).
    """

    def __init__(
        self, parent_frame: tk.Frame,
        item: MenuItem, icon: str, on_click: Callable[[str], None],
    ):
        self.item = item
        self.icon = icon
        self._on_click = on_click

        # 카드 컨테이너
        self.card = HoverCard(
            parent_frame,
            normal_bg=Theme.BG_ALT,
            hover_bg=Theme.BG_HOVER,
            on_click=self._click,
        )
        self.card.pack(fill="x", padx=0, pady=1)

        # 좌측 active 보더 (선택 시만 표시)
        self._border = tk.Frame(self.card, width=2, bg=Theme.BG_ALT)
        self._border.pack(side="left", fill="y")

        # 메인 행
        self._row = tk.Frame(self.card, bg=Theme.BG_ALT)
        self._row.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        # 아이콘
        accent = self._accent_color(item.badge_kind)
        self._icon_lbl = tk.Label(
            self._row, text=icon,
            bg=Theme.BG_ALT, fg=accent,
            font=("Segoe UI Symbol", 14),
            width=2, anchor="center",
        )
        self._icon_lbl.pack(side="left")

        # 라벨 + 설명 (펼친 상태만 표시)
        self._text_col = tk.Frame(self._row, bg=Theme.BG_ALT)
        self._text_col.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self._title_lbl = tk.Label(
            self._text_col, text=item.title,
            bg=Theme.BG_ALT, fg=Theme.FG,
            font=Theme.F_MENU, anchor="w",
        )
        self._title_lbl.pack(fill="x", anchor="w")

        if item.description:
            self._desc_lbl = tk.Label(
                self._text_col, text=item.description,
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_TINY, anchor="w",
            )
            self._desc_lbl.pack(fill="x", anchor="w")
        else:
            self._desc_lbl = None

        # 위험/권장 뱃지 (펼친 상태에서만 표시)
        self._badge_lbl = None
        if item.badge:
            badge_color = self._accent_color(item.badge_kind)
            self._badge_lbl = tk.Label(
                self._row, text=item.badge,
                bg=Theme.BG_ALT, fg=badge_color,
                font=Theme.F_TINY,
            )
            self._badge_lbl.pack(side="right", padx=(0, 0))

        # 접힌 상태용 툴팁
        self.tooltip = Tooltip(self.card, item.title, delay_ms=300)

        # 자식 위젯 모두에 hover/click 이벤트 전파
        # — Tk 표준 <Enter>/<Leave> 가 자식 진입 시 부모 leave 발동하는 문제 해결
        self.card.add_child_bindings()

    @staticmethod
    def _accent_color(kind: str) -> str:
        return {
            "good":   Theme.OK,
            "danger": Theme.DANGER,
            "warn":   Theme.FG_DIM,
        }.get(kind or "", Theme.FG_DIM)

    def _click(self):
        self._on_click(self.item.key)

    def set_selected(self, selected: bool):
        self.card.set_selected(selected)
        self._border.configure(
            bg=Theme.SIDEBAR_ACTIVE_BORDER if selected else Theme.BG_ALT
        )

    def set_collapsed(self, collapsed: bool):
        """접힘 상태 적용 — 라벨/설명/뱃지 숨김."""
        if collapsed:
            self._text_col.pack_forget()
            if self._badge_lbl:
                self._badge_lbl.pack_forget()
        else:
            self._text_col.pack(side="left", fill="x", expand=True, padx=(8, 0))
            if self._badge_lbl:
                self._badge_lbl.pack(side="right")


class Sidebar:
    """전체 사이드바 (헤더 + 항목들 + 푸터).

    토글 시 width 만 즉시 변경 (애니메이션 없음 — Tk 한계).
    """

    # 메뉴 키 -> 아이콘 매핑 (Tk 표준 폰트로 렌더 가능한 유니코드만)
    DEFAULT_ICONS = {
        "1": "▶",   # 채팅 UI (재생)
        "2": "◆",   # 샌드박스
        "3": "⚠",   # 호스트 직접
        "4": "●",   # Ollama
        "5": "≡",   # 모델 정보
        "6": "■",   # Docker 빌드
        "7": "◎",   # SearXNG
        "8": "⚙",   # 설정
        "q": "✕",   # 종료
    }

    def __init__(
        self, parent: tk.Widget,
        items: List[MenuItem],
        on_select: Callable[[str], None],
        on_toggle: Optional[Callable[[bool], None]] = None,
        env_path_str: str = "",
    ):
        self._items = items
        self._on_select = on_select
        self._on_toggle = on_toggle
        self._collapsed = False
        self._sidebar_items: dict[str, SidebarItem] = {}
        self._selected_key: Optional[str] = None

        # 컨테이너 (고정 폭)
        self.frame = tk.Frame(
            parent, bg=Theme.BG_ALT,
            width=SIDEBAR_EXPANDED_WIDTH,
        )
        self.frame.pack_propagate(False)

        # ── 헤더 (토글 버튼) ──
        header = tk.Frame(self.frame, bg=Theme.BG_ALT, height=40)
        header.pack(fill="x")
        header.pack_propagate(False)

        self._toggle_btn = tk.Label(
            header, text="≡",
            bg=Theme.BG_ALT, fg=Theme.FG,
            font=("Segoe UI Symbol", 14),
            cursor="hand2", padx=14, pady=8,
        )
        self._toggle_btn.pack(side="left")
        self._toggle_btn.bind("<Button-1>", lambda e: self.toggle())
        self._toggle_btn.bind(
            "<Enter>", lambda e: self._toggle_btn.configure(fg=Theme.FG_BRIGHT)
        )
        self._toggle_btn.bind(
            "<Leave>", lambda e: self._toggle_btn.configure(fg=Theme.FG)
        )

        self._title_lbl = tk.Label(
            header, text="LLM Launcher",
            bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_SMALL, anchor="w",
        )
        self._title_lbl.pack(side="left", fill="x", expand=True, pady=8)

        # 구분선
        tk.Frame(self.frame, bg=Theme.BORDER, height=1).pack(fill="x")

        # ── 항목 영역 ──
        self._items_frame = tk.Frame(self.frame, bg=Theme.BG_ALT)
        self._items_frame.pack(fill="both", expand=True, pady=(8, 0))

        # 섹션: 실행
        self._section_label("실행")
        for item in items:
            if item.key in ("1", "2", "3"):
                self._add_item(item)

        # 섹션: 관리
        if any(it.key in ("4", "5", "6", "7", "8") for it in items):
            self._section_label("관리", top_pad=10)
        for item in items:
            if item.key in ("4", "5", "6", "7", "8"):
                self._add_item(item)

        # 섹션: 기타 (q 종료 등)
        for item in items:
            if item.key not in ("1", "2", "3", "4", "5", "6", "7", "8"):
                self._add_item(item)

        # ── 푸터 (설치 경로) ──
        tk.Frame(self.frame, bg=Theme.BORDER, height=1).pack(fill="x")
        self._footer = tk.Label(
            self.frame, text=f"📁 {env_path_str}",
            bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_TINY, anchor="w", justify="left",
            wraplength=SIDEBAR_EXPANDED_WIDTH - 24,
            padx=12, pady=10,
        )
        self._footer.pack(fill="x", side="bottom")

    def _section_label(self, text: str, top_pad: int = 4):
        self._section_holders = getattr(self, "_section_holders", [])
        lbl = tk.Label(
            self._items_frame, text=text.upper(),
            bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_TINY, anchor="w",
            padx=14, pady=(0),
        )
        lbl.pack(fill="x", pady=(top_pad, 4))
        self._section_holders.append(lbl)

    def _add_item(self, item: MenuItem):
        si = SidebarItem(
            self._items_frame, item,
            icon=self.DEFAULT_ICONS.get(item.key, "·"),
            on_click=self._on_select,
        )
        self._sidebar_items[item.key] = si

    # ── 외부 API ──
    def set_selected(self, key: str):
        self._selected_key = key
        for k, si in self._sidebar_items.items():
            si.set_selected(k == key)

    def set_disabled(self, disabled: bool):
        """액션 실행 중에 사이드바 클릭 비활성화 (시각 표시).

        실제 클릭 차단은 Presenter._action_busy 에서 하지만,
        시각적으로도 흐리게 만들어 사용자에게 명확히 표시.
        """
        for si in self._sidebar_items.values():
            try:
                cursor = "watch" if disabled else "hand2"
                si.card.configure(cursor=cursor)
                # 텍스트 색을 dim 으로 (현재 선택된 항목 제외)
                if not si.card._selected:
                    si._title_lbl.configure(
                        fg=Theme.DIM if disabled else Theme.FG
                    )
            except (tk.TclError, AttributeError):
                pass

    def toggle(self):
        self._collapsed = not self._collapsed
        new_width = (
            SIDEBAR_COLLAPSED_WIDTH if self._collapsed
            else SIDEBAR_EXPANDED_WIDTH
        )
        self.frame.configure(width=new_width)
        for si in self._sidebar_items.values():
            si.set_collapsed(self._collapsed)
        # 헤더 라벨 / 푸터 / 섹션 라벨도 숨김
        if self._collapsed:
            self._title_lbl.pack_forget()
            self._footer.pack_forget()
            for s in getattr(self, "_section_holders", []):
                s.pack_forget()
        else:
            self._title_lbl.pack(
                side="left", fill="x", expand=True, pady=8
            )
            self._footer.pack(fill="x", side="bottom")
            # 섹션 라벨 다시 표시 (간단히 — pack 순서가 깨지지 않게 정확히)
            # 섹션 라벨은 항상 _items_frame 내부에서 같은 순서로 만들었으므로
            # forget 만 풀면 원래 순서로 복원되지 않음 → 추가 로직 필요
            # 여기서는 단순하게 _items_frame 전체를 다시 그리는 대신
            # 라벨도 메뉴 항목보다 앞서 만들었기에 Tk 가 기본적으로 packing 순서 유지
            for s in getattr(self, "_section_holders", []):
                s.pack(fill="x", pady=(4, 4), before=self._first_visible_card())

        if self._on_toggle:
            self._on_toggle(self._collapsed)

    def _first_visible_card(self):
        """섹션 라벨을 다시 packing 할 때 위치 기준으로 쓰는 첫 카드."""
        for k in ("1", "2", "3", "4", "5", "6", "7", "8", "q"):
            if k in self._sidebar_items:
                return self._sidebar_items[k].card
        return None

    @property
    def collapsed(self) -> bool:
        return self._collapsed
