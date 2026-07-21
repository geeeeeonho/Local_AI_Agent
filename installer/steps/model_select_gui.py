# -*- coding: utf-8 -*-
"""model_select_gui — 모델 관리 통합 창 (설치 + 삭제, 독립 Tkinter, stdlib).

MODEL_MANAGE_GUI_v2.
체크 = "있어야 함":
  - 미설치 + 체크   → 설치(pull)
  - 설치됨 + 체크   → 유지
  - 설치됨 + 체크해제 → 삭제(rm, 확인 후)
  - 미설치 + 체크해제 → 무시

installer.model.download() 와 MANAGE(installer.manage) 가 함께 호출.
반환:
  set[str] : "있어야 할" 최종 태그 집합 (호출부가 installed 와 비교해 install/delete 계산)
  None     : 취소
Tk 사용 불가 시 예외 → 호출부가 자동(권장) 폴백.
"""
from __future__ import annotations

from typing import Optional, Set

_BG = "#1e1e1e"
_CARD = "#252526"
_FG = "#d4d4d4"
_DIM = "#9d9d9d"
_ACC = "#0e639c"
_ACC_HI = "#1177bb"
_OK = "#4ec9b0"
_DEL = "#f48771"
_LINE = "#3c3c3c"


def _texts(ko: bool) -> dict:
    if ko:
        return {
            "title": "모델 관리 (설치 / 삭제)",
            "intro": "체크 = 있어야 함. 체크하면 설치, 설치된 모델을 체크 해제하면 삭제됩니다.",
            "core": "기본 (권장)",
            "adv": "추가 후보 (역할별)",
            "extra": "설치됨 (목록 외)",
            "installed": "설치됨",
            "summary": "설치 예정 {ins}개 (~{gb:.1f} GB)   ·   삭제 예정 {dele}개",
            "all": "전체 선택", "none": "전체 해제", "rec": "권장만",
            "apply": "적용", "cancel": "취소",
            "confirm_t": "삭제 확인",
            "confirm_m": "{n}개 모델을 삭제합니다:\n\n{lst}\n\n계속할까요?",
        }
    return {
        "title": "Model manager (install / delete)",
        "intro": "Checked = should exist. Check to install; uncheck an installed model to delete it.",
        "core": "Core (recommended)",
        "adv": "Candidates (by role)",
        "extra": "Installed (not in catalog)",
        "installed": "installed",
        "summary": "Install {ins} (~{gb:.1f} GB)   ·   Delete {dele}",
        "all": "Select all", "none": "Clear", "rec": "Recommended",
        "apply": "Apply", "cancel": "Cancel",
        "confirm_t": "Confirm delete",
        "confirm_m": "Delete {n} model(s):\n\n{lst}\n\nProceed?",
    }


def select_models(entries, installed, lang: str = "ko") -> Optional[Set[str]]:
    import tkinter as tk
    from tkinter import messagebox

    ko = str(lang).startswith("ko")
    T = _texts(ko)
    installed = set(installed or [])
    cat_tags = {e.tag for e in entries}
    extra_installed = sorted(installed - cat_tags)
    size_of = {e.tag: float(getattr(e, "size_gb", 0.0)) for e in entries}

    root = tk.Tk()
    root.title(T["title"])
    root.configure(bg=_BG)
    root.minsize(700, 540)
    try:
        root.geometry("800x680")
    except Exception:
        pass

    result = {"value": None}
    vars_: dict = {}

    head = tk.Frame(root, bg=_BG)
    head.pack(fill="x", padx=22, pady=(18, 4))
    tk.Label(head, text=T["title"], bg=_BG, fg="#ffffff",
             font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x")
    tk.Label(head, text=T["intro"], bg=_BG, fg=_DIM, font=("Segoe UI", 9),
             anchor="w", justify="left", wraplength=740).pack(fill="x", pady=(4, 0))
    sum_lbl = tk.Label(head, text="", bg=_BG, fg=_OK,
                       font=("Segoe UI", 10, "bold"), anchor="w")
    sum_lbl.pack(fill="x", pady=(8, 0))

    def _recompute(*_a):
        desired = {t for t, v in vars_.items() if v.get()}
        ins = desired - installed
        dele = installed - desired
        gb = sum(size_of.get(t, 0.0) for t in ins)
        sum_lbl.config(text=T["summary"].format(ins=len(ins), gb=gb, dele=len(dele)),
                       fg=(_DEL if dele else _OK))

    body = tk.Frame(root, bg=_BG)
    body.pack(fill="both", expand=True, padx=22, pady=10)
    canvas = tk.Canvas(body, bg=_BG, highlightthickness=0)
    sb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=_BG)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw", width=740)
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
        int(-1 * (e.delta / 120)) if e.delta else 0, "units"))

    def _group(title):
        g = tk.Frame(inner, bg=_BG)
        g.pack(fill="x", pady=(10, 2))
        tk.Label(g, text=title, bg=_BG, fg=_ACC_HI,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        tk.Frame(g, bg=_LINE, height=1).pack(fill="x", pady=(3, 0))

    def _row(tag, role, size, desc, default_checked):
        done = tag in installed
        var = tk.BooleanVar(value=default_checked)
        vars_[tag] = var
        card = tk.Frame(inner, bg=_CARD)
        card.pack(fill="x", pady=4)
        pad = tk.Frame(card, bg=_CARD)
        pad.pack(fill="x", padx=12, pady=8)
        line = tag + "   ·   " + role + "   ·   ~" + format(size, ".1f") + "GB"
        if done:
            line += "   [" + T["installed"] + "]"
        cb = tk.Checkbutton(
            pad, text=line, variable=var, command=_recompute,
            bg=_CARD, fg=(_OK if done else _FG), activebackground=_CARD,
            activeforeground=_FG, selectcolor=_BG, font=("Segoe UI", 10, "bold"),
            anchor="w", justify="left", padx=2, highlightthickness=0, bd=0)
        cb.pack(fill="x", anchor="w")
        if desc:
            tk.Label(pad, text=desc, bg=_CARD, fg=_DIM, font=("Segoe UI", 9),
                     anchor="w", justify="left", wraplength=680).pack(
                         fill="x", padx=(24, 0), pady=(2, 0))

    core = [e for e in entries if getattr(e, "group", "core") == "core"]
    adv = [e for e in entries if getattr(e, "group", "core") != "core"]
    if core:
        _group(T["core"])
        for e in core:
            done = e.tag in installed
            _row(e.tag, getattr(e, "role", ""), getattr(e, "size_gb", 0.0),
                 getattr(e, "desc", ""), done or bool(getattr(e, "recommended", True)))
    if adv:
        _group(T["adv"])
        for e in adv:
            done = e.tag in installed
            _row(e.tag, getattr(e, "role", ""), getattr(e, "size_gb", 0.0),
                 getattr(e, "desc", ""), done or bool(getattr(e, "recommended", False)))
    if extra_installed:
        _group(T["extra"])
        for tag in extra_installed:
            _row(tag, "-", 0.0, "카탈로그에 없는 설치 모델 (체크 해제 시 삭제)", True)

    bar = tk.Frame(root, bg=_BG)
    bar.pack(fill="x", padx=22, pady=(6, 16))

    def _set_all(val):
        for v in vars_.values():
            v.set(val)
        _recompute()

    def _set_rec():
        for e in entries:
            vars_[e.tag].set(e.tag in installed or bool(getattr(e, "recommended", True)))
        for tag in extra_installed:
            vars_[tag].set(True)
        _recompute()

    def _mk(text, cmd, primary=False):
        return tk.Button(bar, text=text, command=cmd,
                         bg=(_ACC if primary else _CARD),
                         fg=("#ffffff" if primary else _FG),
                         activebackground=(_ACC_HI if primary else _LINE),
                         activeforeground="#ffffff",
                         font=("Segoe UI", 10, "bold" if primary else "normal"),
                         relief="flat", bd=0, padx=16, pady=8, cursor="hand2")

    _mk(T["all"], lambda: _set_all(True)).pack(side="left", padx=(0, 6))
    _mk(T["none"], lambda: _set_all(False)).pack(side="left", padx=6)
    _mk(T["rec"], _set_rec).pack(side="left", padx=6)

    def _apply():
        desired = {t for t, v in vars_.items() if v.get()}
        dele = sorted(installed - desired)
        if dele:
            lst = "\n".join("  - " + d for d in dele[:12]) + ("\n  ..." if len(dele) > 12 else "")
            if not messagebox.askyesno(T["confirm_t"],
                                       T["confirm_m"].format(n=len(dele), lst=lst),
                                       parent=root):
                return
        result["value"] = desired
        root.destroy()

    def _cancel():
        result["value"] = None
        root.destroy()

    _mk(T["apply"], _apply, primary=True).pack(side="right")
    _mk(T["cancel"], _cancel).pack(side="right", padx=(0, 8))
    root.protocol("WM_DELETE_WINDOW", _cancel)
    root.bind("<Return>", lambda e: _apply())
    root.bind("<Escape>", lambda e: _cancel())

    _recompute()
    try:
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("+%d+%d" % (max(0, (sw - w) // 2), max(0, (sh - h) // 2)))
    except Exception:
        pass
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.after(500, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    root.mainloop()
    return result["value"]
