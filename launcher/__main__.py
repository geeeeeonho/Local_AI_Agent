#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실행 진입점 — `python -m launcher` 로 실행.

RUN.bat 가 호출함.
"""
from __future__ import annotations

import sys
from pathlib import Path

from launcher import menu, ui
from launcher.i18n import t
from installer.lang_setup import initialize_language

# 프로젝트 루트 = launcher/__main__.py 의 부모의 부모
HERE = Path(__file__).resolve().parent.parent
ENV  = HERE / "llm_environment"


def main():
    # 언어 초기화 (저장된 값이 있으면 자동 적용)
    initialize_language(HERE)

    if not ENV.exists():
        ui.err(t("menu.no_install", path=ENV))
        ui.warn(t("menu.run_install_first"))
        try:
            input(t("common.exit_prompt"))
        except (EOFError, KeyboardInterrupt):
            pass
        sys.exit(1)

    try:
        menu.main_loop(ENV)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
