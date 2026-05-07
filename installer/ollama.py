"""ollama — 포터블 ollama.exe 다운/설치 + 서비스 시작."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict

from . import utils
from .i18n import t

OLLAMA_ZIP_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/"
    "ollama-windows-amd64.zip"
)


def _exe(paths: Dict[str, Path]) -> Path:
    return paths["ollama"] / "ollama.exe"


def install_portable(paths: Dict[str, Path]):
    utils.section(t("install.ollama_section"))

    exe = _exe(paths)
    if exe.exists():
        utils.ok(t("install.ollama_already", path=str(exe)))
        return

    zip_path = paths["ollama"] / "ollama-windows-amd64.zip"
    utils.download_with_progress(OLLAMA_ZIP_URL, zip_path, "Ollama Portable")

    utils.info(t("install.ollama_extracting"))
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(paths["ollama"])
    zip_path.unlink()

    if not exe.exists():
        utils.err(f"ollama.exe not found: {exe}")
        raise RuntimeError("Ollama extraction failed")
    utils.ok(t("install.ollama_done", path=str(exe)))


def is_running() -> bool:
    """11434 포트 응답 여부."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def env_for(paths: Dict[str, Path]) -> dict:
    """OLLAMA_MODELS 등 환경변수 세팅된 dict."""
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(paths["models"])
    env["OLLAMA_HOST"]   = "127.0.0.1:11434"
    return env


def start_service(paths: Dict[str, Path]):
    utils.section(t("install.ollama_service_section"))

    if is_running():
        utils.ok(t("install.ollama_running"))
        return

    log = paths["logs"] / "ollama_install.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    utils.info(t("install.ollama_starting_bg", path=str(log)))

    CREATE_NO_WINDOW = 0x08000000

    # 자식 프로세스에 fd 전달 후 호스트 핸들은 즉시 닫아 누수 방지.
    f = open(log, "ab")
    try:
        subprocess.Popen(
            [str(_exe(paths)), "serve"],
            stdout=f, stderr=f,
            env=env_for(paths),
            creationflags=CREATE_NO_WINDOW,
        )
    finally:
        f.close()

    for i in range(30):
        if is_running():
            utils.ok(t("install.ollama_started", sec=i + 1))
            return
        time.sleep(1)

    utils.err(t("install.ollama_failed"))
    raise RuntimeError("Ollama service start failed")
