"""dialogs — 모달 다이얼로그 (입력 / 위험 확인).

메뉴는 사이드바로 들어갔으니 모달은 진짜 필요한 경우만:
  - 위험 옵션 활성화 (키워드 입력 강제)
  - 자유 텍스트 입력
  - 폴더 선택은 표준 filedialog 사용 (Tk 표준)
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from ..base import RISK_HIGH
from .theme import RISK_KEYWORDS, Theme
from .widgets import make_button


def confirm_dangerous(
    parent: tk.Misc,
    label: str, description: str, risk: int,
) -> bool:
    """위험 옵션 활성화 확인 — 정확한 키워드 입력 요구.

    HIGH:   I-UNDERSTAND
    MEDIUM: ENABLE
    """
    keyword = RISK_KEYWORDS.get(risk, "ENABLE")
    head_color = Theme.DANGER if risk == RISK_HIGH else Theme.FG_DIM
    head_text = (
        "위험한 옵션 활성화" if risk == RISK_HIGH
        else "주의가 필요한 옵션 활성화"
    )
    warn_text = (
        "이 옵션은 시스템에 심각한 영향을 줄 수 있습니다."
        if risk == RISK_HIGH
        else "이 옵션은 추가 위험이 있습니다."
    )

    dlg = tk.Toplevel(parent)
    dlg.title(head_text)
    dlg.configure(bg=Theme.BG)
    dlg.geometry("520x380")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)

    # 위치: 부모 중앙
    try:
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - 520) // 2
        y = py + (ph - 380) // 2
        dlg.geometry(f"520x380+{x}+{y}")
    except Exception:
        pass

    # 헤더
    head = tk.Frame(dlg, bg=Theme.BG)
    head.pack(fill="x", padx=20, pady=(18, 4))
    tk.Label(
        head, text=("⚠ " if risk == RISK_HIGH else "ⓘ "),
        bg=Theme.BG, fg=head_color,
        font=("Segoe UI Symbol", 16),
    ).pack(side="left")
    tk.Label(
        head, text=head_text,
        bg=Theme.BG, fg=Theme.FG_BRIGHT,
        font=("Segoe UI", 13, "bold"),
    ).pack(side="left", padx=(6, 0))

    # 본문
    body = tk.Frame(dlg, bg=Theme.BG_ALT, padx=18, pady=14)
    body.pack(fill="both", expand=True, padx=20, pady=(8, 0))

    tk.Label(
        body, text=label, bg=Theme.BG_ALT, fg=Theme.FG_BRIGHT,
        font=("Segoe UI", 11, "bold"), anchor="w", justify="left",
    ).pack(fill="x", pady=(0, 8))

    if description:
        tk.Label(
            body, text=description, bg=Theme.BG_ALT, fg=Theme.FG_DIM,
            font=Theme.F_SMALL, anchor="w", justify="left",
            wraplength=460,
        ).pack(fill="x", pady=(0, 10))

    tk.Label(
        body, text=warn_text, bg=Theme.BG_ALT, fg=head_color,
        font=Theme.F_BOLD, anchor="w", justify="left", wraplength=460,
    ).pack(fill="x", pady=(0, 10))

    tk.Label(
        body, text=f"활성화하려면 정확히 '{keyword}'를 입력:",
        bg=Theme.BG_ALT, fg=Theme.FG, font=Theme.F_BASE,
        anchor="w",
    ).pack(fill="x", pady=(4, 4))

    entry = tk.Entry(
        body, bg=Theme.BG_INPUT, fg=Theme.FG_BRIGHT,
        insertbackground=Theme.FG_BRIGHT,
        font=Theme.F_MONO, relief="flat",
        highlightthickness=1,
        highlightbackground=Theme.BORDER,
        highlightcolor=Theme.BORDER_FOCUS,
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
    btns.pack(fill="x", padx=20, pady=14)
    make_button(btns, "취소", on_cancel).pack(side="right", padx=(8, 0))
    make_button(
        btns, "활성화", on_ok,
        primary=(risk != RISK_HIGH),
        danger=(risk == RISK_HIGH),
    ).pack(side="right")

    entry.bind("<Return>", lambda e: on_ok())
    dlg.bind("<Escape>", lambda e: on_cancel())
    dlg.protocol("WM_DELETE_WINDOW", on_cancel)

    parent.wait_window(dlg)
    return result["ok"]


def prompt_text(
    parent: tk.Misc, prompt: str, default: str = "",
) -> Optional[str]:
    """자유 텍스트 입력 다이얼로그. None = 취소."""
    dlg = tk.Toplevel(parent)
    dlg.title("입력")
    dlg.configure(bg=Theme.BG)
    dlg.geometry("420x180")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)

    tk.Label(
        dlg, text=prompt,
        bg=Theme.BG, fg=Theme.FG,
        font=Theme.F_BASE, anchor="w", justify="left",
        wraplength=380,
    ).pack(fill="x", padx=18, pady=(18, 6))

    var = tk.StringVar(value=default)
    entry = tk.Entry(
        dlg, textvariable=var,
        bg=Theme.BG_INPUT, fg=Theme.FG_BRIGHT,
        insertbackground=Theme.FG_BRIGHT,
        font=Theme.F_MONO, relief="flat",
        highlightthickness=1,
        highlightbackground=Theme.BORDER,
        highlightcolor=Theme.BORDER_FOCUS,
    )
    entry.pack(fill="x", padx=18, pady=4, ipady=6)
    entry.focus_set()
    entry.icursor("end")

    result = {"value": None}

    def on_ok():
        result["value"] = var.get()
        dlg.destroy()

    def on_cancel():
        result["value"] = None
        dlg.destroy()

    btns = tk.Frame(dlg, bg=Theme.BG)
    btns.pack(fill="x", padx=18, pady=14)
    make_button(btns, "취소", on_cancel).pack(side="right", padx=(8, 0))
    make_button(btns, "확인", on_ok, primary=True).pack(side="right")

    dlg.bind("<Return>", lambda e: on_ok())
    dlg.bind("<Escape>", lambda e: on_cancel())
    dlg.protocol("WM_DELETE_WINDOW", on_cancel)

    parent.wait_window(dlg)
    return result["value"]
