"""Install and manage the LocalAI-owned machine-wide Ollama broker.

Fresh installs use only ``C:\\LocalAI\\ollama`` and ``C:\\LocalAI\\models``. A separately
installed Ollama is never substituted for this broker.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
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
    """Ensure port 11434 is not owned by an unrelated Ollama before setup."""
    svc = _service(Path(env), Path(model_dir))
    if not svc.prepare_install():
        raise RuntimeError(svc.last_error or "Another Ollama service is using the configured port")


def find_existing(paths: Dict[str, Path]) -> Optional[Path]:
    """LocalAI-managed Ollama already present in the shared broker directory."""
    folder = Path(paths["ollama"])
    for name in ollama_paths.executable_names():
        candidate = folder / name
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _is_windows() -> bool:
    """One seam for the platform test.

    Patching ``os.name`` itself is not a substitute: ``pathlib`` reads it on
    every ``Path()``, so a test that flips it globally makes the rest of this
    function raise on any other OS instead of exercising it.
    """
    return os.name == "nt"


def install_official(target: Optional[Path] = None, model_dir: Optional[Path] = None) -> Optional[Path]:
    """Run OllamaSetup into the LocalAI broker directory.

    Pass OLLAMA_MODELS explicitly to the installer process as defense in depth:
    if the installer starts its tray/server before setup returns, that process
    must already inherit the LocalAI shared model store.
    """
    if not _is_windows():
        utils.warn("공식 Ollama 설치기는 Windows 전용입니다.")
        return None
    target = Path(target or ollama_paths.PROJECT_INSTALL_DIR)

    # Do not stage the installer beside C:\\LocalAI\\ollama. A normal desktop process
    # may not be allowed to create files at the drive root even though the
    # official installer itself can negotiate what it needs. A closed temporary
    # file also works under pythonw.exe, where there is no console.
    handle = tempfile.NamedTemporaryFile(
        prefix="LocalAI-OllamaSetup-", suffix=".exe", delete=False
    )
    installer = Path(handle.name)
    handle.close()

    try:
        try:
            utils.download_with_progress(ollama_paths.SETUP_URL, installer, "Ollama")
        except (OSError, RuntimeError) as exc:
            utils.warn("공식 Ollama 설치기 다운로드 실패: " + str(exc))
            return None

        utils.info("공식 Ollama 를 설치합니다: " + str(target))
        try:
            child_env = os.environ.copy()
            if model_dir is not None:
                child_env["OLLAMA_MODELS"] = str(Path(model_dir))
            result = subprocess.run(
                ollama_paths.setup_command(installer, target),
                check=False,
                env=child_env,
                creationflags=config.WIN_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            utils.warn("공식 설치기 실행 실패: " + str(exc))
            return None

        if result.returncode != 0:
            utils.warn("공식 설치기가 코드 %s 로 끝났습니다." % result.returncode)
            return None
        found = None
        for name in ollama_paths.executable_names():
            candidate = target / name
            try:
                if candidate.is_file():
                    found = candidate
                    break
            except OSError:
                continue
        if found is None:
            utils.warn("설치 후에도 LocalAI 공용 경로에서 ollama 실행 파일을 찾지 못했습니다.")
        if not disable_login_autostart():
            utils.warn("Ollama 로그인 자동시작 바로가기를 제거하지 못했습니다. "
                       "작업 관리자 > 시작 앱에서 Ollama를 비활성화하세요.")
        return found
    finally:
        try:
            installer.unlink(missing_ok=True)
        except OSError:
            pass


def disable_login_autostart() -> bool:
    """Remove Ollama's per-user login shortcut for the installing account.

    LocalAI owns broker startup. Ollama's Windows app creates a Startup shortcut
    during installation/first launch; leaving it enabled can start 11434 before
    LocalAI has applied the managed store policy on the next sign-in.
    """
    if not _is_windows():
        return True
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return False
    shortcut = (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "Ollama.lnk"
    )
    # The installer starts the app asynchronously. Give it a short chance to
    # create the shortcut, then remove it. Missing is already the desired state.
    import time
    for _ in range(20):
        try:
            if shortcut.exists():
                shortcut.unlink()
                return not shortcut.exists()
        except OSError:
            return False
        time.sleep(0.1)
    return not shortcut.exists()


def install(paths: Dict[str, Path]) -> Path:
    """Ensure the shared LocalAI-managed Ollama broker exists."""
    utils.section(t("install.ollama_section"))

    existing = find_existing(paths)
    if existing is not None:
        utils.ok(t("install.ollama_already", path=str(existing)))
        return existing

    official = install_official(paths["ollama"], paths["models"])
    if official is not None:
        utils.ok(t("install.ollama_done", path=str(official)))
        return official

    utils.warn("공식 설치를 완료하지 못해 같은 공용 폴더에 포터블 Ollama 로 대체합니다.")
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
    """Environment for model-management CLI calls against the shared store."""
    return _service(paths["env"], paths["models"]).env_vars()


def persist_store(paths: Dict[str, Path]) -> str:
    """Write the model path where Windows keeps it, not just into one child.

    The installer used to hand OLLAMA_MODELS to the server it launched and stop
    there. Nothing else that starts Ollama inherits a child-process variable -
    least of all the Startup entry Windows runs at login - so the very first
    reboot left the server reading its own empty default while the whole
    library sat in the store this installer had just filled.
    """
    svc = _service(paths["env"], paths["models"])
    scope = svc.persist_store_setting()
    if not scope:
        utils.warn('모델 경로를 Windows 설정에 저장하지 못했습니다: %s' % paths["models"])
    return scope


def start_service(paths: Dict[str, Path]):
    utils.section(t("install.ollama_service_section"))
    persist_store(paths)
    svc = _service(paths["env"], paths["models"])
    if svc.ensure_running(boot_timeout=30):
        disable_login_autostart()
        return
    # Setup is an explicit maintenance operation and holds the machine-wide
    # runtime lock. If the canonical broker is already running on a proven
    # different store, repair that mismatch here before any model pull occurs.
    if svc.is_running() and svc.restart_for_store():
        disable_login_autostart()
        return
    raise RuntimeError(svc.last_error or "Managed Ollama service start failed")
