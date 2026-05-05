"""runtime_guard — 사용 중 자동 자원 조절 및 보호.

설계:
  1. 사전 조정 (compute_runtime_params)
     - 가용 RAM 보고 컨텍스트 윈도우 자동 산출
     - Ollama 환경변수(KEEP_ALIVE, NUM_PARALLEL 등) 자동 설정

  2. 백그라운드 감시 (ResourceWatchdog)
     - 1초마다 RAM/CPU/디스크 체크
     - 위험 임계치 지속 시 콜백 트리거 (자동 정지)
     - 일시 스파이크는 무시 (지속 감지 윈도우 사용)

  3. 출력 최소화
     - 정상 동작 중엔 메시지 없음
     - 자동 정지 발동 시에만 한 줄 출력
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional


# ──────────────────────────────────────────────────────────────
#  임계치 (적당히 보수적으로)
# ──────────────────────────────────────────────────────────────

# 가용 RAM 절대 임계치 (GB) — 이 아래로 떨어지면 위험
RAM_DANGER_GB = 0.8       # 가용 RAM 800MB 미만
RAM_CRITICAL_GB = 0.4     # 즉시 정지 트리거

# 위험 상태 지속 시간 (초) — 이만큼 지속돼야 자동 정지
DANGER_PERSIST_SEC = 10   # 일시 스파이크 무시

# 디스크 여유 (GB)
DISK_DANGER_GB = 1.0

# 폴링 주기
POLL_INTERVAL_SEC = 1.0


# ──────────────────────────────────────────────────────────────
#  RAM 측정 (resources.py와 동일 로직 — 의존성 회피용 복제)
# ──────────────────────────────────────────────────────────────

def _get_available_ram_gb() -> float:
    """가용 RAM (GB). 실패 시 -1."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / (1024 ** 3)
        except Exception:
            return -1.0
    else:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) / (1024 ** 2)
        except Exception:
            return -1.0


def _get_total_ram_gb() -> float:
    """전체 RAM (GB)."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            return -1.0
    else:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / (1024 ** 2)
        except Exception:
            return -1.0


def _get_free_disk_gb(path: Path) -> float:
    """경로의 여유 디스크 (GB)."""
    try:
        target = path if path.exists() else path.parent
        return shutil.disk_usage(target).free / (1024 ** 3)
    except Exception:
        return -1.0


# ══════════════════════════════════════════════════════════════
#  1. 사전 조정 — 도구 시작 직전 호출
# ══════════════════════════════════════════════════════════════

@dataclass
class RuntimeParams:
    """도구 실행 시 적용할 동적 파라미터."""
    context_window: int           # 토큰 단위
    ollama_keep_alive: str        # 모델 메모리 유지 시간
    ollama_num_parallel: int      # 동시 요청 처리 수
    ollama_max_loaded: int        # 동시 로드 모델 수


def compute_runtime_params() -> RuntimeParams:
    """현재 시스템 상태 보고 안전한 런타임 파라미터 산출.

    조용히 자동 조정 — 사용자에게 메시지 없음.

    컨텍스트 윈도우 동적 조정:
      - 32K: 일반 (~2GB 추가 RAM 필요)
      - 16K: 가용 RAM 부족 시
      - 8K:  더 부족할 때
      - 4K:  최소
    """
    avail = _get_available_ram_gb()
    total = _get_total_ram_gb()

    # 컨텍스트 크기 결정 (가용 RAM 기준, 모델 14GB 이미 로드됐다고 가정)
    if avail < 0 or total < 0:
        # 측정 실패: 보수적 기본값
        context = 8192
    elif avail >= 6.0 and total >= 16:
        context = 32768
    elif avail >= 4.0:
        context = 16384
    elif avail >= 2.0:
        context = 8192
    else:
        context = 4096

    # Ollama 동작 조정
    # 가용 RAM 적으면 모델을 더 빨리 언로드 (기본 5분 → 1분)
    if avail < 2.0:
        keep_alive = "1m"
        max_loaded = 1
        num_parallel = 1
    elif avail < 4.0:
        keep_alive = "3m"
        max_loaded = 1
        num_parallel = 1
    else:
        keep_alive = "5m"     # Ollama 기본값
        max_loaded = 1        # 14GB 모델 동시 2개는 무리
        num_parallel = 2

    return RuntimeParams(
        context_window=context,
        ollama_keep_alive=keep_alive,
        ollama_num_parallel=num_parallel,
        ollama_max_loaded=max_loaded,
    )


def apply_to_env(params: RuntimeParams, env: Dict[str, str]) -> Dict[str, str]:
    """RuntimeParams를 환경변수 dict에 주입."""
    env["OLLAMA_KEEP_ALIVE"] = params.ollama_keep_alive
    env["OLLAMA_NUM_PARALLEL"] = str(params.ollama_num_parallel)
    env["OLLAMA_MAX_LOADED_MODELS"] = str(params.ollama_max_loaded)
    return env


# ══════════════════════════════════════════════════════════════
#  2. 백그라운드 감시 — 자동 정지 워치독
# ══════════════════════════════════════════════════════════════

class ResourceWatchdog:
    """백그라운드 스레드로 자원 감시.

    - 1초마다 가용 RAM 체크
    - 위험 임계치(RAM_DANGER_GB)에 도달하고 N초 지속되면
      stop_callback 호출 (예: 컨테이너 정지)
    - 더 위급(RAM_CRITICAL_GB)이면 즉시 정지

    조용히 동작 — 정상 시 출력 없음, 정지 시에만 한 줄.
    """

    def __init__(
        self,
        stop_callback: Callable[[str], None],
        log_func: Optional[Callable[[str], None]] = None,
        persist_sec: float = DANGER_PERSIST_SEC,
    ):
        """
        Args:
            stop_callback: 위험 시 호출. 인자는 사유 문자열.
            log_func: 정지 시 메시지 출력 (None 이면 print)
            persist_sec: 위험 상태가 이만큼 지속돼야 정지
        """
        self.stop_callback = stop_callback
        self.log = log_func or print
        self.persist_sec = persist_sec

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._danger_since: Optional[float] = None
        self._triggered = False

    def start(self):
        """감시 시작 (백그라운드 스레드)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._danger_since = None
        self._triggered = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """감시 종료. 워치독은 호출자가 명시적으로 끔."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception:
                # 감시 자체의 오류로 정상 동작을 망치지 않음
                pass
            self._stop_event.wait(POLL_INTERVAL_SEC)

    def _check_once(self):
        if self._triggered:
            return  # 이미 정지 트리거됨 — 중복 호출 방지

        avail = _get_available_ram_gb()
        if avail < 0:
            return  # 측정 실패 — 무시

        # 즉시 정지 (Critical)
        if avail < RAM_CRITICAL_GB:
            self._trigger(
                f"가용 RAM 위급 ({avail*1024:.0f}MB) — 자동 정지"
            )
            return

        # 위험 (Danger): 지속 시간 체크
        if avail < RAM_DANGER_GB:
            if self._danger_since is None:
                self._danger_since = time.time()
            else:
                elapsed = time.time() - self._danger_since
                if elapsed >= self.persist_sec:
                    self._trigger(
                        f"가용 RAM 부족 {avail*1024:.0f}MB가 "
                        f"{elapsed:.0f}초 지속 — 자동 정지"
                    )
                    return
        else:
            # 회복됨 — 카운터 리셋
            self._danger_since = None

    def _trigger(self, reason: str):
        if self._triggered:
            return
        self._triggered = True
        # 한 줄 출력 (사용자가 무슨 일인지 알도록)
        self.log(f"\n[안전 정지] {reason}\n")
        try:
            self.stop_callback(reason)
        except Exception as e:
            self.log(f"[오류] 정지 콜백 실행 실패: {e}")
