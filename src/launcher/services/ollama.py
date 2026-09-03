"""services.ollama — Ollama 포터블 서비스 제어.

이 모듈은 단순히 11434 응답만 확인하지 않는다. 같은 포트에 사용자가 별도로
설치한 Ollama가 떠 있으면 그 프로세스의 환경변수/모델 저장소를 알 수 없기
때문에, 관리형 ``ollama.exe`` 인지 확인한 뒤에만 재사용한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from project_paths import MODEL_STORAGE_DIR
from .. import config


class _Logger(Protocol):
    def info(self, msg: str) -> None: ...
    def ok(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _same_path(left: Path, right: Path) -> bool:
    """Windows 경로의 대소문자/구분자 차이를 무시해 같은 파일인지 비교."""
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _dir_has_entries(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


class OllamaService:
    """프로젝트가 설치한 Ollama 포터블 서비스 제어."""

    def __init__(
        self,
        env: Path,
        logger: Optional[_Logger] = None,
        model_dir: Optional[Path] = None,
    ):
        self.env = Path(env)
        self.exe = self.env / "ollama_runtime" / "ollama.exe"
        self.log_file = self.env / "logs" / "ollama_run.log"
        self.runtime_state_file = self.env / "logs" / "ollama_server.json"
        self.model_dir = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
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

    def is_managed_running(self) -> bool:
        """부작용 없이 현재 포트가 추적 중인 관리형 Ollama인지 확인한다."""
        if not self.is_running():
            return False
        pid = self._listener_pid()
        if pid is None or not self._listener_is_managed(pid):
            return False
        return self._state_matches(pid)

    def _migration_pending(self) -> bool:
        """공용 저장소가 비어 있고 이전/중단 모델 데이터가 남았는지 확인."""
        if _dir_has_entries(self.model_dir):
            return False
        legacy = self.env / "llm_models"
        staging = self.model_dir.with_name(self.model_dir.name + ".migrating")
        return _dir_has_entries(legacy) or staging.exists()

    def _powershell(self, script: str) -> Optional[str]:
        """Windows 프로세스 소유권 확인용 PowerShell 한 줄 실행."""
        if os.name != "nt":
            return None
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": 5,
            "check": False,
        }
        kwargs["creationflags"] = config.WIN_CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        value = (result.stdout or "").strip()
        return value or None

    def _listener_pid(self) -> Optional[int]:
        script = (
            "$c=Get-NetTCPConnection -LocalPort "
            f"{int(config.OLLAMA_PORT)} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; if($c){[Console]::Out.Write($c.OwningProcess)}"
        )
        value = self._powershell(script)
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _process_executable(self, pid: int) -> Optional[Path]:
        value = self._powershell(
            f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
            "if($p){[Console]::Out.Write($p.Path)}"
        )
        return Path(value) if value else None

    def _listener_is_managed(self, pid: Optional[int] = None) -> bool:
        pid = pid if pid is not None else self._listener_pid()
        if pid is None:
            return False
        executable = self._process_executable(pid)
        return executable is not None and _same_path(executable, self.exe)

    def _state_matches(self, pid: int) -> bool:
        try:
            data = json.loads(self.runtime_state_file.read_text(encoding="utf-8"))
            return (
                int(data.get("pid", -1)) == int(pid)
                and _same_path(Path(data["executable"]), self.exe)
                and _same_path(Path(data["model_storage"]), self.model_dir)
                and int(data.get("port", -1)) == int(config.OLLAMA_PORT)
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _write_runtime_state(self, pid: int) -> None:
        self.runtime_state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": int(pid),
            "executable": str(self.exe.resolve()),
            "model_storage": str(self.model_dir.resolve()),
            "host": config.OLLAMA_HOST,
            "port": int(config.OLLAMA_PORT),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        temp = self.runtime_state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.runtime_state_file)

    def _remove_runtime_state(self) -> None:
        try:
            self.runtime_state_file.unlink(missing_ok=True)
        except OSError:
            pass

    # ── 환경변수 ──
    def env_vars(self, base: Optional[dict] = None) -> dict:
        e = (base or os.environ).copy()
        e["OLLAMA_MODELS"] = str(self.model_dir)
        e["OLLAMA_HOST"] = f"{config.OLLAMA_HOST}:{config.OLLAMA_PORT}"
        e.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
        e.setdefault("OLLAMA_KEEP_ALIVE", "5m")
        return e

    # ── 설치 전 정리 ──
    def prepare_install(self, stop_timeout: int = 5) -> bool:
        """설치/마이그레이션 전에 관리형 서버만 종료한다.

        외부 Ollama가 11434를 사용 중이면 강제 종료하지 않는다. 그 서버가 어떤
        ``OLLAMA_MODELS`` 값으로 시작됐는지 보장할 수 없으므로 설치를 중단한다.
        """
        if not self.is_running():
            self._remove_runtime_state()
            return True

        pid = self._listener_pid()
        executable = self._process_executable(pid) if pid is not None else None
        if pid is None or executable is None or not _same_path(executable, self.exe):
            shown = str(executable) if executable is not None else "확인 불가"
            self._err(
                "포트 %s에서 다른 Ollama가 실행 중입니다: %s"
                % (config.OLLAMA_PORT, shown)
            )
            self._err("해당 Ollama를 종료한 뒤 SETUP.bat을 다시 실행하세요.")
            return False

        self._info("모델 저장소 정리를 위해 관리형 Ollama를 잠시 종료합니다.")
        if not self._terminate_listener(pid):
            return False

        deadline = time.monotonic() + max(1, stop_timeout)
        while time.monotonic() < deadline:
            if not self.is_running():
                self._remove_runtime_state()
                return True
            time.sleep(0.1)

        self._err("관리형 Ollama 종료를 확인하지 못했습니다.")
        return False

    def _terminate_listener(self, pid: int) -> bool:
        """프로젝트가 설치한 exe인 경우에만 listener 프로세스를 강제 종료."""
        executable = self._process_executable(pid)
        if executable is None or not _same_path(executable, self.exe):
            self._err("Ollama 프로세스 소유권이 달라 종료하지 않았습니다.")
            return False
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                    creationflags=config.WIN_CREATE_NO_WINDOW,
                )
                if result.returncode != 0:
                    self._err("관리형 Ollama 종료 실패: " + (result.stderr or "").strip())
                    return False
            else:
                os.kill(int(pid), 15)
        except (OSError, subprocess.SubprocessError) as exc:
            self._err(f"관리형 Ollama 종료 실패: {exc}")
            return False
        self._remove_runtime_state()
        return True

    # ── 시작 ──
    def _launch(self) -> int:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.log_file, "ab")
        try:
            kwargs = {
                "stdout": f,
                "stderr": f,
                "env": self.env_vars(),
            }
            if os.name == "nt":
                kwargs["creationflags"] = config.WIN_CREATE_NO_WINDOW
            process = subprocess.Popen([str(self.exe), "serve"], **kwargs)
            return int(process.pid)
        finally:
            f.close()

    def ensure_running(self, boot_timeout: Optional[int] = None) -> bool:
        """공용 모델 경로를 쓰는 관리형 Ollama만 재사용/기동한다."""
        if self.is_running():
            pid = self._listener_pid()
            executable = self._process_executable(pid) if pid is not None else None
            if pid is None or executable is None or not _same_path(executable, self.exe):
                shown = str(executable) if executable is not None else "확인 불가"
                self._err(
                    "포트 %s가 외부 Ollama에 의해 사용 중입니다: %s"
                    % (config.OLLAMA_PORT, shown)
                )
                self._err("외부 Ollama를 종료한 뒤 다시 실행하세요.")
                return False

            if self._state_matches(pid):
                return True

            # 이전 버전이 같은 포터블 exe를 다른 OLLAMA_MODELS 값으로 실행했을 수
            # 있다. 환경변수는 실행 중 프로세스에 소급 적용되지 않으므로 한 번
            # 재시작해 현재 공용 저장소를 확실히 적용한다.
            self._warn("관리형 Ollama의 모델 저장소 설정을 갱신하기 위해 재시작합니다.")
            if not self._terminate_listener(pid):
                return False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not self.is_running():
                    break
                time.sleep(0.1)
            else:
                self._err("기존 관리형 Ollama가 종료되지 않았습니다.")
                return False

        if not self.is_installed():
            self._err(f"Ollama 미설치: {self.exe}")
            self._err("SETUP.bat --install 을 다시 실행하세요.")
            return False

        if self._migration_pending():
            self._err("이전 버전의 모델 저장소 마이그레이션이 아직 완료되지 않았습니다.")
            self._err("SETUP.bat을 실행해 C:\\LLM_Models 이전/복구를 먼저 완료하세요.")
            return False

        self._info("Ollama 가 응답 없음 — 관리형 서비스 시작 시도…")
        try:
            launched_pid = self._launch()
        except (OSError, PermissionError) as exc:
            self._err(f"Ollama 시작 실패: {exc}")
            return False

        timeout = boot_timeout or config.OLLAMA_BOOT_TIMEOUT
        for i in range(timeout):
            if self.is_running():
                listener_pid = self._listener_pid() or launched_pid
                listener_exe = self._process_executable(listener_pid)
                if listener_exe is not None and not _same_path(listener_exe, self.exe):
                    self._err("시작 도중 다른 Ollama가 포트를 선점했습니다.")
                    return False
                self._write_runtime_state(listener_pid)
                self._ok(f"Ollama 가동 확인 ({i + 1}초)")
                return True
            time.sleep(1)

        self._err(f"Ollama 시작 실패 — 로그: {self.log_file}")
        return False

    # ── 로그 헬퍼 ──
    def _info(self, m: str):
        if self._log:
            self._log.info(m)

    def _ok(self, m: str):
        if self._log:
            self._log.ok(m)

    def _warn(self, m: str):
        if self._log:
            self._log.warn(m)

    def _err(self, m: str):
        if self._log:
            self._log.error(m)
