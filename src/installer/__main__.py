#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""설치/복구 전용 진입점 — `RUN.bat --install` 또는 `python -m installer`."""
from __future__ import annotations

import argparse
import sys
from project_paths import (ENV_DIR, MODEL_STORAGE_DIR, PROJECT_ROOT,
                           RUNTIME_ROOT)
from installer import utils, resources, lang_setup
from installer.steps import ollama
from installer.steps import python_tools
from installer.steps import sandbox
from installer.steps import searxng
from installer.steps import tor
from installer.steps import warp
from installer.i18n import t

HERE = PROJECT_ROOT
ENV = ENV_DIR
ROOT = RUNTIME_ROOT


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Local AI Agent install / repair (Windows)")
    p.add_argument("--install", action="store_true",
                   help="설치/복구 실행 (생략해도 동일)")
    p.add_argument("--skip-model",   action="store_true")
    p.add_argument("--skip-sandbox", action="store_true")
    p.add_argument("--skip-build",   action="store_true")
    p.add_argument("--skip-search",  action="store_true")
    p.add_argument("--lang",         default=None,
                   help="ko or en (default: ask user / use saved)")
    return p.parse_args(argv)


# ── 디스크 예산 ────────────────────────────────────────────────────
# Base installation no longer downloads models. Model choice/download belongs
# to the integrated Setup > Models page, so the installer only reserves space
# for runtimes and images here.
_RUNTIME_GB = 5.0


def _base_disk_budget() -> int:
    return int(_RUNTIME_GB) + 1


def _run_install(args) -> int:
    lang_setup.initialize_language(HERE, override=args.lang)

    utils.section(t("install.title"))
    utils.info(t("install.location", path=ROOT))
    utils.info(t("install.python_ver", ver=sys.version.split()[0]))

    utils.preflight_windows()
    utils.preflight_python()
    utils.preflight_disk(MODEL_STORAGE_DIR.parent, need_gb=_base_disk_budget())

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

    ollama.prepare_install(ENV, MODEL_STORAGE_DIR)

    paths = utils.create_environment(ENV)
    components = []
    failed_components = []
    skipped_components = []
    utils.write_install_manifest(paths, HERE, "installing", components)

    ollama.install(paths)
    ollama.start_service(paths)
    components.append("ollama")

    # Model selection/download is intentionally not part of the console
    # installer anymore. The desktop Models page is the single source of truth:
    # selection, disk plan, install/remove and progress all stay in one window.
    skipped_components.append("models")
    if args.skip_model:
        utils.info("모델 다운로드 생략 (--skip-model)")
    else:
        utils.info("모델은 설치 완료 후 RUN.bat --manage > Models에서 선택하고 받습니다.")

    if python_tools.install_anythingllm(paths, profile):
        components.append("anythingllm")
    else:
        failed_components.append("anythingllm")
        utils.warn("AnythingLLM 설치가 완료되지 않았습니다. RUN.bat --install에서 다시 시도할 수 있습니다.")

    if python_tools.install_open_interpreter(paths, profile):
        components.append("open_interpreter")
    else:
        failed_components.append("open_interpreter")
        utils.warn("Open Interpreter 설치가 완료되지 않았습니다. RUN.bat --install에서 다시 시도할 수 있습니다.")

    if not args.skip_sandbox:
        try:
            sandbox.install(paths, profile=profile, build_image=not args.skip_build)
            components.append("sandbox")
        except sandbox.DockerNotAvailable as e:
            skipped_components.append("sandbox")
            utils.warn(t("install.sandbox_skip", reason=str(e)))
            utils.warn(t("install.sandbox_skip_later"))
    else:
        skipped_components.append("sandbox")
        utils.warn(t("install.sandbox_skip", reason="--skip-sandbox"))

    if not args.skip_search:
        try:
            sandbox._check_docker()
            if searxng.install(paths):
                components.append("searxng")
            else:
                failed_components.append("searxng")
                utils.warn("SearXNG 이미지를 준비하지 못했습니다. RUN.bat --install 로 다시 시도할 수 있습니다.")
        except sandbox.DockerNotAvailable as e:
            skipped_components.append("searxng")
            utils.warn(t("install.searxng_skip", reason=str(e)))
    else:
        skipped_components.append("searxng")
        utils.warn(t("install.searxng_skip_optional"))

    # Tor is optional but user-selectable. Prepare it explicitly rather than
    # hiding its pull inside the SearXNG installer.
    try:
        if tor.install(paths):
            components.append("tor")
        elif not args.skip_search:
            # SearXNG settings route all outbound search through llm_tor:9050,
            # so Tor is required when search was requested.
            failed_components.append("tor")
            utils.warn("Tor 이미지를 준비하지 못해 SearXNG 검색 경로가 완전하지 않습니다.")
        else:
            skipped_components.append("tor")
            utils.warn("Tor 이미지는 준비되지 않았습니다. 다른 네트워크 모드는 계속 사용할 수 있습니다.")
    except Exception as exc:
        target = failed_components if not args.skip_search else skipped_components
        target.append("tor")
        utils.warn("Tor 이미지 준비 중 오류: " + repr(exc))

    # WARP is the default network mode and its HTTP bridge reuses either the
    # sandbox image or the SearXNG image. Run this after both image-producing
    # steps so 'warp' means the complete path can actually start.
    try:
        if warp.install(paths):
            components.append("warp")
        else:
            failed_components.append("warp")
            utils.warn("기본 WARP 네트워크 경로를 준비하지 못했습니다. Direct/Block은 사용할 수 있지만 WARP는 복구가 필요합니다.")
    except Exception as exc:
        failed_components.append("warp")
        utils.warn("WARP 설치 중 오류: " + repr(exc))

    status = "partial" if failed_components else "installed"
    utils.write_install_manifest(
        paths, HERE, status, components,
        failed_components=failed_components,
        skipped_components=skipped_components,
    )
    if failed_components:
        utils.warn("일부 필수 구성요소가 준비되지 않았습니다: " + ", ".join(failed_components))
        utils.warn("RUN.bat --manage 에서 상태를 확인하거나 RUN.bat --install 로 복구하세요.")
    utils.finalize_summary(paths, HERE)

    try:
        input("\n" + t("common.exit_prompt"))
    except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
        pass
    return 0


def main(argv=None) -> int:
    # Management belongs to the shared Setup desktop app. This module has one
    # responsibility: install or repair the managed environment.
    return _run_install(_parse_args(argv))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{t('install.user_interrupt')}")
        sys.exit(130)
