# -*- coding: utf-8 -*-
"""model_catalog — 설치/관리용 모델 카탈로그 (단일 소스).

MODEL_CATALOG_v5 — Gemma 4 / Qwen3.6 세대. 목표 하드웨어: 여유 RAM ~20GB.

크기를 두 개로 나눈다. 예전에는 하나로 뭉뚱그려서 사다리가 틀린 판단을 했다.
  size_gb : 다운로드(디스크) 크기. 설치 화면의 "몇 GB 받나" 계산용.
  run_gb  : 실제로 상주하는 메모리. 사다리의 적재 가능 판정용.
대부분 GGUF 는 둘이 같지만 Gemma 4 E 계열(e2b/e4b)은 다르다 —
e4b 는 9.6GB 를 받아도 실제 활성 파라미터만 올려서 ~5GB 로 돈다.
KV 캐시·연산 버퍼 여유는 model_roles._SAFETY(0.92) 가 따로 잡는다.

tools 는 함수/도구 호출 지원 여부다. 에이전트·코딩 사다리는 이게 False 인 모델을
담을 수 없다(tests/test_model_catalog_tiers.py 가 막는다). Open Interpreter 는
도구 호출로 동작하므로, 못 부르는 모델을 골라 놓으면 그냥 멈춘 것처럼 보인다.

v5 규칙 — 카탈로그와 model_roles.TIERS 는 서로의 거울이어야 한다.
  * TIERS 가 고를 수 있는 태그는 반드시 여기에 있어야 한다.
    없으면 사다리가 "설치할 방법이 없는 모델"을 1순위로 고르고 조용히 떨어진다.
  * 여기 있는 chat 모델은 반드시 어떤 티어에든 등장해야 한다.
    없으면 사용자가 받아 놓은 디스크가 런타임에서 한 번도 선택되지 않는다.
  (kind="embed" 는 역할 사다리가 아니라 RAG 임베더용이라 이 규칙에서 빠진다.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

MARKER = "MODEL_CATALOG_v5"


@dataclass(frozen=True)
class CatalogEntry:
    tag: str
    role: str                 # 역할 라벨(설치 시 표시)
    size_gb: float            # 다운로드(디스크) 크기
    desc: str
    run_gb: float = 0.0       # 상주 메모리. 0 이면 size_gb 와 같다고 본다.
    ctx_k: int = 0            # 컨텍스트 창(K 토큰), 0 = 미상
    tools: bool = True        # 함수/도구 호출 지원
    vision: bool = False      # 이미지 입력
    kind: str = "chat"        # "chat" | "embed"
    group: str = "core"       # "core"(기본) | "advanced"(선택)
    recommended: bool = True  # 정적 기본 체크(메모리 감지 실패 시 폴백)

    @property
    def memory_gb(self) -> float:
        return self.run_gb if self.run_gb > 0 else self.size_gb


# ── 기본 설치 세트 ────────────────────────────────────────────────
#  메모리 감지가 되면 recommended 대신 recommended_for(free_gb) 가 기본 체크를
#  정한다. 아래 recommended 플래그는 감지 실패 시의 폴백이다.
CORE: List[CatalogEntry] = [
    CatalogEntry("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
                 "무검열·범용·에이전트 (Gemma ARA)", 15.0,
                 "메인 — Gemma 4 26B-A4B ARA abliterated. 공개 abliteration 중 최저 거부율(7.7%)·"
                 "최고 품질(4.6/5). MoE 활성 ~4B 라 26B 급인데도 빠르다.",
                 run_gb=15.0, ctx_k=256, vision=True),
    CatalogEntry("qwen3.6:27b", "코딩 에이전트 (Open Interpreter)", 18.0,
                 "코딩 1순위 — dense 27B, SWE-bench Verified 77.2. 로컬에서 도구 호출이 가장 "
                 "안정적인 Qwen3 계열이고 Ollama OpenAI 호환 엔드포인트에서 검증됐다.",
                 run_gb=18.0, ctx_k=256, vision=True),
    CatalogEntry("gemma4:12b", "맥락/범용 + Gemma 폴백", 7.6,
                 "맥락·범용 + 에이전트 안전 폴백. Gemma 4 12B dense, 256K·멀티모달·함수호출.",
                 run_gb=7.6, ctx_k=256, vision=True),
    CatalogEntry("qwen2.5-coder:7b", "코딩 폴백", 4.7,
                 "안전 롤백 — 메모리 부족 시 코딩. 도구 호출 지원.",
                 run_gb=4.7, ctx_k=32),
    CatalogEntry("huihui_ai/qwen3-abliterated:8b", "무검열 경량 폴백", 5.0,
                 "안전 롤백 — 무검열 경량(젬마 ARA가 안 뜰 때). 코드블록 형식 준수가 약해 "
                 "코드 실행 역할에는 쓰지 않는다.",
                 run_gb=5.0, ctx_k=32),
]

# ── 선택 설치 ─────────────────────────────────────────────────────
ADVANCED: List[CatalogEntry] = [
    # ── 에이전트/범용 (Gemma 4) ──
    # QAT = 학습 중 4비트를 시뮬레이션한 체크포인트. 사후 반올림(PTQ)보다 양자화
    # 손상이 훨씬 적어 툴콜·코드블록 형식 준수가 안정적이다. Gemma 4 는 τ2-bench
    # (에이전트 도구 사용) 86.4 로 세대가 바뀌며 크게 올랐다(Gemma 3 27B 는 6.6).
    CatalogEntry("gemma4:26b-a4b-it-qat", "에이전트 1순위 (Gemma QAT)", 18.0,
                 "에이전트 최상단 — 26B-A4B QAT. MoE 활성 ~4B 라 도구 왕복이 많은 "
                 "에이전트 루프에서 dense 27B급보다 훨씬 빠르다.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:26b", "Gemma 정식 26B (검열)", 18.0,
                 "정식 26B-A4B MoE — 템플릿/툴콜 보장(검열 있음). 범용·맥락 1순위.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:31b", "Gemma 최상위 dense (여유 22GB+)", 20.0,
                 "dense 31B — Gemma 4 중 도구 사용 점수가 가장 높다(τ2-bench 86.4). "
                 "20GB 상주라 여유 22GB 이상에서만 걸린다.",
                 run_gb=20.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:12b-it-qat", "저사양 에이전트/범용 (QAT)", 8.9,
                 "여유 10GB 안팎 구간. 12B QAT — 저압축에서도 형식 준수 유지.",
                 run_gb=8.9, ctx_k=256, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:e4b-it-qat", "최저사양 폴백 (QAT)", 9.6,
                 "최저사양 마지막 단계. 다운로드는 9.6GB 지만 활성 파라미터만 올려 "
                 "상주는 ~5GB 다. 도구 호출·비전 내장.",
                 run_gb=5.0, ctx_k=128, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("gemma4:e4b", "Gemma 초경량 폴백", 9.6,
                 "e4b 정식 태그(비-QAT). 상주 ~5GB.",
                 run_gb=5.0, ctx_k=128, vision=True,
                 group="advanced", recommended=False),
    # ── 무검열 상위 ──
    CatalogEntry("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q5_K_M",
                 "Gemma ARA 최고품질 (여유 21GB+)", 19.0,
                 "동일 ARA 모델의 Q5 — 품질 최대. 여유 21GB 이상에서만 걸린다.",
                 run_gb=19.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False),
    # ── 코딩 ──
    CatalogEntry("qwen3-coder:30b", "코딩 MoE (속도 우선)", 18.0,
                 "30B-A3B MoE(활성 ~3B) — qwen3.6:27b 보다 품질은 조금 낮지만 훨씬 빠르다. "
                 "긴 에이전트 루프를 자주 돌린다면 이쪽.",
                 run_gb=18.0, ctx_k=256,
                 group="advanced", recommended=False),
    CatalogEntry("huihui_ai/qwen3-coder-abliterated:30b", "무검열 코딩", 19.0,
                 "무검열 코딩 — Qwen3-Coder abliteration. 여유 21GB 이상.",
                 run_gb=19.0, ctx_k=256,
                 group="advanced", recommended=False),
    CatalogEntry("devstral-small-2:24b", "에이전트 코딩 특화 (16GB급)", 15.0,
                 "다중파일·디버깅 루프·툴콜링(Apache). 384K 컨텍스트. 18GB 급이 안 뜨는 "
                 "구간의 코딩 1순위.",
                 run_gb=15.0, ctx_k=384, vision=True,
                 group="advanced", recommended=False),
    CatalogEntry("qwen2.5-coder:14b", "코딩 중간", 9.0,
                 "코딩 중간 롤백 — 10GB 급에서 코드블록·도구 호출이 안정적이라고 실측된 단계.",
                 run_gb=9.0, ctx_k=32,
                 group="advanced", recommended=False),
    # ── 범용/추론 ──
    CatalogEntry("gpt-oss:20b", "에이전트·추론 (MoE)", 14.0,
                 "OpenAI 오픈(Apache) 21B-A3.6B MoE — 에이전트 작업 겨냥 설계라 도구 호출이 "
                 "깔끔하고 안정적. 추론 강도 low/medium/high 조절 가능.",
                 run_gb=14.0, ctx_k=128,
                 group="advanced", recommended=False),
    CatalogEntry("exaone3.5:7.8b", "한국어 특화 경량", 4.8,
                 "LG EXAONE 3.5 — 한·영 이중언어. 저사양에서 한국어 품질이 필요할 때. "
                 "도구 호출은 기대하지 말 것.",
                 run_gb=4.8, ctx_k=32, tools=False,
                 group="advanced", recommended=False),
    # ── RAG 임베더 (역할 사다리가 아님) ──
    # AnythingLLM 기본 임베더는 컨테이너 내장(native) 이라 최초 1회 HuggingFace 에서
    # 받는다. 오프라인이거나 한국어 검색 품질이 아쉬우면 아래를 받고
    # config.ANYTHINGLLM_EMBEDDING_ENGINE 을 "ollama" 로 바꾼다.
    CatalogEntry("bge-m3:567m", "RAG 임베더 (한국어·다국어)", 1.2,
                 "100개 이상 언어·8K 컨텍스트 하이브리드 검색. 한국어 문서 RAG 에 권장.",
                 run_gb=1.5, ctx_k=8, tools=False, kind="embed",
                 group="advanced", recommended=False),
    CatalogEntry("nomic-embed-text:v1.5", "RAG 임베더 (경량 기본)", 0.3,
                 "가장 가벼운 로컬 임베더(768차원). 영문 위주면 이걸로 충분하다.",
                 run_gb=0.5, ctx_k=8, tools=False, kind="embed",
                 group="advanced", recommended=False),
]

# 과거/하위 세트 → 새 세트로 대체되어 삭제 권장
REPLACED: List[str] = [
    "gemma-agent-fixed:Q3_K_M",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M",  # Q4_K_S 로 대체
    "qwen3:8b",
    "devstral-small:24b",     # Ollama 라이브러리에 없던 이름 — devstral-small-2:24b 로 정정
    "deepseek-coder-v2:16b",  # qwen2.5-coder:14b 와 같은 구간, 세대만 더 오래됨
    "qwen2.5:14b",            # gemma4:12b / gpt-oss:20b 로 대체
    "qwen3.5:27b",            # Ollama 도구 호출 결함 보고(#14493) — qwen3.6:27b 사용
    "qwen3.8:27b",            # /v1/chat/completions 무응답 보고 — qwen3.6:27b 사용
]


def all_entries() -> List[CatalogEntry]:
    return list(CORE) + list(ADVANCED)


def chat_entries() -> List[CatalogEntry]:
    return [e for e in all_entries() if e.kind == "chat"]


def by_tag() -> Dict[str, CatalogEntry]:
    return {e.tag: e for e in all_entries()}


def core_tags() -> List[str]:
    return [e.tag for e in CORE]


def catalog_tags() -> Set[str]:
    return {e.tag for e in all_entries()}


def memory_gb(tag: str) -> Optional[float]:
    """태그의 상주 메모리(GB). 카탈로그에 없으면 None."""
    entry = by_tag().get(tag)
    return entry.memory_gb if entry else None


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


# ── 메모리 적응형 기본 선택 ────────────────────────────────────────
#  예전에는 recommended 플래그 하나로 기본 체크를 정해서, 여유 8GB 짜리 PC 도
#  50GB 를 받아 놓고 정작 그 PC 의 사다리가 원하는 저사양 단계는 하나도 받지
#  않았다. 이제 감지된 여유 메모리로 역할마다 "지금 돌아가는 최상단 + 한 단계
#  아래 안전망"을 골라 준다.
_SAFETY = 0.92

# 이 프로그램이 실제로 돌리는 두 런타임(Open Interpreter 코드 실행 / 도구 에이전트).
# 나머지 역할은 CORE 로 덮이면 그대로 두지만, 이 둘만큼은 그 PC 에서 돌아가는
# '가장 좋은' 단계를 받아 둔다 — 여기서 한 단계 밀리면 체감이 바로 나빠진다.
PRIORITY_ROLES = ("coding", "agent")


def recommended_for(free_gb: Optional[float],
                    ladders: Optional[Dict[str, Sequence[Tuple[str, float]]]] = None,
                    ) -> Set[str]:
    """여유 메모리에 맞는 기본 설치 세트.

    규칙은 세 줄이다.
      1) CORE 중 이 PC 에서 상주 가능한 것만 남긴다.
         (예전에는 여유 8GB 짜리도 CORE 50GB 를 통째로 받았다.)
      2) coding / agent 는 그 PC 에서 가능한 최상단 기본단계를 반드시 넣는다.
      3) 그러고도 받을 모델이 하나도 없는 역할이 있으면 그 역할의 최상단을 채운다.
         (예전에는 저사양 PC 가 balanced/context 에서 받을 게 아예 없었다.)

    free_gb 가 None 이면 정적 recommended 플래그로 폴백한다.
    ladders 를 주지 않으면 model_roles.LADDERS 를 읽는다(순환 import 회피용 지연 참조).
    """
    static = {e.tag for e in all_entries() if e.recommended}
    if free_gb is None:
        return static
    if ladders is None:
        try:
            from . import model_roles as _mr
            ladders = _mr.LADDERS
        except Exception:
            return static
    ladders = ladders or {}

    usable = float(free_gb) * _SAFETY
    table = by_tag()

    def fits(tag: str) -> bool:
        entry = table.get(tag)
        return entry is not None and entry.memory_gb <= usable

    picked: Set[str] = {t for t in core_tags() if fits(t)}

    for role, rungs in ladders.items():
        fitting = [tag for tag, _need in rungs if fits(tag)]
        if not fitting:
            continue
        covered = any(tag in picked for tag in fitting)
        if role in PRIORITY_ROLES or not covered:
            picked.add(fitting[0])

    if not picked:
        # 무엇도 안 맞는 초저사양 — 그래도 손에 뭔가는 쥐여 준다.
        lightest = min((e for e in chat_entries()), key=lambda e: e.memory_gb, default=None)
        if lightest:
            picked.add(lightest.tag)
    return picked


def download_gb(tags) -> float:
    """받을 태그들의 디스크 합계(GB)."""
    table = by_tag()
    return sum(table[t].size_gb for t in tags if t in table)


__all__ = [
    "CatalogEntry", "CORE", "ADVANCED", "REPLACED", "MARKER",
    "all_entries", "chat_entries", "by_tag", "core_tags", "catalog_tags",
    "memory_gb", "install_pairs", "replaced_tags", "recommended_for", "download_gb",
]
