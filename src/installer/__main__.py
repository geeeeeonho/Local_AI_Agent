#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""설치/관리 통합 진입점 — `SETUP.bat` 또는 `python -m installer` 로 실행."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def _dir_has_entries(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False



# ── 디스크 예산 ────────────────────────────────────────────────────
_RUNTIME_GB = 5.0        # Ollama / Python 도구 / 샌드박스 이미지 등 모델 외 용량
_FALLBACK_FLOOR_GB = 20  # 카탈로그를 못 읽을 때의 보수적 하한


def _model_disk_budget(skip_model: bool):
    """(하드 최소 GB, 이 PC 의 권장 세트까지 담는 데 필요한 GB).

    하드 최소는 '최저사양 세트' 기준이다. 그보다 적으면 어떤 조합으로도 설치가
    끝나지 않으므로 중단한다. 권장 세트가 더 크면 중단 대신 경고만 하고,
    사용자가 모델 선택 창에서 빼도록 둔다.
    """
    if skip_model:
        return int(_RUNTIME_GB), 0.0
    try:
        from launcher.models import model_catalog as cat
        from launcher.models import model_roles as mr
    except Exception:
        return _FALLBACK_FLOOR_GB, 0.0
    try:
        floor = cat.download_gb(cat.recommended_for(6.0))
        plan = cat.download_gb(cat.recommended_for(mr.detect_free_memory_gb()))
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
            % (plan_gb, target, free))

def _needs_model_storage_migration() -> bool:
    """기존/중단된 모델 저장소가 공용 경로로 수렴해야 하는지 확인."""
    legacy = ENV / "llm_models"
    shared = Path(MODEL_STORAGE_DIR)
    staging = shared.with_name(shared.name + ".migrating")

    # 이미 사용 중인 공용 저장소가 있으면 자동 병합하지 않는다. 설치/관리 화면에서
    # 사용자가 충돌을 확인하도록 두 데이터 세트를 그대로 보존한다.
    if _dir_has_entries(shared):
        return False
    return _dir_has_entries(legacy) or staging.exists()


def _should_manage(args) -> bool:
    """기본(auto) 모드에서 관리 화면으로 갈지 결정한다.

    기존 내부 호출인 ``python -m installer --skip-*`` 는 설치 작업으로 유지한다.
    또한 이전 버전 모델이나 중단된 staging이 남아 있으면 일반 ``SETUP.bat``도
    설치 흐름으로 보내 공용 ``C:\\LLM_Models`` 마이그레이션을 먼저 완료한다.
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
    if ENV.exists() and _needs_model_storage_migration():
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
    # 필요 용량은 고정 20GB 가 아니라 '이 PC 가 실제로 받을 세트' 에서 계산한다.
    # 예전에는 20GB 만 확인하고 그보다 훨씬 큰 세트를 받다가 도중에 디스크가
    # 차서 실패했다.
    _floor_gb, _plan_gb = _model_disk_budget(args.skip_model)
    utils.preflight_disk(MODEL_STORAGE_DIR.parent, need_gb=_floor_gb)
    _warn_if_plan_does_not_fit(_plan_gb)

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

    # ─── Ollama 소유권/파일 잠금 확인 ───
    # 레거시 llm_models 를 옮기기 전에 기존 관리형 Ollama를 종료해야 Windows의
    # 파일 잠금에 걸리지 않는다. 외부 Ollama가 같은 포트를 쓰면 강제 종료하지
    # 않고 설치를 중단한다.
    ollama.prepare_install(ENV, MODEL_STORAGE_DIR)

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
