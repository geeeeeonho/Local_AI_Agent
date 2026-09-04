# -*- coding: utf-8 -*-
"""model_catalog — 설치/관리용 모델 카탈로그 (단일 소스).

MODEL_CATALOG_v4 — 젬마 4 26B-A4B 중심. 여유 ~20GB, 모델당 상한 ~18~19GB.
  핵심: Gemma 4 26B-A4B ARA abliterated (공개 abliteration 중 최저 거부율·최고 품질)
        = 무검열 + 범용 + 에이전트 + 멀티모달 + 256K 를 한 모델로.
  코딩만 전용 모델(qwen3-coder)을 따로 둠. 안전 롤백 소수 유지.
설치기(installer.model)와 GUI 가 공유. stdlib 전용. 함수 시그니처 v1 호환.

v4 규칙 — 카탈로그와 model_roles.TIERS 는 서로의 거울이어야 한다.
  * TIERS 가 고를 수 있는 태그는 반드시 여기에 있어야 한다.
    없으면 사다리가 "설치할 방법이 없는 모델"을 1순위로 고르고 조용히 떨어진다.
  * 여기 있는 태그는 반드시 어떤 티어에든 등장해야 한다.
    없으면 사용자가 받아 놓은 디스크가 런타임에서 한 번도 선택되지 않는다.
  tests/test_model_catalog_tiers.py 가 양방향을 강제한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple

MARKER = "MODEL_CATALOG_v4"


@dataclass(frozen=True)
class CatalogEntry:
    tag: str
    role: str                 # 역할 라벨(설치 시 표시)
    size_gb: float            # 대략 GGUF 다운로드 크기(적재 VRAM 아님)
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
    CatalogEntry("gemma4:12b", "맥락/범용 + Gemma 폴백", 7.6,
                 "맥락·범용 + 에이전트 안전 폴백. Gemma 4 12B dense, 256K·멀티모달·함수호출. 적재 ~6.7GB."),
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
    CatalogEntry("gemma4:26b", "Gemma 정식 에이전트(검열)", 18.0,
                 "정식 26B-A4B MoE(활성 ~4B) — 템플릿/툴콜 보장(검열 있음). 적재 ~14.4GB.",
                 group="advanced", recommended=False),
    # QAT 체크포인트 — 양자화 내성이 좋아 툴콜/형식 준수가 필요한 에이전트용.
    # model_roles.TIERS[TIERS_QAT_v1] 가 이 태그들을 1순위로 고르므로 카탈로그에 반드시 있어야 한다.
    CatalogEntry("gemma4:26b-a4b-it-qat", "에이전트 1순위 (Gemma QAT)", 18.0,
                 "에이전트 최상단 — 학습 중 4비트를 시뮬레이션한 QAT 체크포인트라 "
                 "PTQ 대비 양자화 손상이 적다. 툴콜·코드블록 형식 준수가 안정적.",
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:12b-it-qat", "저사양 에이전트/범용 (QAT)", 8.9,
                 "여유 8.5GB 구간의 기본 단계. 12B QAT — 저압축에서도 형식 준수 유지.",
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:e4b-it-qat", "최저사양 폴백 (QAT)", 9.6,
                 "여유 6GB 구간의 마지막 단계. 적재 ~4.5GB(다운로드는 9.6GB).",
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:e4b", "Gemma 초경량 폴백", 9.6,
                 "저사양/최후 폴백(공식 태그). 적재 ~4.5GB(다운로드는 9.6GB).",
                 group="advanced", recommended=False),
    # 코딩/에이전트 대안
    CatalogEntry("devstral-small-2:24b", "에이전트 코딩 특화", 15.0,
                 "다중파일·디버깅 루프·툴콜링(Apache). 384K 컨텍스트, 16GB VRAM 적합.",
                 group="advanced", recommended=False),
    CatalogEntry("qwen3.6:27b", "코딩 dense 최강", 17.0,
                 "dense SWE-bench 77.2 — 코드 품질 최상(비-MoE).",
                 group="advanced", recommended=False),
    CatalogEntry("huihui_ai/qwen3-coder-abliterated:30b", "무검열 코딩", 19.0,
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
                 "LG EXAONE 3.5 — 한·영 이중언어. 저사양 한국어 대안.",
                 group="advanced", recommended=False),
]

# 과거/하위 세트 → 새 세트로 대체되어 삭제 권장
REPLACED: List[str] = [
    "gemma-agent-fixed:Q3_K_M",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M",  # Q4_K_S 로 대체
    "qwen3:8b",
    "devstral-small:24b",   # Ollama 라이브러리에 없던 이름 — devstral-small-2:24b 로 정정
    "deepseek-coder-v2:16b",  # qwen2.5-coder:14b 와 같은 티어, 세대만 더 오래됨
    "qwen2.5:14b",            # gemma4:12b / gpt-oss:20b 로 대체
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
