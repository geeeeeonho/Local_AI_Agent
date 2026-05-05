"""python_tools — Open WebUI / Open Interpreter venv installation."""
from __future__ import annotations

import subprocess
import venv
from pathlib import Path
from typing import Dict, Optional

from . import utils
from .i18n import t
from .resources import SafetyProfile, env_for_pip


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
        from .resources import compute_safety_profile, detect
        profile = compute_safety_profile(detect(paths["env"]))

    vdir = paths["chat"] / "venv"
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
        from .resources import compute_safety_profile, detect
        profile = compute_safety_profile(detect(paths["env"]))

    vdir = paths["agent"] / "venv"
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
