# Local_AI — 포터블 로컬 LLM 에이전트 환경

> Windows용 **자기완결형 로컬 LLM 스택**. 클라우드 없이 채팅·자동화 에이전트·웹 검색을
> 단일 GUI 런처(`RUN.bat`)에서 제공한다. 모든 사용자 데이터(채팅·설정·로그·에이전트 세션)는
> **`user_data/` 한 곳**에 모이며, 모든 코드 변경은 멱등 패처로 관리된다.

- **실행 환경**: Windows 10/11, Python 3.11+ (권장 3.12.x), Docker Desktop
- **루트 경로 예시**: `C:\Users\ghwork\Works\Local_AI`
- **구동**: `python -m launcher` (GUI) / `python -m installer` (설치) — `RUN.bat`·`MANAGE.bat` 가 감쌈
- **권장 사양**: RAM 약 20GB 가용, VRAM 16GB. 대형 모델은 한 번에 하나만 적재.
- **적용 상태**: `APPLY_ALL.py = v39`(파일 23 + 패치 43) + **`FIX_ALL` 번들**(아래 9-A)
- **채팅 UI**: v41 이후 **Open WebUI → AnythingLLM(Docker)** 로 교체(아래 4-B)
- **네트워크**: **WARP 기본 / Tor 선택 / 직접 연결** 3모드(아래 4-A)
- **도구 계층**: v42 이후 **PreTool 스펙 계층**(`spec`·`tools`·`agent`) 추가 — 도구를 표준 규약으로 노출(아래 6-A)
- **모델 저장소**: `C:\LLM_Models` 로 고정(아래 7-B). 프로젝트 밖이라 백업·이동에 딸려오지 않는다
- **진단 4종**: `DIAG_SEARCH.bat`(검색 9계층) · `TEST_ALL.bat`(패치 코드) · `DIAG_ANYTHINGLLM.bat`(컨테이너 실경로) · `DIAG_TOOLSPEC.bat`(도구 스펙 + 실모델)

---

## 목차
1. 빠른 시작
2. 디렉터리 / 모듈 구조 (상세)
3. 아키텍처 & 데이터 흐름
4. 구성 요소 (Ollama · AnythingLLM · SearXNG · WARP/Tor · 공유 네트워크)
4-A. 인터넷 모드 (WARP / Tor / 직접) ★
4-B. 채팅 UI — AnythingLLM ★신규
5. 에이전트 실행 순서 (agent_chat 파이프라인)
6. PreTool — 에이전트 도구 패키지
6-A. 도구 스펙 계층 — spec · tools · agent ★신규
7. 데이터 저장 구조 (`user_data/`)
7-A. 경로 통합 — user_data 일원화 ★신규
7-B. 모델 저장소 — C:\LLM_Models 고정 ★신규
8. 현재 동작 상태 (해결 / 미해결 / 미검증)
9. 패치 이력
9-A. 통합 도구 — FIX_ALL · TEST_ALL · DIAG_* · CLEAN_LOCAL_AI ★
10. 설정 · 패치 규약
11. 문제 해결 / 다음 단계

---

## 1. 빠른 시작

```bat
:: 프로젝트 루트에서
FIX_ALL.bat --test            :: ★통합 점검·수정 (번들 전개 → 진단 → 적용 → 검증 → 정밀 테스트)
RUN.bat                       :: GUI 런처 (채팅 UI / 에이전트)
MANAGE.bat                    :: 설치·모델 관리 대시보드

:: 진단 (문제 생기면)
TEST_ALL.bat                  :: 패치된 코드 자체 검증 (Docker 불필요)
DIAG_ANYTHINGLLM.bat --full   :: 컨테이너가 실제로 어디로 나가는지 (컨테이너 기동 상태에서)
DIAG_SEARCH.bat               :: 검색 파이프라인 9계층
```

**첫 실행 순서**

1. `FIX_ALL.bat --test` → rc=0 확인
2. **런처를 완전히 종료**했다가 `RUN.bat` 재기동 (컨테이너가 새 설정으로 다시 만들어진다)
3. `[1] 채팅 UI (AnythingLLM)` → 인터넷 모드 선택 → 브라우저 `http://localhost:3001`
4. 최초 1회 설정 마법사 (LLM=Ollama, 벡터DB=LanceDB 가 이미 채워져 있다)

> 컨테이너를 패널 종료 후에도 남기려면 `set LOCAL_AI_ANYTHINGLLM_KEEP=1` 를 먼저 준다.
> `DIAG_ANYTHINGLLM.bat` 은 컨테이너가 떠 있어야 검사할 수 있다.

---

## 2. 디렉터리 / 모듈 구조 (상세)

```
Local_AI/
├── RUN.bat                     python -m launcher (GUI 런처)
├── MANAGE.bat                  python -m installer (설치/관리 대시보드)
├── APPLY_ALL.bat / .py         멱등 일괄 패처 (파일 배치 + 43 패치)
│
├── FIX_ALL.bat / .py           ★통합 점검·수정. 아래 4개 도구를 내장(gzip+base64, SHA-256 검증)
├── PATCH_ANYTHINGLLM.py        ★Open WebUI → AnythingLLM 교체 패처 (REV=8)
├── PATCH_HOST_MINILOOP.py      ★호스트 직접 모드의 Open Interpreter 제거 (REV=2)
├── TEST_ALL.bat / .py          ★패치된 코드 정밀 테스트 (v3, Docker 불필요)
├── DIAG_ANYTHINGLLM.bat / .py  ★AnythingLLM 실경로 진단 (v4)
├── DIAG_SEARCH.bat / .py       검색 파이프라인 계층 진단(9단계 + 마커 스캔)
├── APPLY_PRETOOL_SPEC.bat/.py  ★도구 스펙 계층 설치 (REV=5, 신규 파일 3개만 배치)
├── DIAG_TOOLSPEC.bat / .py     ★도구 스펙 진단 (REV=3, 정적 검사 + 실모델 3군 측정)
├── APPLY_PATH_UNIFY.bat/.py    ★경로 통합 + 잔재 정리 (REV=4, 기본 dry-run)
├── DIAG_PROJECT.bat / .py      ★프로젝트 전수 감사 (REV=2, 읽기 전용, 10계층)
├── CLEAN_LOCAL_AI.bat / .py    ★증거 기반 정리 + 개인 데이터 점검 (REV=5)
├── MODEL_HOME.bat / .py        ★모델 저장소 고정·복구 (그냥 실행하면 끝)
├── DIAG_MODEL_PATH.bat / .py   ★모델 경로·연결 검증 (읽기 전용, 4계층)
├── APPLY_DEAD_CONSTS.bat/.py   ★참조 0 상수 제거 (AST + 런타임 재검증)
├── APPLY_MANAGE_MODELPATH.*    ★MANAGE.bat 에 모델 위치 표시 삽입
├── README.md
│
├── launcher/                   ── GUI 런처 패키지 ──
│   ├── __init__.py __main__.py app.py   부트스트랩/진입
│   ├── config.py               상수: MODEL_TAG, OLLAMA_PORT(11434), SANDBOX_IMAGE,
│   │                           NET_MODE/WARP/TOR, ★ANYTHINGLLM_* 정본
│   ├── i18n.py                 다국어 문자열
│   ├── runtime_guard.py        런타임 가드(컨텍스트 길이 산출)
│   ├── anythingllm_runtime.py  ★AnythingLLM 컨테이너 수명주기 (패처가 생성)
│   │                           start/stop/pull/wait_ready/build_run_cmd/
│   │                           config_signature/proxy_env_for_container/
│   │                           write_node_proxy_bootstrap/register_exit_cleanup
│   ├── tor_runtime.py          Tor 컨테이너 수명주기 (NET_MODE!=tor 면 기동 생략)
│   ├── warp_runtime.py         WARP 컨테이너(llm_warp, SOCKS5 1080) + 브리지 보장
│   ├── http_bridge.py          HTTP→SOCKS5 브리지(llm_httpbridge:8118)
│   ├── searxng_runtime.py      SearXNG 컨테이너 수명주기 (--network llm_net)
│   │
│   ├── core/                   ── 인프라 ──
│   │   ├── lifelog.py          런처 로그 · 종료 cleanup 등록/실행 · 고아 컨테이너 정리
│   │   ├── user_data.py        user_data 경로 해석
│   │   ├── settings_store.py   설정 영속(user_config.json)
│   │   └── docker_maint.py     Docker 정리(★AnythingLLM 패턴 등록됨)
│   │
│   ├── models/                 model_catalog.py · model_roles.py · model_classes.py
│   │
│   ├── agent/                  ── 에이전트 ──
│   │   ├── agent_runner.py     docker run 구성 + 미니루프(b64 REPL)
│   │   │                       ★build_host_miniloop_cmd/env (호스트 모드용)
│   │   ├── agent_lifecycle.py  수명주기(start/stop/poll)
│   │   ├── entry_dialog.py     통합 진입 다이얼로그
│   │   ├── folder_policy.py    허용/금지 폴더 정책
│   │   └── profiles.py         프로필 → 역할/시스템메시지
│   │
│   ├── actions/                ── 메뉴 액션 ──
│   │   ├── chat.py             ★[1] 채팅 UI — AnythingLLM (원본 run 은 _ANYLLM_ORIG_RUN 로 보존)
│   │   ├── agent_chat.py       [2] 에이전트 채팅(GUI)
│   │   ├── agent_direct.py     [3] 호스트 직접 — ★미니루프(OI 불필요)
│   │   ├── agent_sandbox.py    샌드박스 에이전트
│   │   ├── _sandbox_options.py 진입 옵션
│   │   ├── ollama.py searxng.py docker_clean.py docker_image.py
│   │   ├── model_info.py model_manage.py settings.py manage_gui.py
│   │
│   ├── presenter/              base.py · tui.py · gui/(window, presenter, chat_panel,
│   │                           sidebar, menu_panel, panels, dialogs, statusbar, theme, widgets)
│   └── services/               docker.py(DockerService) · ollama.py
│
├── installer/                  ── 설치/관리 패키지 ──
│   ├── manage_gui.py           MANAGE 대시보드
│   ├── i18n.py lang_setup.py resources.py utils.py
│   ├── core/                   console.py download.py filesystem.py preflight.py
│   └── steps/                  model.py ollama.py sandbox.py searxng.py warp.py
│       └── python_tools.py     ★install_open_webui → AnythingLLM 이미지 pull 로 교체
│                                (호출 지점은 그대로, 내용만 교체)
│
├── PreTool/                    ── 에이전트 도구(컨테이너에 마운트) ──
│   ├── __init__.py search.py excel.py report.py files.py dev.py data.py
│   ├── spec.py                 ★스펙 생성기 — JSON Schema + openai/mcp/anthropic
│   │                           어댑터 · call() · recover()
│   ├── tools.py                ★선언 레지스트리 — 타입/노출이름/safe 등급 (원함수 무변경)
│   ├── agent.py                ★Ollama 자체 tool-calling 루프
│   └── sitecustomize.py        PYTHONPATH 자동 실행 → PreTool 함수를 builtin 으로 주입
│
└── user_data/                  ── 사용자 데이터(영속) ──
    ├── settings/               user_config.json, folder_policy.json
    ├── anythingllm/            ★AnythingLLM 저장소 (DB·벡터·문서)
    │   ├── .env                최초 1회만 심음(UI 설정이 되쓰기됨)
    │   └── proxy-bootstrap.js  ★Node fetch 프록시 우회 (프록시 모드에서만 존재)
    ├── chat/                   (구) Open WebUI DB — 사용 안 함, --purge 로 보관 이동
    ├── logs/                   launcher_*.log · fix_all_*.log · test_all_*.log · diag_*.log
    └── interpreter/sandbox/    에이전트 세션 + PreTool/ + sitecustomize.py
```

---

## 3. 아키텍처 & 데이터 흐름

### Presenter 패턴
UI(Tkinter)와 로직을 분리한다. 액션(`actions/*`)은 `Presenter` 인터페이스에만 의존하고,
실제 구현은 `TkPresenter`(GUI) / `TerminalPresenter`(TUI)가 담당.

> **패널 교체 규칙(중요)** — `p.section()` 은 새 로그 패널을 만들어 화면에 올리고,
> `p.show_menu()` 는 화면을 메뉴 패널로 교체한다. `_ensure_log()` 는 현재 로그 패널이
> `None` 일 때만 새로 만들기 때문에, **`show_menu()` 를 부른 뒤에는 반드시 `section()` 으로
> 로그 패널을 다시 열어야 한다.** 순서가 반대면 이후 출력이 보이지 않는 패널에 쌓여
> "메뉴에서 멈춘 것처럼" 보인다(실제로 겪은 버그, `TEST_ALL` T6 가 상시 검사).

### 네트워크 토폴로지
```
[Ollama] 호스트 프로세스 11434 ←─ (host.docker.internal, NO_PROXY 직접) ─┬ [에이전트 컨테이너]
                                                                        └ [llm_anythingllm]
                                                                              │ (llm_net)
 warp 모드(기본)                                                              │
   [llm_httpbridge] 8118 HTTP ──SOCKS5──▶ [llm_warp] 1080 ──▶ Cloudflare ──▶ 인터넷
        ▲ HTTP_PROXY (urllib · Node · Chromium 이 쓰는 경로)                  │
 tor 모드(선택)                                                                │
   [llm_tor] 9050 SOCKS / 8118 HTTP(Privoxy) ──▶ Tor 네트워크 ──▶ 인터넷        │
 direct 모드                                                                   │
   프록시 없음 (내 IP 그대로 노출)                                              │
 공통                                                                          │
   [llm_searxng] 내부 8080 ──llm_net── 검색(프록시 우회) ──────────────────────┘
        └ outgoing(엔진 조회)은 socks5h://llm_warp:1080 또는 llm_tor:9050
```
- **Ollama(호스트 프로세스)** 는 `host.docker.internal` 로 도달(정상).
- **다른 컨테이너의 게시 포트는 `host.docker.internal` 로 도달 불가** → `llm_net` + 컨테이너 이름.

### 데이터 흐름
1. **모델 호출**: AnythingLLM / 미니루프 → `host.docker.internal:11434`(NO_PROXY 직접) → Ollama.
2. **웹 검색(에이전트)**: `web_search` → `llm_searxng:8080` → outgoing 프록시 → 검색 엔진.
3. **웹 검색(채팅 UI)**: `@agent` 스킬 → `AGENT_SEARXNG_API_URL=http://llm_searxng:8080`.
4. **문서 RAG**: 업로드 → 임베딩(native/Xenova 또는 Ollama) → LanceDB(`user_data/anythingllm`).
5. **대화 로깅**: 에이전트는 런처 로그(IO_LOG), AnythingLLM 은 자체 DB.

---

## 4. 구성 요소

| 구성 | 역할 | 컨테이너/포트 | 런타임 모듈 |
|------|------|------|------|
| **Ollama** | 모델 서버(호스트 프로세스) | `:11434` | `services/ollama.py` |
| **AnythingLLM** ★ | 브라우저 채팅 + 문서 RAG + @agent | `llm_anythingllm` (3001) | `anythingllm_runtime.py` |
| **에이전트 미니루프** | Docker 샌드박스 REPL | `llm_agent_chat_*` (`llm-agent-sandbox`) | `agent/agent_runner.py` |
| **SearXNG** | 로컬 메타검색(JSON) | `llm_searxng` (내부 8080) | `searxng_runtime.py` |
| **WARP** 기본 | IP 보호 프록시(SOCKS5 전용) | `llm_warp` (1080) | `warp_runtime.py` |
| **HTTP 브리지** | urllib·Node 용 HTTP→SOCKS5 변환 | `llm_httpbridge` (8118) | `http_bridge.py` |
| **Tor + Privoxy** | 최고 익명 프록시(선택) | `llm_tor` (9050/8118) | `tor_runtime.py` |
| **공유 네트워크** | 컨테이너 간 이름 통신 | `llm_net` | AGENT_NET/NET_CONNECT |

- **종료 정리**: `llm_warp` · `llm_httpbridge` · `llm_tor` · **`llm_anythingllm`** 은 런처 종료 시 자동 제거.
  `llm_anythingllm` 은 **lifelog 의 고아 컨테이너 패턴에 걸리지 않으므로**
  `anythingllm_runtime.register_exit_cleanup()` 이 직접 등록한다(빠뜨리면 컨테이너가 남는다).
- **`docker stop -t 3`** — `-t` 를 안 주면 도커 기본 10초를 매 종료마다 기다린다.

---

## 4-A. 인터넷 모드 (WARP / Tor / 직접) ★

에이전트 진입 다이얼로그와 **채팅 UI 진입 시** 각각 고른다. 선택은 `config.NET_MODE` 에 반영되고
프록시 주소·컨테이너 기동·라벨·SearXNG outgoing 이 전부 그 값을 따라간다.

| 모드 | 나가는 경로 | 특징 |
|------|-------------|------|
| `warp`(기본) | Cloudflare 엣지 IP | 빠르고 차단 적음 |
| `tor` | Tor 출구 노드 | 가장 익명적이나 느리고 차단 많음 |
| `direct` | 프록시 없음 | 내 IP 그대로 노출 |

환경변수로 프롬프트를 건너뛸 수 있다: `set LOCAL_AI_ANYTHINGLLM_NET=warp|tor|direct`.

### HTTP 브리지가 필요한 이유
WARP 는 **SOCKS5 만 제공**한다. 그런데 PreTool 은 `urllib`, AnythingLLM 은 Node 를 쓰는데
**둘 다 SOCKS 를 못 쓴다.** 그래서 WARP 앞에 HTTP 프록시를 한 단 세운다.

```
urllib / Node / Chromium --HTTP--> llm_httpbridge:8118 --SOCKS5--> llm_warp:1080 --> 인터넷
```
호스트명 해석은 SOCKS 서버가 수행하므로 `socks5h` 와 동등(DNS 유출 없음).

### 주입되는 프록시 환경변수

| 변수 | warp | tor | direct |
|------|------|-----|--------|
| `HTTP_PROXY` / `HTTPS_PROXY` | `http://llm_httpbridge:8118` | `http://llm_tor:8118` | 없음 |
| `NO_PROXY` | `host.docker.internal, localhost, 127.0.0.1, ::1, llm_searxng, llm_httpbridge, llm_warp, llm_tor, llm_anythingllm` | 동일 | — |
| `ALL_PROXY` | **주입하지 않음** | **주입하지 않음** | — |

> **`ALL_PROXY` 를 일부러 뺀 이유** — `config.net_proxy_env()` 는 파이썬용으로
> `ALL_PROXY=socks5h://...` 를 함께 준다. 그런데 Node 에는 SOCKS 클라이언트가 없고,
> axios 가 쓰는 `proxy-from-env` 는 `ALL_PROXY` 를 읽어 `socks5h://` 를 HTTP 프록시로
> 취급한다 → **전 요청 실패**. 그래서 AnythingLLM 컨테이너에는 HTTP 프록시만 넣는다.
> `TEST_ALL` 이 세 모드 모두에서 `ALL_PROXY` 미주입을 상시 검사한다.

---

## 4-B. 채팅 UI — AnythingLLM ★신규

### 왜 바꿨나
Open WebUI 는 pip venv 가 **약 2.2GB**, 설치에 5~20분이 걸렸다. AnythingLLM 은 Docker 컨테이너라
이 프로젝트의 기존 구조(SearXNG·WARP·Tor·에이전트가 전부 컨테이너)와 그대로 맞물리고,
설치가 `docker pull` 하나로 끝난다. 문서 RAG(LanceDB)도 기본 제공한다.

### 실행
`RUN.bat` → `[1] 채팅 UI (AnythingLLM)` → 인터넷 모드 선택 → `http://localhost:3001`

기동 절차: Ollama 확인 → Docker 데몬 확인(필요시 자동 시작) → 이미지 확인/pull(3~5GB) →
SearXNG 기동 → 프록시 스택 기동 → 컨테이너 기동 → HTTP 응답 대기.
대기 중에는 **8초마다 경과·health·컨테이너 로그 꼬리**가 표시된다(최초 1~3분).

### 컨테이너 구성

| 항목 | 값 |
|------|-----|
| 이미지 | `mintplexlabs/anythingllm:latest` |
| 이름 / 포트 | `llm_anythingllm` / `3001:3001` |
| 저장소 | `user_data/anythingllm` → `/app/server/storage` |
| 설정 파일 | `user_data/anythingllm/.env` → `/app/server/.env` |
| 권한 | `--cap-add SYS_ADMIN` (내장 Chromium 문서 스크래핑용) |
| 라벨 | `local_ai_netmode` · `local_ai_cfgsig` |

**`.env` 는 최초 1회만 심는다.** AnythingLLM 이 UI 설정을 이 파일에 되쓰기 때문에,
매번 덮어쓰면 사용자가 UI 에서 바꾼 값이 날아간다. 다시 심으려면
`anythingllm_runtime.reseed_env()`.

### 설정 서명(`local_ai_cfgsig`) — 낡은 컨테이너 자동 재생성
이미지·포트·마운트·프록시 env·Chromium 인자·`NODE_OPTIONS` 를 해시해 라벨로 박아 둔다.
다음 기동 때 값이 다르면 **컨테이너를 자동으로 다시 만든다.** 메모리/CPU 는 `auto` 라
매번 달라질 수 있어 서명에서 제외한다.

```
컨테이너를 다시 만듭니다 — 설정이 바뀜 (abb97176cb60 -> fa25c793be77)
컨테이너를 다시 만듭니다 — 네트워크 모드 warp -> tor
컨테이너를 다시 만듭니다 — 설정 서명이 없는 구버전 컨테이너
```

> 이 장치가 없으면 패치를 올려도 `KEEP=1` 로 살아 있는 낡은 컨테이너가 그대로 재사용되어
> 새 설정이 영원히 반영되지 않는다(실제로 겪은 버그).

### Node 18 프록시 우회 (`proxy-bootstrap.js`)
이미지의 Node 는 **v18.20.8**. Node 내장 `fetch` 는 기본적으로 `HTTP_PROXY` 를 무시하고,
`NODE_USE_ENV_PROXY` 는 **v22.21+ / v24+ 에서만** 동작한다. 그래서 우회 장치를 넣는다.

```
storage/proxy-bootstrap.js  ←  NODE_OPTIONS=--require /app/server/storage/proxy-bootstrap.js
   설치된 undici 의 ProxyAgent 를 전역 디스패처로 꽂는다
   (/app/server/node_modules/undici, /app/collector/node_modules/undici 확인됨)
```

- **`NO_PROXY` 를 존중하는 라우팅 디스패처**다. AnythingLLM 의 Ollama 호출도 `fetch` 를 쓰므로,
  전부 프록시로 몰면 `host.docker.internal` 이 프록시 너머에서 해석되지 않아 **모델 호출이 죽는다.**
- `undici.Dispatcher` 는 ES class 라 ES5 방식으로 상속하면
  `Class constructor Dispatcher cannot be invoked without 'new'` 로 기동이 실패한다 →
  **상속하지 않고 평범한 객체**로 만든다.
- undici 를 못 찾으면 조용히 아무것도 하지 않는다(앱은 정상 기동).
- `direct` 모드에서는 파일을 지우고 `NODE_OPTIONS` 도 넣지 않는다.

### Open WebUI 와 다른 점 (실사용 차이)

| 항목 | Open WebUI | AnythingLLM |
|------|-----------|-------------|
| 웹 검색 | 일반 대화에서 자동 | **`@agent 질문` 으로 호출해야 동작** |
| 첫 실행 | 무설정 진입 | 설정 마법사 1회(LLM/임베더/벡터DB/워크스페이스) |
| 임베딩 | 내장 | `native`(Xenova/all-MiniLM-L6-v2) — **최초 1회 HuggingFace 다운로드** |
| 대화 기록 | `user_data/chat` | `user_data/anythingllm` — **스키마가 달라 이전 불가** |
| 포트 | 8080 | 3001 |

> 가장 큰 후퇴는 **웹 검색이 `@agent` 호출 방식으로 바뀐 것**이다.
> 오프라인이면 `.env` 에서 `EMBEDDING_ENGINE="ollama"` +
> `EMBEDDING_BASE_PATH="http://host.docker.internal:11434"` +
> `EMBEDDING_MODEL_PREF="nomic-embed-text:latest"` 로 바꾸고
> 호스트에서 `ollama pull nomic-embed-text` 를 먼저 한다.

### 되돌리기 / 스위치

| 환경변수 | 효과 |
|----------|------|
| `LOCAL_AI_CHAT_ENGINE=openwebui` | 원래 Open WebUI 경로로 복귀(venv 가 남아 있을 때만) |
| `LOCAL_AI_ANYTHINGLLM_KEEP=1` | 패널을 나가도 컨테이너 유지 |
| `LOCAL_AI_ANYTHINGLLM_NET` | `warp`/`tor`/`direct` — 모드 프롬프트 생략 |
| `LOCAL_AI_ANYTHINGLLM_MEM` / `_CPUS` | `auto` 대신 고정(`4g` / `2`) |
| `LOCAL_AI_ANYTHINGLLM_PORT` / `_IMAGE` / `_CONTAINER` / `_EMBED` / `_BOOT_TIMEOUT` | 각 항목 오버라이드 |

코드 전체 되돌리기는 `FIX_ALL.bat --undo`.

---

## 5. 에이전트 실행 순서 (agent_chat 파이프라인)

`_run_gui_chat_unified` 는 `agent.start(cmd)` 앞에서 아래를 순서대로 수행한다.

1. **NETMODE_LOG** — `[인터넷] WARP 경유 (빠름) …` 표시
2. **Docker 게이트** — 데몬 확인/자동시작
3. **DOCKER_READY** — `docker ps` 성공까지 대기
4. **OLLAMA_READY** — Ollama(11434) 응답까지 대기
5. **SEARXNG_AUTOSTART** — 로컬 SearXNG 기동
5-1. **프록시 기동** — `NET_MODE` 에 따라 `warp_runtime`(+브리지) 또는 `tor_runtime`
6. **AGENT_NET** — `llm_net` 생성 + `--network llm_net` + 프록시 env 주입
7. **NET_CONNECT / NET_LOG** — 모드별 컨테이너를 `llm_net` 에 연결
8. **SYSMSG_FILE** — 긴 시스템 메시지를 `@FILE:` 로 → WinError 206 방지
9. **PRETOOL_PATH** — `-e PYTHONPATH=/home/agent/.agent_state`
10. **PRETOOL_SYNC** — PreTool/sitecustomize 를 실제 마운트 폴더로 복사
11. **agent.start(cmd)** → 실패 시 **AGENT_RETRY**(2회) → **START_DIAG/DIAG2**

### 호스트 직접 모드 — Open Interpreter 제거 (`HOST_MINILOOP_v1`)
**샌드박스 모드에는 이미 Open Interpreter 가 없다**(`agent_repl.py v9.3, MINILOOP_v1` —
Ollama `/api/chat` 직접 호출 기반 단일 스텝 코드 에이전트). OI 가 남아 있던 곳은
**호스트 직접 모드뿐**이었고, `PATCH_HOST_MINILOOP` 가 이를 제거한다.

- 샌드박스와 **동일한 미니루프**(`_AGENT_REPL_BOOTSTRAP`)를 docker 없이 호스트 파이썬으로 실행
- stdin/stdout 계약이 같으므로 `UnifiedAgent` 는 수정하지 않는다
- `pythonw.exe` 는 stdout 을 PIPE 로 못 내보내므로 같은 폴더의 `python.exe` 를 우선
- 미니루프가 `python3 -c` 를 쓰면 Windows 에는 없으므로 `python3.exe` 하드링크를 만든다
- 스위치: `LOCAL_AI_HOST_ENGINE=oi`(원본 사용) · `LOCAL_AI_HOST_AUTORUN=1`(코드 자동실행 허용,
  호스트는 격리가 없으므로 기본 off)

---

## 6. PreTool — 에이전트 도구 패키지

| 범주 | 함수 |
|------|------|
| 검색 | `web_search(q)` · `search_summary(q)` · `fetch_text(url)` · `net_diag()` |
| 엑셀/표 | `excel_write(path, rows, headers)` · `csv_write` · `read_table` |
| 문서 | `report_write(path, title, sections)` |
| 파일 | `move` · `copy` · `list_files` · `organize_by_ext` |
| 개발 | `run_tests` · `check_syntax` · `run_python` · `lint` · `outline` · `diff` · `complexity` |
| 데이터 | `calc` · `json_pretty` · `json_query` · `summarize_text` · `word_stats` |

- **순수 stdlib** — 샌드박스에서 pip 불필요.
- **import 없이 호출** — `sitecustomize` 가 `PreTool.__all__` 을 builtin 으로 주입.
- **검색 경로** — `web_search` 는 SearXNG(JSON)→SearXNG(HTML)→DuckDuckGo 3단 폴백.
- 전체 목록: `import PreTool; print(PreTool.catalog())`.

> 위 표와 `catalog()` 는 실제 시그니처와 어긋난 곳이 있다(예: 실제로는
> `report_write(path, title, sections, fmt=None)`, 표에 없는 `open_url`·`page_links`·`research` 존재).
> **6-A 의 스펙 계층은 코드에서 직접 뽑으므로 이 드리프트가 없다.**

---

## 6-A. 도구 스펙 계층 — spec · tools · agent ★신규

PreTool 함수들을 **일반적인 AI 에이전트 도구 규약**으로 노출하는 계층.
`APPLY_PRETOOL_SPEC.bat` (마커 `PRETOOL_SPEC_v1`, REV=5) 가 신규 파일 3개만 배치하며
**기존 파일은 하나도 수정하지 않는다.** 되돌리기는 `--undo`.

### 왜 필요했나
도구 메타데이터가 `__all__` · `catalog()` · base64 시스템 프롬프트 세 곳에 흩어져 있었고,
하나를 추가하면 세 곳을 손으로 맞춰야 했다. 그것이 프롬프트 드리프트의 원인이었다.
이 계층은 **코드를 단일 출처로 삼는다.**

- 타입 → `tools.py` 가 선언
- 설명 → 원함수 독스트링에서 자동 추출(없으면 `_DESC` 가 공급)
- `required` → 실제 시그니처의 기본값 유무에서 자동 판정

### 원함수를 건드리지 않는 이유
선언 스키마는 **실제 허용 입력의 부분집합**이어도 된다. 원함수는 계속 유연 입력을
받고, 레지스트리는 그중 일부만 노출한다. 선언하지 않은 인자는 모델에게 보이지 않고
보내도 거부된다 — 예를 들어 `report_write` 의 `fmt` 를 선언하지 않았으므로
모델은 출력 형식을 바꿀 수 없다(확장자로만 결정).

`register()` 는 선언을 `inspect.signature` 로 실제 함수와 대조한다.
어긋나면 그 도구만 등록하지 않고 `spec.problems()` 에 사유를 남긴다.

### 노출 현황 (등록 22 / 안전 15 / 부수효과 7)

| 노출 이름 | 구현 | 비고 |
|-----------|------|------|
| `web_search` | `web_search` | 통용 명칭 그대로 |
| `web_fetch` | `open_url` | 벤더·MCP 레퍼런스가 공유하는 이름으로 노출 |
| `web_research` | `research` | 검색 + 본문 읽기 |
| `web_links` | `page_links` | 링크 추출 |

**노출 제외**: `search_summary` · `search_urls` · `fetch_text` (`web_search`/`web_fetch` 와
입력이 같고 출력 형식만 달라 모델이 고를 근거가 없음), `net_diag` (사람이 보는 진단).
넷 다 코드블록 miniloop 에서는 `PreTool.search` 로 그대로 쓸 수 있다.

**부수효과 7개**(`move`·`copy`·`organize_by_ext`·`run_python`·`report_write`·`excel_write`·`csv_write`)는
`safe_only=False` 를 줄 때만 노출·실행된다. 기본은 안전 15개.

**미등록**: `run_tests`(`cases` 가 튜플 구조라 JSON 표현 미정) · `diff`(`_src()` 가 문자열을
코드로도 경로로도 해석해 모델이 의도를 지정할 수 없음).

### 사용

```python
from PreTool.spec import specs, to_openai, to_mcp, to_anthropic, call

specs()                              # 안전 15개
specs(safe_only=False)               # 전체 22개
[to_openai(s) for s in specs()]      # OpenAI / Ollama /api/chat
[to_mcp(s) for s in specs()]         # MCP tools/list
call("calc", {"expr": "2*(3+4)**2"})  # -> {'ok': True, 'data': 98}
```

`call()` 은 예외를 밖으로 던지지 않고 항상 `{'ok', 'data'|'error'}` 로 돌아온다.

```bat
py -3 -m PreTool.agent --model qwen2.5-coder:14b "오늘 코스피 지수 알려줘"
py -3 -m PreTool.agent --model qwen2.5-coder:14b --all "이 폴더 정리해줘"
```

환경변수 `OLLAMA_HOST`(기본 `http://127.0.0.1:11434`) · `PRETOOL_AGENT_MODEL`(기본 `qwen2.5-coder:14b`).

### `recover()` — 도구 호출이 본문으로 새는 문제

`DIAG_TOOLSPEC` 실측에서 `qwen2.5-coder:14b` + Ollama 0.32.14 의 도구 선택률이 **0%** 로 나왔다.
그런데 응답 **본문**에는 이렇게 들어 있었다.

```
{"name": "web_search", "arguments": {"query": "오늘 코스피 지수", "n": 1}}
```

**모델은 9/9 올바른 도구를 올바른 인자로 골랐다.** 이스케이프까지 정확했다.
깨진 것은 선택이 아니라 `tool_calls` 승격 한 곳뿐 — 모델이 `<tool_call>` 태그 없이
맨 JSON 을 뱉어 Ollama 파서가 받지 못했다.

3군 통제 실험으로 배제된 가설: 시스템 메시지(A0=A 동일), 언어(영어도 실패),
도구 개수(1개여도 실패), 스펙 품질(선택은 100% 정확),
모델 미지원(`capabilities` 에 `tools` 있음, 템플릿 `.Tools` 참조 True).

Ollama + qwen2.5-coder 조합에서 널리 보고된 문제이며(7b·14b·32b 동일),
여러 프로젝트가 같은 처방에 도달했다 — **`tool_calls` 가 비면 본문의
`{"name":…, "arguments":{…}}` 를 파싱하는 폴백**. 그것이 `recover()` 다.

```python
from PreTool.spec import recover
recover('{"name":"calc","arguments":{"expr":"1+1"}}')   # -> [('calc', {'expr': '1+1'})]
```

`<tool_call>` 태그 · 코드펜스 · 맨 JSON · 앞뒤 설명 혼재 · 복수 호출 · `function` 래핑 ·
`arguments` 가 문자열 — 7형태를 처리하고, **레지스트리와 대조**해 확인된 것만 돌려준다.
미등록 이름 · 쓰기 도구 · 선언 안 된 인자 · 일반 JSON · 산문은 전부 거부한다.

`agent.py` 는 복구한 호출을 **정규 `tool_calls` 형태로 재구성해서** 대화에 넣는다.
그래야 다음 턴에 모델이 자기 호출 이력을 템플릿대로 읽는다.

```
user       "2*(3+4)**2 계산해줘"
assistant  [{"function": {"name": "calc", "arguments": {"expr": "2*(3+4)**2"}}}]
tool       "98"
```

### 도구를 추가하려면
`PreTool/tools.py` 의 `_TABLE` 에 한 줄. 원함수는 건드리지 않는다.

```python
("모듈명", "함수명", safe여부, "범주", {"인자": "타입"}),
```
타입은 `"string"` `"integer"` `"number"` `"boolean"` `"array"` `"object"` `"any"`
또는 완전한 JSON Schema dict. 독스트링이 없으면 `_DESC`, 통용 명칭으로 노출하려면 `_NAME`.
추가 후 `DIAG_TOOLSPEC.bat` 으로 확인 — 선언이 어긋나면 그 도구만 드롭되고 사유가 나온다.

---

## 7. 데이터 저장 구조 (`user_data/`)

```
user_data/
├── settings/        user_config.json, folder_policy.json
├── anythingllm/     ★AnythingLLM 저장소
│   ├── .env             최초 1회 생성 (UI 설정이 되쓰기됨)
│   ├── proxy-bootstrap.js   프록시 모드에서만 존재
│   └── (DB · LanceDB 벡터 · 업로드 문서)
├── chat/            (구) Open WebUI — 사용 안 함
├── logs/            launcher_*.log · fix_all_*.log · test_all_*.log ·
│                    diag_anythingllm_*.log · patch_anythingllm_*.log
└── interpreter/
    └── sandbox/     세션 session_*.json + PreTool/ + sitecustomize.py
```
폴더째 복사하면 다른 PC로 이식 가능.

> **알려진 경로 불일치** — 런처 로그는 루트 `user_data/logs` 로 가는데
> `core.user_data.chat_dir()` 는 `launcher/user_data` 를 가리켜, AnythingLLM 저장소가
> `launcher/user_data/anythingllm` 에 생긴다. 동작에는 지장 없으나 데이터가 두 군데로 갈린다.
> 기존 코드 쪽 사안이며 별도 정리 대상.

---

## 7-A. 경로 통합 — user_data 일원화 ★신규

`APPLY_PATH_UNIFY.bat` (마커 `PATH_UNIFY_v1`, REV=4) 로 적용 완료.

### 무엇이 문제였나
같은 유형의 off-by-one 이 **두 곳**에 있었다. 파일을 하위 폴더로 옮기면서
`.parent` 횟수를 따라 고치지 않은 것이다.

| 파일 | 위치 | 이전 식 | 반환값 |
|------|------|---------|--------|
| `launcher/core/user_data.py` | `core/` 하위 | `.parent.parent` | **`launcher/`** ✗ |
| `launcher/agent/folder_policy.py` | `agent/` 하위 | `.parent.parent` | **`launcher/`** ✗ |
| `launcher/__main__.py` (대조군) | `launcher/` | `.parent.parent` | 루트 ✓ |

그 탓에 세션·AnythingLLM 저장소·설정이 `launcher/user_data/` 로 가고,
런처 로그·`registry.json` 은 루트 `user_data/` 로 가서 **데이터가 두 갈래**였다.
`launcher/settings` 정션은 루트를 향하는데 `settings_dir()` 는 `launcher/` 를
반환해 설정만 **세 곳**이었다.

### 적용 후 (실측)
```
[OK] user_data.root()                   user_data
[OK] user_data.settings_dir()           user_data\settings
[OK] user_data.logs_dir()               user_data\logs
[OK] user_data.interpreter_dir()        user_data\interpreter\sandbox
[OK] folder_policy._store_path()        user_data\settings\folder_policy.json
launcher/user_data                      (없음)
```
`settings_dir()` 가 `launcher/settings` 정션의 타깃과 일치한다.

### 함께 정리된 것
- `lifelog.open_session_log()` 의 이중 join 제거 (`FIX_v1` 위에 `FIX_v2` 가 겹친 잔재)
- `app.py` 메뉴 라벨 `Open WebUI` → `AnythingLLM`
- `.gitignore` 에 `/launcher/user_data/` · `session_*.json` 등 누락 규칙

### 충돌 해소 전략
출발지(launcher)가 최신이고 도착지(루트)가 낡은 상태였으므로
**mtime 기준**으로 최신을 채택하고 진 쪽을 `_conflict_<시각>/` 로 격리했다.
단 `chat/` 의 SQLite 4종(`webui.db` · `-shm` · `-wal` · `.webui_secret_key`)은
**세트 단위**로 움직인다. 파일별로 최신을 고르면 `.db` 와 `-wal` 이 섞여 DB 가 깨진다.
실측에서 출발지 `-wal` 0 B / 도착지 422.5 KB 로 갈려 있었다.

---

## 7-B. 모델 저장소 — `C:\LLM_Models` 고정 ★신규

`MODEL_HOME.bat` 을 **인자 없이 실행**하면 끝난다. 이미 맞아 있으면 아무것도 하지 않고,
일부가 끊겨 있으면 **끊긴 것만 복구**한다.

### 왜 필요했나
`OLLAMA_MODELS` 는 `llm_environment/llm_models` 를 가리키도록 주입되지만,
그 값은 런처가 띄우는 자식 프로세스에만 적용된다. 이미 떠 있는 Ollama
(사용자 설치본/트레이 앱)는 기본 위치를 계속 쓴다.

실측이 이를 확인했다 — `llm_environment/llm_models` 는 **0 B** 였고
`%USERPROFILE%\.ollama\models` 에 **62.8 GB** 가 있었다.
"환경 폴더 하나로 자기완결" 이라는 전제가 모델에 대해서는 성립하지 않았다.

### 구조 — 세 갈래가 한 실체로

```
C:\LLM_Models                        <- 실체
   ^정션              ^정션              ^환경변수
%USERPROFILE%\.ollama\models
llm_environment\llm_models           <- config.py 가 지정하는 경로
OLLAMA_MODELS (사용자 계정, HKCU\Environment)
```

기본 경로를 쓰는 Ollama 도, `OLLAMA_MODELS` 를 보는 Ollama 도 같은 곳에 도착한다.
**`config.py` 를 한 줄도 고치지 않는다** — 런처가 주입하는 경로가 정션이라
그대로 유효해진다. 포트도 건드리지 않는다.

`setx` 는 사용자 범위(`HKCU\Environment`)에, `mklink /J` 는 정션이라
**둘 다 관리자 권한이 필요 없다.** 재부팅해도, Ollama 를 재설치해도 유지된다.

### 왜 Program Files 가 아닌가
쓰기에 관리자 권한이 필요한데 Ollama 트레이 앱은 일반 사용자 권한으로 돈다.
폴더를 만들어도 `pull` 이 액세스 거부로 실패한다. 애초에 Program Files 는
변하지 않는 바이너리 자리이지 수십 GB 짜리 가변 데이터 자리가 아니다.
`C:\` 루트의 전용 폴더는 기본 ACL 상 일반 사용자도 만들 수 있다.

### 검증 결과 (실측)

```
L1  세 경로가 같은 실체를 가리킵니다.
L2  blobs 5개 8.4 GB / manifests 1개
L3  [OK] qwen2.5-coder:14b -> manifests\registry.ollama.ai\library\qwen2.5-coder\14b
L4  [PASS] 모델 저장 위치가 C:\LLM_Models 로 일원화되어 있고 Ollama 가 그것을 씁니다.
```

L3 이 결정적이다. 경로가 같은지 보는 데 그치지 않고 **Ollama 가 내놓는 모델의
manifest 가 실제로 그 폴더에 있는지 파일 단위로 대조**한다. 경로만 맞춰놓고
Ollama 는 딴 데 보는 상황을 이것으로 배제한다.
`ollama pull` 이 처음부터 그 경로로 받은 것도 확인했다(9.0 GB 블롭).

### 주의
- 프로젝트 폴더를 옮기면 `llm_environment\llm_models` 정션이 끊긴다.
  `MODEL_HOME.bat` 을 한 번 더 실행하면 복구된다.
- `robocopy`/`xcopy` 는 기본값으로 정션을 따라간다. 프로젝트 백업 시 `/XJ` 를 써야
  모델이 딸려오지 않는다.
- `%USERPROFILE%\.ollama\` 에는 `models` 말고 `history`(CLI 프롬프트 기록)와
  `id_ed25519`(개인키)가 남는다. 키는 지우면 안 된다.

---

## 8. 현재 동작 상태

### ✅ 검증 완료
- **AnythingLLM 교체** — 기동 4초, health `healthy`, 브라우저 진입 정상.
  종료 시 컨테이너 자동 정리(`stop -t 3`, 약 3.5초).
- **Ollama 연결** — 세션 시작 시 적재 모델 0 → 사용 후 종료 시 `gemma4:12b` 적재 확인.
  AnythingLLM 이 `host.docker.internal:11434` 를 실제로 호출했다는 직접 증거.
- **WARP 경유** — `DIAG_ANYTHINGLLM` 에서 직접 IP 와 프록시 경유 IP 가 실제로 다름.
- **컨테이너 도달성** — Ollama(모델 6개), SearXNG(6287 bytes), 프록시 포트 OPEN.
- **프록시 주입 계약** — 세 모드 모두 `ALL_PROXY` 미주입, `NO_PROXY` 에 Ollama·SearXNG 포함,
  Chromium `--proxy-server` 주입 (`TEST_ALL` 57 PASS / 0 FAIL).
- **패치 위생** — 마커 중복 없음, 원본 함수 보존, undo→재적용 바이트 동일, 재실행 멱등.
- **`proxy-bootstrap.js` 자체** — 실제 Node + undici 8.10 으로 검증:
  프록시 대상은 프록시 경유, `NO_PROXY` 대상은 직결, undici 없으면 무해하게 no-op.
- **에이전트 검색 파이프라인** — `DIAG_SEARCH` 9계층 20/20(기존 유지).
- **도구 스펙 계층(6-A)** — 시그니처 대조 22/22 일치(거부 0), 정적 적합성 ERR 0,
  `recover()` 형태 9종 + 오탐 방어 7종 실패 0, `agent.py` 루프 시나리오 10종·단언 30건 실패 0.
  패처 위생(diag·create·update·skip·undo·conflict·바이트 동일성) 확인,
  **기존 파일 7개 `cmp` 동일(무손상)**.
- **모델의 도구 이해도** — `qwen2.5-coder:14b` 가 한국어 요청 9건에서 **9/9** 올바른 도구를
  올바른 인자로 선택(`DIAG_TOOLSPEC` L2). 잡담에는 도구를 부르지 않음.
- **`agent.py` 실 Ollama 왕복 ★** — 실측 완료.
  `web_search` → 결과의 url 을 `web_fetch` 로 이어 호출 → 최종 답변까지 2단계 성공.
  `role="tool"` 되먹임을 모델이 실제로 읽고, 재구성한 `tool_calls` 턴을 Ollama 가 받아들이며,
  `tool_name` 필드도 문제없음이 한 번에 확인됐다. **두 호출 모두 `복구경로`** 였다 —
  `recover()` 가 없었으면 아무것도 실행되지 않았다.
- **경로 통합(7-A)** — 적용 완료. 경로 5종 전부 `user_data/` 수렴, `launcher/user_data` 소멸.
- **정리** — `CLEAN_LOCAL_AI` 로 40개 / 1.0 MB 정리(빈 Open WebUI DB · PreTool 미러 2벌 ·
  `.prev` 3벌 · `__pycache__`). 증거 검사를 통과하지 못한 2건은 보류.
- **개인 데이터 git 노출** — 0건. 추적 중인 것은 `.gitignore` 의 `!` 예외로 의도한
  `user_data/README.txt` 하나뿐.
- **모델 저장소 고정(7-B) ★** — `DIAG_MODEL_PATH` 4계층 전부 통과, `[PASS]`.
  세 경로 일치 · blobs 8.4 GB · **Ollama 목록의 manifest 파일 단위 대조 일치**.
  `ollama pull` 이 처음부터 `C:\LLM_Models` 로 받는 것도 확인했다.
- **Windows 전용 호출 ★** — `mklink /J`(정션) · `setx`(사용자 환경변수) ·
  `reg query`(되읽기) 셋 다 실측 성공. **관리자 권한 없이** 동작한다.

### ⚠️ 미검증 / 남은 항목
1. **컨테이너 안에서 Node fetch 가 실제로 프록시를 타는지** — REV=8 적용 후
   `DIAG_ANYTHINGLLM.bat --full` 로 확인해야 한다. `[OK] Node fetch 프록시를 탑니다` 가
   나오면 완결. `--full` 은 컨테이너 로그에서 `[proxy-bootstrap] fetch -> …` 줄을 뽑아 준다.
2. **호스트(Windows)가 이미 WARP 를 타고 있다** — 컨테이너의 "직접" 경로도 `warp=on` 으로 보인다.
   지금 fetch 경로가 안전해 보이는 것은 **호스트 WARP 덕분이지 우리 설정 덕분이 아니다.**
   호스트 WARP 를 끄면 부트스트랩이 없는 경로는 그대로 노출된다.
3. **AnythingLLM 바깥 트래픽 중 일부** — axios 경로는 env 프록시로 잡히고, 내장 fetch 는
   부트스트랩으로 잡는다. 각 코드 경로가 어느 쪽인지는 소스를 읽어 확인하지 않았다.
4. **`--cap-add SYS_ADMIN`** 은 컨테이너 권한 상승이다. 껄끄러우면
   `config.ANYTHINGLLM_CAP_ADD = ()` 로 비운다 — 그러면 `.env` 에
   `ANYTHINGLLM_CHROMIUM_ARGS="--no-sandbox,--disable-setuid-sandbox"` 가 자동으로 들어간다.
5. **코드 잔재 — 정정됨 ★** — 이전 판에서 `config.OPEN_WEBUI_PORT/URL` 을 "죽은 코드" 로
   적었으나 **틀렸다.** `DIAG_PROJECT` L5 전수 조사에서 참조 0 이 아니었고,
   `launcher/app.py` 의 `LOCAL_AI_CHAT_ENGINE=openwebui` 롤백 경로와 `chat.py` 가 실제로 쓴다.
   **지우면 롤백이 깨진다.** 실제로 참조 0 인 것은 `AGENT_MAX_TOKENS` ·
   `AGENT_CONTEXT_WINDOW` · `ANYTHINGLLM_URL` 세 개뿐이다.
   `lifelog.py` · `docker_maint.py` 의 `open_webui` 문자열은 **고아 컨테이너 정리 패턴이라
   의도적**이며 지우면 안 된다.
6. **디스크 회수 가능** — Open WebUI venv 약 2213MB(`--purge` 대상),
   Open Interpreter venv 약 530MB(`PATCH_HOST_MINILOOP` 적용 시 불필요해짐).
7. **모델의 도구 shadow** — 모델이 PreTool 의 `web_search` 를 자기 urllib 로 재정의하는 경우가 있다.
   → `qwen2.5-coder:7b/14b` 권장.
8. **검색의 실시간 취득** — `web_fetch` 가 investing.com 에서 2주 전 아카이브 사본을
   돌려준 사례가 있다. 에이전트 루프가 아니라 검색 계층 쪽. `DIAG_SEARCH.bat` 로 확인.
9. **`qwen3:8b` 의 `tool_calls`** — 외부 보고 기반 추정이며 미검증.
   `DIAG_TOOLSPEC.bat --model qwen3:8b,qwen2.5-coder:14b --repeat 3` 로 비교된다.
10. **`agent.py` 의 런처/GUI 연결** — 미착수. 현재는 CLI 와 `from PreTool.agent import run` 만.
11. **`calc()` 오류 계약** — 실패 시 예외 대신 `"계산 불가: ..."` 문자열을 반환하므로
   `spec.call()` 이 `ok=True` 로 처리한다. 기존 코드블록 경로의 동작 변경이라 손대지 않았다.
12. **죽은 상수 3개** — `AGENT_MAX_TOKENS` · `AGENT_CONTEXT_WINDOW` · `ANYTHINGLLM_URL` 은
   참조 0 으로 확정됐다. `APPLY_DEAD_CONSTS.bat` 이 준비돼 있으나 아직 적용하지 않았다.
13. **마커 짝 불일치 2건** — `CACHE_CLEANUP_v1`(열림 2/닫힘 1) ·
   `DOCKER_AUTOCLEAN_v1`(열림 1/닫힘 0), 둘 다 `launcher/__main__.py`.
   동작에는 무관하지만 그 블록을 되돌리는 패처는 실패한다.
14. **`catalog()` 호출부** — `findstr` 가 쓰기 오류로 끊겨 확정하지 못했다.
   그래서 `catalog()` 는 **건드리지 않았다**. 호환 형식이 필요하면 `spec.catalog_like()`.

---

## 9. 패치 이력

### 기존 43개 (테마별)
**기동 안정화** — SYSMSG_FILE/READ(WinError 206) · AGENT_RETRY · DOCKER_READY · OLLAMA_READY ·
START_DIAG/DIAG2 · MID_DOWNGRADE/ENTRY_LADDER/MODEL_DISPLAY/TIERS

**도구(PreTool)** — PRETOOL_HINT/DEV_HINT/FORCE · PRETOOL_PATH · PRETOOL_SYNC · sitecustomize

**검색/네트워크** — WEBSEARCH_HINT/URLENCODE_HINT/SEARCH_RECIPE · HTTP_PROXY(8118) ·
SEARXNG_AUTOSTART · AGENT_NET/NET_CONNECT/NET_LOG · TOR_TOGGLE/AUTOSTART/DOCKER_ORDER/QUIET

**UI/세션** — UNIFIED_ENTRY/ENTRY_INWINDOW · SESSION_RESUME/SESSION_HINT ·
SIDEBAR_RESTORE/STARTUP_BUTTONS/PREWARM_UI · NETMODE_LOG · IO_LOG(chat_panel v4)

**설치/정리** — MANAGE_FIX · SEARXNG_STOP/HARDEN · PRIVACY_GUARD · DEADCODE_CLEANUP · STARTUP_FIX

### 네트워크 재편 (WARP 전환)
| 마커 | 파일 | 내용 |
|------|------|------|
| `NETMODE_WARP_v2` | `config.py` | NET_MODE + WARP 상수 · `active_socks_proxy()` · `net_proxy_env()` |
| `CONFIG_WARP_v1` | `warp_runtime.py`, `installer/steps/warp.py` | WARP 런타임·설치 스텝 |
| `NETMODE_WARP_v4` | `agent/agent_runner.py` | 샌드박스 프록시 주입을 `net_proxy_env()` 로 |
| `NETMODE_RUNTIME_v1` | `actions/agent_chat.py` | 라벨 + 모드별 프록시 기동 선택 |
| `ENTRY_3WAY_v1` | `agent/entry_dialog.py` | 진입 3지선 → `NET_MODE` 반영 |
| `HTTP_BRIDGE_v1` | `http_bridge.py`, `config.py`, `warp_runtime.py` | HTTP→SOCKS5 브리지 |
| `BRIDGE_ENSURE_v1` | `warp_runtime.py` | WARP 가 이미 떠 있어도 브리지 보장 |
| `NET_CLEANUP_v1` | `warp_runtime.py`, `http_bridge.py` | 종료 시 자동 제거 |
| `NETMODE_TOR_GUARD_v1` | `tor_runtime.py` | warp 모드에서 Tor 기동 차단 |
| `NETMODE_PROXY_SYNC_v1` | `searxng_runtime.py` | settings.yml outgoing 양방향 동기화 |

### 채팅 UI 교체 — `ANYTHINGLLM_v1` (REV=8)
| 파일 | 변경 |
|------|------|
| `launcher/anythingllm_runtime.py` | **신규**. 컨테이너 수명주기 전체 |
| `launcher/config.py` | `ANYTHINGLLM_*` 정본 상수 (환경변수 오버라이드 지원) |
| `launcher/actions/chat.py` | `run` 교체 (원본은 `_ANYLLM_ORIG_RUN`) |
| `launcher/app.py` | 메뉴 [1] 라벨 (항목 구성은 원본 그대로) |
| `installer/steps/python_tools.py` | `install_open_webui` → `docker pull` (호출 지점 유지) |
| `launcher/core/docker_maint.py` | `_NAME_PATTERNS`/`_IMAGE_PATTERNS` 에 AnythingLLM 등록 |

**REV 이력** — 각 REV 는 실기 로그에서 드러난 결함을 고친 것이다.

| REV | 고친 것 |
|-----|---------|
| 1 | 최초 교체 |
| 2 | 종료 시 컨테이너 잔존(lifelog 미등록) · `pause()` 취소 시 미정리 · 정션 경로 |
| 3 | WARP/Tor 연결 · `ALL_PROXY` 제외 · Chromium 프록시 · `--audit` |
| 4 | 대기 중 무출력(진행 표시) · lifelog 기록 · `stop -t` · IPv4 우선 프로브 |
| 5 | **패널 순서** — `show_menu` 뒤에 로그 패널을 안 열어 "멈춘 것처럼" 보임 |
| 6 | Node 18 대응 `proxy-bootstrap.js` |
| 7 | **설정 서명** — 낡은 컨테이너가 재사용되던 문제 · Go 템플릿 따옴표 사고 |
| 8 | **꼬리 정규화** — REV 업그레이드마다 빈 줄이 2줄씩 누적 |

### Open Interpreter 제거 — `HOST_MINILOOP_v1` (REV=2)
| 파일 | 변경 |
|------|------|
| `launcher/agent/agent_runner.py` | `build_host_miniloop_cmd/env` · `host_python_argv` · `pretool_pythonpath` |
| `launcher/actions/agent_chat.py` | `_build_cmd_for_mode` 재정의 (sandbox 는 원본 위임) |
| `launcher/actions/agent_direct.py` | `run` 재정의 (심볼 5종 확인될 때만) |

### 도구 스펙 계층 — `PRETOOL_SPEC_v1` (REV=5)
**기존 파일 수정 0건.** 신규 파일 3개만 배치한다.

| 파일 | 역할 |
|------|------|
| `PreTool/spec.py` | 스펙 생성기 · openai/mcp/anthropic 어댑터 · `call()` · `recover()` |
| `PreTool/tools.py` | 선언 레지스트리 (타입 / 노출 이름 / safe 등급) |
| `PreTool/agent.py` | Ollama 자체 tool-calling 루프 |

| REV | 내용 |
|-----|------|
| 1 | `spec.py` + `tools.py` — 시그니처 대조 기반 등록, 26개 |
| 2 | 독스트링이 없는 10개에 `_DESC` 로 설명 공급 (설명 자리에 함수명이 찍히던 문제) |
| 3 | **웹 표면 통용 규약화** — `web_search`/`web_fetch`/`web_research`/`web_links`, 중복 4개 노출 제외 |
| 4 | `recover()` — 도구 호출이 본문 텍스트로 새는 문제 대응 |
| 5 | `agent.py` — tool-calling 루프 (복구 · 되먹임 · 루프 방어 · 안전 게이트) |

### 경로 통합 — `PATH_UNIFY_v1` (REV=4)
신규 파일 없음. 기존 4개 파일을 앵커 기반으로 고치고 데이터를 이관한다.
**기본 실행은 계획만 출력**하며 `--apply` 를 줘야 디스크를 건드린다.

| REV | 내용 |
|-----|------|
| 1 | `user_data.project_root()` 보정 · `lifelog` 이중 join 제거 · 메뉴 라벨 · `.gitignore` |
| 2 | 충돌 상세(동일/다름 · 크기 · 시각) 표시 |
| 3 | `--on-conflict=resolve` — 분류 전략(SQLite 세트 · 재생성 미러 · 잔재 · 설정) |
| 4 | `folder_policy._root()` 보정 추가 · 정본 `PreTool/*.prev` 격리 · `--clean-pycache` |

`--undo` 로 코드와 데이터가 모두 원위치한다(재현 트리 50개 파일 md5 일치로 검증).

### 정리 · 감사 도구 — `CLEANUP_v1` · `PROJECT_AUDIT_v1`

| 도구 | 내용 |
|------|------|
| `CLEAN_LOCAL_AI` (REV=4) | 증거 기반 삭제. `chat/` 은 DB 를 실제로 열어 실사용 테이블이 전부 0행인지 확인한 뒤에만 지운다. `.db`+`-wal`+`-shm` 을 함께 복사해 열므로 **WAL 에만 있는 데이터도 잡힌다.** 개인 데이터 인벤토리와 git 노출 점검 포함 |
| `DIAG_PROJECT` (REV=2) | 읽기 전용 10계층 감사 — 경로 계산 주체 · 데이터 트리 · 중복 · 잔재 · 죽은 상수 · 참조 관계 · 패치 마커 · 인코딩 위생 · 용량 |

### 모델 저장소 — `MODEL_HOME_v2`
`MODEL_HOME.bat` 을 인자 없이 실행하면 설정·복구·확인이 한 번에 끝난다.
세 조각(환경변수 · 정션 2개)을 따로 확인해 **빠진 것만** 다시 만든다.

| 도구 | 내용 |
|------|------|
| `MODEL_HOME` (REV=1) | 폴더 확보 → 기존 모델 이동 → 환경변수 → 정션 2개 → 확인. `--check` 는 읽기 전용, `--undo` 로 기본 경로 복귀 |
| `DIAG_MODEL_PATH` (REV=2) | L1 경로 해석 / L2 실체 / **L2-B 실체 탐색**(연결이 끊겼을 때 드라이브 루트를 훑어 모델을 찾는다) / L3 manifest 파일 단위 대조 / L4 판정 |
| `APPLY_MANAGE_MODELPATH` (REV=2) | `MANAGE.bat` 에 모델 위치 표시를 삽입. 앵커를 고정하지 않고 프롤로그 끝을 런타임에 찾는다 |
| `APPLY_DEAD_CONSTS` (REV=1) | 참조 0 상수 제거. AST 로 대입문을 찾고 **지우기 직전 프로젝트 전체를 다시 훑어 재확인**한다. 주석 언급과 코드 참조를 구분한다 |

### `.bat` 실행 줄 결함 — 전량 수정 ★
아래 형태는 **도구가 rc≠0 으로 끝나면 두 번 실행된다.**

```bat
where py >nul 2>&1 && (py -3 "...") || (python "...")
```

`py -3` 가 비정상 종료로 보여 `||` 가 발동하기 때문이다. rc=0 일 때는 드러나지 않는다.
전체 `.bat` 을 아래 형태로 교체했다.

```bat
set "PYEXE="
py -3 -V >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
%PYEXE% "%~dp0X.py" %*
```

---

## 9-A. 통합 도구 — FIX_ALL · TEST_ALL · DIAG_* · CLEAN_LOCAL_AI ★

### `FIX_ALL.bat` — 통합 점검·수정
검증된 도구 4개를 **gzip+base64 로 내장**하고(전개 시 SHA-256 검증) 올바른 순서로 돌린다.
파일이 하나뿐이라 "어느 파일을 교체했더라" 로 어긋날 일이 없다.

```
[0] 환경 확인   루트·Python·Docker
[1] 번들 전개   같은 내용이면 건너뜀
[2] 사전 진단   --diag (무변경). NO-GO 면 여기서 중단
[3] 적용        구 REV 자동 업그레이드
[4] 설치 검증   패치된 모듈을 실제로 import 해서 심볼 15개 확인 + describe() 출력
[5] 선택        --with-miniloop
[5b] 정밀 테스트 --test
[6] 컨테이너    낡은 서명이면 제거 → 다음 기동 때 새로 생성
[7] 다음 할 일
```

| 옵션 | 효과 |
|------|------|
| `--diag` | 진단만, 무변경 |
| `--test` | 적용 후 `TEST_ALL` 까지 |
| `--with-miniloop` | Open Interpreter 제거도 함께 |
| `--purge` | Open WebUI 잔재 정리(venv 삭제, **데이터는 보관 이동만**) |
| `--undo` | 적용한 패치 전부 되돌림 |
| `--no-container` | 컨테이너를 건드리지 않음 |

### `TEST_ALL.bat` — 패치된 코드 검증 (Docker 불필요)
| | 내용 |
|---|---|
| T1 | UTF-8 · AST · 마커 짝/중복 · BOM/개행 |
| T2 | 런타임이 참조하는 config 상수 40개를 소스에서 추출해 실재 확인 |
| T3 | warp/tor/direct 각각 — 이미지 위치, 라벨 2종, `ALL_PROXY` 미주입, `NO_PROXY`, Chromium, 부트스트랩, 서명 상이·재현성 |
| T4 | 부트스트랩 JS 생성/삭제 · 필수 토큰 · ES class 미상속 · `node --check` |
| T5 | 임시 폴더 복사본에서 undo→재적용이 **바이트 동일**한지 + 멱등 |
| T6 | 원본 함수 보존 · 패널 순서 · try/finally · 정의 중복 없음 · Go 템플릿 사고 없음 |
| T7 | Docker 가 있으면 **실행 중 컨테이너의 서명이 현재 설정과 일치하는지** |

- **운영 상태를 바꾸지 않는다.** T3/T4 가 `proxy-bootstrap.js` 를 쓰거나(직접 모드에선) 지우므로,
  시작 시 스냅샷을 떠 두고 `finally` 로 반드시 되돌린다.
- T6 는 반드시 **마커 블록 안쪽만** 검사한다. 파일 전체에서 찾으면 원본 함수가 걸린다
  (원본 `chat.py` 의 Open WebUI `run()` 도 `reserve_entrypoint` 를 부른다).

### `DIAG_ANYTHINGLLM.bat` — 컨테이너 실경로 진단
컨테이너가 **떠 있는 상태**에서 실행한다. LLM 답변 품질과 무관하게 docker 레벨에서 직접 찌른다.

```
0. 설치된 PATCH REV (디스크의 anythingllm_runtime.py 를 직접 읽음)
1. 컨테이너 상태 / 라벨 / 설정 서명 일치 / 포트 게시
2. 주입된 환경변수 · proxy-bootstrap 파일 · NODE_OPTIONS · undici 존재
3. Node 버전 → 내장 fetch 의 프록시 준수 조건
4. 도달성: Ollama / SearXNG / 프록시
5. 실제 나가는 IP — 직접(--noproxy) vs 프록시 경유 (Cloudflare cdn-cgi/trace)
6. Node fetch 가 진짜 프록시를 타는가
7. 호스트(Windows) 자체가 이미 WARP 인지
```

IP 는 뒤 두 옥텟을 가려 출력하므로 로그를 그대로 공유해도 된다.
`--full` 을 붙이면 컨테이너 로그와 `[proxy-bootstrap]` 줄을 함께 보여 준다.

---

### `DIAG_TOOLSPEC.bat` — 도구 스펙 진단 (REV=3) ★신규
도구가 **일반적인 AI 도구 규약에 맞는지**, 그리고 **실제 모델이 그대로 인식하는지**를
두 층으로 나눠 판정한다.

| 층 | 내용 |
|----|------|
| L0 | Ollama 버전 · 모델 `capabilities` 에 `tools` 존재 · 템플릿 `.Tools` 참조 |
| L1 | 이름 규약 · 설명 부재/잡음 · 스키마 무결 · 직렬화 · 역할 중복 |
| L2 | 실모델 도구선택 — 4군으로 나눠 원인을 분리 |

L2 의 4군: **A0** 표준 도구 1개·영어·시스템 메시지 없음 / **A** 같은 조건 + 시스템 메시지 /
**B** 우리 도구 1개·한국어 / **C** 우리 도구 전부·한국어.
A 가 실패하면 모델 문제, A 만 되고 C 가 실패하면 스펙 문제로 갈린다.
`tool_calls` 가 비면 **본문도 함께 출력**하고 `recover()` 로 복구 가능한 건수를 센다.

```bat
DIAG_TOOLSPEC.bat                                        :: L1 만
DIAG_TOOLSPEC.bat --model qwen2.5-coder:14b --repeat 3   :: L0+L1+L2
DIAG_TOOLSPEC.bat --model qwen3:8b,qwen2.5-coder:14b     :: 모델 비교
DIAG_TOOLSPEC.bat --dump mcp_tools.json                  :: MCP 스펙 추출
```

Ollama 미연결 시 L2 는 한 줄로 끝나고 L1 결과는 보존된다.

---

### `DIAG_PROJECT.bat` — 프로젝트 전수 감사 (REV=2) ★신규
읽기 전용. 결과를 `diag_project_<시각>.txt` 로도 남긴다.

| 층 | 내용 |
|----|------|
| L1 | 경로 계산 주체 — 실제로 import 해서 값을 확인 + 소스 패턴 전수 |
| L2 | 데이터 트리 실태 · 정션 전수 |
| L3 | 중복 파일 · PreTool 정본 대 미러 |
| L4 | 잔재(`.prev` `.bak` `.orig` `.tmp` · `__pycache__`) |
| L5 | `config.py` 상수 참조 전수 → **죽은 상수 확정** |
| L6 | 고아 모듈 · 중복 정의 함수 · `catalog()` 호출부 |
| L7 | 패치 마커 짝 · 중복 적용 |
| L8 | 인코딩 위생(.bat ASCII+CRLF · BOM · EOL 혼재) |
| L9 | 용량 상위 |

### `CLEAN_LOCAL_AI.bat` — 증거 기반 정리 (REV=4) ★신규

```bat
CLEAN_LOCAL_AI.bat                    :: 계획만 (무변경)
CLEAN_LOCAL_AI.bat --show-held        :: 보류 항목 내용 열람
CLEAN_LOCAL_AI.bat --apply --safe     :: 삭제 대신 _trash_<시각>/ 로 이동
CLEAN_LOCAL_AI.bat --apply --logs 30  :: 30일 넘은 세션 로그도 포함
```

이름만 보고 지우지 않는다. `chat/` 은 DB 를 열어 실사용 테이블 17종을 세고,
chroma 컬렉션을 세고, 예상 밖 파일이 있는지 본다. 하나라도 걸리면 **보류**하고 사유를 낸다.

정리 후 **개인 데이터 점검** 과 **사후 확인** 이 자동으로 돈다 —
경로가 다시 갈라졌는지, 잔재가 쌓였는지, 개인 데이터가 git 에 새는지.

---

## 10. 설정 · 패치 규약

**주요 설정(`launcher/config.py`)**: `OLLAMA_PORT=11434`, `SANDBOX_IMAGE=llm-agent-sandbox`,
`MODEL_TAG`(ARA), `MODEL_TAG_FALLBACK`(gemma4:12b), `LLM_NETWORK`(기본 `llm_net`).

**네트워크**: `NET_MODE`(`warp`/`tor`/`direct`) · `WARP_IMAGE`/`WARP_CONTAINER`/`WARP_PORT`(1080) ·
`HTTP_BRIDGE_CONTAINER`/`HTTP_BRIDGE_PORT`(8118) · `TOR_*`.
접근자: `active_socks_proxy()` · `http_bridge_proxy()` · `net_proxy_env()`.

**AnythingLLM**: `ANYTHINGLLM_IMAGE`/`CONTAINER`/`HOST_PORT`(3001)/`STORAGE_MOUNT`/
`SERVER_ENV_MOUNT`/`BOOT_TIMEOUT`/`PULL_TIMEOUT`/`MEM`(auto)/`CPUS`(auto)/`CAP_ADD`/
`VECTOR_DB`/`WHISPER_PROVIDER`/`TTS_PROVIDER`/`OLLAMA_TIMEOUT_MS`/`EMBEDDING_*`/
`EXTRA_ENV`/`NET_AWARE`/`NODE_BOOTSTRAP`/`NODE_OPTIONS_EXTRA`/`NO_PROXY_EXTRA`/
`PROGRESS_EVERY`/`STOP_GRACE`/`PROBE_HOSTS`.

**주소·포트는 config.py 에서만 정의**하고 각 런타임 모듈은 읽기만 한다(단일 소스).
`ANYTHINGLLM_EXTRA_ENV = {"KEY": "VALUE"}` 로 `.env` 에 임의 키를 추가할 수 있다.

### 패치 규약(엄격)
- **멱등** — 버전 마커 + **REV 스탬프**
- **앵커 기반 정확 치환**, MISS 시 무손상 / 또는 **앵커 미사용 append-wrapper**
  (원본은 `_ORIG_*` 로 보존, 뒤에 온 재정의가 이긴다 — 파일 구조가 예상과 달라도 안전)
- AST/compile 검증 후 **원자적 쓰기**(tmp + `os.replace`), BOM·CRLF 보존, `.bak` 없음
- **파일 꼬리는 `rstrip("\n") + "\n"` 으로 정규화** — apply/undo 양쪽에서.
  안 하면 REV 업그레이드마다 빈 줄이 2줄씩 쌓인다.
- **패처의 동작을 바꾸면 REV 를 반드시 올린다.** 안 올리면 기존 설치가 `SKIP` 으로 넘어가
  영원히 갱신되지 않는다(REV=8 에서 실제로 겪은 사고).
- **Go 템플릿에 따옴표를 넣지 않는다** — `{{index .Config.Labels "x"}}` 는 이스케이프가
  뭉개진다. `{{json .Config.Labels}}` 로 받아 파싱한다.
- `.bat` 는 ASCII+CRLF · Windows docker subprocess 는 `CREATE_NO_WINDOW`
- **자식 프로세스 출력은 `PYTHONIOENCODING=utf-8`** 로 맞춘다. 안 맞추면 cp949/UTF-8
  불일치로 한글이 깨지고, ASCII 폴백이 한글을 통째로 날린다.
- **사용자 데이터는 어떤 경우에도 하드 삭제하지 않는다** — `--purge` 도 이름만 바꾼다.

---

## 11. 문제 해결 / 다음 단계

### 채팅 UI 가 메뉴에서 멈춘 것 같다
REV≤4 의 패널 순서 버그. `FIX_ALL.bat` 으로 REV=8 이상으로 올린다.
`TEST_ALL` 의 `패널 순서` 항목이 상시 감시한다.

### 패치했는데 반영이 안 된다
```
findstr /C:"ANYTHINGLLM_REV" PATCH_ANYTHINGLLM.py
findstr /C:"ANYTHINGLLM_REV" launcher\anythingllm_runtime.py
```
두 값이 다르면 `FIX_ALL.bat` 을 실행한다. `DIAG_ANYTHINGLLM.bat` 의 **[0] 설치된 PATCH REV** 가
이 비교를 자동으로 해 준다.

### 컨테이너가 낡은 설정으로 떠 있다
`TEST_ALL` T7 또는 `DIAG` 의 `설정 서명 일치` 가 `컨테이너=… / 현재=…` 로 알려 준다.
**런처를 완전히 종료했다가 다시 띄우면** 서명 불일치를 감지해 자동으로 다시 만든다.
급하면 `docker rm -f llm_anythingllm`.

### 기동이 오래 걸린다 / 멈춘 것 같다
최초 실행은 마이그레이션+벡터DB 초기화로 1~3분 걸린다. 8초마다 진행 상황이 찍히니
그 줄이 갱신되고 있으면 정상이다. Docker Desktop 이 방금 켜졌다면 `docker run` 자체가
수십 초 걸릴 수 있다.

### `healthy` 인데 브라우저가 안 열린다
```
docker port llm_anythingllm
docker logs --tail 50 llm_anythingllm
```
포트 게시/방화벽 문제다. `DIAG` 가 이 상황을 별도 문구로 구분해 준다.

### 웹 검색이 안 된다 (채팅 UI)
AnythingLLM 의 SearXNG 는 **agent 스킬**이다. `@agent 검색어` 형태로 불러야 한다.
일반 대화는 자동 검색하지 않는다(Open WebUI 와 가장 큰 차이).

### 종료했는데 컨테이너가 계속 실행 중
`LOCAL_AI_ANYTHINGLLM_KEEP=1` 이 설정돼 있는지 확인. 아니라면
`register_exit_cleanup` 이 등록되지 않은 구버전이다 → `FIX_ALL.bat`.
잔재는 `docker rm -f llm_anythingllm`.

### 검색 문제 (에이전트) — `DIAG_SEARCH.bat`
9계층(도커 → config → 이미지 → 컨테이너 → 프록시 egress → SearXNG 도달 → 실검색 →
본문 fetch → settings.yml)을 각각 판정한다. `--start`/`--mode tor`/`--quick`.

### `Connection reset by peer` (프록시 egress 실패)
`HTTP_PROXY` 가 `socks5h://...` 로 잡힌 경우. **urllib 도 Node 도 SOCKS 를 못 쓴다.**
→ HTTP 브리지(`llm_httpbridge:8118`)가 필요하다(4-A).

### 모델이 도구를 안 쓰고 자기 코드를 짬
8b 무검열 모델 특성. `qwen2.5-coder:7b/14b` 권장.

### 도구를 고르긴 하는데 `tool_calls` 가 비어 있다
모델이 `<tool_call>` 태그 없이 맨 JSON 을 뱉어 Ollama 파서가 승격하지 못하는 경우.
`DIAG_TOOLSPEC.bat --model <태그> --repeat 3` 을 돌리면 본문과 복구 가능 건수가 함께 나온다.
`agent.py` 는 `spec.recover()` 로 이 경로를 자동 우회한다(6-A).
모델을 바꾸려면 `capabilities` 에 `tools` 가 있는 태그를 쓴다.

### 모델이 어디 저장돼 있는지 모르겠다 / 연결이 끊겼다
`MODEL_HOME.bat --check` 로 확인하고, 그냥 `MODEL_HOME.bat` 을 실행하면 복구된다.
더 자세히 보려면 `DIAG_MODEL_PATH.bat`. 실체가 사라진 것 같으면
L2-B 가 드라이브 루트를 훑어 찾아 주고, `--search <경로>` 로 후보를 직접 줄 수도 있다.

### (참고) 도구 없이 수동으로 확인하기
7-B 적용 전에는 `OLLAMA_MODELS` 가 `llm_environment/llm_models` 를 가리키는데도
그 폴더가 비어 있었다. 도구를 못 쓰는 상황에서 같은 것을 손으로 확인하려면:

```bat
:: 코드가 지정하는 위치
py -3 -c "import sys;sys.path.insert(0,'.');from pathlib import Path;print(Path.cwd()/'llm_environment'/'llm_models')"
dir /b llm_environment\llm_models

:: 실제로 블롭이 있는 곳 (Windows 기본)
dir /b "%USERPROFILE%\.ollama\models"
powershell -c "'{0:N1} GB' -f ((gci -Recurse \"$env:USERPROFILE\.ollama\models\" -File -EA 0 | measure Length -Sum).Sum/1GB)"

:: 지금 도는 Ollama 가 무엇을 쓰는지
echo %OLLAMA_MODELS%
tasklist /fi "imagename eq ollama.exe"
```

`blobs/` 와 `manifests/` 가 있고 용량이 큰 쪽이 실제 위치다.
7-B 적용 후에는 `.ollama\models` 가 정션이므로 `dir` 결과가 `C:\LLM_Models` 와 같아진다.
손으로 고치려면 Ollama 를 완전히 종료한 뒤 두 폴더를 옮기고 **사용자 계정**
환경변수 `OLLAMA_MODELS` 를 설정한 다음 Ollama 를 다시 켜야 한다 —
런처가 자식 프로세스에만 주입하는 값은 이미 떠 있는 Ollama 에 적용되지 않는다.
`MODEL_HOME.bat` 이 이 과정을 대신한다.

### 도구를 추가했는데 스펙에 안 나온다
`DIAG_TOOLSPEC.bat` 의 `[등록 거부]` 목록을 본다. `PreTool/tools.py` 의 `_TABLE` 선언이
실제 시그니처와 어긋나면 그 도구만 드롭되고 사유가 출력된다(인자명 오타가 대부분).

### 재개 시 우선 작업
1. `FIX_ALL.bat --test` → rc=0
2. 런처 재기동 → `[1]` → WARP
3. `DIAG_ANYTHINGLLM.bat --full` → **`Node fetch 프록시를 탑니다`** 확인 (남은 최대 미검증 항목)
4. `CLEAN_LOCAL_AI.bat` → 경로 수렴 `[OK]` 5종 · 개인 데이터 git 노출 0 확인
5. `MODEL_HOME.bat` → 모델 저장소 `C:\LLM_Models` 연결 확인(끊겼으면 자동 복구)
6. 안정 확인 후 `FIX_ALL.bat --purge` 로 약 2.2GB 회수
   (venv 를 지우면 `LOCAL_AI_CHAT_ENGINE=openwebui` 롤백은 못 쓴다)

---

## 부록 — 알려진 제약

- **AnythingLLM 이미지의 Node 는 v18.20.8** — 내장 `fetch` 가 `HTTP_PROXY` 를 무시한다.
  `proxy-bootstrap.js` 로 우회하지만, 이미지가 업데이트되어 v22.21+ 가 되면
  `NODE_USE_ENV_PROXY=1` 만으로 동작하므로 부트스트랩은 무해한 중복이 된다.
- **`ALL_PROXY` 를 Node 컨테이너에 주면 안 된다** — `proxy-from-env` 가 `socks5h://` 를
  HTTP 프록시로 오인해 전 요청이 깨진다.
- **호스트가 WARP 를 타고 있으면** 컨테이너의 "직접" 경로도 `warp=on` 으로 보여
  프록시 적용 여부를 warp 플래그로 판정할 수 없다 → IP 변화로 판정한다.
- `host.docker.internal` 은 호스트 프로세스(Ollama)만 도달, 컨테이너 게시 포트엔 도달 불가
  → `llm_net` 공유 네트워크 + 컨테이너명 통신.
- **WARP 는 SOCKS5 전용** → urllib/Node 에는 HTTP 브리지가 필수.
  Tor 는 Privoxy(8118)를 함께 제공하므로 브리지가 필요 없다.
- WARP IP 는 다수 사용자가 공유하는 대역이라 비-Cloudflare 사이트에서는 캡차가 뜰 수 있다.
- `dperson/torproxy` 는 커스텀 `torrc` 마운트 시 기동 실패 → 기본 구성으로만 사용.
- 서드파티 이미지(`dublok/cloudflare-warp`, `mintplexlabs/anythingllm`)에 의존한다.
  버전 고정이 필요하면 `config.WARP_IMAGE` / `config.ANYTHINGLLM_IMAGE` 를 다이제스트 핀으로.
- **AnythingLLM 대화 기록은 Open WebUI 에서 이전할 수 없다** — 스키마가 완전히 다르다.
- `--cap-add SYS_ADMIN` 은 권한 상승이다. 샌드박스를 중시한다면
  `ANYTHINGLLM_CAP_ADD = ()` 로 비우고 Chromium 인자 방식을 쓴다.
- 8b 무검열 모델(huihui/ARA)은 도구·지시 준수가 불안정 → 스크랩엔 `qwen2.5-coder` 권장.
- **`qwen2.5-coder` 는 도구를 정확히 고르지만 `tool_calls` 로 승격되지 않는다** —
  Ollama + qwen2.5-coder 조합에서 널리 보고된 문제(7b·14b·32b 동일).
  `capabilities` 에 `tools` 가 있고 템플릿도 정상인데도 발생하므로 모델 능력 문제가 아니다.
  `spec.recover()` 가 우회한다(6-A). 역할이 다르므로 **코드블록 miniloop 은 `qwen2.5-coder` 를
  유지하고, tool-calling 이 필요하면 별도 모델을 쓰는 이원화**가 자연스럽다.
- **도구 설명이 겹치면 작은 모델이 못 고른다** — 같은 인자를 받는 도구가 여러 개면
  판단 근거가 없다. `web_search`/`web_fetch`/`web_research` 는 설명에서 서로를 명시적으로
  참조해 구분시킨다. `DIAG_TOOLSPEC` 의 C8 경고가 이런 중복을 잡아낸다.
- **모델 저장 위치는 설정과 다를 수 있다** — `OLLAMA_MODELS` 를 자식 프로세스에 주입해도
  이미 떠 있는 Ollama 는 기본 위치를 계속 쓴다. 실측에서 `llm_environment/llm_models` 는
  0 B, 기본 경로에 62.8 GB 였다. 코드만 보고 판단하면 틀린다.
  → 7-B 의 정션 + 사용자 환경변수 조합으로 해결했다.
- **`.bat` 에서 `&&` / `||` 로 인터프리터를 고르면 안 된다** — 도구가 rc≠0 으로 끝날 때
  `||` 가 발동해 두 번 실행된다. rc=0 일 때는 드러나지 않아 오래 남는다.
- **Windows 정션과 사용자 환경변수는 관리자 권한이 필요 없다** — `mklink /J` 와 `setx`
  둘 다 실측 확인. 반면 `C:\Program Files` 는 쓰기에 권한이 필요해 Ollama 가 `pull` 에
  실패한다.
- **`.gitignore` 의 `!` 예외를 무시하면 오탐이 난다** — `user_data/README.txt` 는 일부러
  추적하는 파일이다. `git rm -r --cached user_data` 처럼 통째로 해제하면 이것까지 날아간다.
- **SQLite 는 `.db` 단독으로 판단하면 안 된다** — 데이터가 `-wal` 에만 있을 수 있다.
  실측에서 `.db` 기준으로는 "비어 있음" 이지만 `-wal` 까지 반영하면 대화 2건이 있었다.
  `.db` · `-shm` · `-wal` 을 **세트로** 다뤄야 한다.
- **선언 스키마를 좁히는 것은 파괴적 변경이 아니다** — 원함수는 유연 입력을 계속 받고
  레지스트리는 부분집합만 노출한다. 그래서 `PreTool/tools.py` 는 원함수를 수정하지 않는다.
