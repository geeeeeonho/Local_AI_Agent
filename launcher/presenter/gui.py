"""presenter.gui — Tkinter 기반 GUI Presenter.

이전 launcher/gui.py 의 기능을 Presenter 인터페이스에 맞게 재구성.
의존성 0 (stdlib tkinter 만 사용).
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, simpledialog, ttk
from typing import List, Optional, Set

from .base import (
    Presenter, MenuItem, Option,
    RISK_MEDIUM, RISK_HIGH,
)


# ─────────────────────────────────────────────
#  테마 (한 곳에서 정의)
# ─────────────────────────────────────────────
class Theme:
    BG = "#1e1e2e"
    BG_ALT = "#313244"
    BG_HOVER = "#45475a"
    FG = "#cdd6f4"
    FG_DIM = "#9399b2"
    ACCENT = "#89b4fa"
    OK = "#a6e3a1"
    WARN = "#f9e2af"
    ERR = "#f38ba8"
    PURPLE = "#cba6f7"

    F_BASE = ("Segoe UI", 10)
    F_BOLD = ("Segoe UI", 10, "bold")
    F_SMALL = ("Segoe UI", 9)
    F_TITLE = ("Segoe UI", 16, "bold")
    F_SUB = ("Segoe UI", 11)
    F_MONO = ("Consolas", 10)


_RISK_KEYWORD = {RISK_HIGH: "I-UNDERSTAND", RISK_MEDIUM: "ENABLE"}


def _make_root(title: str, size: str = "780x680") -> tk.Tk:
    """다크 테마 적용된 Tk 루트."""
    root = tk.Tk()
    root.title(title)
    root.geometry(size)
    root.configure(bg=Theme.BG)
    root.minsize(600, 480)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=Theme.BG)
    style.configure("TLabel", background=Theme.BG,
                    foreground=Theme.FG, font=Theme.F_BASE)
    style.configure("Title.TLabel", background=Theme.BG,
                    foreground=Theme.PURPLE, font=Theme.F_TITLE)
    style.configure("Sub.TLabel", background=Theme.BG,
                    foreground=Theme.FG_DIM, font=Theme.F_SUB)
    return root


# ═════════════════════════════════════════════
#  TkPresenter
# ═════════════════════════════════════════════

class TkPresenter(Presenter):
    """Tkinter Presenter.

    출력(info/ok/warn/error/section)은 GUI 상태창에 누적 표시되며,
    show_menu / show_checkbox 호출 시 별도 모달 윈도우를 띄운다.
    """

    def __init__(self):
        # 진행 메시지 누적 — 다음 모달의 상태바 표시용
        self._log_buffer: List[tuple] = []  # [(level, msg), ...]

    # ── 정보 출력 ──
    def info(self, msg: str) -> None:
        self._log_buffer.append(("info", msg))
        print(f"[INFO] {msg}")

    def ok(self, msg: str) -> None:
        self._log_buffer.append(("ok", msg))
        print(f"[ OK ] {msg}")

    def warn(self, msg: str) -> None:
        self._log_buffer.append(("warn", msg))
        print(f"[WARN] {msg}")

    def error(self, msg: str) -> None:
        self._log_buffer.append(("error", msg))
        print(f"[FAIL] {msg}")

    def section(self, title: str, subtitle: str = "") -> None:
        self._log_buffer.clear()
        self._log_buffer.append(("section", f"{title} | {subtitle}"))
        print(f"\n=== {title} ===")
        if subtitle:
            print(f"    {subtitle}")

    def pause(self, msg: str = "확인") -> None:
        self._show_log_modal(msg)

    def _show_log_modal(self, ok_label: str = "확인"):
        """누적된 로그를 다이얼로그로 표시."""
        if not self._log_buffer:
            return
        dlg = tk.Tk()
        dlg.title("진행 결과")
        dlg.configure(bg=Theme.BG)
        dlg.geometry("640x400")

        text = tk.Text(
            dlg, bg=Theme.BG_ALT, fg=Theme.FG,
            font=Theme.F_MONO, relief="flat",
            padx=12, pady=12, wrap="word",
        )
        text.pack(fill="both", expand=True, padx=14, pady=14)

        for level, msg in self._log_buffer:
            color = {
                "info": Theme.ACCENT, "ok": Theme.OK,
                "warn": Theme.WARN, "error": Theme.ERR,
                "section": Theme.PURPLE,
            }.get(level, Theme.FG)
            text.tag_config(level, foreground=color)
            prefix = {
                "info": "[INFO] ", "ok": "[ OK ] ",
                "warn": "[WARN] ", "error": "[FAIL] ",
                "section": "─── ",
            }.get(level, "")
            text.insert("end", prefix + msg + "\n", level)
        text.config(state="disabled")

        btn = tk.Button(
            dlg, text=ok_label, command=dlg.destroy,
            bg=Theme.OK, fg=Theme.BG, relief="flat",
            font=Theme.F_BOLD, padx=20, pady=8, cursor="hand2",
        )
        btn.pack(pady=(0, 14))
        dlg.bind("<Return>", lambda e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.mainloop()
        self._log_buffer.clear()

    # ── 입력 ──
    def prompt_text(self, prompt: str = "> ", default: str = "") -> str:
        result = simpledialog.askstring("입력", prompt, initialvalue=default)
        return (result or "").strip()

    def prompt_choice(self, prompt: str, choices: List[str]) -> Optional[str]:
        items = [MenuItem(key=c, title=c) for c in choices]
        choice = self.show_menu(prompt, "", items)
        return choice if choice != "q" else None

    def prompt_path(
        self, title: str, default: Path,
        last_used: Optional[Path] = None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        initial = str(last_used or default)
        path_str = filedialog.askdirectory(
            title=title, initialdir=initial, mustexist=must_exist,
        )
        if not path_str:
            return None
        return Path(path_str)

    # ── 메인 메뉴 ──
    def show_menu(
        self, title: str, subtitle: str,
        items: List[MenuItem],
        last_choice: Optional[str] = None,
    ) -> str:
        result = {"key": "q"}

        root = _make_root(title)

        head = ttk.Frame(root, padding=(24, 18, 24, 4))
        head.pack(fill="x")
        ttk.Label(head, text=title, style="Title.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(head, text=subtitle, style="Sub.TLabel").pack(
                anchor="w", pady=(4, 0)
            )

        body = tk.Frame(root, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=14)

        def select(key: str):
            result["key"] = key
            root.destroy()

        for it in items:
            self._render_menu_card(body, it, last_choice, select, root)

        foot = tk.Frame(root, bg=Theme.BG, pady=10)
        foot.pack(fill="x", padx=24, pady=(0, 12))
        tk.Label(
            foot, text="단축키: 항목의 [숫자/문자] 키를 직접 누를 수 있음 · ESC = 종료",
            bg=Theme.BG, fg=Theme.FG_DIM, font=Theme.F_SMALL,
        ).pack(anchor="w")

        root.bind("<Escape>", lambda e: select("q"))
        root.protocol("WM_DELETE_WINDOW", lambda: select("q"))

        root.mainloop()
        return result["key"]

    def _render_menu_card(
        self, parent, it: MenuItem,
        last_choice: Optional[str], select, root,
    ):
        if it.separator_above:
            sep = tk.Frame(parent, bg=Theme.BG_ALT, height=1)
            sep.pack(fill="x", pady=(8, 4))

        is_last = (last_choice == it.key)
        card = tk.Frame(parent, bg=Theme.BG_ALT, cursor="hand2")
        card.pack(fill="x", pady=3)

        def set_bg(c, color):
            c.configure(bg=color)
            for w in c.winfo_children():
                if isinstance(w, (tk.Frame, tk.Label)):
                    w.configure(bg=color)
                    if isinstance(w, tk.Frame):
                        for sub in w.winfo_children():
                            if isinstance(sub, (tk.Frame, tk.Label)):
                                sub.configure(bg=color)

        card.bind("<Enter>", lambda e: set_bg(card, Theme.BG_HOVER))
        card.bind("<Leave>", lambda e: set_bg(card, Theme.BG_ALT))
        card.bind("<Button-1>", lambda e, k=it.key: select(k))

        inner = tk.Frame(card, bg=Theme.BG_ALT, padx=16, pady=12)
        inner.pack(fill="x")
        inner.bind("<Button-1>", lambda e, k=it.key: select(k))

        key_box = tk.Label(
            inner, text=f"[{it.key.upper()}]",
            bg=Theme.BG_ALT, fg=Theme.ACCENT,
            font=("Segoe UI", 12, "bold"), width=4, anchor="w",
        )
        key_box.pack(side="left")
        key_box.bind("<Button-1>", lambda e, k=it.key: select(k))

        text_col = tk.Frame(inner, bg=Theme.BG_ALT)
        text_col.pack(side="left", fill="x", expand=True, padx=(8, 0))
        text_col.bind("<Button-1>", lambda e, k=it.key: select(k))

        title_row = tk.Frame(text_col, bg=Theme.BG_ALT)
        title_row.pack(fill="x", anchor="w")
        title_row.bind("<Button-1>", lambda e, k=it.key: select(k))

        title_lbl = tk.Label(
            title_row, text=it.title, bg=Theme.BG_ALT, fg=Theme.FG,
            font=Theme.F_BOLD, anchor="w",
        )
        title_lbl.pack(side="left")
        title_lbl.bind("<Button-1>", lambda e, k=it.key: select(k))

        if it.badge:
            color = {
                "good": Theme.OK, "warn": Theme.WARN, "danger": Theme.ERR,
            }.get(it.badge_kind, Theme.ACCENT)
            badge_lbl = tk.Label(
                title_row, text=f"  ★ {it.badge}",
                bg=Theme.BG_ALT, fg=color,
                font=("Segoe UI", 9, "bold"),
            )
            badge_lbl.pack(side="left", padx=(6, 0))
            badge_lbl.bind("<Button-1>", lambda e, k=it.key: select(k))

        if is_last:
            tag = tk.Label(
                title_row, text="  · 마지막 선택",
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_SMALL,
            )
            tag.pack(side="left")
            tag.bind("<Button-1>", lambda e, k=it.key: select(k))

        if it.description:
            desc_lbl = tk.Label(
                text_col, text=it.description,
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_SMALL, anchor="w", justify="left",
            )
            desc_lbl.pack(fill="x", anchor="w", pady=(2, 0))
            desc_lbl.bind("<Button-1>", lambda e, k=it.key: select(k))

        # 키보드 단축키
        try:
            root.bind(it.key.lower(), lambda e, k=it.key: select(k))
        except tk.TclError:
            pass

    # ── 체크박스 ──
    def show_checkbox(
        self, title: str, subtitle: str,
        options: List[Option],
        extra_lines: Optional[List[str]] = None,
        override_defaults: Optional[Set[str]] = None,
    ) -> Optional[Set[str]]:
        if not options:
            return set()

        if override_defaults is not None:
            state = {opt.id: (opt.id in override_defaults) for opt in options}
            for opt in options:
                if opt.locked:
                    state[opt.id] = opt.default
        else:
            state = {opt.id: opt.default for opt in options}

        result = {"value": None}
        root = _make_root(title)

        head = ttk.Frame(root, padding=(20, 16, 20, 8))
        head.pack(fill="x")
        ttk.Label(head, text=title, style="Title.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(head, text=subtitle, style="Sub.TLabel").pack(
                anchor="w", pady=(4, 0)
            )

        if extra_lines:
            info_card = tk.Frame(root, bg=Theme.BG_ALT, padx=16, pady=10)
            info_card.pack(fill="x", padx=20, pady=(8, 0))
            for line in extra_lines:
                if not line.strip():
                    continue
                tk.Label(
                    info_card, text=line, bg=Theme.BG_ALT,
                    fg=Theme.FG_DIM, font=Theme.F_SMALL,
                    anchor="w", justify="left",
                ).pack(fill="x")

        # 스크롤 가능 옵션 목록
        list_wrap = tk.Frame(root, bg=Theme.BG)
        list_wrap.pack(fill="both", expand=True, padx=20, pady=12)
        canvas = tk.Canvas(list_wrap, bg=Theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_wrap, orient="vertical",
                                 command=canvas.yview)
        inner = tk.Frame(canvas, bg=Theme.BG)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120),
                                                     "units"))

        var_map: dict = {}

        for opt in options:
            self._render_option_card(inner, opt, state, var_map, root)

        # 하단 버튼
        btns = tk.Frame(root, bg=Theme.BG, pady=12)
        btns.pack(fill="x", padx=20, pady=(0, 16))

        def on_run():
            result["value"] = {oid for oid, on in state.items() if on}
            root.destroy()

        def on_back():
            result["value"] = None
            root.destroy()

        tk.Button(
            btns, text="▶ 실행", command=on_run,
            bg=Theme.OK, fg=Theme.BG, relief="flat",
            font=Theme.F_BOLD, padx=20, pady=8, cursor="hand2",
        ).pack(side="right")

        tk.Button(
            btns, text="뒤로", command=on_back,
            bg=Theme.BG_ALT, fg=Theme.FG, relief="flat",
            font=Theme.F_BASE, padx=18, pady=8, cursor="hand2",
        ).pack(side="right", padx=(0, 8))

        root.bind("<Escape>", lambda e: on_back())
        root.protocol("WM_DELETE_WINDOW", on_back)

        root.mainloop()
        return result["value"]

    def _render_option_card(self, parent, opt: Option, state, var_map, root):
        var = tk.BooleanVar(value=state[opt.id])
        var_map[opt.id] = var

        card = tk.Frame(parent, bg=Theme.BG_ALT, padx=14, pady=12)
        card.pack(fill="x", pady=4)

        top = tk.Frame(card, bg=Theme.BG_ALT)
        top.pack(fill="x")

        if opt.risk == RISK_HIGH:
            risk_label, risk_color = "⚠⚠ HIGH", Theme.ERR
        elif opt.risk == RISK_MEDIUM:
            risk_label, risk_color = "⚠ MEDIUM", Theme.WARN
        else:
            risk_label, risk_color = "✓ SAFE", Theme.OK

        tk.Label(
            top, text=risk_label, bg=Theme.BG_ALT, fg=risk_color,
            font=("Segoe UI", 9, "bold"), width=10, anchor="w",
        ).pack(side="left")

        chk_state = "disabled" if opt.locked else "normal"
        tk.Checkbutton(
            top, text=opt.label, variable=var,
            bg=Theme.BG_ALT, fg=Theme.FG,
            activebackground=Theme.BG_ALT, activeforeground=Theme.FG,
            selectcolor=Theme.BG, font=Theme.F_BOLD,
            anchor="w", state=chk_state, cursor="hand2",
        ).pack(side="left", padx=(8, 0), fill="x", expand=True)

        if opt.description:
            tk.Label(
                card, text=opt.description, bg=Theme.BG_ALT,
                fg=Theme.FG_DIM, font=Theme.F_SMALL,
                anchor="w", justify="left", wraplength=640,
            ).pack(fill="x", padx=(74, 0), pady=(6, 0))

        def on_toggle(*_a):
            if opt.locked:
                var.set(state[opt.id])
                return
            new_val = var.get()
            if new_val and not state[opt.id]:
                if opt.risk >= RISK_MEDIUM:
                    if not self.confirm_dangerous(
                        opt.label, opt.description, opt.risk,
                    ):
                        var.set(False)
                        return
                for ex_id in opt.excludes:
                    if state.get(ex_id) and ex_id in var_map:
                        var_map[ex_id].set(False)
                        state[ex_id] = False
            state[opt.id] = var.get()

        var.trace_add("write", on_toggle)

    # ── 위험 옵션 다이얼로그 ──
    def confirm_dangerous(
        self, label: str, description: str, risk: int,
    ) -> bool:
        keyword = _RISK_KEYWORD.get(risk, "ENABLE")
        head_color = Theme.ERR if risk == RISK_HIGH else Theme.WARN
        head_text = (
            "⚠⚠ 매우 위험한 옵션 활성화" if risk == RISK_HIGH
            else "⚠ 주의 필요한 옵션 활성화"
        )
        warn_text = (
            "이 옵션은 시스템에 심각한 영향을 줄 수 있습니다."
            if risk == RISK_HIGH
            else "이 옵션은 추가 위험이 있습니다."
        )

        # 부모 윈도우 자동 탐색 (열린 Tk 인스턴스 활용)
        try:
            parent = tk._default_root
        except Exception:
            parent = None

        if parent is None:
            dlg = tk.Tk()
            owns_root = True
        else:
            dlg = tk.Toplevel(parent)
            owns_root = False
            dlg.transient(parent)
            dlg.grab_set()

        dlg.title(head_text)
        dlg.configure(bg=Theme.BG)
        dlg.geometry("560x420")
        dlg.resizable(False, False)

        tk.Label(
            dlg, text=head_text, bg=Theme.BG, fg=head_color,
            font=("Segoe UI", 14, "bold"), pady=14,
        ).pack(fill="x")

        body = tk.Frame(dlg, bg=Theme.BG_ALT, padx=20, pady=16)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        tk.Label(
            body, text=label, bg=Theme.BG_ALT, fg=Theme.FG,
            font=("Segoe UI", 12, "bold"), anchor="w", justify="left",
        ).pack(fill="x", pady=(0, 10))

        if description:
            tk.Label(
                body, text=description, bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_SMALL, anchor="w", justify="left", wraplength=480,
            ).pack(fill="x", pady=(0, 12))

        tk.Label(
            body, text=warn_text, bg=Theme.BG_ALT, fg=head_color,
            font=Theme.F_BOLD, anchor="w", justify="left", wraplength=480,
        ).pack(fill="x", pady=(0, 12))

        tk.Label(
            body, text=f"활성화하려면 정확히 '{keyword}'를 입력:",
            bg=Theme.BG_ALT, fg=Theme.FG, font=Theme.F_BASE,
            anchor="w", justify="left",
        ).pack(fill="x", pady=(0, 6))

        entry = tk.Entry(
            body, bg=Theme.BG, fg=Theme.FG, insertbackground=Theme.FG,
            font=Theme.F_MONO, relief="flat", highlightthickness=1,
            highlightbackground=Theme.BG_HOVER,
            highlightcolor=head_color,
        )
        entry.pack(fill="x", ipady=6)
        entry.focus_set()

        result = {"ok": False}

        def on_ok():
            result["ok"] = (entry.get() == keyword)
            dlg.destroy()

        def on_cancel():
            result["ok"] = False
            dlg.destroy()

        btns = tk.Frame(dlg, bg=Theme.BG)
        btns.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(
            btns, text="취소", command=on_cancel,
            bg=Theme.BG_ALT, fg=Theme.FG, relief="flat",
            font=Theme.F_BASE, padx=18, pady=6, cursor="hand2",
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            btns, text="활성화", command=on_ok,
            bg=head_color, fg=Theme.BG, relief="flat",
            font=Theme.F_BOLD, padx=18, pady=6, cursor="hand2",
        ).pack(side="right")

        entry.bind("<Return>", lambda e: on_ok())
        dlg.bind("<Escape>", lambda e: on_cancel())

        if owns_root:
            dlg.mainloop()
        else:
            parent.wait_window(dlg)

        return result["ok"]
