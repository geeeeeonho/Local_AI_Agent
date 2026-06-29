# -*- coding: utf-8 -*-
"""model_roles — 모델-역할 레지스트리 + 메모리 적응형 모델 선택.

MODEL_GEMMA_v9 — Gemma 4 26B-A4B ARA abliterated 중심 (다운로드 카탈로그 v3 정합).
각 역할은 모델/샘플링/컨텍스트/설명을 묶고, 사이즈 다단계 롤백 사다리(LADDERS)와
실적재 probe 기반 자동 강등(resolve_with_rollback)을 제공한다.
stdlib 전용. 기존 인터페이스(resolve / by_key / default / Resolution / ModelRole /
detect_free_memory_gb / LADDERS / resolve_ladder / resolve_with_rollback) 보존.
"""
from __future__ import annotations

import json as _json
import os
import urllib.request as _urlreq
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────
#  메모리 탐지 (Windows: GlobalMemoryStatusEx / 그 외: /proc, psutil)
# ─────────────────────────────────────────────
def detect_free_memory_gb() -> Optional[float]:
    """여유(가용) 물리 메모리를 GB 로 반환. 실패 시 None."""
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
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = float(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        pass
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
    description: str
    model: str
    need_gb: float
    temperature: float
    context_window: int
    system_hint: str
    fallback: Optional[str] = None
    fallback_need_gb: float = 0.0


# 하위호환 상수 (외부 참조 가능성 대비)
CODER_14B_MIN_FREE_GB = 14.0

# 핵심 모델 태그 (v3 카탈로그와 동일)
_ARA = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"   # 무검열·범용·에이전트 (15GB)
_CODER = "qwen3-coder:30b"                                    # 코딩 (18GB, MoE)
_GEMMA12 = "gemma4:12b"                                       # 맥락/폴백 (7.5GB)
_CODER_FB = "qwen2.5-coder:7b"                                # 코딩 폴백 (4.7GB)
_UNC_FB = "huihui_ai/qwen3-abliterated:8b"                    # 무검열 폴백 (5GB)

ROLES: List[ModelRole] = [
    ModelRole(
        key="1", name="uncensored", label="무검열 검색/번역",
        description="검열 없이 과감한 검색·번역·범용. Gemma 4 26B-A4B ARA(멀티모달·256K). 부족하면 8b.",
        model=_ARA, need_gb=15.5,
        temperature=0.6, context_window=8192,
        system_hint="당신은 검열 없이 솔직하게 답하는 다국어 보조자입니다. "
                    "번역/요약/검색 요청에 직접적으로 응답하고, 한국어로 자연스럽게 옮깁니다.",
        fallback=_UNC_FB, fallback_need_gb=8.0,
    ),
    ModelRole(
        key="2", name="coding", label="코딩 에이전트 (Open Interpreter)",
        description="코드 작성·실행·파일 작업. qwen3-coder:30b(MoE·256K), 부족하면 7b 자동.",
        model=_CODER, need_gb=17.0,
        temperature=0.2, context_window=8192,
        system_hint="당신은 코드를 작성하고 실행하는 자율 코딩 에이전트입니다.",
        fallback=_CODER_FB, fallback_need_gb=8.0,
    ),
    ModelRole(
        key="3", name="context", label="맥락 이해",
        description="긴 문맥·문서 이해와 추론. Gemma 4 12B(256K, 멀티모달).",
        model=_GEMMA12, need_gb=10.0,
        temperature=0.3, context_window=16384,
        system_hint="당신은 긴 맥락과 문서를 정확히 이해하고 근거를 들어 설명하는 보조자입니다.",
    ),
    ModelRole(
        key="4", name="balanced", label="균형 (범용)",
        description="일상·범용. Gemma 4 12B 공유.",
        model=_GEMMA12, need_gb=10.0,
        temperature=0.4, context_window=8192,
        system_hint="당신은 다재다능한 범용 보조자입니다.",
    ),
    ModelRole(
        key="5", name="agent", label="자동화 에이전트",
        description="도구 호출·자율 실행. Gemma 4 26B-A4B ARA(무검열·MoE 활성4B·툴). 부족하면 12B.",
        model=_ARA, need_gb=15.5,
        temperature=0.4, context_window=8192,
        system_hint="당신은 도구를 호출하고 작업을 실행하는 자율 에이전트입니다.",
        fallback=_GEMMA12, fallback_need_gb=10.0,
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
    seen: List[str] = []
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
    """역할 + 여유 메모리로 실제 사용할 모델 결정 (단일 폴백)."""
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


# >>> MODEL_ROLLBACK_v1 — 사이즈 다단계 롤백 (additive)
_SAFETY = 0.92  # 가용 메모리의 92%만 사용 (KV 캐시/순간 스파이크 대비)

# 역할별 후보 사다리: (모델, 권장 최소 여유 GB). 고품질 → 저압축 순.
LADDERS = {
    "agent": [(_ARA, 15.5), (_GEMMA12, 10.0)],
    "coding": [(_CODER, 17.0), (_CODER_FB, 8.0)],
    "uncensored": [(_ARA, 15.5), (_UNC_FB, 8.0)],
    "context": [(_GEMMA12, 10.0)],
    "balanced": [(_GEMMA12, 10.0)],
}


def ladder_for(role_name: str):
    return list(LADDERS.get(role_name, []))


def resolve_ladder(role_name: str, free_gb: Optional[float] = None):
    """여유 메모리에 맞는 최상위 후보 1차 선택. 사다리 없으면 None."""
    lad = LADDERS.get(role_name)
    if not lad:
        return None
    free = free_gb if free_gb is not None else detect_free_memory_gb()
    if free is None:
        return lad[-1][0]  # 탐지 실패 → 가장 안전한 최하위
    usable = free * _SAFETY
    for model, need in lad:
        if need <= usable:
            return model
    return lad[-1][0]


def _load_probe(model, host="127.0.0.1:11434", timeout=180):
    """짧은 요청으로 실제 적재 성공 여부 확인. OOM/실패/타임아웃이면 False."""
    body = _json.dumps({"model": model, "prompt": "hi", "stream": False,
                        "options": {"num_predict": 1}}).encode()
    req = _urlreq.Request("http://" + host + "/api/generate", data=body,
                          headers={"Content-Type": "application/json"})
    try:
        with _urlreq.urlopen(req, timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False


def resolve_with_rollback(role_name, free_gb=None, presenter=None, host="127.0.0.1:11434"):
    """1차 선택 후 적재 실패 시 사다리를 따라 자동 강등. 최종 모델 태그 반환."""
    lad = LADDERS.get(role_name)
    if not lad:
        return None
    seq = [m for m, _ in lad]
    model = resolve_ladder(role_name, free_gb) or seq[0]
    while True:
        if _load_probe(model, host=host):
            return model
        idx = seq.index(model) if model in seq else 0
        if idx + 1 >= len(seq):
            if presenter is not None:
                try:
                    presenter.warn(model + " 적재 실패 — 더 낮은 후보 없음")
                except Exception:
                    pass
            return model
        nxt = seq[idx + 1]
        if presenter is not None:
            try:
                presenter.warn(model + " 적재 실패 → " + nxt + " 롤백")
            except Exception:
                pass
        model = nxt


# >>> MODEL_INSTALLED_MATCH_v1 — 설치 모델 자동 매치 (additive)
def installed_models(host="127.0.0.1:11434", timeout=5):
    """Ollama /api/tags 로 설치된 모델 태그 집합 반환. 조회 실패 시 None."""
    try:
        req = _urlreq.Request("http://" + host + "/api/tags")
        with _urlreq.urlopen(req, timeout=timeout) as r:
            data = _json.loads(r.read().decode("utf-8"))
        out = set()
        for m in (data.get("models") or []):
            nm = m.get("name") or m.get("model")
            if nm:
                out.add(nm)
        return out
    except Exception:
        return None


def auto_match_installed(desired_tag, role_name=None, free_gb=None, host="127.0.0.1:11434"):
    """설치된 모델을 보고 실제 사용할 태그를 결정. 반환 (tag, note).

    desired_tag 가 설치돼 있으면 그대로. 아니면 역할 사다리 / 유사이름 / 임의 설치 순 폴백.
    설치된 모델이 전혀 없으면 tag=None. /api/tags 조회 실패면 desired_tag 그대로(기존 동작).
    """
    inst = installed_models(host)
    if inst is None:
        return desired_tag, None
    if desired_tag and desired_tag in inst:
        return desired_tag, None
    free = free_gb if free_gb is not None else detect_free_memory_gb()
    usable = (free * _SAFETY) if free is not None else None

    lad = LADDERS.get(role_name) if role_name else None
    if lad:
        for m, need in lad:
            if m in inst and (usable is None or need <= usable):
                return m, "선택 모델 미설치 → 설치된 " + m + " 자동 사용"
        for m, _n in lad:
            if m in inst:
                return m, "선택 모델 미설치 → 설치된 " + m + " 사용(메모리 빠듯)"

    allc = [(need, m) for _ln, _l in LADDERS.items() for m, need in _l if m in inst]
    fit = [(n, m) for n, m in allc if usable is None or n <= usable]
    pool = fit if fit else allc
    if pool:
        pool.sort(reverse=True)
        return pool[0][1], "역할 모델 미설치 → 설치된 " + pool[0][1] + " 자동 사용"

    bases = set()
    for _ln, _l in LADDERS.items():
        for m, _n in _l:
            bases.add(m.split(":")[0])
    if desired_tag:
        bases.add(desired_tag.split(":")[0])
    base_hits = sorted(x for x in inst if x.split(":")[0] in bases)
    if base_hits:
        return base_hits[0], "정확한 태그 미설치 → 유사 모델 " + base_hits[0] + " 사용"

    if inst:
        any_m = sorted(inst)[0]
        return any_m, "역할 매칭 없음 → 설치된 " + any_m + " 사용"

    return None, "설치된 모델이 없습니다 — MANAGE.bat [2] 모델 관리에서 받으세요"
# <<< MODEL_INSTALLED_MATCH_v1
# <<< MODEL_ROLLBACK_v1


__all__ = [
    "ModelRole", "ROLES", "Resolution", "CODER_14B_MIN_FREE_GB",
    "detect_free_memory_gb", "resolve", "by_key", "default", "all_models_to_install",
    "LADDERS", "ladder_for", "resolve_ladder", "resolve_with_rollback",
    "installed_models", "auto_match_installed",
]
