"""services.docker — Docker 데몬 / 이미지 / 컨테이너 헬퍼.

이전: launcher/handlers.py 의 _check_docker_image,
     launcher/searxng_runtime.py 의 image_exists/container_exists
     installer/sandbox.py 의 _check_docker
중복을 통합. 단일 진입점.

중요: 모든 subprocess 호출은 Windows 에서 CREATE_NO_WINDOW 플래그 사용.
      pythonw.exe 로 실행될 때 콘솔 창이 깜빡 뜨는 문제 차단.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from .. import config


# Windows 에서 subprocess 가 콘솔 창을 띄우지 않게 하는 플래그
_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = config.WIN_CREATE_NO_WINDOW


class DockerError(Exception):
    """Docker 실패 표현."""


class DockerService:
    """Docker 명령 wrapper. 모든 메서드는 예외 대신 bool/Optional 반환.

    pythonw.exe (콘솔 없는 GUI 모드) 에서도 콘솔 깜빡임 없이 동작.
    """

    # ── 데몬 ──
    @staticmethod
    def daemon_alive() -> bool:
        try:
            subprocess.run(
                ["docker", "info"],
                capture_output=True, check=True,
                timeout=config.DOCKER_PROBE_TIMEOUT,
                **_NO_WINDOW_KW,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return False

    # ── 이미지 ──
    @staticmethod
    def image_exists(image: str) -> bool:
        try:
            subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True, check=True,
                timeout=config.DOCKER_PROBE_TIMEOUT,
                **_NO_WINDOW_KW,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return False

    @staticmethod
    def pull_image(image: str) -> bool:
        # pull 은 진행률 출력이 필요해 콘솔 차단 X (사용자가 명시적 호출)
        try:
            subprocess.run(["docker", "pull", image], check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    # ── 컨테이너 ──
    @staticmethod
    def container_exists(name: str) -> bool:
        try:
            r = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name=^{name}$",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True,
                timeout=config.DOCKER_PROBE_TIMEOUT, check=True,
                **_NO_WINDOW_KW,
            )
            return name in r.stdout.split()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return False

    @staticmethod
    def container_running(name: str) -> bool:
        try:
            r = subprocess.run(
                ["docker", "ps", "--filter", f"name=^{name}$",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True,
                timeout=config.DOCKER_PROBE_TIMEOUT, check=True,
                **_NO_WINDOW_KW,
            )
            return name in r.stdout.split()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return False

    @staticmethod
    def container_logs(name: str, tail: int = 50) -> str:
        try:
            r = subprocess.run(
                ["docker", "logs", "--tail", str(tail), name],
                capture_output=True, text=True, timeout=5,
                **_NO_WINDOW_KW,
            )
            return (r.stdout or "") + (r.stderr or "")
        except Exception as e:
            return f"<로그 가져오기 실패: {e}>"

    @staticmethod
    def stop_container(name: str, timeout: int = 5) -> bool:
        try:
            subprocess.run(
                ["docker", "stop", "-t", str(timeout), name],
                capture_output=True, timeout=timeout + 5,
                **_NO_WINDOW_KW,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def remove_container(name: str, force: bool = True) -> bool:
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(name)
        try:
            subprocess.run(
                cmd, capture_output=True, timeout=10,
                **_NO_WINDOW_KW,
            )
            return True
        except Exception:
            return False

    # ── Docker Desktop 자동 시작 (Windows 전용) ──
    @staticmethod
    def find_desktop_executable() -> Optional[str]:
        """Docker Desktop 실행 파일 경로 탐색 (Windows).

        반환:
          str: 찾은 경우 절대 경로
          None: 못 찾음
        """
        if os.name != "nt":
            return None

        # 표준 설치 경로 우선 탐색
        candidates = [
            r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
            r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
        ]
        # 사용자별 설치
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(
                os.path.join(
                    user_profile,
                    r"AppData\Local\Programs\Docker\Docker\Docker Desktop.exe",
                )
            )
        # 환경변수 ProgramFiles
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            pf = os.environ.get(env_key)
            if pf:
                candidates.append(
                    os.path.join(pf, "Docker", "Docker", "Docker Desktop.exe")
                )

        # 중복 제거하면서 순서 유지
        seen = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def start_desktop() -> bool:
        """Docker Desktop 시작 시도 (Windows).

        반환:
          True:  실행 명령은 성공 (데몬 응답까지는 별도 대기 필요)
          False: 실행 파일 없음 또는 실패
        """
        if os.name != "nt":
            return False

        exe = DockerService.find_desktop_executable()
        if not exe:
            return False

        try:
            # Docker Desktop 은 GUI 앱이므로 Popen 으로 띄우고 즉시 리턴
            subprocess.Popen(
                [exe],
                creationflags=config.WIN_CREATE_NO_WINDOW,
                close_fds=True,
            )
            return True
        except (OSError, FileNotFoundError):
            return False

    @staticmethod
    def wait_until_alive(
        timeout: int = 60,
        poll_interval: float = 1.5,
        cancel_check: Optional[callable] = None,
    ) -> bool:
        """Docker 데몬이 응답할 때까지 폴링.

        Args:
          timeout: 최대 대기 시간 (초)
          poll_interval: 폴링 간격 (초)
          cancel_check: callable() -> bool. True 반환하면 즉시 중단.

        반환:
          True:  데몬 응답함
          False: timeout 초과 또는 cancel_check 가 True 반환
        """
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel_check and cancel_check():
                return False
            if DockerService.daemon_alive():
                return True
            time.sleep(poll_interval)
        return False

    @staticmethod
    def ensure_daemon(
        logger=None, timeout: int = 60,
        cancel_check: Optional[callable] = None,
    ) -> bool:
        """Docker 데몬이 응답하지 않으면 Docker Desktop 자동 시작 후 대기.

        Args:
          logger: Presenter 또는 호환 객체 (info/ok/warn/error 메서드)
          timeout: 시작 후 응답까지 대기 시간
          cancel_check: 취소 체크 콜백

        반환:
          True:  데몬 응답함 (이미 떠있었거나 시작 후 응답)
          False: 시작 실패 또는 timeout
        """
        # 이미 살아있으면 바로 OK
        if DockerService.daemon_alive():
            return True

        if logger:
            logger.info("Docker 데몬이 응답하지 않습니다 — 자동 시작 시도")

        exe = DockerService.find_desktop_executable()
        if not exe:
            if logger:
                logger.error("Docker Desktop 실행 파일을 찾지 못했습니다")
                logger.warn("Docker Desktop 을 수동으로 시작 후 재시도하세요")
                logger.info("표준 경로: C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe")
            return False

        if logger:
            logger.info(f"Docker Desktop 시작 중: {exe}")

        if not DockerService.start_desktop():
            if logger:
                logger.error("Docker Desktop 시작 실패")
            return False

        if logger:
            logger.info(f"Docker 데몬 응답 대기 중 (최대 {timeout}초)...")

        ok = DockerService.wait_until_alive(
            timeout=timeout, cancel_check=cancel_check,
        )
        if ok:
            if logger:
                logger.ok("Docker 데몬 응답 확인됨")
            return True
        else:
            if logger:
                if cancel_check and cancel_check():
                    logger.warn("Docker 시작 대기를 사용자가 취소함")
                else:
                    logger.error(f"Docker 응답 시간 초과 ({timeout}초)")
                    logger.warn("Docker Desktop 이 정상 시작되지 않았을 수 있습니다")
            return False
