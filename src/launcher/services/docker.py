"""services.docker — Docker CLI 공통 primitive와 데몬/이미지/컨테이너 헬퍼.

일반적인 Docker 명령 실행 방법은 이 모듈이 소유한다. 각 서비스의 의미 있는
health check(WARP/Tor handshake, AnythingLLM/SearXNG readiness, OI sandbox
version validation)는 각 runtime이 계속 소유한다.

중요: 모든 Docker subprocess 호출은 Windows 에서 CREATE_NO_WINDOW 플래그를
사용해 pythonw.exe GUI 실행 중 콘솔 창이 깜빡이지 않게 한다.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
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

    @staticmethod
    def run_stream(
        args: Iterable[object],
        *,
        logger=None,
        timeout: float = 1200,
        cancel_check=None,
    ) -> Optional[int]:
        """Run Docker hidden while forwarding stdout/stderr line-by-line."""
        command = [str(part) for part in args]
        if not command or command[0].lower() != "docker":
            command.insert(0, "docker")

        options = dict(_NO_WINDOW_KW)
        options.update({
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        })
        try:
            process = subprocess.Popen(command, **options)
        except OSError:
            return None

        lines = queue.Queue()
        finished = object()

        def pump():
            try:
                for line in process.stdout or ():
                    lines.put(line.rstrip("\r\n"))
            finally:
                lines.put(finished)

        threading.Thread(
            target=pump, daemon=True, name="localai-docker-output"
        ).start()

        def emit(message):
            if logger is None:
                return
            try:
                if callable(logger):
                    logger(message)
                else:
                    logger.info(message)
            except Exception:
                pass

        deadline = time.monotonic() + max(1.0, float(timeout))
        reader_done = False
        while True:
            if cancel_check is not None and cancel_check():
                emit("Docker 작업 취소 요청")
                try:
                    process.terminate()
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
                return None
            if time.monotonic() >= deadline:
                emit("Docker 작업 시간 초과")
                try:
                    process.kill()
                except OSError:
                    pass
                return None
            try:
                item = lines.get(timeout=0.1)
            except queue.Empty:
                item = None
            if item is finished:
                reader_done = True
            elif item:
                emit(str(item))
            if process.poll() is not None and reader_done:
                return int(process.returncode or 0)

    @staticmethod
    def build_image_stream(
        tag: str,
        context: os.PathLike | str,
        *,
        dockerfile: os.PathLike | str | None = None,
        build_args: Mapping[str, object] | None = None,
        logger=None,
        timeout: float = 1200,
        cancel_check=None,
    ) -> Optional[int]:
        args = ["build", "-t", str(tag)]
        if dockerfile is not None:
            args += ["-f", str(Path(dockerfile))]
        for key, value in sorted((build_args or {}).items()):
            args += ["--build-arg", f"{key}={value}"]
        args.append(str(Path(context)))
        return DockerService.run_stream(
            args, logger=logger, timeout=timeout, cancel_check=cancel_check)

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
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            # Current Docker Desktop per-user install location.
            candidates.append(
                os.path.join(
                    local_appdata,
                    "Programs", "DockerDesktop", "Docker Desktop.exe",
                )
            )
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            # Retain the older candidate for machines installed by previous
            # Docker Desktop releases/custom packaging.
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

    # ── Docker Desktop 종료 (우리가 켠 경우에만) ──────────────────
    # 우리가 켜지 않은 Docker 는 사용자의 것이다. 창을 닫았다고 남의 데몬을
    # 내리면 사용자의 다른 컨테이너까지 함께 죽는다. 그래서 "이 프로세스가
    # 실제로 시작시켰는가" 를 기억해 두고, 그 경우에만 되돌린다.
    _started_by_us = False
    _shutdown_registered = False

    #: 우리 제품이 만드는 컨테이너 이름 접두사. 이 밖의 컨테이너가 돌고 있으면
    #: Docker 를 내리지 않는다 — 사용자의 작업을 끊는 일이기 때문이다.
    OWN_CONTAINER_PREFIXES = ("llm_", "ai_box_")

    @staticmethod
    def own_container_names() -> tuple:
        """config 가 이름을 바꿔 둘 수 있으므로 실제 값도 함께 우리 것으로 본다."""
        names = []
        for key in ("SEARXNG_CONTAINER", "TOR_CONTAINER", "WARP_CONTAINER",
                    "HTTP_BRIDGE_CONTAINER", "ANYTHINGLLM_CONTAINER"):
            value = str(getattr(config, key, "") or "").strip()
            if value:
                names.append(value)
        return tuple(names)

    @staticmethod
    def is_own_container(name: str) -> bool:
        text = str(name or "")
        prefixes = tuple(DockerService.OWN_CONTAINER_PREFIXES)
        prefix = str(getattr(config, "SANDBOX_CONTAINER_PREFIX", "") or "").strip()
        if prefix:
            prefixes = prefixes + (prefix,)
        return text.startswith(prefixes) or text in DockerService.own_container_names()

    @staticmethod
    def keep_desktop_running() -> bool:
        value = os.environ.get("LOCAL_AI_KEEP_DOCKER", "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def foreign_containers() -> Optional[list]:
        """우리 것이 아닌 실행 중 컨테이너 목록. ``None`` 이면 확인 실패."""
        result = DockerService.run(
            ["ps", "--format", "{{.Names}}"],
            timeout=config.DOCKER_PROBE_TIMEOUT,
        )
        if result is None or result.returncode != 0:
            return None
        return [name for name in (result.stdout or "").split()
                if not DockerService.is_own_container(name)]

    @staticmethod
    def shutdown_desktop(logger=None) -> bool:
        """``Docker Desktop.exe -Shutdown`` 으로 데몬을 정상 종료한다."""
        if os.name != "nt":
            return False
        exe = DockerService.find_desktop_executable()
        if not exe:
            return False
        try:
            subprocess.Popen(
                [exe, "-Shutdown"],
                creationflags=config.WIN_CREATE_NO_WINDOW,
                close_fds=True,
            )
        except (OSError, FileNotFoundError) as exc:
            if logger:
                logger.warn("Docker Desktop 종료 요청 실패: " + str(exc))
            return False
        if logger:
            logger.info("Docker Desktop 종료 요청됨 (이 창이 시작했습니다)")
        return True

    @staticmethod
    def stop_desktop_if_started(logger=None) -> bool:
        """이 프로세스가 켠 Docker Desktop 만 되돌린다."""
        if not DockerService._started_by_us:
            return True
        if DockerService.keep_desktop_running():
            return True
        if not DockerService.daemon_alive():
            DockerService._started_by_us = False
            return True
        remaining = DockerService.foreign_containers()
        if remaining is None:
            if logger:
                logger.warn("Docker 컨테이너 상태를 확인하지 못해 데몬을 그대로 둡니다.")
            return False
        if remaining:
            if logger:
                logger.info("다른 컨테이너가 실행 중이라 Docker Desktop 을 유지합니다: "
                            + ", ".join(remaining[:5]))
            return False
        ok = DockerService.shutdown_desktop(logger=logger)
        if ok:
            DockerService._started_by_us = False
        return ok

    @staticmethod
    def _register_desktop_shutdown() -> None:
        if DockerService._shutdown_registered:
            return
        try:
            from ..core import lifelog
        except Exception:
            try:
                from launcher.core import lifelog  # type: ignore
            except Exception:
                return

        def _do() -> None:
            try:
                lifelog.log("CLEANUP", "Docker Desktop 정리 (이 창이 시작했습니다)")
            except Exception:
                pass
            try:
                DockerService.stop_desktop_if_started()
            except Exception:
                pass

        try:
            # 컨테이너를 멈추는 정리들이 모두 끝난 뒤에 데몬을 내려야 한다.
            lifelog.register_cleanup(_do, stage="daemon")
        except Exception:
            return
        DockerService._shutdown_registered = True

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
            DockerService._started_by_us = True
            DockerService._register_desktop_shutdown()
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
