# -*- coding: utf-8 -*-
"""model_catalog — 설치/관리용 모델 카탈로그 (단일 소스).

MODEL_CATALOG_v6 — Gemma 4 / Qwen3.6 세대. 목표 하드웨어: 모델용 메모리 ~20GB.

메모리 예산이 이 파일의 출발점이다. MEMORY_BUDGET_GB 를 넘겨 적재할 수 없는
모델은 아예 담지 않는다 — 목록에만 있으면 디스크만 먹고 사다리는 매번 그 아래로
떨어진다. 예산 안에서 역할마다 3단계(상/중/하)를 둔다(LEVELS).

크기를 두 개로 나눈다. 예전에는 하나로 뭉뚱그려서 사다리가 틀린 판단을 했다.
  size_gb : 다운로드(디스크) 크기. 설치 화면의 "몇 GB 받나" 계산용.
  run_gb  : 실제로 상주하는 메모리. 사다리의 적재 가능 판정용.
대부분 GGUF 는 둘이 같지만 Gemma 4 E 계열(e2b/e4b)은 다르다 —
e4b 는 9.6GB 를 받아도 실제 활성 파라미터만 올려서 ~5GB 로 돈다.

tools 는 함수/도구 호출 지원 여부다. 에이전트·코딩 사다리는 이게 False 인 모델을
담을 수 없다(tests/test_model_catalog_tiers.py 가 막는다). Open Interpreter 는
도구 호출로 동작하므로, 못 부르는 모델을 골라 놓으면 그냥 멈춘 것처럼 보인다.

v6 규칙 — 카탈로그와 model_roles.TIERS 는 서로의 거울이어야 한다.
  * TIERS 가 고를 수 있는 태그는 반드시 여기에 있어야 한다.
    없으면 사다리가 "설치할 방법이 없는 모델"을 1순위로 고르고 조용히 떨어진다.
  * 여기 있는 chat 모델은 반드시 어떤 티어에든 등장해야 한다.
    없으면 사용자가 받아 놓은 디스크가 런타임에서 한 번도 선택되지 않는다.
  (kind="embed" 는 역할 사다리가 아니라 RAG 임베더용이라 이 규칙에서 빠진다.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

MARKER = "MODEL_CATALOG_v6"

# ── 하드웨어 예산 ──────────────────────────────────────────────────
#  이 PC 가 모델에 내줄 수 있는 최대 상주 메모리(GB).
#
#  ★ '지금 여유' 가 아니라 이 값으로 무엇을 받을지 정한다. 브라우저를 켜 둔 채
#    설치했다는 이유로 좋은 모델을 영영 못 받게 되면 안 된다.
#    실행 시점의 모델 선택만 실제 여유 메모리를 본다(model_roles.resolve_ladder).
#
#  이 값을 넘는 모델은 카탈로그에 두지 않는다. 받아도 절대 못 뜨는데 목록에만
#  있으면 디스크만 먹고 사다리는 매번 그 아래로 떨어진다.
MEMORY_BUDGET_GB = float(os.environ.get("LLM_MEMORY_BUDGET_GB", "20"))

#  KV 캐시·연산 버퍼 몫. 여유의 이만큼만 가중치에 쓴다 (model_roles._SAFETY 와 같은 값).
_SAFETY = 0.92

#  그래서 실제로 올릴 수 있는 가중치 상한은 예산 그대로가 아니라 이 값이다.
#  20GB 예산 -> 18.4GB. 19~21GB 짜리 모델은 "예산 안" 처럼 보여도 절대 안 뜬다.
MAX_MODEL_GB = MEMORY_BUDGET_GB * _SAFETY

#  예산 안에서 쓰는 3단계. 여유 메모리는 상황에 따라 오르내리므로(브라우저·Docker)
#  한 단계만 받아 두면 그 단계가 안 맞는 순간 쓸 게 없어진다.
#    상 — 다른 걸 거의 안 띄웠을 때. 이 등급이 실질적인 최고 품질이다.
#    중 — 브라우저·Docker 를 같이 쓰는 평소 상태.
#    하 — 메모리가 빠듯할 때의 최후 단계.
#  (min_gb, max_gb] 로 모델을 등급에 배정한다.
LEVELS: Tuple[Tuple[str, str, float, float], ...] = (
    ("high", "상", 13.0, MAX_MODEL_GB),
    ("mid", "중", 6.0, 13.0),
    ("low", "하", 0.0, 6.0),
)
LEVEL_KEYS = tuple(key for key, _label, _lo, _hi in LEVELS)


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
    uncensored: bool = False  # abliteration/무검열 파인튜닝 계열
    note: str = ""            # 후보군에서 이 모델의 성격 (한 줄)
    kind: str = "chat"        # "chat" | "embed"
    group: str = "core"       # "core"(기본) | "advanced"(선택)
    recommended: bool = True  # 정적 기본 체크(메모리 감지 실패 시 폴백)

    @property
    def memory_gb(self) -> float:
        return self.run_gb if self.run_gb > 0 else self.size_gb


# ── 전체 목록 ─────────────────────────────────────────────────────
#  기본/선택 구분은 아래 _CORE_TAGS 에서 한 번만 정한다. 예전에는 각 항목의
#  group·recommended 플래그와 실제 기본 세트가 따로 놀아서, 손으로 맞춰야 했다.
_ALL: List[CatalogEntry] = [
    CatalogEntry("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
                 "무검열·범용·에이전트 (Gemma ARA)", 15.0,
                 "메인 — Gemma 4 26B-A4B ARA abliterated. 공개 abliteration 중 최저 거부율(7.7%)·"
                 "최고 품질(4.6/5). MoE 활성 ~4B 라 26B 급인데도 빠르다.",
                 run_gb=15.0, ctx_k=256, vision=True,
                 uncensored=True, note="거부율 최저"),
    CatalogEntry("qwen3.6:27b", "코딩 에이전트 (Open Interpreter)", 18.0,
                 "코딩 1순위 — dense 27B, SWE-bench Verified 77.2. 로컬에서 도구 호출이 가장 "
                 "안정적인 Qwen3 계열이고 Ollama OpenAI 호환 엔드포인트에서 검증됐다.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 note="품질 최고"),
    CatalogEntry("gemma4:12b", "맥락/범용 + Gemma 폴백", 7.6,
                 "맥락·범용 + 에이전트 안전 폴백. Gemma 4 12B dense, 256K·멀티모달·함수호출.",
                 run_gb=7.6, ctx_k=256, vision=True,
                 note="역할 공유"),
    CatalogEntry("qwen2.5-coder:7b", "코딩 폴백", 4.7,
                 "안전 롤백 — 메모리 부족 시 코딩. 도구 호출 지원.",
                 run_gb=4.7, ctx_k=32,
                 note="가장 가벼움"),
    CatalogEntry("huihui_ai/qwen3-abliterated:8b", "무검열 경량 폴백", 5.0,
                 "안전 롤백 — 무검열 경량(젬마 ARA가 안 뜰 때). 코드블록 형식 준수가 약해 "
                 "코드 실행 역할에는 쓰지 않는다.",
                 run_gb=5.0, ctx_k=32,
                 uncensored=True, note="가장 가벼움"),
    # ── 에이전트/범용 (Gemma 4) ──
    # QAT = 학습 중 4비트를 시뮬레이션한 체크포인트. 사후 반올림(PTQ)보다 양자화
    # 손상이 훨씬 적어 툴콜·코드블록 형식 준수가 안정적이다. Gemma 4 는 τ2-bench
    # (에이전트 도구 사용) 86.4 로 세대가 바뀌며 크게 올랐다(Gemma 3 27B 는 6.6).
    CatalogEntry("gemma4:26b-a4b-it-qat", "에이전트 1순위 (Gemma QAT)", 18.0,
                 "에이전트 최상단 — 26B-A4B QAT. MoE 활성 ~4B 라 도구 왕복이 많은 "
                 "에이전트 루프에서 dense 27B급보다 훨씬 빠르다.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 note="형식 안정"),
    CatalogEntry("gemma4:26b", "Gemma 정식 26B (검열)", 18.0,
                 "정식 26B-A4B MoE — 템플릿/툴콜 보장(검열 있음). 범용·맥락 1순위.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 note="이미지·툴콜"),
    CatalogEntry("gemma4:12b-it-qat", "저사양 에이전트/범용 (QAT)", 8.9,
                 "여유 10GB 안팎 구간. 12B QAT — 저압축에서도 형식 준수 유지.",
                 run_gb=8.9, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 note="형식 안정"),
    CatalogEntry("gemma4:e4b-it-qat", "최저사양 폴백 (QAT)", 9.6,
                 "최저사양 마지막 단계. 다운로드는 9.6GB 지만 활성 파라미터만 올려 "
                 "상주는 ~5GB 다. 도구 호출·비전 내장.",
                 run_gb=5.0, ctx_k=128, vision=True,
                 group="advanced", recommended=False,
                 note="이미지·툴콜"),
    CatalogEntry("gemma4:e4b", "Gemma 초경량 폴백", 9.6,
                 "e4b 정식 태그(비-QAT). 상주 ~5GB.",
                 run_gb=5.0, ctx_k=128, vision=True,
                 group="advanced", recommended=False,
                 note="비-QAT 원본"),
    # ── 무검열 그룹 (번역·창작·검열 없는 범용) ──
    #  CORE 의 ARA 는 "거부율 최저" 로 뽑힌 특수 abliteration 이고, 아래는 크기별
    #  사다리를 메우는 축이다. 예전에는 15GB 와 5GB 사이가 통째로 비어 있어서,
    #  여유 8~14GB 인 PC 는 무검열 작업을 8b 로밖에 못 했다.
    CatalogEntry("huihui_ai/gemma-4-abliterated:26b-qat",
                 "무검열 1순위 (Gemma 4 QAT abliterated)", 18.0,
                 "무검열 + QAT — 검열만 제거하고 양자화 내성은 유지한 26B-A4B. "
                 "멀티모달·256K·툴콜. 무검열 상단에서 형식이 가장 덜 깨진다.",
                 run_gb=18.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 uncensored=True, note="형식 안정"),
    CatalogEntry("huihui_ai/Qwen3.6-abliterated:27b",
                 "무검열 번역·다국어 (Qwen3.6)", 17.0,
                 "무검열 Qwen3.6 27B — Qwen 계열이 한·중·일 토크나이즈가 가장 좋아 "
                 "번역·다국어 작업의 무검열 상단으로 적합. 256K·멀티모달.",
                 run_gb=17.0, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 uncensored=True, note="번역·다국어"),
    # Ollama supports explicit Hugging Face GGUF tags in hf.co/owner/repo:quant form.
    # TrevorJS Q8_0 is ~12.7 GB; Q4_K_M (~7.4 GB) remains an optional fallback.
    CatalogEntry("hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0",
                 "무검열 중간 추천 (TrevorJS Gemma 4 12B Q8_0)", 12.7,
                 "TrevorJS Gemma 4 12B Uncensored — Q8_0 GGUF (8비트). "
                 "다운로드 약 12.7GB, 상주 메모리는 실행 환경·컨텍스트에 따라 "
                 "달라집니다. 12GB GPU에는 일부 CPU 오프로딩이 필요할 수 있습니다.",
                 run_gb=12.7, ctx_k=256, tools=False,
                 uncensored=True, note="중간 추천 · Q8_0"),
    CatalogEntry("hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q4_K_M",
                 "무검열 중간 추가 옵션 (TrevorJS Gemma 4 12B Q4_K_M)", 7.4,
                 "동일 TrevorJS 모델의 Q4_K_M 경량 버전. VRAM 부족 시 선택.",
                 run_gb=7.4, ctx_k=256, tools=False,
                 group="advanced", recommended=False,
                 uncensored=True, note="추가 옵션 · Q4_K_M"),
    CatalogEntry("huihui_ai/qwen3-abliterated:14b", "무검열 중간 (번역 주력)", 9.0,
                 "무검열 14B — 이 체급 무검열 중 가장 최신 세대. 다국어가 강해 "
                 "여유 10~15GB 구간의 번역·범용 주력.",
                 run_gb=9.0, ctx_k=40,
                 group="advanced", recommended=False,
                 uncensored=True, note="다국어"),
    CatalogEntry("huihui_ai/qwen3-vl-abliterated:8b", "무검열 + 이미지", 6.1,
                 "무검열 Qwen3-VL 8B — 이미지 속 글자를 검열 없이 읽고 옮긴다. "
                 "스캔본·스크린샷 번역용. 256K.",
                 run_gb=6.1, ctx_k=256, vision=True, uncensored=True, note="이미지",
                 group="advanced", recommended=False),
    CatalogEntry("dolphin3:8b", "무검열 경량 (파인튜닝)", 5.0,
                 "Dolphin 3.0 (Llama 3.1 8B) — 가중치를 깎는 abliteration 이 아니라 "
                 "무검열 데이터로 재학습한 쪽. 함수 호출·수학까지 무난. 128K.",
                 run_gb=5.0, ctx_k=128, uncensored=True, note="파인튜닝계",
                 group="advanced", recommended=False),
    CatalogEntry("mannix/llama3.1-8b-abliterated:q5_K_M", "무검열 경량 (Llama)", 5.7,
                 "Llama 3.1 8B abliterated — Ollama 에서 가장 많이 받은 abliterated Llama. "
                 "Qwen 이 안 맞을 때의 다른 계열 선택지.",
                 run_gb=5.7, ctx_k=128, uncensored=True, note="다른 계열",
                 group="advanced", recommended=False),
    CatalogEntry("huihui_ai/gemma-4-abliterated:12b", "무검열 경량 (멀티모달)", 7.6,
                 "무검열 12B — 이미지 입력·256K 를 유지한 채 검열만 뺀다. "
                 "저사양에서 문서/이미지까지 다뤄야 할 때.",
                 run_gb=7.6, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 uncensored=True, note="이미지"),
    # ── 코딩 ──
    CatalogEntry("qwen3-coder:30b", "코딩 MoE (속도 우선)", 18.0,
                 "30B-A3B MoE(활성 ~3B) — qwen3.6:27b 보다 품질은 조금 낮지만 훨씬 빠르다. "
                 "긴 에이전트 루프를 자주 돌린다면 이쪽.",
                 run_gb=18.0, ctx_k=256,
                 group="advanced", recommended=False,
                 note="속도 우선"),
    CatalogEntry("devstral-small-2:24b", "에이전트 코딩 특화 (16GB급)", 15.0,
                 "다중파일·디버깅 루프·툴콜링(Apache). 384K 컨텍스트. 18GB 급이 안 뜨는 "
                 "구간의 코딩 1순위.",
                 run_gb=15.0, ctx_k=384, vision=True,
                 group="advanced", recommended=False,
                 note="에이전트 코딩"),
    CatalogEntry("qwen3:14b", "범용+코딩 중간", 9.3,
                 "Qwen3 14B — 대화·코드 도움·리팩터링의 중간 지점. 네이티브 도구 호출.",
                 run_gb=9.3, ctx_k=40, note="범용 겸용",
                 group="advanced", recommended=False),
    CatalogEntry("qwen3:8b", "경량 코딩 (검열본)", 5.2,
                 "Qwen3 8B — 7/8B 급에서 HumanEval 최고. 같은 체급의 abliterated 판은 "
                 "코드블록 형식이 깨진다고 실측돼, 코드 실행에는 이 검열본을 쓴다.",
                 run_gb=5.2, ctx_k=40, note="형식 안정",
                 group="advanced", recommended=False),
    CatalogEntry("qwen2.5-coder:14b", "코딩 중간", 9.0,
                 "코딩 중간 롤백 — 10GB 급에서 코드블록·도구 호출이 안정적이라고 실측된 단계.",
                 run_gb=9.0, ctx_k=32,
                 group="advanced", recommended=False,
                 note="코딩 안정"),
    # ── 사무·문서 (스캔 문서·스크린샷 읽기) ──
    #  한국어 스캔본·표·스크린샷을 읽어야 하는 사무 작업용. Gemma 4 도 이미지를
    #  보지만, CJK 문자 OCR 은 Qwen3-VL 이 확실히 낫다.
    CatalogEntry("qwen3-vl:8b", "문서 OCR·이미지 (한국어)", 6.1,
                 "Qwen3-VL 8B — 한·중·일 문자 OCR 과 손글씨까지. 스캔 PDF·"
                 "스크린샷에서 표와 텍스트를 뽑을 때. 256K.",
                 run_gb=6.1, ctx_k=256, vision=True,
                 group="advanced", recommended=False,
                 note="이미지 OCR"),
    # ── 범용/추론 ──
    CatalogEntry("gpt-oss:20b", "에이전트·추론 (MoE)", 14.0,
                 "OpenAI 오픈(Apache) 21B-A3.6B MoE — 에이전트 작업 겨냥 설계라 도구 호출이 "
                 "깔끔하고 안정적. 추론 강도 low/medium/high 조절 가능.",
                 run_gb=14.0, ctx_k=128,
                 group="advanced", recommended=False,
                 note="추론 강도 조절"),
    CatalogEntry("exaone3.5:7.8b", "한국어 특화 경량", 4.8,
                 "LG EXAONE 3.5 — 한·영 이중언어. 저사양에서 한국어 품질이 필요할 때. "
                 "도구 호출은 기대하지 말 것.",
                 run_gb=4.8, ctx_k=32, tools=False,
                 group="advanced", recommended=False,
                 note="한국어"),
    # ── RAG 임베더 (역할 사다리가 아님) ──
    # AnythingLLM 기본 임베더는 컨테이너 내장(native) 이라 최초 1회 HuggingFace 에서
    # 받는다. 오프라인이거나 한국어 검색 품질이 아쉬우면 아래를 받고
    # config.ANYTHINGLLM_EMBEDDING_ENGINE 을 "ollama" 로 바꾼다.
    CatalogEntry("bge-m3:567m", "RAG 임베더 (한국어·다국어)", 1.2,
                 "100개 이상 언어·8K 컨텍스트 하이브리드 검색. 한국어 문서 RAG 에 권장.",
                 run_gb=1.5, ctx_k=8, tools=False, kind="embed",
                 group="advanced", recommended=False,
                 note="한국어 RAG"),
    CatalogEntry("nomic-embed-text:v1.5", "RAG 임베더 (경량 기본)", 0.3,
                 "가장 가벼운 로컬 임베더(768차원). 영문 위주면 이걸로 충분하다.",
                 run_gb=0.5, ctx_k=8, tools=False, kind="embed",
                 group="advanced", recommended=False,
                 note="가장 가벼움"),
]

# 3단계(상/중/하) × 역할의 '기본단계' 전부. plan_by_level() 결과와 같아야 하고
# tests/test_model_catalog_tiers.py 가 그것을 확인한다.
_CORE_TAGS = frozenset({
    # 상 — 다른 걸 거의 안 띄웠을 때 (14~18GB)
    "gemma4:26b",           # 사무·문서 1순위 (이 예산 안 범용 품질 최고 + 이미지)
    "devstral-small-2:24b",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
    "gpt-oss:20b",
    # 중 — 6~13GB 적재 메모리 범위 (Q8_0 포함)
    "qwen2.5-coder:14b",
    "hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0",
    "gemma4:12b",
    # 하 — 메모리가 빠듯할 때 (5GB 급)
    "gemma4:e4b-it-qat",
    "huihui_ai/qwen3-abliterated:8b",
    "qwen2.5-coder:7b",
})


def _split(entries: List[CatalogEntry]):
    core, advanced = [], []
    for entry in entries:
        if entry.tag in _CORE_TAGS:
            core.append(replace(entry, group="core", recommended=True))
        else:
            advanced.append(replace(entry, group="advanced", recommended=False))
    return core, advanced


CORE, ADVANCED = _split(_ALL)

# 과거/하위 세트 → 새 세트로 대체되어 삭제 권장
REPLACED: List[str] = [
    "gemma-agent-fixed:Q3_K_M",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M",  # Q4_K_S 로 대체
    "devstral-small:24b",     # Ollama 라이브러리에 없던 이름 — devstral-small-2:24b 로 정정
    "deepseek-coder-v2:16b",  # qwen2.5-coder:14b 와 같은 구간, 세대만 더 오래됨
    "qwen2.5:14b",            # gemma4:12b / gpt-oss:20b 로 대체
    "qwen3.5:27b",            # Ollama 도구 호출 결함 보고(#14493) — qwen3.6:27b 사용
    "qwen3.8:27b",            # /v1/chat/completions 무응답 보고 — qwen3.6:27b 사용
    # 아래는 20GB 예산에서 가중치 상한(18.4GB)을 넘어 절대 적재되지 않는다.
    # 목록에 두면 디스크만 먹고 사다리는 매번 그 아래로 떨어진다.
    "gemma4:31b",
    "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q5_K_M",
    "huihui_ai/qwen3-coder-abliterated:30b",
    "qwen3-vl:32b",
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
def level_of(tag_or_gb) -> Optional[str]:
    """모델(또는 GB 수치)이 속한 메모리 등급. 가중치 상한을 넘으면 None."""
    if isinstance(tag_or_gb, str):
        gb = memory_gb(tag_or_gb)
    else:
        gb = float(tag_or_gb)
    if gb is None:
        return None
    for key, _label, lo, hi in LEVELS:
        if lo < gb <= hi:
            return key
    return None


def level_label(key: str) -> str:
    for k, label, _lo, _hi in LEVELS:
        if k == key:
            return label
    return key


def by_level() -> Dict[str, List[CatalogEntry]]:
    """등급 -> 그 등급의 카탈로그 항목(무거운 것부터)."""
    out: Dict[str, List[CatalogEntry]] = {k: [] for k in LEVEL_KEYS}
    for entry in chat_entries():
        key = level_of(entry.tag)
        if key:
            out[key].append(entry)
    for rows in out.values():
        rows.sort(key=lambda e: -e.memory_gb)
    return out


def plan_by_level(budget_gb: Optional[float] = None,
                  tiers: Optional[Dict[str, Sequence[dict]]] = None,
                  ) -> Dict[str, List[str]]:
    """예산 안에서 역할마다 3단계 기본단계를 뽑아 등급별로 묶는다.

    ★ 여기 들어가는 값은 '지금 여유' 가 아니라 이 PC 의 메모리 예산이다.
      브라우저를 켜 둔 채 설치했다고 해서 상 등급을 영영 못 받으면 안 된다.
      실행 시점의 선택만 실제 여유를 본다(model_roles.resolve_ladder).

    대안(alts)은 넣지 않는다 — 같은 등급의 취향 선택이라 기본 설치를 부풀린다.
    """
    budget = MEMORY_BUDGET_GB if budget_gb is None else float(budget_gb)
    ceiling = budget * _SAFETY
    if tiers is None:
        try:
            from . import model_roles as _mr
            tiers = _mr.TIERS
        except Exception:
            tiers = None
    out: Dict[str, List[str]] = {k: [] for k in LEVEL_KEYS}
    if not tiers:
        return out
    table = by_tag()
    seen: Set[str] = set()
    for tier_list in tiers.values():
        for tier in tier_list:
            tag = tier.get("primary")
            entry = table.get(tag)
            if entry is None or tag in seen or entry.memory_gb > ceiling:
                continue
            key = level_of(tag)
            if key:
                seen.add(tag)
                out[key].append(tag)
    for key in out:
        out[key].sort(key=lambda t: -table[t].memory_gb)
    return out


def recommended_for(budget_gb: Optional[float],
                    ladders: Optional[Dict[str, Sequence[Tuple[str, float]]]] = None,
                    ) -> Set[str]:
    """예산에 맞는 기본 설치 세트 = 3단계 기본단계 전부.

    단계를 하나만 받아 두면 여유 메모리가 오르내릴 때 쓸 게 없어지고,
    대안까지 다 받으면 디스크만 먹는다. 그 사이가 이 세트다.
    budget_gb 가 None 이면 정적 recommended 플래그로 폴백한다.
    """
    static = {e.tag for e in all_entries() if e.recommended}
    if budget_gb is None:
        return static
    tiers = None
    if ladders is not None:
        # 사다리만 주어진 경우(테스트) — 평탄 목록에서 등급별 최상단을 고른다.
        ceiling = float(budget_gb) * _SAFETY
        table = by_tag()
        picked: Set[str] = set()
        for rungs in ladders.values():
            per_level: Dict[str, str] = {}
            for tag, _need in rungs:
                entry = table.get(tag)
                if entry is None or entry.memory_gb > ceiling:
                    continue
                key = level_of(tag)
                if key and key not in per_level:
                    per_level[key] = tag
            picked.update(per_level.values())
        return picked or static
    plan = plan_by_level(budget_gb, tiers)
    picked = {tag for tags in plan.values() for tag in tags}
    return picked or static


# ── 설치 여부 대조 ────────────────────────────────────────────────
#  카탈로그에는 대소문자가 섞인 벤더 태그가 있다
#  (prutser/...:Q4_K_S, huihui_ai/Qwen3.6-abliterated:27b).
#  Ollama 가 돌려주는 이름과 대소문자만 달라도 그대로 비교하면 "미설치" 로 보고
#  15GB 짜리를 다시 받는다. 대조는 항상 아래 함수를 거친다.
def find_installed(tag: str, installed) -> Optional[str]:
    """installed 안에서 tag 와 같은 모델을 찾아 '설치된 실제 이름'을 돌려준다."""
    if not tag or not installed:
        return None
    if tag in installed:
        return tag
    wanted = tag.lower()
    for name in installed:
        if str(name).lower() == wanted:
            return name
    return None


def is_installed(tag: str, installed) -> bool:
    return find_installed(tag, installed) is not None


def canonicalize_installed(installed) -> Set[str]:
    """설치 목록을 카탈로그 표기로 정규화한다.

    Ollama 가 돌려준 이름이 카탈로그 태그와 대소문자만 다르면 카탈로그 쪽 철자로
    바꿔 담는다. 그래야 이후의 평범한 `tag in installed` 비교가 전부 맞는다.
    카탈로그에 없는 이름은 그대로 둔다(사용자가 직접 받은 모델).
    """
    known = {t.lower(): t for t in catalog_tags()}
    return {known.get(str(name).lower(), str(name)) for name in (installed or ())}


def download_gb(tags) -> float:
    """받을 태그들의 디스크 합계(GB)."""
    table = by_tag()
    return sum(table[t].size_gb for t in tags if t in table)


__all__ = [
    "CatalogEntry", "CORE", "ADVANCED", "REPLACED", "MARKER",
    "all_entries", "chat_entries", "by_tag", "core_tags", "catalog_tags",
    "memory_gb", "install_pairs", "replaced_tags", "recommended_for", "download_gb",
    "find_installed", "is_installed", "canonicalize_installed",
    "MEMORY_BUDGET_GB", "MAX_MODEL_GB", "LEVELS", "LEVEL_KEYS",
    "level_of", "level_label", "by_level", "plan_by_level",
]
