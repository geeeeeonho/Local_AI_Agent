"""ollama — 공식 Ollama 탐지/설치와 관리형 서비스 수명주기.

이 프로젝트는 Ollama 를 중간 매개체로 씁니다. 그래서 Ollama 를 프로젝트 안에
따로 품지 않고, 기계에 이미 있으면 그걸 쓰고 없을 때만 공식 설치기를 돌립니다.
모델 위치는 어느 쪽이든 Ollama 가 정합니다(``core.ollama_paths``).
"""
from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, Optional

from core import ollama_paths
from installer import utils
from installer.i18n import t
from launcher import config
from launcher.services.ollama import OllamaService

# 공식 설치기가 안 되는 환경에서만 쓰는 최후 폴백.
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


def find_existing(paths: Dict[str, Path]) -> Optional[Path]:
    """이미 설치된 Ollama. 프로젝트가 예전에 넣은 포터블 exe 도 포함한다."""
    return ollama_paths.find_executable(fallback=(paths["ollama"],))


def install_official(target: Optional[Path] = None) -> Optional[Path]:
    """공식 설치기를 /DIR 로 돌려 Ollama 를 설치하고 실행 파일을 돌려준다.

    설치 위치만 정하고 모델 위치는 건드리지 않는다 — 그건 Ollama 몫이다.
    Program Files 로는 넣지 않는다. 공식 설치기가 per-machine 파일과 per-user
    레지스트리가 섞인 상태를 만든다고 보고돼 있다.
    """
    if os.name != "nt":
        utils.warn("공식 Ollama 설치기는 Windows 전용입니다.")
        return None
    target = Path(target or ollama_paths.PROJECT_INSTALL_DIR)
    installer = target.parent / "OllamaSetup.exe"
    installer.parent.mkdir(parents=True, exist_ok=True)
    utils.download_with_progress(ollama_paths.SETUP_URL, installer, "Ollama")
    utils.info("공식 Ollama 를 설치합니다: " + str(target))
    try:
        result = subprocess.run(
            ollama_paths.setup_command(installer, target),
            check=False, creationflags=config.WIN_CREATE_NO_WINDOW)
    except OSError as exc:
        utils.warn("공식 설치기 실행 실패: " + str(exc))
        return None
    finally:
        try:
            installer.unlink(missing_ok=True)
        except OSError:
            pass
    if result.returncode != 0:
        utils.warn("공식 설치기가 코드 %s 로 끝났습니다." % result.returncode)
        return None
    found = ollama_paths.find_executable(extra=(target,))
    if found is None:
        utils.warn("설치 후에도 ollama 실행 파일을 찾지 못했습니다.")
    return found


def install(paths: Dict[str, Path]) -> Path:
    """설치된 Ollama 를 확보한다: 기존 → 공식 설치 → 포터블 폴백."""
    utils.section(t("install.ollama_section"))

    existing = find_existing(paths)
    if existing is not None:
        utils.ok(t("install.ollama_already", path=str(existing)))
        return existing

    official = install_official()
    if official is not None:
        utils.ok(t("install.ollama_done", path=str(official)))
        return official

    utils.warn("공식 설치를 완료하지 못해 포터블 Ollama 로 대체합니다.")
    install_portable(paths)
    return _exe(paths)


def install_portable(paths: Dict[str, Path]):
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
    """모델 관리 CLI가 서버와 같은 저장소/호스트를 보게 한다.

    저장소를 여기서 강제하지 않는다. 서비스와 같은 규칙을 쓰므로 Ollama 가
    스스로 고른 위치(사용자가 이미 옮겨 둔 위치 포함)를 그대로 따른다.
    """
    return _service(paths["env"], paths["models"]).env_vars()


def start_service(paths: Dict[str, Path]):
    utils.section(t("install.ollama_service_section"))
    svc = _service(paths["env"], paths["models"])
    if not svc.ensure_running(boot_timeout=30):
        raise RuntimeError("Managed Ollama service start failed")
