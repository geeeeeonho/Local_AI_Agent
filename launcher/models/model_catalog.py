# -*- coding: utf-8 -*-
"""model_catalog — 설치/관리용 모델 카탈로그 (단일 소스).

MODEL_CATALOG_v3 — 젬마 4 26B-A4B 중심. 여유 ~20GB, 모델당 상한 ~18~19GB.
  핵심: Gemma 4 26B-A4B ARA abliterated (공개 abliteration 중 최저 거부율·최고 품질)
        = 무검열 + 범용 + 에이전트 + 멀티모달 + 256K 를 한 모델로.
  코딩만 전용 모델(qwen3-coder)을 따로 둠. 안전 롤백 소수 유지.
설치기(installer.model)와 GUI 가 공유. stdlib 전용. 함수 시그니처 v1 호환.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple

MARKER = "MODEL_CATALOG_v3"


@dataclass(frozen=True)
class CatalogEntry:
    tag: str
    role: str                 # 역할 라벨(설치 시 표시)
    size_gb: float            # 대략 GGUF 크기(공식 표기 기준)
    desc: str
    group: str = "core"       # "core"(기본) | "advanced"(선택)
    recommended: bool = True  # 다운로드 체크박스 기본 체크 여부


# ── 기본 설치 세트 (젬마 ARA 메인 + 코딩 전용 + 안전 롤백) ──
CORE: List[CatalogEntry] = [
    CatalogEntry("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
                 "무검열·범용·에이전트 (Gemma ARA)", 15.0,
                 "메인 — Gemma 4 26B-A4B ARA abliterated. 공개 abliteration 중 최저 거부율(7.7%)·최고 품질(4.6/5). "
                 "MoE 4B 활성으로 빠름, 256K, 멀티모달, 툴. 15GB라 헤드룸 여유."),
    CatalogEntry("qwen3-coder:30b", "코딩 에이전트 (Open Interpreter)", 18.0,
                 "코딩 전용 — 30B-A3B MoE(활성 ~3B), 256K, 툴콜링. 젬마가 약한 순수 코딩 보강. 8K 컨텍스트 권장."),
    CatalogEntry("gemma4:12b", "맥락/범용 + Gemma 폴백", 7.5,
                 "맥락·범용 + 에이전트 안전 폴백. Gemma 4 12B, 256K·멀티모달·함수호출."),
    CatalogEntry("qwen2.5-coder:7b", "코딩 폴백", 4.7,
                 "안전 롤백 — 메모리 부족 시 코딩."),
    CatalogEntry("huihui_ai/qwen3-abliterated:8b", "무검열 경량 폴백", 5.0,
                 "안전 롤백 — 무검열 경량(젬마 ARA가 안 뜰 때)."),
]

# ── 선택 설치 (대안/최고품질/특수, 모두 ≤ ~19GB) ──
ADVANCED: List[CatalogEntry] = [
    # Gemma 계열 대안
    CatalogEntry("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q5_K_M",
                 "Gemma ARA 최고품질", 19.0,
                 "동일 ARA 모델의 Q5 — 품질 최대지만 20GB에 빠듯(컨텍스트 작게 권장).",
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:26b", "Gemma 정식 에이전트(검열)", 14.4,
                 "정식 QAT — 템플릿/툴콜 보장(검열 있음). 안정적 에이전트.",
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:e4b", "Gemma 초경량 폴백", 5.0,
                 "저사양/최후 폴백(공식 태그).",
                 group="advanced", recommended=False),
    # 코딩/에이전트 대안
    CatalogEntry("devstral-small:24b", "에이전트 코딩 특화", 14.0,
                 "다중파일·디버깅 루프·툴콜링(Apache). 16GB VRAM 적합.",
                 group="advanced", recommended=False),
    CatalogEntry("qwen3.6:27b", "코딩 dense 최강", 17.0,
                 "dense SWE-bench 77.2 — 코드 품질 최상(비-MoE).",
                 group="advanced", recommended=False),
    CatalogEntry("huihui_ai/qwen3-coder-abliterated:30b", "무검열 코딩", 18.0,
                 "무검열 코딩 — Qwen3-Coder abliteration. num_gpu 상향 권장.",
                 group="advanced", recommended=False),
    CatalogEntry("qwen2.5-coder:14b", "코딩 중간", 9.0,
                 "코딩 중간 롤백 — 16GB VRAM 안정.",
                 group="advanced", recommended=False),
    # 범용/한국어
    CatalogEntry("gpt-oss:20b", "범용·에이전트", 13.0,
                 "OpenAI 오픈(Apache) — 추론+에이전트, MoE 고속.",
                 group="advanced", recommended=False),
    CatalogEntry("exaone3.5:7.8b", "한국어 특화", 4.8,
                 "LG EXAONE 3.5 — 한·영 이중언어.",
                 group="advanced", recommended=False),
]

# 과거/하위 세트 → 새 세트로 대체되어 삭제 권장
REPLACED: List[str] = [
    "gemma-agent-fixed:Q3_K_M",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M",  # Q4_K_S 로 대체
    "qwen3:8b",
]


def all_entries() -> List[CatalogEntry]:
    return list(CORE) + list(ADVANCED)


def core_tags() -> List[str]:
    return [e.tag for e in CORE]


def catalog_tags() -> Set[str]:
    return {e.tag for e in all_entries()}


def install_pairs() -> List[Tuple[str, str]]:
    """설치기용 (역할라벨, 태그) — core 세트(중복 제거)."""
    seen: Set[str] = set()
    out: List[Tuple[str, str]] = []
    for e in CORE:
        if e.tag not in seen:
            seen.add(e.tag)
            out.append((e.role, e.tag))
    return out


def replaced_tags() -> List[str]:
    return list(REPLACED)


__all__ = [
    "CatalogEntry", "CORE", "ADVANCED", "REPLACED", "MARKER",
    "all_entries", "core_tags", "catalog_tags", "install_pairs", "replaced_tags",
]
