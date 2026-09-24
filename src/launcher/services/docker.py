"""services.docker — Docker CLI 공통 primitive와 데몬/이미지/컨테이너 헬퍼.

일반적인 Docker 명령 실행 방법은 이 모듈이 소유한다. 각 서비스의 의미 있는
health check(WARP/Tor handshake, AnythingLLM/SearXNG readiness, OI sandbox
version validation)는 각 runtime이 계속 소유한다.

중요: 모든 Docker subprocess 호출은 Windows 에서 CREATE_NO_WINDOW 플래그를
사용해 pythonw.exe GUI 실행 중 콘솔 창이 깜빡이지 않게 한다.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .. import config


_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = config.WIN_CREATE_NO_WINDOW


class DockerService:
    """Canonical Docker CLI boundary used by launcher/installer code."""

    @staticmethod
    def run(
        args: Iterable[object],
        *,
        timeout: float = 25,
        capture_output: bool = True,
        text: bool = True,
        check: bool = False,
        **kwargs,
    ) -> Optional[subprocess.CompletedProcess]:
        """Run one Docker command and return ``None`` on CLI/timeout failures.

        ``args`` normally excludes the leading ``docker`` token. Supplying it is
        also accepted so migration callers can delegate without rebuilding a
        command list first.
        """
        command = [str(part) for part in args]
        if not command or command[0].lower() != "docker":
            command.insert(0, "docker")

        options = dict(_NO_WINDOW_KW)
        options.update(kwargs)
        options.setdefault("timeout", timeout)
        options.setdefault("capture_output", capture_output)
        options.setdefault("text", text)
        if options.get("text"):
            # Docker emits UTF-8 even on Windows; relying on cp949 can turn an
            # otherwise successful connectivity command into UnicodeDecodeError.
            options.setdefault("encoding", "utf-8")
            options.setdefault("errors", "replace")
        options.setdefault("check", check)
        try:
            return subprocess.run(command, **options)
        except (OSError, subprocess.SubprocessError):
            return None

    # ── generic primitives ──────────────────────────────────────────
    @staticmethod
    def inspect(
        target: str,
        *,
        format: str | None = None,
        timeout: float = 20,
    ) -> Optional[subprocess.CompletedProcess]:
        args = ["inspect"]
        if format:
            args += ["--format", format]
        args.append(str(target))
        return DockerService.run(args, timeout=timeout)

    @staticmethod
    def build_image(
        tag: str,
        context: os.PathLike | str,
        *,
        dockerfile: os.PathLike | str | None = None,
        build_args: Mapping[str, object] | None = None,
        timeout: float = 1200,
        capture_output: bool = False,
    ) -> Optional[subprocess.CompletedProcess]:
        args = ["build", "-t", str(tag)]
        if dockerfile is not None:
            args += ["-f", str(Path(dockerfile))]
        for key, value in sorted((build_args or {}).items()):
            args += ["--build-arg", f"{key}={value}"]
        args.append(str(Path(context)))
        return DockerService.run(
            args,
            timeout=timeout,
            capture_output=capture_output,
            text=True,
        )

    @staticmethod
    def network_inspect(
        name: str,
        *,
        format: str | None = None,
        timeout: float = 20,
    ) -> Optional[subprocess.CompletedProcess]:
        args = ["network", "inspect"]
        if format:
            args += ["--format", format]
        args.append(str(name))
        return DockerService.run(args, timeout=timeout)

    @staticmethod
    def network_create(
        name: str,
        *,
        driver: str = "bridge",
        internal: bool = False,
        timeout: float = 30,
    ) -> Optional[subprocess.CompletedProcess]:
        args = ["network", "create", "--driver", str(driver)]
        if internal:
            args.append("--internal")
        args.append(str(name))
        return DockerService.run(args, timeout=timeout)

    @staticmethod
    def network_connect(
        network: str,
        container: str,
        *,
        timeout: float = 20,
    ) -> Optional[subprocess.CompletedProcess]:
        return DockerService.run(
            ["network", "connect", str(network), str(container)],
            timeout=timeout,
        )

    # ── daemon ─────────────────────────────────────────────────────
    @staticmethod
    def daemon_alive() -> bool:
        result = DockerService.run(
            ["info"],
            timeout=config.DOCKER_PROBE_TIMEOUT,
            check=True,
        )
        return bool(result and result.returncode == 0)

    # ── image ──────────────────────────────────────────────────────
    @staticmethod
    def image_exists(image: str) -> bool:
        result = DockerService.run(
            ["image", "inspect", image],
            timeout=config.DOCKER_PROBE_TIMEOUT,
            check=True,
        )
        return bool(result and result.returncode == 0)

    @staticmethod
    def pull_image(image: str) -> bool:
        result = DockerService.run(
            ["pull", image],
            timeout=1200,
            capture_output=False,
            text=True,
            check=True,
        )
        return bool(result and result.returncode == 0)

    # ── container ──────────────────────────────────────────────────
    @staticmethod
    def container_exists(name: str) -> bool:
        result = DockerService.run(
            ["ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            timeout=config.DOCKER_PROBE_TIMEOUT,
            check=True,
        )
        return bool(result and name in (result.stdout or "").split())

    @staticmethod
    def container_running(name: str) -> bool:
        result = DockerService.run(
            ["ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            timeout=config.DOCKER_PROBE_TIMEOUT,
            check=True,
        )
        return bool(result and name in (result.stdout or "").split())

    @staticmethod
    def container_logs(name: str, tail: int = 50) -> str:
        result = DockerService.run(
            ["logs", "--tail", str(tail), name],
            timeout=5,
        )
        if result is None:
            return "<로그 가져오기 실패>"
        return (result.stdout or "") + (result.stderr or "")

    @staticmethod
    def stop_container(name: str, timeout: int = 5) -> bool:
        result = DockerService.run(
            ["stop", "-t", str(timeout), name],
            timeout=timeout + 5,
        )
        return bool(result and result.returncode == 0)

    @staticmethod
    def remove_container(name: str, force: bool = True) -> bool:
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(name)
        result = DockerService.run(args, timeout=10)
        return bool(result and result.returncode == 0)

    # ── Docker Desktop 자동 시작 (Windows 전용) ──────────────────
    @staticmethod
    def find_desktop_executable() -> Optional[str]:
        if os.name != "nt":
            return None

        candidates = [
            r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
            r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
        ]
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(
                os.path.join(
                    user_profile,
                    r"AppData\Local\Programs\Docker\Docker\Docker Desktop.exe",
                )
            )
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            pf = os.environ.get(env_key)
            if pf:
                candidates.append(
                    os.path.join(pf, "Docker", "Docker", "Docker Desktop.exe")
                )

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
        if os.name != "nt":
            return False

        exe = DockerService.find_desktop_executable()
        if not exe:
            return False

        try:
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
        logger=None,
        timeout: int = 60,
        cancel_check: Optional[callable] = None,
    ) -> bool:
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
            timeout=timeout,
            cancel_check=cancel_check,
        )
        if ok:
            if logger:
                logger.ok("Docker 데몬 응답 확인됨")
            return True

        if logger:
            if cancel_check and cancel_check():
                logger.warn("Docker 시작 대기를 사용자가 취소함")
            else:
                logger.error(f"Docker 응답 시간 초과 ({timeout}초)")
                logger.warn("Docker Desktop 이 정상 시작되지 않았을 수 있습니다")
        return False
