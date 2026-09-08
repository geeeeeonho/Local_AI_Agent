"""Single-window GUI panel for the Open Interpreter automation agent.

The panel is deliberately runtime-agnostic. It emits user commands through the
registered input callback; Open Interpreter thread/session ownership stays in
the agent service/controller layer.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, simpledialog
from typing import Callable, Optional

from .theme import Theme
from .widgets import make_button


_LEVEL_COLORS = {
    "stdout": Theme.FG,
    "stderr": "#e1bda5",
    "info": Theme.ACCENT,
    "warn": "#d7ba7d",
    "error": Theme.DANGER,
    "user": Theme.OK,
    "system": Theme.FG_DIM,
    "terminated": Theme.DANGER,
}


class ChatPanel:
    """Integrated agent conversation panel."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str = "에이전트 대화",
        subtitle: str = "",
        workspace: Optional[Path] = None,
    ):
        self.frame = tk.Frame(parent, bg=Theme.BG)
        self._workspace = workspace
        self._on_input: Optional[Callable[[str], None]] = None
        self._on_stop: Optional[Callable[[], None]] = None
        self._on_restart: Optional[Callable[[], None]] = None
        self._on_open_folder: Optional[Callable[[], None]] = None
        self._on_close: Optional[Callable[[], None]] = None
        self._close_fired = False
        self._current_model: str | None = None

        self._build_header(title, subtitle)
        self._build_body()
        self._build_input_bar()

    def _build_header(self, title: str, subtitle: str) -> None:
        head = tk.Frame(self.frame, bg=Theme.BG)
        head.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(
            head,
            text=title,
            bg=Theme.BG,
            fg=Theme.FG_BRIGHT,
            font=Theme.F_TITLE,
        ).pack(side="left")
        if subtitle:
            tk.Label(
                head,
                text="  " + subtitle,
                bg=Theme.BG,
                fg=Theme.FG_DIM,
                font=Theme.F_SUB,
            ).pack(side="left")

    def _build_body(self) -> None:
        body = tk.Frame(self.frame, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=20, pady=4)

        left = tk.Frame(body, bg=Theme.PANEL)
        left.pack(side="left", fill="both", expand=True)
        self._log = scrolledtext.ScrolledText(
            left,
            bg=Theme.PANEL,
            fg=Theme.FG,
            insertbackground=Theme.FG,
            selectbackground=Theme.ACCENT,
            font=Theme.F_MONO if hasattr(Theme, "F_MONO") else ("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
            state="disabled",
        )
        self._log.pack(fill="both", expand=True)
        for level, color in _LEVEL_COLORS.items():
            self._log.tag_configure(level, foreground=color)
        self._log.tag_configure(
            "bold",
            font=Theme.F_BOLD if hasattr(Theme, "F_BOLD") else ("Consolas", 10, "bold"),
        )

        right = tk.Frame(body, bg=Theme.BG, width=260)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)

        tk.Label(
            right,
            text="작업 폴더 파일",
            bg=Theme.BG,
            fg=Theme.FG_DIM,
            font=Theme.F_SUB,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        list_wrap = tk.Frame(right, bg=Theme.PANEL)
        list_wrap.pack(fill="both", expand=True)
        self._file_list = tk.Listbox(
            list_wrap,
            bg=Theme.PANEL,
            fg=Theme.FG,
            selectbackground=Theme.ACCENT,
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",
        )
        self._file_list.pack(fill="both", expand=True, padx=4, pady=4)

        tk.Label(
            right,
            text="시스템",
            bg=Theme.BG,
            fg=Theme.FG_DIM,
            font=Theme.F_SUB,
            anchor="w",
        ).pack(fill="x", pady=(12, 4))
        self._status_label = tk.Label(
            right,
            text="대기 중…",
            bg=Theme.PANEL,
            fg=Theme.FG,
            font=("Consolas", 9),
            anchor="w",
            justify="left",
            padx=8,
            pady=6,
            wraplength=240,
        )
        self._status_label.pack(fill="x")

    def _build_input_bar(self) -> None:
        bar = tk.Frame(self.frame, bg=Theme.BG)
        bar.pack(fill="x", padx=20, pady=(8, 16))

        self._input = tk.Text(
            bar,
            height=3,
            bg=Theme.PANEL,
            fg=Theme.FG,
            insertbackground=Theme.FG,
            font=("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=6,
        )
        self._input.pack(side="left", fill="both", expand=True)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", lambda event: None)

        btn_col = tk.Frame(bar, bg=Theme.BG)
        btn_col.pack(side="right", fill="y", padx=(8, 0))

        self._send_btn = make_button(
            btn_col,
            text="전송",
            command=self._fire_input,
            kind="accent",
        )
        self._send_btn.pack(fill="x", pady=(0, 4))

        self._newchat_btn = tk.Button(
            btn_col,
            text="새 대화",
            command=self._new_chat,
            bg=Theme.PANEL,
            fg=Theme.FG,
            relief="flat",
            bd=0,
            activebackground=Theme.ACCENT,
            font=("Segoe UI", 8),
        )
        self._newchat_btn.pack(fill="x", pady=(0, 4))

        self._sessions_btn = tk.Button(
            btn_col,
            text="세션 이어가기",
            command=self._open_sessions,
            bg=Theme.PANEL,
            fg=Theme.FG,
            relief="flat",
            bd=0,
            activebackground=Theme.ACCENT,
            font=("Segoe UI", 8),
        )
        self._sessions_btn.pack(fill="x", pady=(0, 4))

        self._model_var = tk.StringVar(value="모델 ▾")
        model_options = self._model_options() or ["(목록 없음)"]
        self._model_menu = tk.OptionMenu(
            btn_col,
            self._model_var,
            *model_options,
            command=self._on_model_pick,
        )
        self._model_menu.configure(
            bg=Theme.PANEL,
            fg=Theme.FG,
            relief="flat",
            activebackground=Theme.ACCENT,
            highlightthickness=0,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self._model_menu.pack(fill="x", pady=(0, 4))

        row2 = tk.Frame(btn_col, bg=Theme.BG)
        row2.pack(fill="x")
        self._stop_btn = make_button(
            row2,
            text="중단",
            command=self._fire_stop,
            kind="danger",
        )
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._restart_btn = make_button(
            row2,
            text="재시작",
            command=self._fire_restart,
            kind="default",
        )
        self._restart_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))

        self._open_btn = make_button(
            btn_col,
            text="📁 폴더",
            command=self._fire_open_folder,
            kind="default",
        )
        self._open_btn.pack(fill="x", pady=(4, 0))

    def _on_enter(self, event):
        if event.state & 0x0001:
            return None
        self._fire_input()
        return "break"

    def _fire_input(self) -> None:
        text = self._input.get("1.0", "end").rstrip()
        if not text:
            return
        self.append_message("user", "> " + text)
        self._input.delete("1.0", "end")
        if self._on_input is not None:
            try:
                self._on_input(text)
            except Exception as exc:
                self.append_message("error", "입력 처리 오류: " + str(exc))

    def _fire_stop(self) -> None:
        if self._on_stop is not None:
            try:
                self._on_stop()
            except Exception as exc:
                self.append_message("error", "중단 실패: " + str(exc))

    def _fire_restart(self) -> None:
        if self._on_restart is not None:
            try:
                self._on_restart()
            except Exception as exc:
                self.append_message("error", "재시작 실패: " + str(exc))

    def _fire_open_folder(self) -> None:
        if self._on_open_folder is not None:
            try:
                self._on_open_folder()
            except Exception as exc:
                self.append_message("error", "폴더 열기 실패: " + str(exc))

    def append_message(self, level: str, text: str) -> None:
        try:
            lifelog = None
            for module_name in ("launcher.core.lifelog", "launcher.lifelog"):
                try:
                    lifelog = __import__(module_name, fromlist=["log"])
                    break
                except Exception:
                    lifelog = None
            if lifelog is not None:
                clipped = text if len(text) <= 4000 else text[:4000] + " ...(생략)"
                lifelog.log("CHAT", "[%s] %s" % (level, clipped))
        except Exception:
            pass

        try:
            if "[모델 자동 강등]" in text and "->" in text:
                tail = text.split("->", 1)[1].strip()
                tag = tail.split(" (", 1)[0].strip().split()[0].strip()
                if tag:
                    self.set_current_model(tag)
        except Exception:
            pass

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

    def _send_command(self, text: str) -> None:
        self.append_message("user", "> " + text)
        if self._on_input is not None:
            try:
                self._on_input(text)
            except Exception as exc:
                self.append_message("error", "명령 처리 오류: " + str(exc))

    def _new_chat(self) -> None:
        self.clear()
        self._send_command("/new")

    def _model_options(self) -> list[str]:
        try:
            from launcher.models import model_roles
            tags: list[str] = []
            for ladder in getattr(model_roles, "LADDERS", {}).values():
                for model, _need in ladder:
                    if model not in tags:
                        tags.append(model)
            return tags[:20]
        except Exception:
            return []

    def _on_model_pick(self, tag) -> None:
        value = str(tag)
        if value and not value.startswith("모델") and not value.startswith("("):
            self._send_command("/model " + value)
            self.set_current_model(value)
        else:
            self._refresh_model_label()

    def set_current_model(self, tag) -> None:
        try:
            self._current_model = str(tag)
        except Exception:
            self._current_model = None
        self._refresh_model_label()

    def _refresh_model_label(self) -> None:
        try:
            if self._current_model:
                display = (
                    self._current_model
                    if len(self._current_model) <= 20
                    else self._current_model[:19] + "…"
                )
                self._model_var.set("모델: " + display + " ▾")
            else:
                self._model_var.set("모델 ▾")
        except Exception:
            pass

    def _open_sessions(self) -> None:
        """Resume an Open Interpreter thread by its native thread ID."""
        try:
            parent = self.frame.winfo_toplevel()
        except Exception:
            parent = None
        thread_id = simpledialog.askstring(
            "세션 이어가기",
            "Open Interpreter thread ID를 입력하세요.\n현재 ID는 대화창에서 /session 으로 확인할 수 있습니다.",
            parent=parent,
        )
        thread_id = str(thread_id or "").strip()
        if not thread_id:
            return
        self.clear()
        self._send_command("/resume " + thread_id)

    def set_stop_callback(self, fn: Callable[[], None]) -> None:
        self._on_stop = fn

    def set_restart_callback(self, fn: Callable[[], None]) -> None:
        self._on_restart = fn

    def set_open_folder_callback(self, fn: Callable[[], None]) -> None:
        self._on_open_folder = fn

    def refresh_files(self, folder: Optional[Path] = None) -> None:
        folder = folder or self._workspace
        if folder is None:
            return
        try:
            entries = sorted(folder.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
        except (OSError, PermissionError):
            return
        self._file_list.delete(0, "end")
        for path in entries[:200]:
            icon = "📁 " if path.is_dir() else "📄 "
            self._file_list.insert("end", icon + path.name)

    def set_status(self, text: str) -> None:
        try:
            self._status_label.configure(text=text)
        except tk.TclError:
            pass

    def disable_send(self) -> None:
        self._send_btn.configure(state="disabled")

    def enable_send(self) -> None:
        self._send_btn.configure(state="normal")

    def pack(self, **kwargs):
        return self.frame.pack(**kwargs)

    def _fire_close_once(self) -> None:
        if self._close_fired or self._on_close is None:
            return
        self._close_fired = True
        try:
            self._on_close()
        except Exception:
            pass

    def destroy(self) -> None:
        self._fire_close_once()
        try:
            self.frame.destroy()
        except tk.TclError:
            pass

    def on_destroy(self) -> None:
        self._fire_close_once()

    def set_close_callback(self, fn: Optional[Callable[[], None]]) -> None:
        self._on_close = fn


__all__ = ["ChatPanel"]
