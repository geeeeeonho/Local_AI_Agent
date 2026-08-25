"""statusbar — 하단 상태바.

Ollama / Docker / SearXNG 상태 + 최근 메시지 표시.

성능 핵심:
  - 폴링은 백그라운드 스레드에서 실행 (메인 스레드 블록 X)
  - subprocess.run(timeout=10) 같은 무거운 호출이 GUI 를 멈추지 않음
  - 결과는 root.after(0, ...) 로 메인 스레드에 전달
  - 동일 폴러가 이미 실행 중이면 새 호출 안 함 (중복 방지)
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional

from .theme import Theme


class StatusBar:
    """하단 상태바.

    상태 점(●): 초록=실행 중, 회색=정지/미가동
    """

    POLL_MS = 5000           # 5초마다 갱신 (이전 2초 → 완화)
    INITIAL_DELAY_MS = 1500  # 첫 폴링 전 대기 (창 안정화 시간)

    def __init__(self, parent: tk.Widget):
        self._parent = parent

        # 상단 구분선 + 본문 frame 을 묶는 컨테이너
        self._wrap = tk.Frame(parent, bg=Theme.BG_ALT)
        tk.Frame(self._wrap, bg=Theme.BORDER, height=1).pack(
            fill="x", side="top"
        )
        self.frame = tk.Frame(self._wrap, bg=Theme.BG_ALT, height=26)
        self.frame.pack(fill="x", side="top")
        self.frame.pack_propagate(False)

        # 상태 항목들 (좌측 정렬)
        self._ollama_dot, self._ollama_lbl = self._make_indicator("Ollama")
        self._docker_dot, self._docker_lbl = self._make_indicator("Docker")
        self._searxng_dot, self._searxng_lbl = self._make_indicator("SearXNG")

        # 우측 메시지
        self._msg_lbl = tk.Label(
            self.frame, text="대기 중",
            bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_SMALL, anchor="e",
        )
        self._msg_lbl.pack(side="right", padx=14)

        # 폴러 + 상태
        self._pollers: dict = {}
        self._poll_after_id: Optional[str] = None
        self._stopped = False
        self._pending: dict = {}  # name -> bool: 이미 백그라운드 진행 중인지

    def _make_indicator(self, label: str):
        wrap = tk.Frame(self.frame, bg=Theme.BG_ALT)
        wrap.pack(side="left", padx=(14, 0), pady=4)
        dot = tk.Label(
            wrap, text="●",
            bg=Theme.BG_ALT, fg=Theme.DIM,
            font=Theme.F_SMALL,
        )
        dot.pack(side="left")
        lbl = tk.Label(
            wrap, text=label,
            bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_SMALL,
        )
        lbl.pack(side="left", padx=(4, 0))
        return dot, lbl

    def set_pollers(
        self,
        ollama_check=None, docker_check=None, searxng_check=None,
    ):
        """상태 검사 함수 주입. 각 함수는 bool 반환 (예외는 False 처리).

        주의: 이 함수들은 백그라운드 스레드에서 호출됨.
        메인 스레드의 Tk 위젯을 만지면 안 됨.
        """
        self._pollers = {
            "ollama": ollama_check,
            "docker": docker_check,
            "searxng": searxng_check,
        }

    def start_polling(self, root: tk.Tk):
        self._stopped = False
        # 첫 폴링은 지연 후 — 창이 안정적으로 그려진 다음 시작
        try:
            self._poll_after_id = root.after(
                self.INITIAL_DELAY_MS, lambda: self._poll(root)
            )
        except tk.TclError:
            pass

    def stop_polling(self, root: tk.Tk):
        self._stopped = True
        if self._poll_after_id:
            try:
                root.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

    def _poll(self, root: tk.Tk):
        """폴링 한 라운드 — 모든 폴러를 백그라운드 스레드로 시작."""
        if self._stopped:
            return
        try:
            root.winfo_exists()
        except tk.TclError:
            return

        # 폴러 호출 (백그라운드)
        for name, fn in self._pollers.items():
            if fn is None:
                self._apply_result(name, False)
            else:
                self._start_async_check(name, fn, root)

        # 다음 폴링 예약
        try:
            self._poll_after_id = root.after(
                self.POLL_MS, lambda: self._poll(root)
            )
        except tk.TclError:
            self._poll_after_id = None

    def _start_async_check(self, name: str, fn: Callable, root: tk.Tk):
        """백그라운드 스레드에서 fn() 실행. 결과를 메인 스레드로 전달.

        같은 name 의 폴러가 이미 진행 중이면 새로 시작하지 않음
        (느린 docker 명령이 쌓이는 것 방지).
        """
        if self._pending.get(name):
            return
        self._pending[name] = True

        def runner():
            running = False
            try:
                running = bool(fn())
            except Exception:
                running = False
            finally:
                self._pending[name] = False

            if self._stopped:
                return
            try:
                root.after(0, lambda r=running: self._apply_result(name, r))
            except tk.TclError:
                pass

        threading.Thread(target=runner, daemon=True).start()

    def _apply_result(self, name: str, running: bool):
        """메인 스레드에서 호출 — 점/라벨 색상 업데이트."""
        mapping = {
            "ollama": (self._ollama_dot, self._ollama_lbl),
            "docker": (self._docker_dot, self._docker_lbl),
            "searxng": (self._searxng_dot, self._searxng_lbl),
        }
        if name not in mapping:
            return
        dot, lbl = mapping[name]
        try:
            if running:
                dot.configure(fg=Theme.OK)
                lbl.configure(fg=Theme.FG)
            else:
                dot.configure(fg=Theme.DIM)
                lbl.configure(fg=Theme.FG_DIM)
        except tk.TclError:
            pass

    def set_message(self, msg: str, level: str = "info"):
        color = {
            "info": Theme.FG_DIM,
            "ok":   Theme.OK,
            "warn": Theme.FG_DIM,
            "error": Theme.DANGER,
        }.get(level, Theme.FG_DIM)
        if len(msg) > 80:
            msg = msg[:77] + "…"
        try:
            self._msg_lbl.configure(text=msg, fg=color)
        except tk.TclError:
            pass
