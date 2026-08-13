"""python_tools — Open WebUI / Open Interpreter venv installation."""
from __future__ import annotations

import subprocess
import venv
from pathlib import Path
from typing import Dict, Optional

from installer import utils
from installer.i18n import t
from installer.resources import SafetyProfile, env_for_pip


def _already(tool_exe, label):
    """이미 설치된 도구면 메시지 출력 후 True (pip 단계 건너뜀 — 작동 환경 보호)."""
    if tool_exe.exists():
        from installer.i18n import get_language
        msg = ("이미 설치됨 — 건너뜀: " if get_language() == "ko"
               else "Already installed - skipping: ")
        utils.ok(f"{label} {msg}{tool_exe.parent.parent}")
        return True
    return False


def _make_venv(vdir: Path):
    py = vdir / "Scripts" / "python.exe"
    if py.exists():
        utils.ok(f"venv reused: {vdir}")
        return
    utils.info(f"venv create: {vdir}")
    venv.create(vdir, with_pip=True, clear=False)


def _pip(vdir: Path) -> Path:
    return vdir / "Scripts" / "pip.exe"


def _safe_pip_install(
    pip_path: Path,
    package: str,
    profile: SafetyProfile,
    label: str,
) -> bool:
    """pip install with resource limits + OOM auto-fallback."""
    env = env_for_pip(profile)

    utils.info(t("install.pip_label_install", label=label, jobs=profile.pip_jobs))

    try:
        subprocess.run(
            [str(pip_path), "install", "--upgrade", package],
            env=env, check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        utils.warn(t("install.pip_first_failed", label=label, rc=e.returncode))

    # 보수 모드 재시도
    env["MAKEFLAGS"] = "-j1"
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = "1"
    env["MAX_JOBS"] = "1"

    try:
        subprocess.run(
            [str(pip_path), "install", "--upgrade", "--prefer-binary", package],
            env=env, check=True,
        )
        utils.ok(t("install.pip_second_ok", label=label))
        return True
    except subprocess.CalledProcessError as e:
        utils.err(t("install.pip_final_failed", label=label, rc=e.returncode))
        utils.warn(t("install.pip_manual", pip=str(pip_path), package=package))
        return False


def install_open_webui(paths: Dict[str, Path], profile: Optional[SafetyProfile] = None):
    utils.section(t("install.webui_section"))

    if profile is None:
        from installer.resources import compute_safety_profile, detect
        profile = compute_safety_profile(detect(paths["env"]))

    vdir = paths["chat"] / "venv"
    if _already(vdir / "Scripts" / "open-webui.exe", "Open WebUI"):
        return
    _make_venv(vdir)
    pip = _pip(vdir)

    utils.info(t("install.pip_upgrade"))
    try:
        subprocess.run(
            [str(pip), "install", "--upgrade", "pip", "wheel", "setuptools"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        utils.warn(f"pip upgrade failed - continuing")

    utils.warn(t("install.webui_dep_warn"))
    if _safe_pip_install(pip, "open-webui", profile, "Open WebUI"):
        utils.ok(t("install.tool_done", path=str(vdir)))


def install_open_interpreter(
    paths: Dict[str, Path], profile: Optional[SafetyProfile] = None
):
    utils.section(t("install.interpreter_section"))

    if profile is None:
        from installer.resources import compute_safety_profile, detect
        profile = compute_safety_profile(detect(paths["env"]))

    vdir = paths["agent"] / "venv"
    if _already(vdir / "Scripts" / "interpreter.exe", "Open Interpreter"):
        return
    _make_venv(vdir)
    pip = _pip(vdir)

    utils.info(t("install.pip_upgrade"))
    try:
        subprocess.run(
            [str(pip), "install", "--upgrade", "pip", "wheel", "setuptools"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        utils.warn(f"pip upgrade failed - continuing")

    if _safe_pip_install(pip, "open-interpreter", profile, "Open Interpreter"):
        utils.ok(t("install.tool_done", path=str(vdir)))


# >>> ANYTHINGLLM_v1 (PATCH_ANYTHINGLLM.py)  ANYTHINGLLM_REV=8
# 설치 단계에서 pip open-webui 대신 AnythingLLM 이미지를 받는다.
# installer/__main__.py 의 호출 지점(install_open_webui)은 그대로 두고 내용만 바꾼다.
# 되돌리기: set LOCAL_AI_CHAT_ENGINE=openwebui
_ANYLLM_ORIG_INSTALL_WEBUI = install_open_webui


def _anyllm_msg(ko, en):
    """installer 의 언어 설정을 따른다 (python_tools._already 와 같은 방식)."""
    try:
        from installer.i18n import get_language
        return ko if str(get_language()).lower().startswith("ko") else en
    except Exception:
        return ko


def install_open_webui(paths, profile=None):
    import os as _os_al
    if _os_al.environ.get("LOCAL_AI_CHAT_ENGINE", "").lower() in ("openwebui", "webui"):
        return _ANYLLM_ORIG_INSTALL_WEBUI(paths, profile)

    utils.section(_anyllm_msg("AnythingLLM 설치 (Docker 이미지)",
                              "AnythingLLM installation (Docker image)"))
    try:
        from launcher import anythingllm_runtime as _al
    except Exception as _e_al:
        utils.warn(_anyllm_msg("anythingllm_runtime 을 불러오지 못했습니다: ",
                               "Could not import anythingllm_runtime: ") + repr(_e_al))
        utils.warn(_anyllm_msg("PATCH_ANYTHINGLLM.bat 을 먼저 실행하세요.",
                               "Run PATCH_ANYTHINGLLM.bat first."))
        return

    if _al.image_exists():
        utils.ok(_anyllm_msg("이미 설치됨 — 건너뜀: ",
                             "Already installed - skipping: ") + _al.IMAGE)
        return

    utils.warn(_anyllm_msg("약 3~5GB. 5~20분 소요됩니다 (네트워크 속도 영향).",
                           "About 3-5GB. Takes 5-20 minutes depending on network."))
    if _al.pull(log=utils.info):
        utils.ok(_anyllm_msg("이미지 준비 완료: ", "Image ready: ") + _al.IMAGE)
    else:
        utils.err(_anyllm_msg("이미지 pull 실패", "Image pull failed"))
        utils.warn(_anyllm_msg("수동 시도: ", "Manual: ") + "docker pull " + _al.IMAGE)
# <<< ANYTHINGLLM_v1
