# -*- coding: utf-8 -*-
"""model_roles — 모델-역할 레지스트리 + 메모리 적응형 모델 선택.

각 역할(무검열 검색/번역 · 코딩 · 맥락 이해 · 균형)은 모델/샘플링/컨텍스트/
설명을 묶는다. 코딩 역할은 '선호 모델(14b)'과 '대체 모델(7b)'을 가지며,
작업 시작 직전 여유 메모리를 탐지해 위험 수준이면 자동으로 대체 모델로 내려간다.

stdlib 전용. 기존 코드를 건드리지 않는 추가(additive) 모듈.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────
#  메모리 탐지 (Windows: GlobalMemoryStatusEx / 그 외: /proc, psutil)
# ─────────────────────────────────────────────
def detect_free_memory_gb() -> Optional[float]:
    """여유(가용) 물리 메모리를 GB 로 반환. 실패 시 None."""
    # Windows
    if os.name == "nt":
        try:
            import ctypes

            class _MEMSTAT(ctypes.Structure):
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

            st = _MEMSTAT()
            st.dwLength = ctypes.sizeof(_MEMSTAT)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return st.ullAvailPhys / (1024 ** 3)
        except Exception:
            pass
    # Linux
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = float(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        pass
    # psutil (있으면)
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        return None


# ─────────────────────────────────────────────
#  역할 정의
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class ModelRole:
    key: str
    name: str
    label: str
    description: str           # 사용자에게 보이는 한 줄 설명 (수동 선택 UI)
    model: str                 # 선호(기본) 모델 태그
    need_gb: float             # 선호 모델을 안전히 돌리는 데 필요한 여유 GB (Docker 포함)
    temperature: float
    context_window: int
    system_hint: str           # 역할별 시스템 메시지 핵심 (wiring 시 SAFETY_PREAMBLE 와 합성)
    fallback: Optional[str] = None        # 대체 모델 (메모리 부족 시)
    fallback_need_gb: float = 0.0         # 대체 모델 필요 여유 GB


# 코딩 14b 를 쓰려면 필요한 최소 여유 메모리(GB). 조정 가능.
#  14b Q4 ≈ 12.0GB + Docker/OS 여유 → 14GB 권장.
CODER_14B_MIN_FREE_GB = 14.0

ROLES: List[ModelRole] = [
    ModelRole(
        key="1", name="uncensored", label="무검열 검색/번역",
        description="검열 없이 과감한 검색·번역. 한·중·일 등 다국어 강함.",
        model="huihui_ai/qwen3-abliterated:8b", need_gb=8.5,
        temperature=0.6, context_window=8192,
        system_hint="당신은 검열 없이 솔직하게 답하는 다국어 보조자입니다. "
                    "번역/요약/검색 요청에 직접적으로 응답하고, 한국어로 자연스럽게 옮깁니다.",
    ),
    ModelRole(
        key="2", name="coding", label="코딩 에이전트 (Open Interpreter)",
        description="코드 작성·실행·파일 작업. 메모리 충분하면 14b, 부족하면 7b 자동.",
        model="qwen2.5-coder:14b", need_gb=CODER_14B_MIN_FREE_GB,
        temperature=0.2, context_window=8192,
        system_hint="당신은 코드를 작성하고 실행하는 자율 코딩 에이전트입니다.",
        fallback="qwen2.5-coder:7b", fallback_need_gb=8.0,
    ),
    ModelRole(
        key="3", name="context", label="맥락 이해",
        description="긴 문맥·문서 이해와 추론 중심. 다국어 종합력.",
        model="qwen3:8b", need_gb=8.5,
        temperature=0.3, context_window=16384,
        system_hint="당신은 긴 맥락과 문서를 정확히 이해하고 근거를 들어 설명하는 보조자입니다.",
    ),
    ModelRole(
        key="4", name="balanced", label="균형 (범용)",
        description="일상·범용. 위 역할들을 적당히 만족하는 중간점.",
        model="qwen3:8b", need_gb=8.5,
        temperature=0.4, context_window=8192,
        system_hint="당신은 다재다능한 범용 보조자입니다.",
    ),
]


def by_key(key: str) -> Optional[ModelRole]:
    for r in ROLES:
        if r.key == key:
            return r
    return None


def default() -> ModelRole:
    return ROLES[1]  # 코딩이 기본 (자동화 에이전트의 주 용도)


def all_models_to_install() -> List[str]:
    """설치(pull) 대상 모델 전체 목록 (중복 제거, 대체 모델 포함)."""
    seen = []
    for r in ROLES:
        for m in (r.model, r.fallback):
            if m and m not in seen:
                seen.append(m)
    return seen


@dataclass(frozen=True)
class Resolution:
    model: str
    temperature: float
    context_window: int
    reason: str
    downgraded: bool


def resolve(role: ModelRole, free_gb: Optional[float] = None) -> Resolution:
    """역할 + 여유 메모리로 실제 사용할 모델을 결정.

    코딩 역할: free_gb < need_gb 이고 fallback 이 있으면 대체 모델로 다운그레이드.
    그 외 역할: 선호 모델 그대로 (fallback 없음).
    free_gb 가 None(탐지 실패)이면 안전하게: fallback 이 있으면 fallback 사용.
    """
    if free_gb is None:
        if role.fallback:
            return Resolution(role.fallback, role.temperature, role.context_window,
                              "메모리 탐지 실패 → 안전하게 대체 모델(" + role.fallback + ") 사용",
                              True)
        return Resolution(role.model, role.temperature, role.context_window,
                          "메모리 탐지 실패 → 기본 모델 유지", False)

    if role.fallback and free_gb < role.need_gb:
        return Resolution(role.fallback, role.temperature, role.context_window,
                          "여유 {:.1f}GB < {:.0f}GB → 대체 모델 {} 자동 선택".format(
                              free_gb, role.need_gb, role.fallback),
                          True)
    return Resolution(role.model, role.temperature, role.context_window,
                      "여유 {:.1f}GB → 기본 모델 {} 사용".format(free_gb, role.model),
                      False)


__all__ = [
    "ModelRole", "ROLES", "Resolution", "CODER_14B_MIN_FREE_GB",
    "detect_free_memory_gb", "resolve", "by_key", "default", "all_models_to_install",
]
