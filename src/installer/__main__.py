#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
설치 진입점 — `python -m installer` 로 실행.

INSTALL.bat 가 호출함.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer import utils, resources, lang_setup
from installer.steps import ollama
from installer.steps import model
from installer.steps import python_tools
from installer.steps import sandbox
from installer.steps import searxng
from installer.i18n import t

# 프로젝트 루트 = installer/__main__.py 의 부모의 부모
HERE = Path(__file__).resolve().parent.parent
ENV  = HERE / "llm_environment"


def main():
    p = argparse.ArgumentParser(description="LLM Integrated Environment Installer (Windows)")
    p.add_argument("--skip-model",   action="store_true")
    p.add_argument("--skip-sandbox", action="store_true")
    p.add_argument("--skip-build",   action="store_true")
    p.add_argument("--skip-search",  action="store_true")
    p.add_argument("--lang",         default=None,
                   help="ko or en (default: ask user / use saved)")
    args = p.parse_args()

    # ─── 언어 설정 (저장된 값 → CLI 인자 → 사용자 선택 순) ───
    lang_setup.initialize_language(HERE, override=args.lang)

    utils.section(t("install.title"))
    utils.info(t("install.location", path=ENV))
    utils.info(t("install.python_ver", ver=sys.version.split()[0]))

    # ─── 사전 검사 ───
    utils.preflight_windows()
    utils.preflight_python()
    utils.preflight_disk(ENV.parent, need_gb=20 if not args.skip_model else 5)

    # ─── 시스템 자원 감지 + 안전 프로필 ───
    utils.section(t("install.resources_section"))
    spec = resources.detect(ENV)
    utils.info(f"  {spec}")
    profile = resources.compute_safety_profile(spec)
    utils.info(t("install.safety_profile", profile=profile))

    if profile.warnings:
        print()
        for w in profile.warnings:
            utils.warn(w)
        print()

    if not profile.can_run_full:
        utils.err(t("install.cant_run_full"))
        utils.warn(t("install.proceeding_in_5"))
        import time
        time.sleep(5)

    # ─── 환경 폴더 ───
    paths = utils.create_environment(ENV)

    # ─── 핵심 ───
    ollama.install_portable(paths)
    ollama.start_service(paths)

    if not args.skip_model:
        model.download(paths)
    else:
        utils.warn("Model download skipped (--skip-model)")

    python_tools.install_open_webui(paths, profile)
    python_tools.install_open_interpreter(paths, profile)

    # ─── 샌드박스 ───
    if not args.skip_sandbox:
        try:
            sandbox.install(paths, profile=profile, build_image=not args.skip_build)
        except sandbox.DockerNotAvailable as e:
            utils.warn(t("install.sandbox_skip", reason=str(e)))
            utils.warn(t("install.sandbox_skip_later"))
    else:
        utils.warn(t("install.sandbox_skip", reason="--skip-sandbox"))

    # ─── SearXNG ───
    if not args.skip_search:
        try:
            sandbox._check_docker()
            searxng.install(paths)
        except sandbox.DockerNotAvailable as e:
            utils.warn(t("install.searxng_skip", reason=str(e)))
    else:
        utils.warn(t("install.searxng_skip_optional"))

    # ─── 마무리 ───
    utils.finalize_summary(paths, HERE)

    try:
        input("\n" + t("common.exit_prompt"))
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{t('install.user_interrupt')}")
        sys.exit(130)
