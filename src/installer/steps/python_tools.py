"""python_tools — AnythingLLM / managed Open Interpreter 설치."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from core.progress import LogAdapter
from installer import utils
from installer.i18n import t
from installer.resources import SafetyProfile
from runtime_versions import (
    OPEN_INTERPRETER_VERSION,
    open_interpreter_install_script,
)

OPEN_INTERPRETER_INSTALL_SCRIPT = open_interpreter_install_script("ps1")


def _anyllm_msg(ko: str, en: str) -> str:
    try:
        from installer.i18n import get_language
        return ko if str(get_language()).lower().startswith("ko") else en
    except Exception:
        return ko


def install_anythingllm(
    paths: Dict[str, Path], profile: Optional[SafetyProfile] = None
) -> bool:
    """Install the AnythingLLM Docker image used by ChatService."""
    del paths, profile  # runtime owns its persistent storage and Docker settings
    utils.section(_anyllm_msg(
        "AnythingLLM 설치 (Docker 이미지)",
        "AnythingLLM installation (Docker image)",
    ))
    try:
        from launcher import anythingllm_runtime as runtime
        from launcher.services.docker import DockerService
    except Exception as exc:
        utils.warn(_anyllm_msg(
            "AnythingLLM 설치 구성요소를 불러오지 못했습니다: ",
            "Could not import AnythingLLM installer dependencies: ",
        ) + repr(exc))
        return False

    utils.info(_anyllm_msg(
        "Chat 준비 1/3: Docker Desktop 확인",
        "Chat preparation 1/3: checking Docker Desktop",
    ))
    try:
        # Without a logger this is up to ninety silent seconds in a console the
        # user is watching, and then a bare failure line.
        docker_ready = DockerService.ensure_daemon(
            logger=LogAdapter(utils.info), timeout=90)
    except Exception as exc:
        utils.err(_anyllm_msg(
            "Docker Desktop 준비 중 오류: ",
            "Docker Desktop preparation failed: ",
        ) + repr(exc))
        return False
    if not docker_ready:
        utils.err(_anyllm_msg(
            "Docker Desktop을 준비할 수 없어 AnythingLLM 설치를 건너뜁니다.",
            "Docker Desktop is not ready; skipping AnythingLLM installation.",
        ))
        return False

    utils.info(_anyllm_msg(
        "Chat 준비 2/3: AnythingLLM 이미지 확인",
        "Chat preparation 2/3: checking AnythingLLM image",
    ))
    if runtime.image_exists():
        utils.ok(_anyllm_msg(
            "이미 설치됨 — 건너뜀: ",
            "Already installed - skipping: ",
        ) + runtime.IMAGE)
        utils.info(_anyllm_msg(
            "Chat 준비 3/3: 이미지 준비 완료. 실제 Ollama/모델 연결은 Chat 시작 시 검증합니다.",
            "Chat preparation 3/3: image ready. Ollama/model connectivity is verified when Chat starts.",
        ))
        return True

    utils.warn(_anyllm_msg(
        "약 3~5GB. 5~20분 소요됩니다 (네트워크 속도 영향).",
        "About 3-5GB. Takes 5-20 minutes depending on network.",
    ))
    if runtime.pull(log=utils.info):
        utils.ok(_anyllm_msg("이미지 준비 완료: ", "Image ready: ") + runtime.IMAGE)
        utils.info(_anyllm_msg(
            "Chat 준비 3/3: 이미지 준비 완료. 실제 Ollama/모델 연결은 Chat 시작 시 검증합니다.",
            "Chat preparation 3/3: image ready. Ollama/model connectivity is verified when Chat starts.",
        ))
        return True

    utils.err(_anyllm_msg("이미지 pull 실패", "Image pull failed"))
    utils.warn(_anyllm_msg("수동 시도: ", "Manual: ") + "docker pull " + runtime.IMAGE)
    return False


def _download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Local_AI_Agent installer"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    Path(destination).write_bytes(data)


def _installed_interpreter_version(exe: Path) -> str | None:
    if not exe.is_file():
        return None
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 15,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        result = subprocess.run([str(exe), "--version"], **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = ((result.stdout or "") + " " + (result.stderr or "")).strip()
    match = re.search(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", text)
    return match.group(1) if match else None


def install_open_interpreter(
    paths: Dict[str, Path], profile: Optional[SafetyProfile] = None
) -> bool:
    """Install the pinned standalone Rust Open Interpreter distribution."""
    del profile  # standalone distribution is not built locally
    utils.section(t("install.interpreter_section"))

    bin_dir = paths.get("open_interpreter_bin", paths["env"] / "open_interpreter" / "bin")
    package_home = paths.get("open_interpreter_home", paths["env"] / "open_interpreter" / "home")
    bin_dir.mkdir(parents=True, exist_ok=True)
    package_home.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "interpreter.exe"

    current = _installed_interpreter_version(exe)
    if current == OPEN_INTERPRETER_VERSION:
        utils.ok(f"Open Interpreter {OPEN_INTERPRETER_VERSION} already installed: {exe}")
        return True
    if current:
        utils.info(f"Open Interpreter update: {current} -> {OPEN_INTERPRETER_VERSION}")

    install_env = dict(os.environ)
    install_env["OPEN_INTERPRETER_INSTALL_DIR"] = str(bin_dir)
    install_env["OPEN_INTERPRETER_RELEASE"] = OPEN_INTERPRETER_VERSION
    install_env["OPEN_INTERPRETER_NONINTERACTIVE"] = "1"
    install_env["INTERPRETER_HOME"] = str(package_home)

    try:
        with tempfile.TemporaryDirectory(prefix="local-ai-oi-") as temp_dir:
            script = Path(temp_dir) / "install-open-interpreter.ps1"
            utils.info(f"Open Interpreter installer download: {OPEN_INTERPRETER_VERSION}")
            _download_file(OPEN_INTERPRETER_INSTALL_SCRIPT, script)
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(script),
            ]
            result = subprocess.run(
                command,
                env=install_env,
                check=False,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            if result.returncode != 0:
                utils.err(f"Open Interpreter standalone install failed: rc={result.returncode}")
                return False
    except (OSError, urllib.error.URLError, subprocess.SubprocessError) as exc:
        utils.err(f"Open Interpreter standalone install failed: {exc}")
        return False

    installed = _installed_interpreter_version(exe)
    if installed != OPEN_INTERPRETER_VERSION:
        utils.err(
            "Open Interpreter version verification failed: "
            f"expected {OPEN_INTERPRETER_VERSION}, got {installed or 'unknown'}"
        )
        return False

    utils.ok(f"Open Interpreter {installed} ready: {exe}")
    return True


__all__ = ["install_anythingllm", "install_open_interpreter"]
