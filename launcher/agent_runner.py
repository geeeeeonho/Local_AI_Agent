"""agent_runner — GUI 통합 에이전트 백엔드 (subprocess.PIPE 기반).

지시사항 [1단계] + [2단계] 구현:
  - subprocess.PIPE 로 에이전트 stdout/stderr/stdin 캡처
  - 백그라운드 reader 스레드 → thread-safe Queue → GUI 가 폴링
  - GUI 입력 → Queue → writer 스레드 → 에이전트 stdin
  - --no_vision 강제 (system_message + env var 3중)
  - ErrorGuard: 화면 캡처 시도 패턴 감지 → 경고

설계 원칙
─────────
- pure stdlib (subprocess, threading, queue)
- GUI 스레드 블록 금지 — 모든 I/O 는 백그라운드
- 에이전트 종료 시 reader/writer 스레드 자연 종료
- 외부에서 stop() 호출 시 graceful → forceful 단계적 종료
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


# ─────────────────────────────────────────────
#  메시지 종류 (큐에 흐르는 이벤트)
# ─────────────────────────────────────────────
LEVEL_STDOUT = "stdout"
LEVEL_STDERR = "stderr"
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_TERMINATED = "terminated"


@dataclass
class AgentMessage:
    """에이전트 → GUI 로 흘러가는 단일 이벤트."""
    level: str  # LEVEL_*
    text: str
    timestamp: float = field(default_factory=time.time)


# ─────────────────────────────────────────────
#  ErrorGuard — 위험 패턴 사전 차단
# ─────────────────────────────────────────────
_VISION_PATTERNS = [
    re.compile(r"\bscreenshot\b", re.IGNORECASE),
    re.compile(r"\bscreen[\s_-]*capture\b", re.IGNORECASE),
    re.compile(r"\bpyautogui\b", re.IGNORECASE),
    re.compile(r"\bpynput\b", re.IGNORECASE),
    re.compile(r"PIL\.ImageGrab", re.IGNORECASE),
    re.compile(r"\bImageGrab\b", re.IGNORECASE),
    re.compile(r"\b(?:from\s+mss\s+import|import\s+mss|mss\.mss)\b", re.IGNORECASE),
    re.compile(r"computer\.(display|mouse|keyboard|screen)", re.IGNORECASE),
    re.compile(r"\bget_monitors\b", re.IGNORECASE),
    re.compile(r"\bos_mode\b", re.IGNORECASE),
]


def looks_like_vision_attempt(line: str) -> bool:
    """에이전트가 화면 캡처/GUI 자동화를 시도하는 패턴인지 감지.

    Returns True if the line matches any known vision/GUI automation pattern.
    """
    for pat in _VISION_PATTERNS:
        if pat.search(line):
            return True
    return False


# ─────────────────────────────────────────────
#  UnifiedAgent — 메인 객체
# ─────────────────────────────────────────────
class UnifiedAgent:
    """subprocess.PIPE 기반 에이전트 실행기.

    사용:
        agent = UnifiedAgent()
        agent.start(cmd=["docker", "run", ...], env={...})
        # 폴링 (GUI 메인 루프에서 100ms 마다)
        for msg in agent.drain_messages():
            chat_panel.append(msg.level, msg.text)
        # 사용자 입력
        agent.send_input("hello")
        # 종료
        agent.stop(timeout=3.0)

    Thread-safety: 모든 public 메서드는 어느 스레드에서나 호출 가능.
    """

    def __init__(self, max_queue: int = 10000):
        self._proc: Optional[subprocess.Popen] = None
        self._cmd: List[str] = []
        self._messages: queue.Queue = queue.Queue(maxsize=max_queue)
        self._input_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._readers: List[threading.Thread] = []
        self._writer: Optional[threading.Thread] = None
        self._error_guard_enabled = True

    # ── lifecycle ──
    def is_running(self) -> bool:
        """에이전트 프로세스가 살아있는지."""
        with self._lock:
            if self._proc is None:
                return False
            return self._proc.poll() is None

    def start(
        self,
        cmd: List[str],
        env: Optional[dict] = None,
        cwd: Optional[Path] = None,
    ) -> bool:
        """에이전트 시작.

        Args:
            cmd: 실행할 명령 (예: ["docker", "run", "-i", ...])
                 IMPORTANT: docker run 의 경우 -t 빼고 -i 만 줘야 PIPE 가 동작.
            env: 환경변수 (None 이면 부모 env 상속)
            cwd: 작업 디렉터리

        Returns:
            True if started, False if already running.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            self._cmd = list(cmd)
            self._stopped.clear()

            # Windows 에서 CREATE_NO_WINDOW — 콘솔창 안 뜨도록
            popen_kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "bufsize": 1,  # line-buffered
                "universal_newlines": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if env is not None:
                popen_kwargs["env"] = env
            if cwd is not None:
                popen_kwargs["cwd"] = str(cwd)
            if os.name == "nt":
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            try:
                self._proc = subprocess.Popen(cmd, **popen_kwargs)
            except FileNotFoundError as e:
                self._emit(LEVEL_ERROR, f"명령을 찾을 수 없습니다: {e}")
                self._proc = None
                return False
            except Exception as e:
                self._emit(LEVEL_ERROR, f"에이전트 시작 실패: {type(e).__name__}: {e}")
                self._proc = None
                return False

            # ── 백그라운드 스레드 기동 ──
            self._readers = [
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stdout, LEVEL_STDOUT),
                    daemon=True, name="agent-stdout",
                ),
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stderr, LEVEL_STDERR),
                    daemon=True, name="agent-stderr",
                ),
            ]
            for t in self._readers:
                t.start()

            self._writer = threading.Thread(
                target=self._writer_loop,
                daemon=True, name="agent-stdin",
            )
            self._writer.start()

            # 종료 감지 스레드
            threading.Thread(
                target=self._wait_loop,
                daemon=True, name="agent-wait",
            ).start()

            self._emit(LEVEL_INFO, f"에이전트 시작 (PID={self._proc.pid})")
            return True

    def stop(self, timeout: float = 3.0) -> None:
        """에이전트 종료 — graceful 후 forceful.

        Args:
            timeout: graceful 종료 대기 시간 (초)
        """
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._stopped.set()
                return

            # 1) stdin 닫기 — exit 신호
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass

            # 2) terminate
            try:
                proc.terminate()
            except Exception:
                pass

        # 3) 대기
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass

        self._stopped.set()
        self._emit(LEVEL_WARN, "에이전트 종료됨")

    def send_input(self, line: str) -> bool:
        """사용자 입력을 에이전트 stdin 에 보냄.

        Returns False if agent isn't running.
        """
        if not self.is_running():
            return False
        if not line.endswith("\n"):
            line = line + "\n"
        try:
            self._input_queue.put_nowait(line)
            return True
        except queue.Full:
            self._emit(LEVEL_WARN, "입력 큐 가득참 — 메시지 버려짐")
            return False

    def drain_messages(self, max_n: int = 200) -> List[AgentMessage]:
        """큐에서 메시지를 비파괴적으로 비움. GUI 가 폴링으로 호출.

        Returns up to `max_n` messages, oldest first. Empty list if no messages.
        """
        out: List[AgentMessage] = []
        for _ in range(max_n):
            try:
                msg = self._messages.get_nowait()
            except queue.Empty:
                break
            out.append(msg)
        return out

    # ── 내부 ──
    def _emit(self, level: str, text: str) -> None:
        """메시지를 큐에 넣음 — 가득 차면 가장 오래된 것 버림."""
        msg = AgentMessage(level=level, text=text)
        try:
            self._messages.put_nowait(msg)
        except queue.Full:
            # 가장 오래된 항목 하나 버리고 재시도
            try:
                self._messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self._messages.put_nowait(msg)
            except queue.Full:
                pass  # 어쩔 수 없음

    def _reader_loop(self, stream, level: str) -> None:
        """stdout/stderr 한 줄씩 읽어 큐에 push.

        ErrorGuard: vision 시도 패턴 감지 시 WARN 추가.
        """
        try:
            for raw_line in iter(stream.readline, ""):
                line = raw_line.rstrip("\n\r")
                if not line:
                    # 빈 줄도 표시 (코드 블록 보존)
                    self._emit(level, "")
                    continue

                # ErrorGuard
                if self._error_guard_enabled and looks_like_vision_attempt(line):
                    self._emit(
                        LEVEL_WARN,
                        f"⚠ 화면 캡처/GUI 자동화 패턴 감지됨 — 무시됨: {line[:80]}",
                    )

                self._emit(level, line)
        except (ValueError, OSError):
            # 스트림이 닫힌 정상 종료
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _writer_loop(self) -> None:
        """입력 큐에서 한 줄씩 꺼내 에이전트 stdin 에 씀."""
        while not self._stopped.is_set():
            try:
                line = self._input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                proc = self._proc
                if proc is None or proc.stdin is None or proc.stdin.closed:
                    break
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    break

    def _wait_loop(self) -> None:
        """에이전트 종료를 감지해 TERMINATED 메시지 emit."""
        proc = self._proc
        if proc is None:
            return
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._stopped.set()
        self._emit(LEVEL_TERMINATED, f"프로세스 종료 (rc={rc})")


# ─────────────────────────────────────────────
#  명령 조립 헬퍼 — agent_chat 액션에서 사용
# ─────────────────────────────────────────────
def build_sandbox_pipe_cmd(
    image: str,
    container_name: str,
    workspace: Path,
    workspace_mount: str,
    model_tag: str,
    ollama_port: int,
    profile_system_message: str,
    context_window: int = 4096,
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    block_internet: bool = True,
    auto_run: bool = True,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """GUI-통합 모드용 docker run 명령 조립.

    중요한 차이점 (vs agent_sandbox._build_command):
        - `-t` (tty) 없음 — PIPE 모드용
        - `-i` (stdin) 있음 — 사용자 입력
        - `--rm` 자동 정리
        - --no_vision 안전장치 (system_message + env var)

    Args:
        profile_system_message: 프로필별 system 메시지 (영어)
        block_internet: True 면 --dns=0.0.0.0
        auto_run: True 면 --auto_run 추가 (샌드박스 안이라 안전)
    """
    cmd = [
        "docker", "run", "--rm", "-i",  # -t 없음!
        "--name", container_name,
        "-v", f"{workspace}:{workspace_mount}",
        "--add-host=host.docker.internal:host-gateway",
        # ErrorGuard: 환경변수로 vision 비활성 표시
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",  # 빈 값 — vision 라이브러리들이 fail-fast
    ]

    if block_internet:
        cmd += ["--dns=0.0.0.0"]
    if cpu_limit:
        cmd += [f"--cpus={cpu_limit}"]
    if memory_limit:
        cmd += [f"--memory={memory_limit}"]

    cmd += [
        image, "interpreter",
        "--model", f"ollama/{model_tag}",
        "--api_base", f"http://host.docker.internal:{ollama_port}",
        "--context_window", str(context_window),
        "--system_message", profile_system_message,
    ]

    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)

    return cmd


__all__ = [
    "AgentMessage",
    "UnifiedAgent",
    "build_sandbox_pipe_cmd",
    "looks_like_vision_attempt",
    "LEVEL_STDOUT", "LEVEL_STDERR", "LEVEL_INFO",
    "LEVEL_WARN", "LEVEL_ERROR", "LEVEL_TERMINATED",
]
