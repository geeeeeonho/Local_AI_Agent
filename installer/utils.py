"""utils — 출력 / 다운로드 / 사전 검사 / 환경 폴더 생성"""
from __future__ import annotations

import os
import platform
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Dict

from .i18n import t


# ──────────────────────────────────────────────────────────────
# 콘솔 초기화: UTF-8 + ANSI
# ──────────────────────────────────────────────────────────────
def _init_console():
    """Windows 콘솔에 UTF-8 출력 + ANSI 이스케이프 활성화.

    1) Python 표준 입출력 스트림을 UTF-8 로 강제
       → 한글 인쇄 시 cp949 ↔ utf-8 인코딩 충돌 방지
    2) ANSI 색상 코드 활성화 시도
       → 실패하면 색상 코드를 빈 문자열로 자동 무력화 (텍스트 깨짐 방지)
    """
    # 표준 입출력 UTF-8 강제
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if os.name != "nt":
        return True  # 유닉스는 보통 ANSI OK

    # Windows 10+ : SetConsoleMode 로 VT 시퀀스 활성화
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
            # UTF-8 코드 페이지
            kernel32.SetConsoleOutputCP(65001)
            return True
    except Exception:
        pass

    # 실패 시: os.system("") 로 한 번 더 시도 (구버전 Windows)
    try:
        os.system("")
        return True
    except Exception:
        return False


_ANSI_OK = _init_console()


# ──────────────────────────────────────────────────────────────
# 색상 클래스 — ANSI 미지원이면 자동으로 빈 문자열
# ──────────────────────────────────────────────────────────────
class _Colors:
    if _ANSI_OK:
        G   = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
        B   = "\033[94m"; BD = "\033[1m"; DIM = "\033[2m"; E = "\033[0m"
    else:
        G = Y = R = B = BD = DIM = E = ""


C = _Colors


def info(m):    print(f"{C.B}[INFO]{C.E} {m}")
def ok(m):      print(f"{C.G}[ OK ]{C.E} {m}")
def warn(m):    print(f"{C.Y}[WARN]{C.E} {m}")
def err(m):     print(f"{C.R}[FAIL]{C.E} {m}")
def section(m): print(f"\n{C.BD}{C.B}== {m} =={C.E}\n")


# ────────── 사전 검사 ──────────
def preflight_windows():
    if platform.system() != "Windows":
        err(t("install.preflight_windows_fail", os=platform.system()))
        sys.exit(1)
    ok(t("install.preflight_windows_ok"))


def preflight_python(min_version=(3, 11)):
    if sys.version_info < min_version:
        err(t("install.preflight_python_fail",
              min_ver=f"{min_version[0]}.{min_version[1]}",
              ver=sys.version.split()[0]))
        sys.exit(1)
    ok(t("install.preflight_python_ok", ver=sys.version.split()[0]))


def preflight_disk(parent: Path, need_gb: int):
    try:
        target = parent if parent.exists() else parent.parent
        free = shutil.disk_usage(target).free / (1024 ** 3)
        if free < need_gb:
            err(t("install.preflight_disk_fail", gb=free, need=need_gb))
            sys.exit(1)
        ok(t("install.preflight_disk_ok", gb=free))
    except Exception:
        warn(t("install.preflight_disk_unknown"))


# ────────── 환경 폴더 ──────────
def create_environment(env: Path) -> Dict[str, Path]:
    """llm_environment/ 트리 생성 후 경로 dict 반환."""
    section(t("install.create_dirs"))
    paths = {
        "env":       env,
        "ollama":    env / "ollama_runtime",
        "models":    env / "llm_models",
        "chat":      env / "chat_ui",
        "agent":     env / "agent",
        "sandbox":   env / "agent" / "sandbox",
        "workspace": env / "agent" / "workspace",
        "searxng":   env / "searxng",
        "scripts":   env / "scripts",
        "logs":      env / "logs",
    }
    for name, p in paths.items():
        p.mkdir(parents=True, exist_ok=True)
        ok(f"  {name:<10} → {p}")
    return paths


# ────────── 다운로드 ──────────
def download_with_progress(url: str, dest: Path, label: str = ""):
    """진행률 표시 다운로드 (stdlib only)."""
    info(f"다운로드: {label or dest.name}")
    info(f"  → {dest}")

    def report(blocknum, blocksize, totalsize):
        if totalsize <= 0:
            return
        d = blocknum * blocksize
        pct = min(100, d * 100 / totalsize)
        mb_n, mb_t = d / (1024 ** 2), totalsize / (1024 ** 2)
        filled = int(30 * pct / 100)
        bar = "█" * filled + "░" * (30 - filled)
        sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%  {mb_n:7.1f}/{mb_t:7.1f} MB")
        sys.stdout.flush()

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest, reporthook=report)
        sys.stdout.write("\n")
        ok(f"완료 ({dest.stat().st_size / (1024 ** 2):.1f} MB)")
    except Exception as e:
        sys.stdout.write("\n")
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"다운로드 실패: {e}")


# ────────── 마무리 요약 ──────────
def finalize_summary(paths: Dict[str, Path], here: Path):
    section(t("install.complete"))
    print()
    print(f"  {C.BD}{t('install.location', path=paths['env'])}{C.E}")
    print()
    print(f"  {C.BD}{t('install.next_step')}{C.E}")
    print()
