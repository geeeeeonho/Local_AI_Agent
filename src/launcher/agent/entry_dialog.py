# -*- coding: utf-8 -*-
"""Integrated Agent entry settings.

Network mode is a product policy, not a Sandbox-only option. The selected mode
is therefore committed through ``launcher.network_policy`` for both Host and
Sandbox sessions before the controller starts a runtime.
"""
from __future__ import annotations

# Neutral fallback for legacy launch contexts without a shared theme controller.
_BG = "#f2f3f5"
_CARD = "#fafbfc"
_DIM = "#526071"
_ACC = "#425b73"
_ACC_HI = "#354b61"
_WARN = "#815621"
_LINE = "#cad1d8"
_FG = "#25313d"
_INK = "#ffffff"

EXEC_KEYS = ("5", "2", "3", "4")


def _model_roles():
    try:
        from ..models import model_roles as mr
        return mr
    except Exception:
        pass
    from launcher.models import model_roles as mr
    return mr


def _resolve(mr, role_key, free):
    role = mr.by_key(role_key) or mr.by_key("2")
    res = mr.resolve(role, free)
    tag, reason = res.model, res.reason
    ladders = getattr(mr, "LADDERS", {})
    if getattr(role, "name", "") in ladders and hasattr(mr, "resolve_ladder"):
        picked = mr.resolve_ladder(role.name, free)
        if picked is None:
            return {"tag": None,
                    "reason": "현재 여유 메모리로 적재 가능한 모델이 없습니다. "
                              "Models 화면에서 하 단계 모델을 수동 설치하거나 메모리를 확보하세요.",
                    "label": getattr(role, "label", role_key)}
        tag = picked
    return {"tag": tag, "reason": reason, "label": getattr(role, "label", role_key)}


def _active_network_mode():
    """The mode the desktop already prepared, or the canonical default."""
    try:
        try:
            from .. import network_policy
        except Exception:
            from launcher import network_policy  # type: ignore
        return network_policy.current_mode().value
    except Exception:
        return "warp"


def agent_setup(env=None, presenter=None, active_network=None):
    del env
    try:
        mr = _model_roles()
        roles = [mr.by_key(key) for key in EXEC_KEYS if mr.by_key(key)]
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
        from tkinter import messagebox, ttk
        from apps.shared.widgets import ScrollArea
        import threading
    except Exception:
        return False

    result = {"value": False}
    done = threading.Event()
    free_txt = ("여유 메모리 %.1fGB" % free) if free is not None else "여유 메모리 탐지 실패"
    # 이 창은 이미 한 가지 네트워크 모드를 준비해 두고 열린다. 그런데 기본값이
    # 늘 "warp" 로 고정돼 있어서, Network 화면에서 direct/tor/block 을 고른
    # 사용자는 아무것도 바꾸지 않고 [시작] 을 눌러도 "활성 네트워크가 ...로
    # 고정되어 있습니다" 로 거절당했다. 준비된 모드를 그대로 보여 준다.
    active = str(active_network or _active_network_mode()).strip().lower()
    if active not in ("warp", "tor", "direct", "block"):
        active = "warp"

    def build_setup(parent):
        # Follow the selected Studio palette instead of opening a permanently
        # dark Agent wizard over a light workspace.
        palette = getattr(getattr(parent.winfo_toplevel(),
                                  "_localai_theme", None), "palette", None)
        _BG = palette.bg if palette else globals()["_BG"]
        _CARD = palette.surface if palette else globals()["_CARD"]
        _DIM = palette.muted if palette else globals()["_DIM"]
        _ACC = palette.chat if palette else globals()["_ACC"]
        _ACC_HI = _ACC
        _WARN = palette.warning if palette else globals()["_WARN"]
        _LINE = palette.border if palette else globals()["_LINE"]
        _FG = palette.fg if palette else globals()["_FG"]
        _INK = palette.solid_ink if palette else globals()["_INK"]
        base = tk.Frame(parent, bg=_BG)
        try:
            tk.Label(
                base,
                text="에이전트 시작 설정",
                bg=_BG,
                fg=_FG,
                font=("Segoe UI", 14, "bold"),
                anchor="w",
            ).pack(fill="x", padx=18, pady=(16, 2))
            tk.Label(
                base,
                text=free_txt + " · 아래에서 선택 후 [시작]",
                bg=_BG,
                fg=_DIM,
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(fill="x", padx=18, pady=(0, 8))

            # A fixed footer takes priority over the scrollable configuration.
            # ScrollArea normally packs itself; defer packing until after
            # Start/Cancel have claimed their guaranteed height.
            scroller = ScrollArea(base)
            scroller.frame.pack_forget()
            config_body = scroller.body

            role_var = tk.StringVar(value=(roles[0].key if roles else "5"))
            mode_var = tk.StringVar(value="sandbox")
            net_var = tk.StringVar(value=active)

            def _section(title, desc):
                card = tk.Frame(config_body, bg=_CARD)
                card.pack(fill="x", padx=10, pady=(3, 2))
                tk.Label(
                    card,
                    text=title,
                    bg=_CARD,
                    fg=_ACC_HI,
                    font=("Segoe UI", 10, "bold"),
                    anchor="w",
                ).pack(fill="x", padx=12, pady=(8, 0))
                if desc:
                    tk.Label(
                        card,
                        text=desc,
                        bg=_CARD,
                        fg=_DIM,
                        font=("Segoe UI", 8),
                        anchor="w",
                    ).pack(fill="x", padx=12)
                return card

            def _radio(par, var, value, title, sub, danger=False):
                row = tk.Frame(par, bg=_CARD)
                row.pack(fill="x", padx=12, pady=(2, 1))
                tk.Radiobutton(
                    row,
                    variable=var,
                    value=value,
                    bg=_CARD,
                    activebackground=_CARD,
                    selectcolor=_CARD,
                    highlightthickness=0,
                    bd=0,
                    fg=_FG,
                    activeforeground=_FG,
                    text=" " + title,
                    font=("Segoe UI", 9, "bold"),
                    anchor="w",
                    justify="left",
                ).pack(anchor="w")
                if sub:
                    tk.Label(
                        row,
                        text=sub,
                        bg=_CARD,
                        fg=(_WARN if danger else _DIM),
                        font=("Segoe UI", 8),
                        anchor="w",
                        justify="left",
                        wraplength=460,
                    ).pack(anchor="w", padx=(24, 0))

            sec = _section("모델 역할", "세션 중 /model 로 변경 가능")
            for index, role in enumerate(roles):
                star = "  ★기본" if index == 0 else ""
                _radio(
                    sec,
                    role_var,
                    role.key,
                    getattr(role, "label", role.key) + star,
                    getattr(role, "description", ""),
                )
            tk.Label(sec, text="", bg=_CARD).pack(pady=(0, 1))

            sec2 = _section("실행 모드", None)
            _radio(sec2, mode_var, "sandbox", "샌드박스 (권장·안전)", "격리된 컨테이너에서 실행")
            _radio(sec2, mode_var, "host", "호스트 직접 (위험)", "PC 에 직접 영향 — 주의", danger=True)
            tk.Label(sec2, text="", bg=_CARD).pack(pady=(0, 1))

            sec3 = _section(
                "인터넷",
                "현재 준비된 모드: " + active
                + " · 다른 모드로 바꾸려면 Network 화면에서 먼저 변경하세요",
            )
            def _net_label(value, text):
                return text + (" ★현재" if active == value else "")

            _radio(
                sec3,
                net_var,
                "warp",
                _net_label("warp", "WARP 경유 (빠름)"),
                "Cloudflare WARP + HTTP 브리지로 IP 보호",
            )
            _radio(sec3, net_var, "tor", _net_label("tor", "Tor 경유 (최고 익명)"),
                   "가장 익명적이나 느림")
            _radio(
                sec3,
                net_var,
                "direct",
                _net_label("direct", "직접 연결"),
                "프록시 없이 외부 연결 — 실제 IP가 노출될 수 있음",
                danger=True,
            )
            _radio(
                sec3,
                net_var,
                "block",
                _net_label("block", "차단"),
                "샌드박스의 관리형 웹 접근 차단. Host는 아직 강제 경계가 없어 선택 불가",
            )
            tk.Label(sec3, text="", bg=_CARD).pack(pady=(0, 1))

            def _show_progress():
                for widget in base.winfo_children():
                    try:
                        widget.destroy()
                    except Exception:
                        pass
                tk.Label(
                    base,
                    text="에이전트 준비 중...",
                    bg=_BG,
                    fg=_FG,
                    font=("Segoe UI", 14, "bold"),
                ).pack(pady=(70, 10))
                tk.Label(
                    base,
                    text="컨테이너·프록시·모델 런타임을 준비합니다.",
                    bg=_BG,
                    fg=_DIM,
                    font=("Segoe UI", 9),
                ).pack(pady=(0, 18))
                try:
                    progress = ttk.Progressbar(base, mode="indeterminate", length=340)
                    progress.pack(pady=8)
                    progress.start(12)
                except Exception:
                    pass

            def _start():
                try:
                    selected = _resolve(mr, role_var.get(), free)
                except Exception:
                    selected = {"tag": None, "reason": "resolve 실패", "label": role_var.get()}

                if not selected.get("tag"):
                    messagebox.showwarning(
                        "모델 메모리 부족",
                        selected.get("reason") or "현재 실행 가능한 모델이 없습니다.",
                        parent=base,
                    )
                    return

                _nm = net_var.get().strip().lower()
                if mode_var.get() == "host" and _nm == "block":
                    messagebox.showwarning(
                        "Host 차단 모드 미지원",
                        "Host 모드에는 아직 OS 수준 외부 egress 차단 경계가 없습니다. "
                        "샌드박스 차단을 사용하거나 WARP/Tor/직접 연결 중 하나를 선택하세요.",
                        parent=base,
                    )
                    return

                try:
                    try:
                        from .. import network_policy
                    except Exception:
                        from launcher import network_policy
                    canonical = network_policy.set_mode(_nm)
                    _nm = canonical.value
                except Exception:
                    pass

                selected["mode"] = mode_var.get()
                selected["net_mode"] = _nm
                # Historic controller compatibility only. It means "protected
                # proxy mode"; WARP vs Tor is resolved by network_policy.
                selected["tor"] = _nm in ("warp", "tor")
                result["value"] = selected
                try:
                    _show_progress()
                except Exception:
                    pass
                done.set()

            def _cancel():
                result["value"] = None
                done.set()

            foot = tk.Frame(base, bg=_BG)
            foot.pack(side="bottom",fill="x", padx=12, pady=(5, 8))
            tk.Button(
                foot,
                text="시작",
                command=_start,
                bg=_ACC,
                fg=_INK,
                activeforeground=_INK,
                activebackground=_ACC_HI,
                relief="flat",
                font=("Segoe UI", 11, "bold"),
                padx=22,
                pady=7,
            ).pack(side="left")
            tk.Button(
                foot,
                text="취소",
                command=_cancel,
                bg=_CARD,
                fg=_FG,
                activeforeground=_FG,
                activebackground=_LINE,
                relief="flat",
                font=("Segoe UI", 10),
                padx=16,
                pady=7,
            ).pack(side="right")

            # Keep Sandbox and the already-pinned Network mode as safe defaults.
            # The user can reveal advanced choices without losing their state.
            advanced = tk.Button(
                config_body, text="고급 실행·인터넷 설정 ▸",
                bg=_CARD, fg=_FG, activebackground=_LINE,
                activeforeground=_FG, relief="flat",
                font=("Segoe UI", 9), anchor="w",
                padx=12, pady=5)
            advanced.pack(after=sec,fill="x",padx=10,pady=(4,4))
            sec2.pack_forget()
            sec3.pack_forget()
            expanded = [False]
            def toggle_options():
                expanded[0] = not expanded[0]
                if expanded[0]:
                    sec2.pack(after=advanced,fill="x",padx=10,pady=(3,2))
                    sec3.pack(after=sec2,fill="x",padx=10,pady=(3,2))
                else:
                    sec2.pack_forget()
                    sec3.pack_forget()
                advanced.configure(
                    text="고급 실행·인터넷 설정 ▾" if expanded[0]
                         else "고급 실행·인터넷 설정 ▸")
                scroller.bind_content()
            advanced.configure(command=toggle_options)
            scroller.frame.pack(fill="both",expand=True)
            scroller.bind_content()
        except Exception:
            result["value"] = False
            done.set()
        return base

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
