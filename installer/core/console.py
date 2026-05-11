"""installer.core.console — 콘솔 색상 / 포맷."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict


def init_console() -> bool:
    """Windows 콘솔에 VT 시퀀스 + UTF-8 활성화.

    pythonw.exe (콘솔 없는 환경) 에서 부작용이 없게 만들어야 함.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if os.name != "nt":
        return True

    # pythonw.exe 감지
    if sys.stdout is None or sys.stderr is None:
        return False

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VT = 0x0004
        h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        if not h or h == 0xFFFFFFFF or h == ctypes.c_void_p(-1).value:
            return False
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h, mode.value | ENABLE_VT | 0x0001)
            kernel32.SetConsoleOutputCP(65001)
            return True
    except Exception:
        pass

    # os.system("") 호출 안 함 — pythonw.exe 에서 cmd 창이 뜨는 원인.
    return False


_ANSI_OK = init_console()


class C:
    if _ANSI_OK:
        G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
        B = "\033[94m"; M = "\033[95m"
        BD = "\033[1m"; DIM = "\033[2m"
        E = "\033[0m"
    else:
        G = Y = R = B = M = BD = DIM = E = ""


# ── 출력 ──
def section(title: str):
    print()
    print(C.BD + "=" * 60 + C.E)
    print(C.BD + "  " + title + C.E)
    print(C.BD + "=" * 60 + C.E)


def info(m: str):
    print(f"{C.B}[INFO]{C.E} {m}")


def ok(m: str):
    print(f"{C.G}[ OK ]{C.E} {m}")


def warn(m: str):
    print(f"{C.Y}[WARN]{C.E} {m}")


def err(m: str):
    print(f"{C.R}[FAIL]{C.E} {m}")


def finalize_summary(paths: Dict[str, Path], here: Path):
    """설치 마무리 요약."""
    try:
        from ..i18n import t
        section(t("install.complete"))
        print()
        print(f"  {C.BD}{t('install.location', path=paths['env'])}{C.E}")
        print()
        print(f"  {C.BD}{t('install.next_step')}{C.E}")
        print()
    except Exception:
        # i18n 없는 환경에서도 동작
        section("Installation complete")
        print()
        print(f"  Install location: {paths['env']}")
        print()
        print("  Next step: run RUN.bat")
        print()
