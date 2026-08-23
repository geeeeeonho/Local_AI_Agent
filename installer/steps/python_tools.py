"""python_tools — 채팅 UI / Open Interpreter 설치."""
from __future__ import annotations

import os
import subprocess
import venv
from pathlib import Path
from typing import Dict, Optional

from installer import utils
from installer.i18n import t
from installer.resources import SafetyProfile, env_for_pip


def _already(tool_exe, label):
    """이미 설치된 도구면 메시지 출력 후 True."""
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


def _profile(paths: Dict[str, Path], profile: Optional[SafetyProfile]) -> SafetyProfile:
    if profile is not None:
        return profile
    from installer.resources import compute_safety_profile, detect
    return compute_safety_profile(detect(paths["env"]))


def _anyllm_msg(ko: str, en: str) -> str:
    try:
        from installer.i18n import get_language
        return ko if str(get_language()).lower().startswith("ko") else en
    except Exception:
        return ko


def _install_open_webui(paths: Dict[str, Path], profile: Optional[SafetyProfile] = None):
    utils.section(t("install.webui_section"))
    profile = _profile(paths, profile)
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
        utils.warn("pip upgrade failed - continuing")

    utils.warn(t("install.webui_dep_warn"))
    if _safe_pip_install(pip, "open-webui", profile, "Open WebUI"):
        utils.ok(t("install.tool_done", path=str(vdir)))


def _install_anythingllm(paths: Dict[str, Path], profile: Optional[SafetyProfile] = None):
    utils.section(_anyllm_msg(
        "AnythingLLM 설치 (Docker 이미지)",
        "AnythingLLM installation (Docker image)",
    ))
    try:
        from launcher import anythingllm_runtime as runtime
    except Exception as exc:
        utils.warn(_anyllm_msg(
            "anythingllm_runtime 을 불러오지 못했습니다: ",
            "Could not import anythingllm_runtime: ",
        ) + repr(exc))
        return

    if runtime.image_exists():
        utils.ok(_anyllm_msg(
            "이미 설치됨 — 건너뜀: ",
            "Already installed - skipping: ",
        ) + runtime.IMAGE)
        return

    utils.warn(_anyllm_msg(
        "약 3~5GB. 5~20분 소요됩니다 (네트워크 속도 영향).",
        "About 3-5GB. Takes 5-20 minutes depending on network.",
    ))
    if runtime.pull(log=utils.info):
        utils.ok(_anyllm_msg("이미지 준비 완료: ", "Image ready: ") + runtime.IMAGE)
    else:
        utils.err(_anyllm_msg("이미지 pull 실패", "Image pull failed"))
        utils.warn(_anyllm_msg("수동 시도: ", "Manual: ") + "docker pull " + runtime.IMAGE)


def install_open_webui(paths: Dict[str, Path], profile: Optional[SafetyProfile] = None):
    """호환 진입점. 환경변수에 따라 실제 채팅 엔진을 설치한다."""
    engine = os.environ.get("LOCAL_AI_CHAT_ENGINE", "").lower()
    if engine in ("openwebui", "webui"):
        return _install_open_webui(paths, profile)
    return _install_anythingllm(paths, profile)


def install_open_interpreter(
    paths: Dict[str, Path], profile: Optional[SafetyProfile] = None
):
    utils.section(t("install.interpreter_section"))
    profile = _profile(paths, profile)
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
        utils.warn("pip upgrade failed - continuing")

    if _safe_pip_install(pip, "open-interpreter", profile, "Open Interpreter"):
        utils.ok(t("install.tool_done", path=str(vdir)))
