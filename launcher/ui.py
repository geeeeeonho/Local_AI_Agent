"""ui — 색상 / 화면 클리어 / 헤더 / 프롬프트.

콘솔 호환성:
  - UTF-8 표준 입출력 강제 (한글 깨짐 방지)
  - ANSI 색상은 지원되는 환경에서만 활성화
  - 미지원 환경에서는 색상 코드가 빈 문자열로 자동 대체
"""
from __future__ import annotations

import os
import sys


def _init_console():
    """Windows 콘솔에 UTF-8 + ANSI 이스케이프 활성화."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if os.name != "nt":
        return True

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VT = 0x0004
        ENABLE_PROCESSED_OUTPUT = 0x0001
        h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                h, mode.value | ENABLE_VT | ENABLE_PROCESSED_OUTPUT
            )
            kernel32.SetConsoleOutputCP(65001)
            return True
    except Exception:
        pass

    try:
        os.system("")
        return True
    except Exception:
        return False


_ANSI_OK = _init_console()


class _Colors:
    if _ANSI_OK:
        G   = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
        B   = "\033[94m"; M = "\033[95m"
        BD  = "\033[1m"; DIM = "\033[2m"; INV = "\033[7m"
        E   = "\033[0m"
    else:
        G = Y = R = B = M = BD = DIM = INV = E = ""


C = _Colors


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def hr(char: str = "-", color: str = ""):
    print(color + (char * 60) + (C.E if color else ""))


def header(title: str, subtitle: str = ""):
    clear()
    print(C.BD + "=" * 60 + C.E)
    print(C.BD + "  " + title + C.E)
    if subtitle:
        print("  " + C.DIM + subtitle + C.E)
    print(C.BD + "=" * 60 + C.E)
    print()


def info(m):  print(f"{C.B}[INFO]{C.E} {m}")
def ok(m):    print(f"{C.G}[ OK ]{C.E} {m}")
def warn(m):  print(f"{C.Y}[WARN]{C.E} {m}")
def err(m):   print(f"{C.R}[FAIL]{C.E} {m}")


def prompt(text: str = "> ") -> str:
    try:
        return input(text).strip()
    except (KeyboardInterrupt, EOFError):
        return "q"


def pause(text: str = "엔터를 누르면 계속..."):
    print()
    try:
        input(C.DIM + text + C.E)
    except (KeyboardInterrupt, EOFError):
        pass
