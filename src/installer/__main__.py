#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""설치/복구 전용 진입점 — `RUN.bat --install` 또는 `python -m installer`."""
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
_RUNTIME_GB = 5.0        # Ollama / Python 도구 / 샌드박스 이미지 등 모델 외 용량
_FALLBACK_FLOOR_GB = 20  # 카탈로그를 못 읽을 때의 보수적 하한


def _model_disk_budget(skip_model: bool):
    """(하드 최소 GB, 이 PC 의 권장 세트까지 담는 데 필요한 GB)."""
    if skip_model:
        return int(_RUNTIME_GB), 0.0
    try:
        from launcher.models import model_catalog as cat
    except Exception:
        return _FALLBACK_FLOOR_GB, 0.0
    try:
        floor = cat.download_gb(cat.plan_by_level().get("low") or ())
        plan = cat.download_gb(cat.recommended_for(cat.MEMORY_BUDGET_GB))
    except Exception:
        return _FALLBACK_FLOOR_GB, 0.0
    return int(_RUNTIME_GB + floor) + 1, _RUNTIME_GB + plan


def _warn_if_plan_does_not_fit(plan_gb: float) -> None:
    if not plan_gb:
        return
    import shutil
    target = MODEL_STORAGE_DIR if MODEL_STORAGE_DIR.exists() else MODEL_STORAGE_DIR.parent
    try:
        free = shutil.disk_usage(target).free / (1024 ** 3)
    except OSError:
        return
    if free < plan_gb:
        utils.warn(
            "권장 모델 세트는 약 %.0fGB 인데 %s 의 여유는 %.0fGB 입니다. "
            "모델 선택 창에서 일부를 빼거나, 다 받은 뒤 [모델 관리]에서 정리하세요."
            % (plan_gb, target, free)
        )


def _run_install(args) -> int:
    lang_setup.initialize_language(HERE, override=args.lang)

    utils.section(t("install.title"))
    utils.info(t("install.location", path=ENV))
    utils.info(t("install.python_ver", ver=sys.version.split()[0]))

    utils.preflight_windows()
    utils.preflight_python()
    _floor_gb, _plan_gb = _model_disk_budget(args.skip_model)
    utils.preflight_disk(MODEL_STORAGE_DIR.parent, need_gb=_floor_gb)
    _warn_if_plan_does_not_fit(_plan_gb)

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

    if not args.skip_model:
        prepared_models = model.download(paths)
        if prepared_models:
            components.append("models")
        else:
            failed_components.append("models")
            utils.warn("로컬 모델 준비가 완료되지 않았습니다. Setup의 모델 화면에서 다시 적용할 수 있습니다.")
    else:
        skipped_components.append("models")
        utils.warn("Model download skipped (--skip-model)")

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
            searxng.install(paths)
            components.append("searxng")
        except sandbox.DockerNotAvailable as e:
            skipped_components.append("searxng")
            utils.warn(t("install.searxng_skip", reason=str(e)))
    else:
        skipped_components.append("searxng")
        utils.warn(t("install.searxng_skip_optional"))

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
