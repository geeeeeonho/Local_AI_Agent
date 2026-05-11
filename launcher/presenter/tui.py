"""presenter.tui — 터미널 UI 구현.

기존 launcher/ui.py + launcher/checkbox.py 통합 + Presenter 인터페이스 구현.
ANSI 색상 / UTF-8 자동 처리 / Windows 콘솔 호환.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Set

from .base import (
    Presenter, MenuItem, Option,
    RISK_SAFE, RISK_MEDIUM, RISK_HIGH,
)


# ─────────────────────────────────────────────
#  콘솔 초기화 (Windows VT 시퀀스 + UTF-8)
# ─────────────────────────────────────────────

def _init_console() -> bool:
    """Windows 콘솔에 VT 시퀀스 + UTF-8 활성화.

    중요: pythonw.exe (콘솔 없는 GUI 환경) 에서 호출되면 콘솔창을
    띄우는 부작용이 없도록 만들어야 함. 이전 버전에서는 폴백으로
    os.system("") 을 호출했는데, 이게 pythonw.exe 에서 새 cmd 창을
    띄웠다 닫는 원인이었음 — 제거함.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if os.name != "nt":
        return True

    # pythonw.exe 환경 감지 — 표준 핸들이 없거나 sys.stdout 이 None
    if sys.stdout is None or sys.stderr is None:
        return False

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VT = 0x0004
        ENABLE_PROCESSED_OUTPUT = 0x0001
        h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        # pythonw.exe 등 콘솔 없는 환경: GetStdHandle 가 INVALID_HANDLE_VALUE 반환
        if not h or h == 0xFFFFFFFF or h == ctypes.c_void_p(-1).value:
            return False
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                h, mode.value | ENABLE_VT | ENABLE_PROCESSED_OUTPUT
            )
            kernel32.SetConsoleOutputCP(65001)
            return True
    except Exception:
        pass

    # NOTE: 이전에 여기서 os.system("") 를 호출했으나, 이 호출이
    # pythonw.exe 환경에서 새 cmd 창을 깜빡 띄우는 부작용이 있어 제거.
    # Windows 10 1607+ 에선 ctypes 경로가 정상 동작하므로 영향 없음.
    return False


_ANSI_OK = _init_console()


class _C:
    if _ANSI_OK:
        G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
        B = "\033[94m"; M = "\033[95m"
        BD = "\033[1m"; DIM = "\033[2m"; INV = "\033[7m"
        E = "\033[0m"
    else:
        G = Y = R = B = M = BD = DIM = INV = E = ""


# ─────────────────────────────────────────────
#  위험옵션 키워드 (정책)
# ─────────────────────────────────────────────
_RISK_KEYWORD = {
    RISK_HIGH: "I-UNDERSTAND",
    RISK_MEDIUM: "ENABLE",
}


# ═════════════════════════════════════════════
#  TerminalPresenter
# ═════════════════════════════════════════════

class TerminalPresenter(Presenter):
    """터미널 기반 Presenter."""

    def __init__(self):
        # 짧은 시간 연속 EOF 발생 카운터 (stdin 없는 환경 감지용)
        self._eof_count = 0

    # ── 헬퍼 ──
    def _clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    def _hr(self, char: str = "-", color: str = ""):
        print(color + (char * 60) + (_C.E if color else ""))

    # ── 정보 출력 ──
    def info(self, msg: str) -> None:
        print(f"{_C.B}[INFO]{_C.E} {msg}")

    def ok(self, msg: str) -> None:
        print(f"{_C.G}[ OK ]{_C.E} {msg}")

    def warn(self, msg: str) -> None:
        print(f"{_C.Y}[WARN]{_C.E} {msg}")

    def error(self, msg: str) -> None:
        print(f"{_C.R}[FAIL]{_C.E} {msg}")

    def section(self, title: str, subtitle: str = "") -> None:
        self._clear()
        print(_C.BD + "=" * 60 + _C.E)
        print(_C.BD + "  " + title + _C.E)
        if subtitle:
            print("  " + _C.DIM + subtitle + _C.E)
        print(_C.BD + "=" * 60 + _C.E)
        print()

    def pause(self, msg: str = "엔터를 누르면 계속...") -> None:
        print()
        try:
            input(_C.DIM + msg + _C.E)
        except (KeyboardInterrupt, EOFError):
            self._eof_count += 1
            self._maybe_abort_on_eof_storm()

    # ── 입력 ──
    def prompt_text(self, prompt: str = "> ", default: str = "") -> str:
        """자유 텍스트 입력. EOF/KeyboardInterrupt 시 빈 문자열.

        EOF 가 짧은 시간에 반복되면 stdin 이 없는 환경 (pythonw 등) 으로 보고
        프로세스를 종료. 무한 루프 방지.
        """
        try:
            response = input(prompt).strip()
            self._eof_count = 0  # 정상 입력 → 카운터 리셋
            return response if response else default
        except (KeyboardInterrupt, EOFError):
            self._eof_count += 1
            self._maybe_abort_on_eof_storm()
            return ""

    def _maybe_abort_on_eof_storm(self):
        """짧은 시간 EOF 가 5회 이상이면 stdin 없는 환경으로 판단, 종료.

        pythonw.exe 로 실행하면 stdin 이 없어 input() 이 즉시 EOFError 를
        반환. 이 경우 메뉴 루프가 무한 재출력되므로 강제 종료가 필요.
        """
        if self._eof_count >= 5:
            import sys
            print(
                "\n[FATAL] stdin 입력 불가 (pythonw / 헤드리스 환경 추정). "
                "터미널 세션에서 다시 실행하세요.",
                file=sys.stderr,
            )
            sys.exit(2)

    def prompt_choice(self, prompt: str, choices: List[str]) -> Optional[str]:
        choice_str = "/".join(choices)
        full = f"{prompt} [{choice_str}]: "
        try:
            r = input(full).strip().lower()
            return r if r in [c.lower() for c in choices] else None
        except (KeyboardInterrupt, EOFError):
            return None

    def prompt_path(
        self, title: str, default: Path,
        last_used: Optional[Path] = None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        suggested = default
        if last_used and last_used.exists():
            suggested = last_used

        self.section(title)
        if last_used and last_used.exists() and suggested != default:
            print(f"  {_C.G}마지막 사용: {suggested}{_C.E}")
            print(f"  {_C.DIM}기본값: {default}{_C.E}")
        else:
            print(f"  {_C.B}기본값: {suggested}{_C.E}")
        print()
        print(f"  {_C.DIM}엔터: 위 경로 사용{_C.E}")
        print(f"  {_C.DIM}경로 입력: 다른 폴더 사용{_C.E}")
        print(f"  {_C.DIM}b: 뒤로{_C.E}")
        print()

        r = self.prompt_text().strip()
        if r.lower() in ("b", "back", "q", ""):
            if r == "":
                suggested.mkdir(parents=True, exist_ok=True)
                return suggested
            return None

        custom = Path(r).expanduser().resolve()
        if must_exist and not custom.exists():
            self.error(f"폴더가 존재하지 않습니다: {custom}")
            self.pause()
            return self.prompt_path(title, default, last_used, must_exist)
        if not must_exist:
            custom.mkdir(parents=True, exist_ok=True)
        return custom

    # ── 메뉴 ──
    def show_menu(
        self, title: str, subtitle: str,
        items: List[MenuItem],
        last_choice: Optional[str] = None,
    ) -> str:
        while True:
            self.section(title, subtitle)

            for it in items:
                if it.separator_above:
                    self._hr(color=_C.DIM)
                    print()

                badge = ""
                if it.badge:
                    color = self._badge_color(it.badge_kind)
                    badge = f" {color}*{it.badge}*{_C.E}"

                key_disp = f"[{it.key.upper()}]"
                hint = ""
                if last_choice and it.key == last_choice:
                    hint = f"  {_C.DIM}(마지막 선택){_C.E}"

                print(f"  {_C.BD}{key_disp}{_C.E} {it.title}{badge}{hint}")
                if it.description:
                    print(f"      {_C.DIM}{it.description}{_C.E}")
                if not it.separator_above:
                    pass
                print() if it.description else None
            print()
            choice = self.prompt_text("> ").lower()

            for it in items:
                if choice == it.key.lower():
                    return it.key
            # 알 수 없는 입력 → 다시
            if choice in ("q", "quit", "exit"):
                return "q"

    @staticmethod
    def _badge_color(kind: str) -> str:
        return {
            "good": _C.G,
            "warn": _C.Y,
            "danger": _C.R,
        }.get(kind, _C.B)

    # ── 체크박스 ──
    def show_checkbox(
        self, title: str, subtitle: str,
        options: List[Option],
        extra_lines: Optional[List[str]] = None,
        override_defaults: Optional[Set[str]] = None,
    ) -> Optional[Set[str]]:
        # 초기 상태
        if override_defaults is not None:
            state = {opt.id: (opt.id in override_defaults) for opt in options}
            for opt in options:
                if opt.locked:
                    state[opt.id] = opt.default
        else:
            state = {opt.id: opt.default for opt in options}

        last_msg: Optional[str] = None

        while True:
            self.section(title, subtitle)

            if extra_lines:
                for line in extra_lines:
                    print("  " + line)
                print()

            for i, opt in enumerate(options, 1):
                mark = self._check_marker(state[opt.id], opt.locked)
                risk = self._risk_marker(opt.risk)
                num = f"{_C.DIM}{i:2d}.{_C.E}"
                print(f"  {num}  {mark} {risk} {opt.label}")
                if opt.description:
                    first = opt.description.split("\n")[0]
                    print(f"           {_C.DIM}{first}{_C.E}")

            print()
            self._hr(color=_C.DIM)
            print(f"  {_C.DIM}번호 입력: 토글 (예: '3' 또는 '3 5'){_C.E}")
            print(f"  {_C.DIM}go: 실행  |  b: 뒤로  |  q: 종료{_C.E}")

            if last_msg:
                print()
                print(f"  {last_msg}")
                last_msg = None

            print()
            cmd = self.prompt_text("> ").lower()

            if cmd in ("q", "quit"):
                return None
            if cmd in ("b", "back"):
                return None
            if cmd in ("go", "g", "r", "run"):
                return {oid for oid, on in state.items() if on}

            try:
                indices = [int(t) - 1 for t in cmd.split()]
            except ValueError:
                last_msg = _C.Y + "잘못된 입력 — 번호 또는 명령어" + _C.E
                continue

            for idx in indices:
                if not (0 <= idx < len(options)):
                    last_msg = _C.Y + f"범위 밖: {idx + 1}" + _C.E
                    continue
                opt = options[idx]
                if opt.locked:
                    last_msg = _C.Y + f"'{opt.label}' 잠김" + _C.E
                    continue

                if not state[opt.id]:
                    # 켜는 중
                    if opt.risk >= RISK_MEDIUM:
                        if not self.confirm_dangerous(
                            opt.label, opt.description, opt.risk,
                        ):
                            last_msg = _C.DIM + f"'{opt.label}' 취소" + _C.E
                            continue
                    # 상호 배제
                    for ex_id in opt.excludes:
                        if state.get(ex_id):
                            state[ex_id] = False
                    state[opt.id] = True
                else:
                    state[opt.id] = False

    @staticmethod
    def _risk_marker(risk: int) -> str:
        if risk == RISK_HIGH:
            return _C.R + "⚠⚠" + _C.E
        if risk == RISK_MEDIUM:
            return _C.Y + "⚠ " + _C.E
        return "  "

    @staticmethod
    def _check_marker(checked: bool, locked: bool) -> str:
        if locked and checked:
            return _C.DIM + "[✓]" + _C.E
        if locked:
            return _C.DIM + "[ ]" + _C.E
        return _C.G + "[✓]" + _C.E if checked else "[ ]"

    # ── 위험 옵션 확인 ──
    def confirm_dangerous(
        self, label: str, description: str, risk: int,
    ) -> bool:
        keyword = _RISK_KEYWORD.get(risk, "ENABLE")
        head_color = _C.R if risk == RISK_HIGH else _C.Y
        head_text = (
            "⚠⚠ 매우 위험한 옵션 활성화 ⚠⚠" if risk == RISK_HIGH
            else "⚠ 주의 필요한 옵션 활성화 ⚠"
        )

        self._clear()
        print(head_color + _C.BD + head_text + _C.E)
        self._hr()
        print()
        print(f"  옵션: {_C.BD}{label}{_C.E}")
        print()
        if description:
            print(f"  {_C.DIM}설명:{_C.E}")
            for line in description.split("\n"):
                print(f"    {line}")
            print()
        print(f"  활성화하려면 정확히 {_C.BD}'{keyword}'{_C.E}를 입력하세요.")
        print(f"  {_C.DIM}그 외 입력은 취소.{_C.E}")
        print()
        return self.prompt_text("> ") == keyword


# ─────────────────────────────────────────────
#  레거시 호환 (ui.py shim 용)
# ─────────────────────────────────────────────
C = _C  # 외부에서 ui.C.G 등을 참조하던 코드 호환


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def hr(char: str = "-", color: str = ""):
    print(color + (char * 60) + (_C.E if color else ""))


def header(title: str, subtitle: str = ""):
    clear()
    print(_C.BD + "=" * 60 + _C.E)
    print(_C.BD + "  " + title + _C.E)
    if subtitle:
        print("  " + _C.DIM + subtitle + _C.E)
    print(_C.BD + "=" * 60 + _C.E)
    print()


def info(m): print(f"{_C.B}[INFO]{_C.E} {m}")
def ok(m): print(f"{_C.G}[ OK ]{_C.E} {m}")
def warn(m): print(f"{_C.Y}[WARN]{_C.E} {m}")
def err(m): print(f"{_C.R}[FAIL]{_C.E} {m}")


def prompt(text: str = "> ") -> str:
    try:
        return input(text).strip()
    except (KeyboardInterrupt, EOFError):
        return "q"


def pause(text: str = "엔터를 누르면 계속..."):
    print()
    try:
        input(_C.DIM + text + _C.E)
    except (KeyboardInterrupt, EOFError):
        pass
