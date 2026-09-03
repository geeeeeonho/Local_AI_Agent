"""ollama — 포터블 ollama.exe 설치와 관리형 서비스 수명주기."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Dict

from installer import utils
from installer.i18n import t
from launcher import config
from launcher.services.ollama import OllamaService

OLLAMA_ZIP_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/"
    "ollama-windows-amd64.zip"
)


class _InstallerLogger:
    def info(self, msg: str) -> None:
        utils.info(msg)

    def ok(self, msg: str) -> None:
        utils.ok(msg)

    def warn(self, msg: str) -> None:
        utils.warn(msg)

    def error(self, msg: str) -> None:
        utils.err(msg)


def _exe(paths: Dict[str, Path]) -> Path:
    return paths["ollama"] / "ollama.exe"


def _service(env: Path, model_dir: Path) -> OllamaService:
    return OllamaService(env, logger=_InstallerLogger(), model_dir=model_dir)


def prepare_install(env: Path, model_dir: Path) -> None:
    """레거시 모델 이동 전에 관리형 Ollama를 멈추고 외부 충돌을 차단."""
    svc = _service(Path(env), Path(model_dir))
    if not svc.prepare_install():
        raise RuntimeError("Another Ollama service is using the configured port")


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
    return OllamaService.is_running()


def env_for(paths: Dict[str, Path]) -> dict:
    """모델 관리 CLI가 관리형 서버와 같은 경로/호스트를 사용하도록 한다."""
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(paths["models"])
    env["OLLAMA_HOST"] = f"{config.OLLAMA_HOST}:{config.OLLAMA_PORT}"
    return env


def start_service(paths: Dict[str, Path]):
    utils.section(t("install.ollama_service_section"))
    svc = _service(paths["env"], paths["models"])
    if not svc.ensure_running(boot_timeout=30):
        raise RuntimeError("Managed Ollama service start failed")
