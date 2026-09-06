# -*- coding: utf-8 -*-
"""model_roles — 모델-역할 레지스트리 + 메모리 적응형 모델 선택.

MODEL_GEMMA_v10 — Gemma 4 26B-A4B 중심 (다운로드 카탈로그 v4 정합).
각 역할은 라벨/샘플링/설명을 묶고, 사이즈 다단계 롤백 사다리(LADDERS)와
실적재 probe 기반 자동 강등(resolve_with_rollback)을 제공한다.

모델 선택의 정본은 TIERS 하나뿐이다.
  ROLES[*].model / fallback / need_gb 는 화면 표시용이며, 임포트 시점에
  _sync_roles_with_tiers() 가 TIERS 의 1·2단계로 덮어쓴다. 직접 적지 말 것 —
  예전에는 손으로 적힌 값이 사다리와 어긋나 "권장 모델"이라고 안내한 태그를
  런타임이 한 번도 쓰지 않는 상태였다.
stdlib 전용.
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


# 핵심 모델 태그 (v3 카탈로그와 동일)
_ARA = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"   # 무검열·범용·에이전트 (15GB)
_CODER = "qwen3-coder:30b"                                    # 코딩 (18GB, MoE)
_GEMMA12 = "gemma4:12b"                                       # 맥락/폴백 (7.5GB)
_CODER_MID = "qwen2.5-coder:14b"                              # 코딩 중간 (9GB, 16GB VRAM 적합)
_CODER_FB = "qwen2.5-coder:7b"                                # 코딩 폴백 (4.7GB)
_UNC_FB = "huihui_ai/qwen3-abliterated:8b"                    # 무검열 폴백 (5GB)

ROLES: List[ModelRole] = [
    ModelRole(
        key="1", name="uncensored", label="무검열 검색/번역",
        description="검열 없이 과감한 검색·번역·범용. 멀티모달·긴 컨텍스트. 여유가 모자라면 경량 무검열로 자동 강등.",
        model=_ARA, need_gb=15.5,
        temperature=0.6, context_window=8192,
        system_hint="당신은 검열 없이 솔직하게 답하는 다국어 보조자입니다. "
                    "번역/요약/검색 요청에 직접적으로 응답하고, 한국어로 자연스럽게 옮깁니다.",
        fallback=_UNC_FB, fallback_need_gb=8.0,
    ),
    ModelRole(
        key="2", name="coding", label="코딩 에이전트 (Open Interpreter)",
        description="코드 작성·실행·파일 작업. MoE 코딩 모델 우선, 여유에 따라 중간·경량 코더로 자동 강등.",
        model=_CODER, need_gb=17.0,
        temperature=0.2, context_window=8192,
        system_hint="당신은 코드를 작성하고 실행하는 자율 코딩 에이전트입니다.",
        fallback=_CODER_FB, fallback_need_gb=8.0,
    ),
    ModelRole(
        key="3", name="office", label="사무·문서 보조",
        description="요약·보고서·긴 문서, 스캔본과 스크린샷 읽기. 속도보다 품질을 우선한다.",
        model=_GEMMA12, need_gb=10.0,
        temperature=0.3, context_window=16384,
        system_hint="당신은 긴 문서를 정확히 이해하고 근거를 들어 정리·요약하는 사무 보조자입니다.",
    ),
    ModelRole(
        key="4", name="balanced", label="균형 (범용)",
        description="일상·범용. Gemma 4 계열 공유, 저사양에서는 QAT 체크포인트로 강등.",
        model=_GEMMA12, need_gb=10.0,
        temperature=0.4, context_window=8192,
        system_hint="당신은 다재다능한 범용 보조자입니다.",
    ),
    ModelRole(
        key="5", name="agent", label="자동화 에이전트",
        description="도구 호출·자율 실행. 툴콜/형식 준수가 좋은 체크포인트 우선, 여유에 따라 자동 강등.",
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

# 역할별 후보 사다리 (모델, 권장 최소 여유 GB) — 아래 TIERS 에서 파생된다.
LADDERS: dict = {}

# >>> TIERS_v2 — 역할별 선호 순서. 각 티어는 "비슷한 크기의 대안 묶음"이다.
#
#  need 는 그 티어 기본 모델의 상주 메모리(model_catalog.run_gb)와 같다.
#  실제 적재 가능 판정은 _flatten_tiers 가 모델마다 카탈로그 값을 다시 읽어
#  개별로 한다 — 같은 티어라도 크기가 조금씩 다르기 때문이다.
#
#  근거 요약(2026-09 기준):
#   * 코딩은 Qwen3.6-27B dense 가 SWE-bench Verified 77.2 로 이 체급 최고고,
#     Ollama OpenAI 호환 엔드포인트에서 도구 호출이 검증됐다. qwen3.5/3.8 계열은
#     도구 호출 결함이 보고돼 REPLACED 로 뺐다.
#   * 에이전트는 도구 왕복이 많아 토큰 속도가 곧 체감 속도다. 그래서 dense 최상위
#     대신 MoE(활성 ~4B) 인 Gemma 4 26B-A4B 를 위에 둔다. Gemma 4 는 τ2-bench
#     86.4 로 도구 사용 자체는 강하다(Gemma 3 27B 는 6.6).
#     [TIERS_QAT_v1] 그중에서도 QAT 체크포인트를 먼저 쓴다 — 학습 중 4비트를
#     시뮬레이션해 양자화 오차에 미리 적응하므로, 사후 반올림(PTQ)보다 툴콜·
#     코드블록 형식이 덜 깨진다. 실측: 8b abliterated 는 코드블록 펜스를 못 지켜
#     미니루프가 실행조차 못 했고, qwen2.5-coder:14b 로 바꾸자 정상 동작했다.
#   * 반대로 맥락/범용은 속도보다 품질이라 dense 31B 를 최상단에 둔다.
TIERS = {
    "coding": [
        {"need": 18.0, "primary": "qwen3.6:27b",
         "alts": ["qwen3-coder:30b",                       # MoE — 품질 조금 낮고 훨씬 빠름
                  "huihui_ai/qwen3-coder-abliterated:30b"]},  # 무검열 코딩
        {"need": 15.0, "primary": "devstral-small-2:24b",
         "alts": ["gpt-oss:20b"]},
        {"need": 9.0, "primary": "qwen2.5-coder:14b", "alts": []},
        {"need": 4.7, "primary": "qwen2.5-coder:7b", "alts": []},
    ],
    "agent": [
        {"need": 18.0, "primary": "gemma4:26b-a4b-it-qat",
         # qwen3.6 은 도구 호출 누락률이 가장 낮은 계열이지만 dense 라 느리다.
         # 기본단계로 올리지 않고 대안으로 둔다 — 받아 둔 사람에게만 걸린다.
         "alts": ["gemma4:26b", "qwen3.6:27b"]},
        {"need": 15.0, "primary": "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
         "alts": ["gpt-oss:20b"]},
        {"need": 9.0, "primary": "qwen2.5-coder:14b",
         "alts": ["gemma4:12b-it-qat", "gemma4:12b"]},
        {"need": 5.0, "primary": "gemma4:e4b-it-qat",
         "alts": ["gemma4:e4b", "qwen2.5-coder:7b"]},
    ],
    # 무검열은 번역·창작·자유로운 범용이 목적이라 도구 호출을 요구하지 않는다.
    # 예전에는 15GB 와 5GB 사이가 통째로 비어서, 여유 8~14GB 인 PC 는 무검열
    # 작업을 곧바로 8b 로 떨어뜨렸다. 그 사이를 14b -> 12b 로 메운다.
    "uncensored": [
        {"need": 18.0, "primary": "huihui_ai/gemma-4-abliterated:26b-qat",
         "alts": ["huihui_ai/Qwen3.6-abliterated:27b",          # 번역·다국어 축
                  "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q5_K_M"]},
        {"need": 15.0, "primary": "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
         "alts": []},
        {"need": 9.0, "primary": "huihui_ai/qwen3-abliterated:14b", "alts": []},
        {"need": 7.6, "primary": "huihui_ai/gemma-4-abliterated:12b", "alts": []},
        {"need": 5.0, "primary": "huihui_ai/qwen3-abliterated:8b", "alts": []},
    ],
    "balanced": [
        {"need": 18.0, "primary": "gemma4:26b", "alts": ["gemma4:31b"]},
        {"need": 14.0, "primary": "gpt-oss:20b", "alts": []},
        {"need": 7.6, "primary": "gemma4:12b", "alts": ["gemma4:12b-it-qat"]},
        {"need": 5.0, "primary": "gemma4:e4b-it-qat",
         "alts": ["gemma4:e4b", "exaone3.5:7.8b"]},
    ],
    # 사무·문서 (구 "context"). 요약·보고서·긴 문서 + 스캔본/스크린샷 읽기.
    # 속도보다 품질이라 여기서는 dense 31B 를 기본단계로 올린다
    # (Gemma 4 31B 는 요약 평가 94.6/100). 아래쪽에는 CJK OCR 이 되는
    # Qwen3-VL 을 둬서 한국어 스캔 문서를 다룰 수 있게 한다.
    "office": [
        {"need": 20.0, "primary": "gemma4:31b", "alts": ["qwen3-vl:32b"]},
        {"need": 18.0, "primary": "gemma4:26b", "alts": []},
        # 10~16GB 구간이 비어 있으면 이 구간의 PC 가 26B 에서 곧바로 12B 로
        # 떨어진다. gpt-oss 는 추론 강도를 조절할 수 있어 요약·보고서 작성에
        # 잘 맞는다(이미지 입력은 안 되므로 그건 아래 단계가 맡는다).
        {"need": 14.0, "primary": "gpt-oss:20b", "alts": []},
        {"need": 7.6, "primary": "gemma4:12b", "alts": ["gemma4:12b-it-qat"]},
        {"need": 6.1, "primary": "qwen3-vl:8b", "alts": ["exaone3.5:7.8b"]},
        {"need": 5.0, "primary": "gemma4:e4b-it-qat", "alts": ["gemma4:e4b"]},
    ],
}

# 예전 역할 이름 -> 지금 이름. user_data/models/registry.json 에 옛 키를 적어 둔
# 사용자가 조용히 무시당하지 않도록 받아 준다.
ROLE_ALIASES = {"context": "office"}


def _canonical(installed):
    """설치 목록을 카탈로그 표기로 맞춘다 (대소문자 차이 흡수)."""
    try:
        from . import model_catalog as _cat
    except Exception:
        try:
            from launcher.models import model_catalog as _cat
        except Exception:
            return set(installed)
    try:
        return _cat.canonicalize_installed(installed)
    except Exception:
        return set(installed)


def _installed_match(tag, installed):
    """설치 목록에서 tag 를 찾는다(대소문자 무시). 없으면 None.

    벤더 태그는 대소문자가 섞여 있고(prutser/...:Q4_K_S) Ollama 가 그대로
    돌려준다는 보장이 없다. 문자열을 그대로 비교하면 멀쩡히 깔린 모델을
    '미설치' 로 보고 사다리를 한참 아래로 떨어뜨린다.
    """
    if not tag or not installed:
        return None
    try:
        from . import model_catalog as _cat
    except Exception:
        try:
            from launcher.models import model_catalog as _cat
        except Exception:
            return tag if tag in installed else None
    return _cat.find_installed(tag, installed)


def _catalog_memory(tag):
    """카탈로그가 아는 상주 메모리(GB). 모르면 None."""
    try:
        from . import model_catalog as _cat
    except Exception:
        try:
            from launcher.models import model_catalog as _cat
        except Exception:
            return None
    try:
        return _cat.memory_gb(tag)
    except Exception:
        return None


def _flatten_tiers(_tiers):
    """티어 -> 평탄 사다리 [(model, need), ...].

    need 는 모델마다 카탈로그의 run_gb 를 쓴다. 예전에는 같은 티어면 대안까지
    티어 need 를 그대로 물려받아, 다운로드 9.6GB 지만 상주는 5GB 인 gemma4:e4b
    같은 모델을 실제보다 무겁게 봤고 반대로 18GB 모델을 17GB 로 가볍게 봤다.
    카탈로그에 없는 태그(레지스트리로 추가한 것)는 티어 need 를 그대로 쓴다.
    """
    _out = {}
    for _role, _tl in _tiers.items():
        _seq = []
        for _t in _tl:
            _fallback = float(_t["need"])
            for _m in [_t["primary"]] + list(_t.get("alts", [])):
                _known = _catalog_memory(_m)
                _seq.append((_m, float(_known) if _known else _fallback))
        _out[_role] = _seq
    return _out


# >>> MODEL_REGISTRY_v1 - user_data/models/registry.json 으로 티어 덮어쓰기/추가
def _registry_path():
    """<프로젝트루트>/user_data/models/registry.json"""
    here = os.path.dirname(os.path.abspath(__file__))          # launcher/models
    root = os.path.dirname(os.path.dirname(here))              # 프로젝트 루트
    return os.path.join(root, "user_data", "models", "registry.json")


def _valid_tier(t):
    if not isinstance(t, dict):
        return False
    if not isinstance(t.get("primary"), str) or not t["primary"].strip():
        return False
    try:
        float(t.get("need"))
    except (TypeError, ValueError):
        return False
    a = t.get("alts", [])
    return isinstance(a, list) and all(isinstance(x, str) for x in a)


def _norm_tier(t):
    return {"need": float(t["need"]), "primary": t["primary"].strip(),
            "alts": [x.strip() for x in t.get("alts", []) if x.strip()]}


def load_registry(path=None):
    """레지스트리를 읽어 (replace, add, errors) 반환. 실패해도 예외를 내지 않는다."""
    path = path or _registry_path()
    if not os.path.isfile(path):
        return {}, {}, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        return {}, {}, ["registry.json 읽기 실패: %s: %s" % (type(e).__name__, e)]
    if not isinstance(data, dict):
        return {}, {}, ["registry.json 최상위가 객체가 아닙니다"]
    errs = []
    out = {}
    for key in ("replace", "add"):
        sec = data.get(key) or {}
        if not isinstance(sec, dict):
            errs.append("%s 가 객체가 아닙니다" % key)
            sec = {}
        clean = {}
        for role, tiers in sec.items():
            role = ROLE_ALIASES.get(role, role)
            if not isinstance(tiers, list):
                errs.append("%s.%s 가 배열이 아닙니다" % (key, role))
                continue
            good = []
            for i, t in enumerate(tiers):
                if _valid_tier(t):
                    good.append(_norm_tier(t))
                else:
                    errs.append("%s.%s[%d] 형식 오류 - 건너뜀" % (key, role, i))
            if good:
                clean[role] = good
        out[key] = clean
    return out.get("replace", {}), out.get("add", {}), errs


def apply_registry(tiers, path=None):
    """TIERS 사본에 레지스트리를 반영해 돌려준다. 원본은 건드리지 않는다."""
    rep, add, errs = load_registry(path)
    merged = {k: list(v) for k, v in tiers.items()}
    for role, tl in rep.items():
        merged[role] = list(tl)
    for role, tl in add.items():
        merged[role] = list(merged.get(role, [])) + list(tl)
    for role in list(merged):
        # need 내림차순(고품질 -> 저압축). 같은 need 는 원래 순서 유지.
        merged[role] = sorted(merged[role], key=lambda t: -float(t["need"]))
    return merged, errs


REGISTRY_ERRORS = []
try:
    TIERS, REGISTRY_ERRORS = apply_registry(TIERS)
except Exception as _e:
    REGISTRY_ERRORS = ["registry 적용 실패(기본 TIERS 유지): %s" % _e]
# <<< MODEL_REGISTRY_v1

LADDERS = _flatten_tiers(TIERS)  # 원본 LADDERS 를 티어 기반(대안 포함)으로 대체


# >>> ROLES_TIER_SYNC_v1 — 화면에 뜨는 "권장 모델" 을 실제 사다리와 일치시킨다.
#
#  resolve() 가 고른 model 은 호출부(agent_chat / entry_dialog)에서 곧바로
#  resolve_ladder() 결과로 덮어써진다. 즉 선택은 100% TIERS 가 한다.
#  그런데 model_info._show_role_table / chat._show_model_tips 는 ROLES.model 을
#  그대로 출력하므로, 손으로 적은 값이 남아 있으면 "코딩 -> qwen3-coder:30b
#  (부족 시 qwen2.5-coder:7b)" 처럼 실제 사다리(30b -> 14b -> 7b)와 다른 안내가
#  나간다. 여기서 티어 1·2단계로 덮어써 두 값이 갈라질 수 없게 만든다.
def _sync_roles_with_tiers(roles, tiers):
    import dataclasses
    out = []
    for r in roles:
        tl = tiers.get(r.name) or []
        if not tl:
            out.append(r)
            continue
        primary = tl[0]["primary"]
        need = float(tl[0]["need"])
        fb = tl[1]["primary"] if len(tl) > 1 else None
        fb_need = float(tl[1]["need"]) if len(tl) > 1 else 0.0
        out.append(dataclasses.replace(
            r, model=primary, need_gb=need, fallback=fb, fallback_need_gb=fb_need))
    return out


ROLES = _sync_roles_with_tiers(ROLES, TIERS)
# <<< ROLES_TIER_SYNC_v1
# <<< TIERS_v1


def _lightest(lad, installed=None):
    """[LADDER_FALLBACK_v1] 사다리에서 '진짜 가장 가벼운' 후보.

    기존 코드는 lad[-1][0] 을 최하위로 봤는데, _flatten_tiers 가 같은 need 의
    대안(alts)을 뒤에 이어 붙이므로 lad[-1] 은 마지막 티어의 '대안' 이다.
    실측: usable 9.2GB 에서 agent -> gpt-oss:20b(미설치), balanced -> qwen2.5:14b(미설치).
    """
    if not lad:
        return None
    if installed:
        have = [(need, m) for m, need in lad if _installed_match(m, installed)]
        if have:
            return min(have)[1]
    return min(lad, key=lambda x: x[1])[0]


def resolve_ladder(role_name: str, free_gb: Optional[float] = None):
    """여유 메모리에 맞는 최상위 후보 1차 선택. 사다리 없으면 None.

    [LADDER_FALLBACK_v1] 설치된 모델을 우선한다. 없는 모델을 골라 놓고
    뒤늦게 auto_match_installed 가 수습하면 엉뚱한 곳으로 떨어진다.
    설치 목록 조회에 실패하면 기존 동작(설치 무시)으로 안전 폴백한다.
    """
    lad = LADDERS.get(role_name)
    if not lad:
        return None
    try:
        installed = installed_models()
    except Exception:
        installed = None
    free = free_gb if free_gb is not None else detect_free_memory_gb()
    if free is None:
        return _lightest(lad, installed)
    usable = free * _SAFETY
    fits = [(m, need) for m, need in lad if need <= usable]
    if installed:
        for m, _need in fits:
            if _installed_match(m, installed):
                return m
    if fits:
        return fits[0][0]
    return _lightest(lad, installed)


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
    # 이름이 아니라 '위치' 로 내려간다. seq.index() 로 되찾으면 같은 태그가 사다리에
    # 두 번 나올 때(레지스트리 add 로 충분히 생긴다) 첫 번째 위치로 되돌아가 영원히
    # 같은 구간을 맴돈다.
    idx = seq.index(model) if model in seq else 0
    while True:
        if _load_probe(model, host=host):
            return model
        if idx + 1 >= len(seq):
            if presenter is not None:
                try:
                    presenter.warn(model + " 적재 실패 — 더 낮은 후보 없음")
                except Exception:
                    pass
            return model
        idx += 1
        nxt = seq[idx]
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
        return _canonical(out)
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
    exact = _installed_match(desired_tag, inst)
    if exact:
        return exact, None
    free = free_gb if free_gb is not None else detect_free_memory_gb()
    usable = (free * _SAFETY) if free is not None else None

    lad = LADDERS.get(role_name) if role_name else None
    if lad:
        for m, need in lad:
            hit = _installed_match(m, inst)
            if hit and (usable is None or need <= usable):
                return hit, "선택 모델 미설치 → 설치된 " + hit + " 자동 사용"
        for m, _n in lad:
            hit = _installed_match(m, inst)
            if hit:
                return hit, "선택 모델 미설치 → 설치된 " + hit + " 사용(메모리 빠듯)"

    allc = [(need, _installed_match(m, inst))
            for _ln, _l in LADDERS.items() for m, need in _l
            if _installed_match(m, inst)]
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

    return None, "설치된 모델이 없습니다 — SETUP.bat --manage 에서 받으세요"
# <<< MODEL_INSTALLED_MATCH_v1
# <<< MODEL_ROLLBACK_v1


__all__ = [
    "ModelRole", "ROLES", "Resolution",
    "detect_free_memory_gb", "resolve", "by_key",
    "TIERS", "LADDERS", "resolve_ladder", "resolve_with_rollback",
    "installed_models", "auto_match_installed",
    "load_registry", "apply_registry", "REGISTRY_ERRORS",
]
