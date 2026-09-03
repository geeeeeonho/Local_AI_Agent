#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""설치/관리 통합 진입점 — `SETUP.bat` 또는 `python -m installer` 로 실행."""
from __future__ import annotations

import argparse
import sys

from project_paths import ENV_DIR, MODEL_STORAGE_DIR, PROJECT_ROOT
from installer import utils, resources, lang_setup
from installer.steps import ollama
from installer.steps import model
from installer.steps import python_tools
from installer.steps import sandbox
from installer.steps import searxng
from installer.i18n import t

HERE = PROJECT_ROOT
ENV = ENV_DIR


def _parse_args():
    p = argparse.ArgumentParser(description="LLM Integrated Environment Setup (Windows)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true",
                      help="설치/재설치 흐름을 강제로 실행")
    mode.add_argument("--manage", action="store_true",
                      help="설치된 환경 관리 화면을 강제로 실행")
    p.add_argument("--skip-model",   action="store_true")
    p.add_argument("--skip-sandbox", action="store_true")
    p.add_argument("--skip-build",   action="store_true")
    p.add_argument("--skip-search",  action="store_true")
    p.add_argument("--lang",         default=None,
                   help="ko or en (default: ask user / use saved)")
    return p.parse_args()


def _should_manage(args) -> bool:
    """기본(auto) 모드에서 관리 화면으로 갈지 결정한다.

    기존 내부 호출인 ``python -m installer --skip-*`` 는 설치 작업으로 유지한다.
    이렇게 해야 관리 GUI의 환경 업데이트가 다시 관리 GUI를 여는 재귀를 만들지 않는다.
    """
    if args.manage:
        return True
    if args.install:
        return False
    install_flags = (
        args.skip_model,
        args.skip_sandbox,
        args.skip_build,
        args.skip_search,
    )
    if any(install_flags):
        return False
    return ENV.exists()


def _run_manage(args) -> int:
    lang_setup.initialize_language(HERE, override=args.lang)
    from installer import manage_gui
    return int(manage_gui.main([]) or 0)


def _run_install(args) -> int:
    # ─── 언어 설정 (저장된 값 → CLI 인자 → 사용자 선택 순) ───
    lang_setup.initialize_language(HERE, override=args.lang)

    utils.section(t("install.title"))
    utils.info(t("install.location", path=ENV))
    utils.info(t("install.python_ver", ver=sys.version.split()[0]))

    # ─── 사전 검사 ───
    utils.preflight_windows()
    utils.preflight_python()
    # 대용량 모델은 프로젝트 위치가 아니라 C:\LLM_Models 에 저장된다.
    utils.preflight_disk(MODEL_STORAGE_DIR.parent, need_gb=20 if not args.skip_model else 5)

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

    # ─── 환경 폴더 + 설치 식별 정보 ───
    paths = utils.create_environment(ENV)
    components = []
    utils.write_install_manifest(paths, HERE, "installing", components)

    # ─── 핵심 ───
    ollama.install_portable(paths)
    ollama.start_service(paths)
    components.append("ollama")

    if not args.skip_model:
        model.download(paths)
        components.append("models")
    else:
        utils.warn("Model download skipped (--skip-model)")

    python_tools.install_open_webui(paths, profile)
    components.append("open_webui")
    python_tools.install_open_interpreter(paths, profile)
    components.append("open_interpreter")

    # ─── 샌드박스 ───
    if not args.skip_sandbox:
        try:
            sandbox.install(paths, profile=profile, build_image=not args.skip_build)
            components.append("sandbox")
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
            components.append("searxng")
        except sandbox.DockerNotAvailable as e:
            utils.warn(t("install.searxng_skip", reason=str(e)))
    else:
        utils.warn(t("install.searxng_skip_optional"))

    # ─── 마무리 ───
    utils.write_install_manifest(paths, HERE, "installed", components)
    utils.finalize_summary(paths, HERE)

    try:
        input("\n" + t("common.exit_prompt"))
    except (EOFError, KeyboardInterrupt):
        pass
    return 0


def main() -> int:
    args = _parse_args()
    if _should_manage(args):
        return _run_manage(args)
    return _run_install(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{t('install.user_interrupt')}")
        sys.exit(130)
