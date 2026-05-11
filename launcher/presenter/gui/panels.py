"""panels — 메인 영역의 패널들.

각 패널은 PanelHost 가 내용 영역을 비우고 다시 그릴 때 사용.
- HomePanel: 환영 / 시스템 상태 요약
- CheckboxPanel: 위험도-인지 옵션 메뉴
- LogPanel: 누적 로그 + 확인 버튼
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional, Set

from ..base import Option, RISK_MEDIUM
from .dialogs import confirm_dangerous
from .theme import Theme, risk_color, risk_icon, risk_label
from .widgets import HoverCard, make_button


class _BasePanel:
    """공통 헤더 (제목 + 부제 + 뱃지) 렌더링 헬퍼."""

    @staticmethod
    def render_header(
        parent: tk.Widget, title: str,
        subtitle: str = "", badge: str = "", badge_kind: str = "",
    ):
        head = tk.Frame(parent, bg=Theme.BG)
        head.pack(fill="x", padx=24, pady=(20, 0))

        title_row = tk.Frame(head, bg=Theme.BG)
        title_row.pack(fill="x")
        tk.Label(
            title_row, text=title,
            bg=Theme.BG, fg=Theme.FG_BRIGHT,
            font=Theme.F_TITLE,
        ).pack(side="left")

        if badge:
            color = {
                "good": Theme.OK,
                "danger": Theme.DANGER,
                "warn": Theme.FG_DIM,
            }.get(badge_kind, Theme.FG_DIM)
            tk.Label(
                title_row, text=f"  {badge}",
                bg=Theme.BG, fg=color,
                font=Theme.F_SMALL,
            ).pack(side="left", padx=(4, 0))

        if subtitle:
            tk.Label(
                head, text=subtitle,
                bg=Theme.BG, fg=Theme.FG_DIM,
                font=Theme.F_SUB,
                anchor="w", justify="left", wraplength=720,
            ).pack(fill="x", pady=(6, 0))


class HomePanel(_BasePanel):
    """첫 화면 — 시작 안내."""

    def __init__(self, parent: tk.Widget, env_path: str):
        self.frame = tk.Frame(parent, bg=Theme.BG)
        self.render_header(
            self.frame,
            title="LLM Environment",
            subtitle="좌측 사이드바에서 메뉴를 선택하세요.",
        )

        body = tk.Frame(self.frame, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=18)

        # 빠른 시작 카드들
        for title, desc, hint in [
            ("채팅 UI 시작",
             "Open WebUI 가 브라우저에서 열리고, 자동 웹 검색이 켜집니다.",
             "사이드바 → 채팅 UI"),
            ("샌드박스 에이전트 (권장)",
             "Docker 컨테이너 안에서 LLM 에이전트가 실행됩니다. 호스트는 안전합니다.",
             "사이드바 → 샌드박스 에이전트"),
            ("Ollama / Docker / SearXNG 상태",
             "하단 상태바에서 각 서비스 가동 여부를 확인하세요.",
             "초록 ● = 가동 중"),
        ]:
            card = tk.Frame(
                body, bg=Theme.BG_ALT, padx=16, pady=12,
            )
            card.pack(fill="x", pady=(0, 8))
            tk.Label(
                card, text=title,
                bg=Theme.BG_ALT, fg=Theme.FG_BRIGHT,
                font=Theme.F_BOLD, anchor="w",
            ).pack(fill="x")
            tk.Label(
                card, text=desc,
                bg=Theme.BG_ALT, fg=Theme.FG, font=Theme.F_BASE,
                anchor="w", justify="left", wraplength=680,
            ).pack(fill="x", pady=(2, 0))
            tk.Label(
                card, text=hint,
                bg=Theme.BG_ALT, fg=Theme.FG_DIM, font=Theme.F_TINY,
                anchor="w",
            ).pack(fill="x", pady=(4, 0))

    def pack(self, **kw):
        self.frame.pack(**kw)

    def destroy(self):
        self.frame.destroy()


class CheckboxPanel(_BasePanel):
    """체크박스 옵션 패널 (Presenter.show_checkbox 의 메인 영역 구현).

    실행 / 취소 버튼이 콜백을 호출 — Presenter 의 동기 흐름에서는
    뒷단에서 wait_variable 로 결과를 수신.
    """

    def __init__(
        self, parent: tk.Widget,
        title: str, subtitle: str,
        options: List[Option],
        extra_lines: Optional[List[str]] = None,
        override_defaults: Optional[Set[str]] = None,
        on_done: Optional[Callable[[Optional[Set[str]]], None]] = None,
        parent_window: Optional[tk.Misc] = None,
    ):
        self._on_done = on_done
        self._parent_window = parent_window or parent
        self._options = options

        # 초기 상태
        if override_defaults is not None:
            self._state = {opt.id: (opt.id in override_defaults)
                           for opt in options}
            for opt in options:
                if opt.locked:
                    self._state[opt.id] = opt.default
        else:
            self._state = {opt.id: opt.default for opt in options}

        self.frame = tk.Frame(parent, bg=Theme.BG)
        self.render_header(self.frame, title=title, subtitle=subtitle)

        # 추가 정보 (마운트 경로 등)
        if extra_lines:
            info = tk.Frame(self.frame, bg=Theme.BG_ALT)
            info.pack(fill="x", padx=24, pady=(12, 0))
            for line in extra_lines:
                if not line.strip():
                    continue
                tk.Label(
                    info, text=line, bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                    font=Theme.F_SMALL, anchor="w", justify="left",
                    padx=14, pady=2,
                ).pack(fill="x")

        # 옵션 목록 (스크롤)
        list_wrap = tk.Frame(self.frame, bg=Theme.BG)
        list_wrap.pack(fill="both", expand=True, padx=24, pady=12)
        canvas = tk.Canvas(list_wrap, bg=Theme.BG, highlightthickness=0)
        scroll = tk.Scrollbar(list_wrap, orient="vertical",
                              command=canvas.yview)
        inner = tk.Frame(canvas, bg=Theme.BG)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120),
                                                     "units"))

        self._var_map: dict = {}
        for opt in options:
            self._render_option(inner, opt)

        # 버튼
        btns = tk.Frame(self.frame, bg=Theme.BG)
        btns.pack(fill="x", padx=24, pady=(0, 16))
        make_button(btns, "취소", self._cancel).pack(
            side="right", padx=(8, 0)
        )
        make_button(btns, "▶ 실행", self._run, primary=True).pack(
            side="right"
        )

    def _render_option(self, parent: tk.Widget, opt: Option):
        var = tk.BooleanVar(value=self._state[opt.id])
        self._var_map[opt.id] = var

        # 위험도별 좌측 보더 색
        is_high = opt.risk >= RISK_MEDIUM and opt.risk == 2
        border_color = (
            Theme.DANGER if is_high
            else Theme.BG_ALT
        )

        card = tk.Frame(parent, bg=Theme.BG_ALT, padx=0, pady=0)
        card.pack(fill="x", pady=4)

        # 좌측 보더
        tk.Frame(card, bg=border_color, width=2).pack(side="left", fill="y")

        body = tk.Frame(card, bg=Theme.BG_ALT, padx=12, pady=10)
        body.pack(side="left", fill="x", expand=True)

        # 상단 행
        top = tk.Frame(body, bg=Theme.BG_ALT)
        top.pack(fill="x")

        # 체크박스
        chk_state = "disabled" if opt.locked else "normal"
        chk = tk.Checkbutton(
            top, variable=var,
            bg=Theme.BG_ALT, activebackground=Theme.BG_ALT,
            selectcolor=Theme.BG_INPUT,
            highlightthickness=0, bd=0,
            state=chk_state, cursor="hand2",
        )
        chk.pack(side="left")

        # 위험도 아이콘
        rcolor = risk_color(opt.risk)
        tk.Label(
            top, text=risk_icon(opt.risk),
            bg=Theme.BG_ALT, fg=rcolor,
            font=("Segoe UI Symbol", 13),
            width=2, anchor="center",
        ).pack(side="left", padx=(2, 4))

        # 옵션 라벨
        tk.Label(
            top, text=opt.label, bg=Theme.BG_ALT, fg=Theme.FG_BRIGHT,
            font=Theme.F_BOLD, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # 우측 라벨 (위험도 / 잠김)
        if opt.locked:
            tk.Label(
                top, text="🔒 필수",
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_TINY,
            ).pack(side="right")
        elif opt.risk >= RISK_MEDIUM:
            label_text = f"{risk_label(opt.risk)} — 키워드 입력"
            tk.Label(
                top, text=label_text,
                bg=Theme.BG_ALT, fg=rcolor,
                font=Theme.F_TINY,
            ).pack(side="right")

        # 설명
        if opt.description:
            tk.Label(
                body, text=opt.description,
                bg=Theme.BG_ALT, fg=Theme.FG_DIM,
                font=Theme.F_SMALL,
                anchor="w", justify="left", wraplength=620,
            ).pack(fill="x", padx=(28, 0), pady=(4, 0))

        # 토글 핸들러
        def on_toggle(*_a):
            if opt.locked:
                var.set(self._state[opt.id])
                return
            new_val = var.get()
            if new_val and not self._state[opt.id]:
                if opt.risk >= RISK_MEDIUM:
                    if not confirm_dangerous(
                        self._parent_window,
                        opt.label, opt.description, opt.risk,
                    ):
                        var.set(False)
                        return
                # 상호 배제
                for ex_id in opt.excludes:
                    if self._state.get(ex_id):
                        self._state[ex_id] = False
                        if ex_id in self._var_map:
                            self._var_map[ex_id].set(False)
            self._state[opt.id] = var.get()

        var.trace_add("write", on_toggle)

    def _run(self):
        selected = {oid for oid, on in self._state.items() if on}
        if self._on_done:
            self._on_done(selected)

    def _cancel(self):
        if self._on_done:
            self._on_done(None)

    def pack(self, **kw):
        self.frame.pack(**kw)

    def destroy(self):
        self.frame.destroy()


class LogPanel(_BasePanel):
    """텍스트 로그 + 진행 스피너 + 진입점 버튼 + 확인 버튼.

    액션이 진행 중인 동안:
      - 상단에 스피너 (회전 점선 + "진행 중...")
      - 진입점 버튼 영역 (회색, 비활성)
      - 텍스트 영역에 INFO/OK/WARN/ERROR 누적
      - [확인] 버튼은 비활성 (회색)
    액션 완료 시:
      - 스피너 → 체크마크
      - 진입점 버튼이 활성화 (예: "브라우저 열기 (http://localhost:8080)")
      - [확인] 버튼 활성화
    외부 프로세스 종료 감지 시:
      - 진입점 버튼이 "종료됨 - 다시 시작" 으로 바뀜 (다시 누르면 재시작)
    """

    def __init__(
        self, parent: tk.Widget,
        title: str = "결과", subtitle: str = "",
        on_done: Optional[Callable[[], None]] = None,
    ):
        # 지연 임포트 (순환 회피)
        from .widgets import Spinner

        self._on_done = on_done

        self.frame = tk.Frame(parent, bg=Theme.BG)
        self.render_header(self.frame, title=title, subtitle=subtitle)

        # ── 스피너 영역 ──
        spinner_wrap = tk.Frame(self.frame, bg=Theme.BG)
        spinner_wrap.pack(fill="x", padx=24, pady=(8, 0))
        self._spinner = Spinner(
            spinner_wrap, text="진행 중...",
            bg=Theme.BG,
        )
        self._spinner.frame.configure(bg=Theme.BG)
        self._spinner._spin_lbl.configure(bg=Theme.BG)
        self._spinner._text_lbl.configure(bg=Theme.BG)
        self._spinner.pack(anchor="w")

        # ── 진입점 버튼 영역 (스피너 아래) ──
        # 액션이 register_entrypoint() 호출하면 활성화됨
        self._entrypoint_wrap = tk.Frame(self.frame, bg=Theme.BG)
        self._entrypoint_wrap.pack(fill="x", padx=24, pady=(8, 0))
        self._entrypoint_btn: Optional[tk.Button] = None
        self._entrypoint_callback: Optional[Callable] = None
        self._entrypoint_label: str = ""
        self._entrypoint_status: str = "pending"  # pending|ready|terminated

        # ── 로그 텍스트 ──
        body = tk.Frame(self.frame, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=12)

        self._text = tk.Text(
            body, bg=Theme.BG_ALT, fg=Theme.FG,
            insertbackground=Theme.FG, font=Theme.F_MONO,
            relief="flat", padx=14, pady=12, wrap="word",
            state="disabled",
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        scroll = tk.Scrollbar(body, command=self._text.yview)
        self._text.configure(yscrollcommand=scroll.set)
        self._text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 색상 태그
        self._text.tag_config("info", foreground=Theme.INFO)
        self._text.tag_config("ok", foreground=Theme.OK)
        self._text.tag_config("warn", foreground=Theme.FG_DIM)
        self._text.tag_config("error", foreground=Theme.DANGER)
        self._text.tag_config("section", foreground=Theme.FG_BRIGHT)

        # ── 버튼 영역 ──
        btns = tk.Frame(self.frame, bg=Theme.BG)
        btns.pack(fill="x", padx=24, pady=(0, 16))

        # 확인 버튼 (처음엔 비활성)
        self._done_btn = make_button(btns, "진행 중...", self._done, primary=False)
        self._done_btn.configure(state="disabled")
        self._done_btn.pack(side="right")

        # 취소 버튼 (진행 중에만 보임)
        self._cancel_callback: Optional[Callable] = None
        self._cancel_btn = tk.Button(
            btns, text="✕ 취소", command=self._cancel,
            bg=Theme.BG_INPUT, fg=Theme.FG,
            activebackground=Theme.BG_HOVER,
            activeforeground=Theme.FG_BRIGHT,
            relief="flat", bd=0, font=Theme.F_BASE,
            padx=14, pady=6, cursor="hand2",
        )
        self._cancel_btn.pack(side="right", padx=(0, 8))
        # 처음엔 hover만 변경되게 — 콜백 없으면 누를 수 없음
        self._cancel_btn.configure(state="disabled")

        self._spinner_active = True

    def set_cancel_callback(self, callback: Optional[Callable]):
        """취소 버튼 활성/비활성. None 주면 비활성."""
        self._cancel_callback = callback
        try:
            if callback is None:
                self._cancel_btn.configure(
                    state="disabled",
                    bg=Theme.BG_INPUT, fg=Theme.FG_DIM,
                )
            else:
                self._cancel_btn.configure(
                    state="normal",
                    bg=Theme.BG_INPUT, fg=Theme.FG,
                    cursor="hand2",
                )
        except tk.TclError:
            pass

    def hide_cancel(self):
        """취소 버튼 완전히 숨김 (액션 끝났을 때)."""
        try:
            self._cancel_btn.pack_forget()
        except tk.TclError:
            pass

    def _cancel(self):
        if self._cancel_callback:
            try:
                self._cancel_callback()
            except Exception:
                pass

    def reserve_entrypoint(self, label: str):
        """액션 시작 시 호출 — 회색 버튼 placeholder 만 만들어 둠.

        실제 동작은 enable_entrypoint() 가 호출되어야 활성화.
        """
        self._entrypoint_label = label
        self._entrypoint_status = "pending"
        try:
            if self._entrypoint_btn is None:
                self._entrypoint_btn = tk.Button(
                    self._entrypoint_wrap,
                    text=f"⏳ {label}  (준비 중...)",
                    bg=Theme.BG_INPUT, fg=Theme.FG_DIM,
                    activebackground=Theme.BG_INPUT,
                    activeforeground=Theme.FG_DIM,
                    relief="flat", bd=0, font=Theme.F_BASE,
                    padx=14, pady=8, cursor="arrow",
                    state="disabled",
                )
                self._entrypoint_btn.pack(side="left", anchor="w")
            else:
                self._entrypoint_btn.configure(
                    text=f"⏳ {label}  (준비 중...)",
                    bg=Theme.BG_INPUT, fg=Theme.FG_DIM,
                    state="disabled", cursor="arrow",
                )
        except tk.TclError:
            pass

    def enable_entrypoint(self, callback: Callable, button_text: str = None):
        """진입점이 준비됨 — 버튼 활성화 (파란색).

        클릭하면 callback 호출.
        """
        self._entrypoint_callback = callback
        self._entrypoint_status = "ready"
        text = button_text or f"▶ {self._entrypoint_label} 열기"
        if self._entrypoint_btn is None:
            try:
                self._entrypoint_btn = tk.Button(
                    self._entrypoint_wrap,
                    text=text, command=self._on_entrypoint_click,
                    bg=Theme.ACCENT, fg=Theme.FG_BRIGHT,
                    activebackground=Theme.ACCENT_HOVER,
                    activeforeground=Theme.FG_BRIGHT,
                    relief="flat", bd=0, font=Theme.F_BOLD,
                    padx=18, pady=8, cursor="hand2",
                )
                self._entrypoint_btn.pack(side="left", anchor="w")
            except tk.TclError:
                return
        else:
            try:
                self._entrypoint_btn.configure(
                    text=text, command=self._on_entrypoint_click,
                    bg=Theme.ACCENT, fg=Theme.FG_BRIGHT,
                    activebackground=Theme.ACCENT_HOVER,
                    activeforeground=Theme.FG_BRIGHT,
                    font=Theme.F_BOLD, cursor="hand2",
                    state="normal",
                )
            except tk.TclError:
                pass

    def mark_entrypoint_terminated(self, restart_callback: Optional[Callable] = None):
        """외부 프로세스 종료 감지 — 버튼을 '재시작' 으로 변경.

        restart_callback 주어지면 누를 때 재시작.
        """
        if self._entrypoint_btn is None:
            return
        self._entrypoint_status = "terminated"
        text = f"⟳ {self._entrypoint_label}  (종료됨 - 다시 시작)"
        try:
            if restart_callback:
                self._entrypoint_callback = restart_callback
                self._entrypoint_btn.configure(
                    text=text, command=self._on_entrypoint_click,
                    bg=Theme.BG_INPUT, fg=Theme.FG,
                    activebackground=Theme.BG_HOVER,
                    activeforeground=Theme.FG_BRIGHT,
                    state="normal", cursor="hand2",
                )
            else:
                self._entrypoint_btn.configure(
                    text=f"✗ {self._entrypoint_label}  (종료됨)",
                    bg=Theme.BG_INPUT, fg=Theme.FG_DIM,
                    state="disabled", cursor="arrow",
                )
        except tk.TclError:
            pass

    def _on_entrypoint_click(self):
        if self._entrypoint_callback:
            try:
                self._entrypoint_callback()
            except Exception:
                pass

    def append(self, level: str, msg: str):
        try:
            self._text.configure(state="normal")
            prefix = {
                "info": "[INFO] ", "ok": "[ OK ] ",
                "warn": "[WARN] ", "error": "[FAIL] ",
                "section": "── ",
            }.get(level, "")
            self._text.insert("end", prefix + msg + "\n", level)
            self._text.see("end")
            self._text.configure(state="disabled")
            if self._spinner_active and level in ("info", "section"):
                if len(msg) <= 60:
                    self._spinner.set_text(msg)
        except tk.TclError:
            pass

    def clear(self):
        try:
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.configure(state="disabled")
        except tk.TclError:
            pass

    def mark_done(self):
        """액션 완료 — 스피너를 체크마크로, 확인 버튼 활성화, 취소 버튼 숨김."""
        if not self._spinner_active:
            return
        self._spinner_active = False
        try:
            self._spinner.stop(final_text="완료", final_color=Theme.OK)
            self._done_btn.configure(
                text="확인", state="normal",
                bg=Theme.ACCENT, fg=Theme.FG_BRIGHT,
            )
            # 취소 버튼은 끝났으니 숨김
            self.hide_cancel()
        except tk.TclError:
            pass

    def _done(self):
        if self._on_done:
            self._on_done()

    def pack(self, **kw):
        self.frame.pack(**kw)

    def destroy(self):
        try:
            self._spinner.destroy()
        except Exception:
            pass
        try:
            self.frame.destroy()
        except tk.TclError:
            pass
