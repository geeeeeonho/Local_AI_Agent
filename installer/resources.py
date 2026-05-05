"""resources — 시스템 자원 감지 + 안전한 설치 파라미터 자동 산출.

설계:
  - psutil 같은 외부 의존성 없이 stdlib + ctypes 만으로 구현
  - 감지된 시스템 사양에 따라 pip / Docker / 모델 로드의 자원 한도를 자동 조정
  - 사용자에게 묻지 않고 자동으로 안전한 값 선택 (개입 최소화)
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────────
#  자료구조
# ──────────────────────────────────────────────────────────────

@dataclass
class SystemSpec:
    """감지된 시스템 사양."""
    total_ram_gb: float
    available_ram_gb: float
    cpu_count: int
    is_ssd: Optional[bool]   # None = 감지 불가
    free_disk_gb: float
    vram_gb: Optional[float]  # None = GPU 감지 불가

    def __str__(self):
        ssd = "SSD" if self.is_ssd else ("HDD" if self.is_ssd is False else "?")
        vram = f"{self.vram_gb:.0f}GB" if self.vram_gb else "?"
        return (
            f"RAM {self.total_ram_gb:.1f}GB ({self.available_ram_gb:.1f}GB free) | "
            f"CPU {self.cpu_count} | "
            f"VRAM {vram} | Disk {self.free_disk_gb:.0f}GB free, {ssd}"
        )


@dataclass
class SafetyProfile:
    """자동 산출된 안전 설치 파라미터."""
    pip_jobs: int                # pip 빌드 병렬도 (1=순차, 0=자동)
    docker_build_memory: str     # 예 "4g"
    docker_build_cpus: str       # 예 "2"
    container_memory: str        # 컨테이너 실행 시 메모리
    container_cpus: str          # 컨테이너 실행 시 CPU
    warnings: list               # 사용자에게 표시할 경고 메시지
    can_run_full: bool           # False 면 일부 설치 자동 건너뜀

    def __str__(self):
        return (
            f"pip jobs={self.pip_jobs}, "
            f"docker build={self.docker_build_memory}/{self.docker_build_cpus}, "
            f"container={self.container_memory}/{self.container_cpus}"
        )


# ──────────────────────────────────────────────────────────────
#  RAM
# ──────────────────────────────────────────────────────────────

def _get_ram_gb() -> tuple[float, float]:
    """(total_gb, available_gb) 반환. 실패 시 (0, 0)."""
    if os.name == "nt":
        # MEMORYSTATUSEX 구조체로 정확한 값
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
            total = stat.ullTotalPhys / (1024 ** 3)
            avail = stat.ullAvailPhys / (1024 ** 3)
            return (total, avail)
        except Exception:
            return (0.0, 0.0)
    else:
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])  # kB
            total = mem.get("MemTotal", 0) / (1024 ** 2)
            avail = mem.get("MemAvailable", mem.get("MemFree", 0)) / (1024 ** 2)
            return (total, avail)
        except Exception:
            return (0.0, 0.0)


# ──────────────────────────────────────────────────────────────
#  GPU / VRAM (NVIDIA만 지원, 그 외는 None)
# ──────────────────────────────────────────────────────────────

def _get_vram_gb() -> Optional[float]:
    """nvidia-smi 로 VRAM 감지. NVIDIA 미설치/AMD/intel 은 None."""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return None

    try:
        r = subprocess.run(
            [nvsmi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        # 첫 GPU 의 메모리(MiB)
        line = r.stdout.strip().splitlines()[0]
        mib = int(line.strip())
        return mib / 1024  # GB
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
#  디스크 종류 (SSD vs HDD)
# ──────────────────────────────────────────────────────────────

def _is_ssd(path: Path) -> Optional[bool]:
    """경로의 드라이브가 SSD 인지. 감지 실패 시 None."""
    if os.name != "nt":
        return None
    try:
        # PowerShell 로 MediaType 조회 — 실패하면 None
        drive_letter = str(path.resolve())[0]
        cmd = (
            f"Get-PhysicalDisk | "
            f"Where-Object {{$_.MediaType -ne 'Unspecified'}} | "
            f"Select-Object -First 1 -ExpandProperty MediaType"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip().upper()
        if "SSD" in out:
            return True
        if "HDD" in out:
            return False
        return None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
#  메인 API
# ──────────────────────────────────────────────────────────────

def detect(install_path: Path) -> SystemSpec:
    """현재 시스템 사양 감지."""
    total_ram, avail_ram = _get_ram_gb()
    try:
        free_disk = shutil.disk_usage(
            install_path if install_path.exists() else install_path.parent
        ).free / (1024 ** 3)
    except Exception:
        free_disk = 0.0

    return SystemSpec(
        total_ram_gb=total_ram,
        available_ram_gb=avail_ram,
        cpu_count=os.cpu_count() or 2,
        is_ssd=_is_ssd(install_path),
        free_disk_gb=free_disk,
        vram_gb=_get_vram_gb(),
    )


def compute_safety_profile(spec: SystemSpec) -> SafetyProfile:
    """시스템 사양에 따라 안전 파라미터 자동 산출.

    저사양 PC 일수록 보수적으로 (병렬 ↓, 메모리 ↓).
    """
    warnings = []
    can_run_full = True

    # ─── pip 빌드 병렬도 ───
    # RAM 8GB 미만: 1 (순차) — 빌드 OOM 방지
    # RAM 8~16GB: 2
    # RAM 16GB 이상: CPU 절반 (최대 4)
    if spec.total_ram_gb < 8:
        pip_jobs = 1
        warnings.append(
            f"RAM {spec.total_ram_gb:.1f}GB 감지 — pip 빌드를 단일 워커로 진행 "
            "(시간 ↑ 안정성 ↑)"
        )
    elif spec.total_ram_gb < 16:
        pip_jobs = 2
    else:
        pip_jobs = min(4, max(2, (spec.cpu_count or 2) // 2))

    # ─── Docker 빌드 자원 ───
    # 빌드는 단발성이라 가용 메모리의 절반 정도까지 허용
    # 단 컨테이너 실행 시엔 좀 더 보수적
    if spec.total_ram_gb >= 16:
        build_mem = "4g"
        build_cpus = "2"
        run_mem = "4g"
        run_cpus = "2"
    elif spec.total_ram_gb >= 8:
        build_mem = "2g"
        build_cpus = "2"
        run_mem = "2g"
        run_cpus = "2"
    else:
        # RAM 부족: Docker 빌드는 안 시도 (warnings 에서 안내)
        build_mem = "1g"
        build_cpus = "1"
        run_mem = "1g"
        run_cpus = "1"
        warnings.append(
            "RAM 8GB 미만 — Docker 작업이 매우 느리거나 실패할 수 있음"
        )

    # ─── VRAM 부족 경고 ───
    if spec.vram_gb is None:
        warnings.append(
            "NVIDIA GPU 미감지 — Ollama 가 CPU 추론으로 동작 (매우 느림)"
        )
    elif spec.vram_gb < 14:
        warnings.append(
            f"VRAM {spec.vram_gb:.1f}GB 감지 — Q3_K_M 모델(~14GB)이 일부 RAM 으로 "
            "넘어갈 수 있음. 첫 응답이 느릴 수 있습니다"
        )

    # ─── 디스크 종류 ───
    if spec.is_ssd is False:
        warnings.append(
            "HDD 감지 — 모델 로드/실행이 SSD 대비 5~10배 느립니다"
        )

    # ─── 가용 RAM 위험 수준 ───
    if spec.available_ram_gb < 2:
        warnings.append(
            f"가용 RAM {spec.available_ram_gb:.1f}GB — 다른 무거운 앱을 닫고 "
            "설치를 진행하세요"
        )
        # 자동 진행 가능하지만 경고
    if spec.total_ram_gb < 4 and spec.total_ram_gb > 0:
        warnings.append(
            "RAM 4GB 미만 — 설치가 실패할 가능성이 높습니다"
        )
        can_run_full = False

    return SafetyProfile(
        pip_jobs=pip_jobs,
        docker_build_memory=build_mem,
        docker_build_cpus=build_cpus,
        container_memory=run_mem,
        container_cpus=run_cpus,
        warnings=warnings,
        can_run_full=can_run_full,
    )


def env_for_pip(profile: SafetyProfile) -> dict:
    """pip 빌드 시 사용할 환경변수.

    MAKEFLAGS / CMAKE_BUILD_PARALLEL_LEVEL 로 병렬도 제한.
    이걸로 메모리 폭주 거의 다 막힘.
    """
    env = os.environ.copy()
    jobs = str(profile.pip_jobs)
    env["MAKEFLAGS"] = f"-j{jobs}"
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = jobs
    env["MAX_JOBS"] = jobs                           # PyTorch 등에서 사용
    env["NPY_NUM_BUILD_JOBS"] = jobs                 # numpy
    env["PIP_NO_CACHE_DIR"] = "1"                    # 디스크 압박 줄이기
    return env
