# -*- coding: utf-8 -*-
"""entry_dialog — 에이전트 진입 통합 설정 (ENTRY_DIALOG_v3, 메인 창 내장 + 진행바).

v2 버그 수정: PanelHost.replace 는 build(parent) 가 '패널 객체를 반환'하고 그 객체를
.pack()/.destroy() 하도록 기대한다. v2 는 프레임을 직접 pack 하고 None 을 반환해
None.pack() 예외 -> [시작] 무반응이었다. v3 는 프레임을 반환한다(호스트가 pack).
또한 [시작] 시 동일 UI 에 진행 프로세스바(ttk indeterminate)를 띄운다.

agent_setup(env, presenter) 반환:
  dict {"tag","reason","label","mode","tor"} / None(취소) / False(폴백)
"""
from __future__ import annotations

_BG = "#1e1e1e"
_CARD = "#252526"
_DIM = "#9d9d9d"
_ACC = "#0e639c"
_ACC_HI = "#1177bb"
_WARN = "#d7ba7d"
_LINE = "#3c3c3c"

EXEC_KEYS = ("5", "2", "3", "4")


def _model_roles():
    try:
        from ..models import model_roles as mr
        return mr
    except Exception:
        pass
    try:
        from launcher.models import model_roles as mr
        return mr
    except Exception:
        pass
    from launcher import model_roles as mr
    return mr


def _resolve(mr, role_key, free):
    role = mr.by_key(role_key) or mr.by_key("2")
    res = mr.resolve(role, free)
    tag, reason = res.model, res.reason
    lad = getattr(mr, "LADDERS", {})
    if getattr(role, "name", "") in lad and hasattr(mr, "resolve_ladder"):
        picked = mr.resolve_ladder(role.name, free)
        if picked:
            tag = picked
    return {"tag": tag, "reason": reason, "label": getattr(role, "label", role_key)}


def agent_setup(env=None, presenter=None):
    try:
        mr = _model_roles()
        roles = [mr.by_key(k) for k in EXEC_KEYS if mr.by_key(k)]
        if not roles:
            return False
        try:
            free = mr.detect_free_memory_gb()
        except Exception:
            free = None
    except Exception:
        return False

    main_window = getattr(presenter, "_window", None)
    if main_window is None or not hasattr(main_window, "host") or not hasattr(main_window, "root"):
        return False
    try:
        import tkinter as tk
        from tkinter import ttk
        import threading
    except Exception:
        return False

    result = {"value": False}
    done = threading.Event()
    free_txt = ("여유 메모리 %.1fGB" % free) if free is not None else "여유 메모리 탐지 실패"

    def build_setup(parent):
        base = tk.Frame(parent, bg=_BG)  # 호스트가 pack 함 (직접 pack 하지 않음!)
        try:
            tk.Label(base, text="에이전트 시작 설정", bg=_BG, fg="#ffffff",
                     font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x", padx=18, pady=(16, 2))
            tk.Label(base, text=free_txt + " · 아래에서 선택 후 [시작]", bg=_BG, fg=_DIM,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=18, pady=(0, 8))

            role_var = tk.StringVar(value=(roles[0].key if roles else "5"))
            mode_var = tk.StringVar(value="sandbox")
            net_var = tk.StringVar(value="block")

            def _section(title, desc):
                c = tk.Frame(base, bg=_CARD)
                c.pack(fill="x", padx=18, pady=(6, 2))
                tk.Label(c, text=title, bg=_CARD, fg=_ACC_HI, font=("Segoe UI", 10, "bold"),
                         anchor="w").pack(fill="x", padx=12, pady=(8, 0))
                if desc:
                    tk.Label(c, text=desc, bg=_CARD, fg=_DIM, font=("Segoe UI", 8),
                             anchor="w").pack(fill="x", padx=12)
                return c

            def _radio(par, var, value, title, sub, danger=False):
                row = tk.Frame(par, bg=_CARD)
                row.pack(fill="x", padx=12, pady=1)
                tk.Radiobutton(row, variable=var, value=value, bg=_CARD, activebackground=_CARD,
                               selectcolor=_ACC, highlightthickness=0, bd=0,
                               fg="#dddddd", activeforeground="#ffffff",
                               text=" " + title, font=("Segoe UI", 9, "bold"),
                               anchor="w", justify="left").pack(side="left")
                if sub:
                    tk.Label(row, text="  " + sub, bg=_CARD, fg=(_WARN if danger else _DIM),
                             font=("Segoe UI", 8), anchor="w").pack(side="left")

            sec = _section("모델 역할", "세션 중 /model 로 변경 가능")
            for i, r in enumerate(roles):
                star = "  ★기본" if i == 0 else ""
                _radio(sec, role_var, r.key, getattr(r, "label", r.key) + star,
                       getattr(r, "description", ""))
            tk.Label(sec, text="", bg=_CARD).pack(pady=(0, 4))

            sec2 = _section("실행 모드", None)
            _radio(sec2, mode_var, "sandbox", "샌드박스 (권장·안전)", "격리된 컨테이너에서 실행")
            _radio(sec2, mode_var, "host", "호스트 직접 (위험)", "PC 에 직접 영향 — 주의", danger=True)
            tk.Label(sec2, text="", bg=_CARD).pack(pady=(0, 4))

            sec3 = _section("인터넷 (샌드박스)", None)
            _radio(sec3, net_var, "block", "차단 (기본·안전)", "외부 인터넷 없음")
            _radio(sec3, net_var, "tor", "Tor 경유 허용", "외부 트래픽을 Tor 로 우회 (Tor 필요)", danger=True)
            tk.Label(sec3, text="", bg=_CARD).pack(pady=(0, 4))

            def _show_progress():
                for w in base.winfo_children():
                    try:
                        w.destroy()
                    except Exception:
                        pass
                tk.Label(base, text="에이전트 준비 중...", bg=_BG, fg="#ffffff",
                         font=("Segoe UI", 14, "bold")).pack(pady=(70, 10))
                tk.Label(base, text="컨테이너 기동·모델 적재를 시작합니다. 잠시만 기다려 주세요.",
                         bg=_BG, fg=_DIM, font=("Segoe UI", 9)).pack(pady=(0, 18))
                try:
                    pb = ttk.Progressbar(base, mode="indeterminate", length=340)
                    pb.pack(pady=8)
                    pb.start(12)
                except Exception:
                    pass

            def _start():
                try:
                    sel = _resolve(mr, role_var.get(), free)
                except Exception:
                    sel = {"tag": None, "reason": "resolve 실패", "label": role_var.get()}
                sel["mode"] = mode_var.get()
                sel["tor"] = (net_var.get() == "tor" and mode_var.get() == "sandbox")
                result["value"] = sel
                try:
                    _show_progress()  # 동일 UI 에 진행바
                except Exception:
                    pass
                done.set()

            def _cancel():
                result["value"] = None
                done.set()

            foot = tk.Frame(base, bg=_BG)
            foot.pack(fill="x", padx=18, pady=(12, 16))
            tk.Button(foot, text="시작", command=_start, bg=_ACC, fg="#ffffff",
                      activebackground=_ACC_HI, relief="flat", font=("Segoe UI", 11, "bold"),
                      padx=22, pady=7).pack(side="left")
            tk.Button(foot, text="취소", command=_cancel, bg=_CARD, fg="#dddddd",
                      activebackground=_LINE, relief="flat", font=("Segoe UI", 10),
                      padx=16, pady=7).pack(side="right")
        except Exception:
            result["value"] = False
            done.set()
        return base  # 반드시 반환 (호스트가 .pack() 함)

    def _on_main():
        try:
            main_window.host.replace(build_setup)
        except Exception:
            result["value"] = False
            done.set()

    try:
        main_window.root.after(0, _on_main)
    except Exception:
        return False

    if not done.wait(timeout=600):
        return None
    return result["value"]
