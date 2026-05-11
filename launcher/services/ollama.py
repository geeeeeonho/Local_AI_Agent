"""services.ollama — Ollama 포터블 서비스 제어.

이전: launcher/handlers.py 의 _ollama_running, _ensure_ollama
     installer/ollama.py 의 is_running, env_for, start_service
중복 코드를 통합.
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

from .. import config


class _Logger(Protocol):
    def info(self, msg: str) -> None: ...
    def ok(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


class OllamaService:
    """Ollama 포터블 서비스 제어.

    Presenter (혹은 임의 logger) 를 주입받아 사용자 메시지 출력.
    UI 종류에 무관하게 동작.
    """

    def __init__(self, env: Path, logger: Optional[_Logger] = None):
        self.env = env
        self.exe = env / "ollama_runtime" / "ollama.exe"
        self.log_file = env / "logs" / "ollama_run.log"
        self._log = logger

    # ── 상태 확인 ──
    @staticmethod
    def is_running() -> bool:
        try:
            urllib.request.urlopen(
                config.OLLAMA_API_TAGS, timeout=config.OLLAMA_PROBE_TIMEOUT,
            )
            return True
        except (urllib.error.URLError, OSError):
            return False

    def is_installed(self) -> bool:
        return self.exe.exists()

    # ── 환경변수 ──
    def env_vars(self, base: Optional[dict] = None) -> dict:
        e = (base or os.environ).copy()
        e["OLLAMA_MODELS"] = str(self.env / "llm_models")
        e["OLLAMA_HOST"] = f"{config.OLLAMA_HOST}:{config.OLLAMA_PORT}"
        return e

    # ── 시작 ──
    def ensure_running(self, boot_timeout: Optional[int] = None) -> bool:
        """Ollama 가 안 켜져 있으면 백그라운드로 시작 후 폴링."""
        if self.is_running():
            return True

        if not self.is_installed():
            self._err(f"Ollama 미설치: {self.exe}")
            self._err("install 을 다시 실행하세요")
            return False

        self._info("Ollama 가 응답 없음 — 백그라운드 시작 시도…")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # 자식 프로세스에 fd 전달 후 호스트 핸들은 즉시 닫기 (fd 누수 방지)
        f = open(self.log_file, "ab")
        try:
            kwargs = {
                "stdout": f, "stderr": f,
                "env": self.env_vars(),
            }
            if os.name == "nt":
                kwargs["creationflags"] = config.WIN_CREATE_NO_WINDOW
            subprocess.Popen([str(self.exe), "serve"], **kwargs)
        finally:
            f.close()

        timeout = boot_timeout or config.OLLAMA_BOOT_TIMEOUT
        for i in range(timeout):
            if self.is_running():
                self._ok(f"Ollama 가동 확인 ({i + 1}초)")
                return True
            time.sleep(1)

        self._err(f"Ollama 시작 실패 — 로그: {self.log_file}")
        return False

    # ── 로그 헬퍼 (logger 주입 안 됐어도 동작) ──
    def _info(self, m: str):
        if self._log: self._log.info(m)

    def _ok(self, m: str):
        if self._log: self._log.ok(m)

    def _warn(self, m: str):
        if self._log: self._log.warn(m)

    def _err(self, m: str):
        if self._log: self._log.error(m)
