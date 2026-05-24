"""chat_panel — GUI 통합 대화창 패널.

지시사항 [2단계] 단일 윈도우 데스크탑 대화 UI.
3단 구조:
  ┌──────────────────────────────────────┐
  │   [Title]                            │
  ├──────────────────────────┬───────────┤
  │ 대화창 (출력+컬러)        │ 작업 폴더 │
  │                          │ 파일 리스트│
  │                          │           │
  │                          │ ─────────  │
  │                          │ 시스템상태│
  │                          │           │
  ├──────────────────────────┴───────────┤
  │ [입력창........................][전송]│
  │  [중단] [재시작] [폴더열기]            │
  └──────────────────────────────────────┘

설계
────
- ChatPanel.append_message(level, text) — Queue 폴링한 GUI 가 호출
- ChatPanel.set_input_callback(fn) — 사용자가 [전송] 누르면 fn(text)
- ChatPanel.set_stop_callback(fn) — [중단] 콜백
- 폴링 주기는 호출자가 결정 (보통 100ms)
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext
from typing import Callable, Optional

from .theme import Theme
from .widgets import make_button


# ─────────────────────────────────────────────
#  레벨별 색상 (Theme 보강)
# ─────────────────────────────────────────────
_LEVEL_COLORS = {
    "stdout": Theme.FG,
    "stderr": "#e1bda5",          # 옅은 주황 (오류 가독성)
    "info":   Theme.ACCENT,
    "warn":   "#d7ba7d",          # 약한 노랑이 아닌 모카톤
    "error":  Theme.DANGER,
    "user":   Theme.OK,           # 사용자 입력 — 초록
    "system": Theme.FG_DIM,       # 시스템 메시지
    "terminated": Theme.DANGER,
}


class ChatPanel:
    """GUI 통합 대화창.

    Public API:
        append_message(level, text) — 로그에 한 줄 추가
        clear() — 로그 비우기
        set_input_callback(fn) — 사용자가 입력 후 [전송] 누름
        set_stop_callback(fn) — [중단] 콜백
        set_restart_callback(fn) — [재시작] 콜백
        set_open_folder_callback(fn) — [폴더열기] 콜백
        refresh_files(folder) — 우측 파일 리스트 갱신
        set_status(text) — 우측 하단 시스템 상태 텍스트
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str = "에이전트 대화",
        subtitle: str = "",
        workspace: Optional[Path] = None,
    ):
        self.frame = tk.Frame(parent, bg=Theme.BG)
        self._workspace = workspace

        # 콜백 슬롯
        self._on_input: Optional[Callable[[str], None]] = None
        self._on_stop: Optional[Callable[[], None]] = None
        self._on_restart: Optional[Callable[[], None]] = None
        self._on_open_folder: Optional[Callable[[], None]] = None

        self._build_header(title, subtitle)
        self._build_body()
        self._build_input_bar()

    # ── 빌드 ──
    def _build_header(self, title: str, subtitle: str) -> None:
        head = tk.Frame(self.frame, bg=Theme.BG)
        head.pack(fill="x", padx=20, pady=(16, 8))

        tk.Label(
            head, text=title,
            bg=Theme.BG, fg=Theme.FG_BRIGHT,
            font=Theme.F_TITLE,
        ).pack(side="left")

        if subtitle:
            tk.Label(
                head, text="  " + subtitle,
                bg=Theme.BG, fg=Theme.FG_DIM,
                font=Theme.F_SUB,
            ).pack(side="left")

    def _build_body(self) -> None:
        body = tk.Frame(self.frame, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=20, pady=4)

        # 왼쪽: 채팅 로그 (대부분의 공간)
        left = tk.Frame(body, bg=Theme.PANEL)
        left.pack(side="left", fill="both", expand=True)

        self._log = scrolledtext.ScrolledText(
            left,
            bg=Theme.PANEL, fg=Theme.FG,
            insertbackground=Theme.FG,
            selectbackground=Theme.ACCENT,
            font=Theme.F_MONO if hasattr(Theme, "F_MONO") else ("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10, pady=8,
            state="disabled",
        )
        self._log.pack(fill="both", expand=True)

        # 컬러 태그 등록
        for level, color in _LEVEL_COLORS.items():
            self._log.tag_configure(level, foreground=color)
        self._log.tag_configure("bold", font=Theme.F_BOLD if hasattr(Theme, "F_BOLD") else ("Consolas", 10, "bold"))

        # 오른쪽: 사이드 패널 (파일 + 상태)
        right = tk.Frame(body, bg=Theme.BG, width=260)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)  # 너비 고정

        # 파일 리스트
        tk.Label(
            right, text="작업 폴더 파일",
            bg=Theme.BG, fg=Theme.FG_DIM,
            font=Theme.F_SUB, anchor="w",
        ).pack(fill="x", pady=(0, 4))

        list_wrap = tk.Frame(right, bg=Theme.PANEL)
        list_wrap.pack(fill="both", expand=True)

        self._file_list = tk.Listbox(
            list_wrap,
            bg=Theme.PANEL, fg=Theme.FG,
            selectbackground=Theme.ACCENT,
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",
        )
        self._file_list.pack(fill="both", expand=True, padx=4, pady=4)

        # 시스템 상태
        tk.Label(
            right, text="시스템",
            bg=Theme.BG, fg=Theme.FG_DIM,
            font=Theme.F_SUB, anchor="w",
        ).pack(fill="x", pady=(12, 4))

        self._status_label = tk.Label(
            right, text="대기 중…",
            bg=Theme.PANEL, fg=Theme.FG,
            font=("Consolas", 9),
            anchor="w", justify="left",
            padx=8, pady=6,
            wraplength=240,
        )
        self._status_label.pack(fill="x")

    def _build_input_bar(self) -> None:
        bar = tk.Frame(self.frame, bg=Theme.BG)
        bar.pack(fill="x", padx=20, pady=(8, 16))

        # 입력창
        self._input = tk.Text(
            bar,
            height=3,
            bg=Theme.PANEL, fg=Theme.FG,
            insertbackground=Theme.FG,
            font=("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=8, pady=6,
        )
        self._input.pack(side="left", fill="both", expand=True)
        # Enter = 전송, Shift+Enter = 줄바꿈
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", lambda e: None)

        # 우측 버튼들 (세로)
        btn_col = tk.Frame(bar, bg=Theme.BG)
        btn_col.pack(side="right", fill="y", padx=(8, 0))

        self._send_btn = make_button(
            btn_col, text="전송",
            command=self._fire_input,
            kind="accent",
        )
        self._send_btn.pack(fill="x", pady=(0, 4))

        row2 = tk.Frame(btn_col, bg=Theme.BG)
        row2.pack(fill="x")
        self._stop_btn = make_button(
            row2, text="중단",
            command=self._fire_stop,
            kind="danger",
        )
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))

        self._restart_btn = make_button(
            row2, text="재시작",
            command=self._fire_restart,
            kind="default",
        )
        self._restart_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))

        self._open_btn = make_button(
            btn_col, text="📁 폴더",
            command=self._fire_open_folder,
            kind="default",
        )
        self._open_btn.pack(fill="x", pady=(4, 0))

    # ── 이벤트 핸들러 ──
    def _on_enter(self, event):
        """Enter: 전송. Shift+Enter: 줄바꿈."""
        if event.state & 0x0001:  # Shift
            return  # 기본 동작 (줄바꿈)
        self._fire_input()
        return "break"  # 기본 Enter 동작 차단

    def _fire_input(self) -> None:
        text = self._input.get("1.0", "end").rstrip()
        if not text:
            return
        # 사용자 입력은 즉시 로그에 표시
        self.append_message("user", f"> {text}")
        self._input.delete("1.0", "end")
        if self._on_input is not None:
            try:
                self._on_input(text)
            except Exception as e:
                self.append_message("error", f"입력 처리 오류: {e}")

    def _fire_stop(self) -> None:
        if self._on_stop is not None:
            try:
                self._on_stop()
            except Exception as e:
                self.append_message("error", f"중단 실패: {e}")

    def _fire_restart(self) -> None:
        if self._on_restart is not None:
            try:
                self._on_restart()
            except Exception as e:
                self.append_message("error", f"재시작 실패: {e}")

    def _fire_open_folder(self) -> None:
        if self._on_open_folder is not None:
            try:
                self._on_open_folder()
            except Exception as e:
                self.append_message("error", f"폴더 열기 실패: {e}")

    # ── public API ──
    def append_message(self, level: str, text: str) -> None:
        """로그에 한 줄 추가 (Tk 스레드에서만 호출)."""
        if level not in _LEVEL_COLORS:
            level = "stdout"
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", level)
        self._log.see("end")
        self._log.configure(state="disabled")

    def clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def set_input_callback(self, fn: Callable[[str], None]) -> None:
        self._on_input = fn

    def set_stop_callback(self, fn: Callable[[], None]) -> None:
        self._on_stop = fn

    def set_restart_callback(self, fn: Callable[[], None]) -> None:
        self._on_restart = fn

    def set_open_folder_callback(self, fn: Callable[[], None]) -> None:
        self._on_open_folder = fn

    def refresh_files(self, folder: Optional[Path] = None) -> None:
        """우측 파일 리스트를 갱신."""
        folder = folder or self._workspace
        if folder is None:
            return
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (OSError, PermissionError):
            return

        self._file_list.delete(0, "end")
        for p in entries[:200]:  # 최대 200개
            icon = "📁 " if p.is_dir() else "📄 "
            self._file_list.insert("end", icon + p.name)

    def set_status(self, text: str) -> None:
        """시스템 상태 텍스트 갱신."""
        try:
            self._status_label.configure(text=text)
        except tk.TclError:
            pass

    def disable_send(self) -> None:
        self._send_btn.configure(state="disabled")

    def enable_send(self) -> None:
        self._send_btn.configure(state="normal")

    # ── 패널 라이프사이클 ──
    def pack(self, **kwargs):
        return self.frame.pack(**kwargs)

    def destroy(self):
        try:
            self.frame.destroy()
        except tk.TclError:
            pass


__all__ = ["ChatPanel"]
