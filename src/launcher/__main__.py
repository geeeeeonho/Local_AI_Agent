#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""launcher 진입점.

기본 동작:
    python -m launcher          → GUI (Tkinter)
    python -m launcher --tui    → 터미널 UI (강제)
    python -m launcher --gui    → GUI (명시, 기본과 동일)
    python -m launcher --lang ko/en  → 언어 강제

GUI 가 사용 불가능한 환경 (tkinter 모듈 없음 / DISPLAY 없는 헤드리스 등)
에서는 자동으로 TUI 로 폴백합니다.

RUN.bat       → 인자 없이 호출 → 기본 GUI
RUN.bat --tui → 터미널 UI 강제
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_paths import (ENV_DIR, PROJECT_ROOT, RUNTIME_ROOT,
                           USER_DATA_DIR, LOGS_DIR)

HERE = PROJECT_ROOT
ENV = ENV_DIR


def parse_args():
    p = argparse.ArgumentParser(
        prog="launcher",
        description="LLM Local Setup Launcher",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--gui", action="store_true",
                   help="Tkinter GUI 모드 (기본)")
    g.add_argument("--tui", action="store_true",
                   help="터미널 UI 강제 (헤드리스 / 원격 환경)")
    p.add_argument("--lang", default=None,
                   help="언어 강제: ko / en")
    return p.parse_args()


def _resolve_mode(args) -> str:
    """CLI 인자 → UI 모드 결정."""
    from launcher import config as launcher_config

    if args.tui:
        return launcher_config.UI_MODE_TUI
    if args.gui:
        return launcher_config.UI_MODE_GUI
    return launcher_config.DEFAULT_UI_MODE


def _create_presenter_with_fallback(requested_mode: str):
    """요청된 모드 생성 시도, GUI 가 안 되면 자동 TUI 폴백."""
    from launcher.presenter import create_presenter
    from launcher import config as launcher_config

    try:
        return create_presenter(requested_mode), requested_mode
    except ImportError as e:
        if requested_mode == launcher_config.UI_MODE_GUI:
            print(f"[WARN] GUI 사용 불가: {e}", file=sys.stderr)
            print("[INFO] 터미널 UI 로 폴백합니다", file=sys.stderr)
            return (
                create_presenter(launcher_config.UI_MODE_TUI),
                launcher_config.UI_MODE_TUI,
            )
        raise
    except Exception as e:
        if requested_mode == launcher_config.UI_MODE_GUI:
            print(f"[WARN] GUI 초기화 실패: {e}", file=sys.stderr)
            print("[INFO] 터미널 UI 로 폴백합니다", file=sys.stderr)
            return (
                create_presenter(launcher_config.UI_MODE_TUI),
                launcher_config.UI_MODE_TUI,
            )
        raise


def _fatal_log_path() -> Path:
    """치명적 예외 트레이스백을 현재 Windows 계정 로그에 저장한다."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / "launcher_fatal.log"


def _write_fatal(exc: BaseException, ctx: str = ""):
    """예외를 fatal_log 에 기록 + stderr 에도 출력."""
    import datetime, traceback
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    tb = traceback.format_exc()
    msg = (
        f"\n{'='*60}\n"
        f"[{ts}] FATAL ({ctx})\n"
        f"{'='*60}\n"
        f"{tb}\n"
    )
    try:
        from core import vault
        with vault.open_log(_fatal_log_path(), "a") as f:
            f.write(msg)
    except Exception:
        pass
    print(msg, file=sys.stderr, flush=True)


def main():
    args = parse_args()

    try:
        from services.system.bootstrap import install_exit_hooks
        if not install_exit_hooks(RUNTIME_ROOT):
            print("[WARN] 종료 정리 hook 초기화 실패", file=sys.stderr)
    except Exception as exc:
        print("[WARN] 종료 정리 hook 초기화 실패: " + str(exc), file=sys.stderr)

    def _trace(stage):
        try:
            from launcher.core import lifelog
            lifelog.log("TRACE", "[main] " + stage)
        except Exception:
            try:
                print("[TRACE main] " + stage, file=sys.stderr)
            except Exception:
                pass

    _trace("진입 — 종료 hook 설치 직후")

    # >>> CACHE_CLEANUP_v1 - 종료 시 캐시 자동 정리 등록
    try:
        from launcher.core import lifelog as _ll5
        if hasattr(_ll5, "register_cache_cleanup"):
            _ll5.register_cache_cleanup(USER_DATA_DIR)
            _trace("캐시 정리 cleanup 등록 완료")
    except Exception as _cce:
        _trace("캐시 정리 cleanup 등록 실패: " + str(_cce))

    # ── 언어/설정 초기화 ──
    _trace("언어 초기화 직전")
    try:
        from installer.lang_setup import initialize_language
        initialize_language(HERE, override=args.lang)
        _trace("언어 초기화 완료")
    except Exception as _le:
        _trace("언어 초기화 예외: " + str(_le))

    # ── 설치 폴더 확인 ──
    _trace("설치 폴더 확인 직전 ENV=" + str(ENV))
    if not ENV.exists():
        print(f"[FAIL] 설치 폴더가 없습니다: {ENV}", file=sys.stderr)
        print("[INFO] RUN.bat --install 을 실행하세요", file=sys.stderr)
        # pythonw 환경에선 콘솔이 안 보이므로 fatal_log 에도 남김
        with open(_fatal_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n[FAIL] 설치 폴더 없음: {ENV}\n")
        sys.exit(1)

    # ── Presenter (자동 폴백) ──
    _trace("모드 결정 직전")
    mode = _resolve_mode(args)
    _trace("모드 결정 완료: " + str(mode))

    presenter = None
    _trace("Presenter 생성 직전")
    try:
        presenter, _actual_mode = _create_presenter_with_fallback(mode)
        _trace("Presenter 생성 완료: " + type(presenter).__name__)
    except Exception as e:
        _write_fatal(e, ctx="Presenter 생성")
        sys.exit(3)

    # ── 메뉴 루프 ──
    _trace("Application import 직전")
    try:
        from launcher.app import Application
        _trace("Application import 완료")
        _trace("Application(ENV, presenter) 인스턴스화 직전")
        _app = Application(ENV, presenter)
        _trace("Application 인스턴스화 완료")
        _trace("Application.run() 호출 직전")
        _app.run()
        _trace("Application.run() 반환됨")
    except KeyboardInterrupt:
        print()
    except Exception as e:
        _write_fatal(e, ctx="Application.run")

        # 이미 TUI 였다면 더 이상 폴백 X
        from launcher.presenter.tui import TerminalPresenter
        if isinstance(presenter, TerminalPresenter):
            sys.exit(4)

        # GUI 가 죽은 경우 → TUI 로 한 번 재시도
        try:
            from launcher.presenter import create_presenter
            from launcher import config as launcher_config
            tui_presenter = create_presenter(launcher_config.UI_MODE_TUI)
            tui_presenter.warn("GUI 가 비정상 종료됨 — 터미널 모드로 재시도")
            tui_presenter.warn(f"자세한 내용: {_fatal_log_path()}")
            from launcher.app import Application
            Application(ENV, tui_presenter).run()
        except Exception as e2:
            _write_fatal(e2, ctx="TUI 폴백")
            sys.exit(5)


if __name__ == "__main__":
    main()
