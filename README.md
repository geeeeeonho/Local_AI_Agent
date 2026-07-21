# Local_AI — 포터블 로컬 LLM 에이전트 환경

> Windows용 **자기완결형 로컬 LLM 스택**. 클라우드 없이 채팅·자동화 에이전트·웹 검색을
> 단일 GUI 런처(`RUN.bat`)에서 제공한다. 모든 사용자 데이터(채팅·설정·로그·에이전트 세션)는
> **`user_data/` 한 곳**에 모이며, 모든 코드 변경은 멱등 패처(`APPLY_ALL.bat`)로 관리된다.

- **실행 환경**: Windows 10/11, Python 3.11+ (권장 3.12.x), Docker Desktop
- **루트 경로 예시**: `C:\Users\ghwork\Works\Local_AI`
- **구동**: `python -m launcher` (GUI) / `python -m installer` (설치) — `RUN.bat`·`MANAGE.bat` 가 감쌈
- **권장 사양**: RAM 약 20GB 가용, VRAM 16GB. 대형 모델은 한 번에 하나만 적재.
- **적용 상태**: `APPLY_ALL.py = v39` (파일 23 + 패치 43). 재실행 안전(SKIP).

---

## 목차
1. 빠른 시작
2. 디렉터리 / 모듈 구조 (상세)
3. 아키텍처 & 데이터 흐름
4. 구성 요소 (Ollama · SearXNG · Tor · 공유 네트워크)
5. 에이전트 실행 순서 (agent_chat 파이프라인)
6. PreTool — 에이전트 도구 패키지
7. 데이터 저장 구조 (`user_data/`)
8. 현재 동작 상태 (해결/미해결)
9. 패치 이력 (테마별 43개)
10. 설정 · 패치 규약
11. 문제 해결 / 다음 단계

---

## 1. 빠른 시작

```bat
:: 프로젝트 루트에서
APPLY_ALL.bat                 :: 파일 배치 + 43개 패치 멱등 적용
docker rm -f llm_tor llm_searxng   :: (선택) 오래된 컨테이너 정리
RUN.bat                       :: GUI 런처 (에이전트/채팅)
MANAGE.bat                    :: 설치·모델 관리 대시보드
```

에이전트 진입 → 프로필 선택(범용 개발 등) → 인터넷 모드(차단 / Tor 경유) → 메시지 입력.
`net_diag()` 로 네트워크 경로를 점검할 수 있고, 모든 대화·코드·결과는 런처 로그에 남는다(IO_LOG).

---

## 2. 디렉터리 / 모듈 구조 (상세)

```
Local_AI/
├── RUN.bat                     python -m launcher (GUI 런처)
├── MANAGE.bat                  python -m installer (설치/관리 대시보드)
├── APPLY_ALL.bat / .py         멱등 일괄 패처 (파일 배치 + 43 패치)
├── APPLY_*.bat / .py           개별 패처(자기삭제 쌍)
├── README.md
│
├── launcher/                   ── GUI 런처 패키지 ──
│   ├── __init__.py __main__.py app.py   부트스트랩/진입
│   ├── config.py               상수: MODEL_TAG, OLLAMA_PORT(11434), SANDBOX_IMAGE 등
│   ├── i18n.py                 다국어 문자열
│   ├── runtime_guard.py        런타임 가드
│   ├── tor_runtime.py          Tor 컨테이너 수명주기 (v8, --network llm_net)
│   ├── searxng_runtime.py      SearXNG 컨테이너 수명주기 (--network llm_net)
│   │   (호환 shim: 루트의 lifelog/user_data/model_roles/settings_store/docker_maint/
│   │    folder_policy/profiles/agent_runner 등은 아래 서브패키지로 재배치 + shim 유지)
│   │
│   ├── core/                   ── 인프라 ──
│   │   ├── lifelog.py          런처 로그 · 종료 cleanup 등록/실행 · [CHAT]/[net] 기록
│   │   ├── user_data.py        user_data 경로 해석 (interpreter_dir("sandbox") 등)
│   │   ├── settings_store.py   설정 영속(user_config.json)
│   │   └── docker_maint.py     Docker 정리(고아 컨테이너 이름/이미지 패턴)
│   │
│   ├── models/                 ── 모델 선택 ──
│   │   ├── model_catalog.py    다운로드 카탈로그(v3)
│   │   ├── model_roles.py      런타임 역할·사다리·RAM 자동 강등(auto_match_installed)
│   │   └── model_classes.py    클래스별 사다리 시각화(공용 뷰: 일반/무검열/관리특화)
│   │
│   ├── agent/                  ── 에이전트 ──
│   │   ├── agent_runner.py     docker run 명령 구성 + 미니루프(b64 인코딩된 REPL 소스)
│   │   ├── agent_lifecycle.py  에이전트 수명주기(start/stop/poll)
│   │   ├── entry_dialog.py     통합 진입 다이얼로그(창 안에서, host.replace)
│   │   ├── folder_policy.py    허용/금지 폴더 정책(allowed/denied)
│   │   └── profiles.py         프로필(범용 개발 등) → 역할/시스템메시지
│   │
│   ├── actions/                ── 메뉴 액션(런처가 호출) ──
│   │   ├── agent_chat.py       ★에이전트 채팅(GUI) — 최근 패치 대부분이 여기 적용
│   │   ├── agent_direct.py     직접(호스트) 에이전트
│   │   ├── agent_sandbox.py    샌드박스 에이전트
│   │   ├── _sandbox_options.py 인터넷/폴더 등 진입 옵션
│   │   ├── chat.py             Open WebUI(DATA_DIR=user_data/chat)
│   │   ├── ollama.py           Ollama 시작/정리
│   │   ├── searxng.py          SearXNG 액션
│   │   ├── docker_clean.py docker_image.py   Docker 정리/이미지
│   │   ├── model_info.py model_manage.py     모델 조회/관리
│   │   ├── settings.py         설정
│   │   └── manage_gui.py       관리 GUI 연결
│   │
│   ├── presenter/              ── Presenter 패턴(로직↔UI 분리) ──
│   │   ├── base.py             Presenter 추상
│   │   ├── tui.py              TerminalPresenter
│   │   └── gui/
│   │       ├── window.py       메인 윈도우(host: 화면 교체 컨테이너)
│   │       ├── presenter.py    TkPresenter
│   │       ├── chat_panel.py   채팅 로그 패널(★IO_LOG: append_message → 런처 로그)
│   │       ├── sidebar.py menu_panel.py panels.py   좌측/메뉴/패널
│   │       ├── dialogs.py statusbar.py              다이얼로그/상태바
│   │       └── theme.py widgets.py                  VS Code Dark 테마/위젯
│   │
│   └── services/              ── 외부 서비스 래퍼 ──
│       ├── docker.py           DockerService(daemon_alive, ensure_daemon)
│       └── ollama.py           Ollama 서비스(가용성/모델)
│
├── installer/                  ── 설치/관리 패키지 (python -m installer) ──
│   ├── __init__.py __main__.py
│   ├── manage_gui.py           MANAGE 대시보드(진단 + 모델 설치/삭제, 창 안 임베드)
│   ├── i18n.py lang_setup.py resources.py utils.py
│   ├── core/                   console.py download.py filesystem.py preflight.py
│   └── steps/                  model.py ollama.py python_tools.py sandbox.py searxng.py
│
├── PreTool/                    ── 에이전트 도구(컨테이너에 마운트) ──
│   ├── __init__.py             catalog() · 전 함수 노출
│   ├── search.py               web_search/search_summary/fetch_text/net_diag (SearXNG 우선)
│   ├── excel.py                excel_write/csv_write/read_table (순수 stdlib xlsx)
│   ├── report.py               report_write (md/html)
│   ├── files.py                move/copy/list_files/organize_by_ext
│   ├── dev.py                  run_tests/check_syntax/run_python/lint/outline/diff/complexity
│   ├── data.py                 calc/json_pretty/json_query/summarize_text/word_stats
│   └── sitecustomize.py        PYTHONPATH 자동 실행 → PreTool 함수를 builtin 으로 주입
│
└── user_data/                  ── 사용자 데이터(영속) ──
    ├── settings/               user_config.json, folder_policy.json  ← launcher/settings 정션
    ├── chat/                   Open WebUI DB + 캐시
    ├── logs/                   launcher_*.log (대화·[net]·기동 전부)
    └── interpreter/sandbox/    에이전트 세션(session_*.json) + PreTool/ + sitecustomize.py
                                 (컨테이너 /home/agent/.agent_state 로 마운트)
```

> **런타임 파일 3종**(`tor_runtime.py`, `searxng_runtime.py`, `agent/entry_dialog.py`)은
> "내 버전이면 갱신, 사용자 커스텀이면 보존" 정책(FILES_MINE). 나머지는 항상 배치(FILES).

---

## 3. 아키텍처 & 데이터 흐름

### Presenter 패턴
UI(Tkinter)와 로직을 분리한다. 액션(`actions/*`)은 `Presenter` 인터페이스에만 의존하고,
실제 구현은 `TkPresenter`(GUI) / `TerminalPresenter`(TUI)가 담당. 화면 전환은 메인 윈도우의
`host` 컨테이너를 `host.replace(frame)` 로 교체(통합 진입 다이얼로그도 이 방식).

### 핵심 호출관계 (에이전트 채팅)
```
RUN.bat → python -m launcher → app → TkPresenter
   → menu → actions/agent_chat._run_gui_chat_unified(env, presenter, cmd, is_host)
        1) 인터넷 모드 표시(NETMODE_LOG) · Docker/Tor/SearXNG 준비
        2) cmd 조정(네트워크/프록시/시스템메시지/PYTHONPATH)  ← 최근 패치 집중 지점
        3) agent.start(cmd)  → agent/agent_runner (docker run + 미니루프)
        4) poll 루프: 컨테이너 stdout → chat_panel.append_message → 화면 + 런처 로그
```

### 네트워크 토폴로지 (v36~)
```
[Ollama]  호스트 프로세스, 11434  ←── (host.docker.internal, NO_PROXY 직접) ── [에이전트 컨테이너]
                                                                                    │  (llm_net)
[llm_tor]   9050 SOCKS / 8118 HTTP  ──llm_net── 프록시(HTTP_PROXY=llm_tor:8118) ────┤
[llm_searxng] 내부 8080 (JSON 검색)  ──llm_net── web_search(llm_searxng:8080) ───────┘
```
- **Ollama(호스트 프로세스)** 는 `host.docker.internal` 로 도달(정상).
- **다른 컨테이너의 게시 포트는 `host.docker.internal` 로 도달 불가**(Docker Desktop 특성) →
  **공유 네트워크 `llm_net` + 컨테이너 이름**으로 통신하도록 전환(AGENT_NET/NET_CONNECT).

### 데이터 흐름
1. **모델 호출**: 미니루프 → `host.docker.internal:11434`(NO_PROXY 직접) → Ollama.
2. **웹 검색**: `web_search` → `llm_searxng:8080`(JSON, 프록시 우회) → SearXNG → (Tor) → 인터넷.
3. **대화 로깅**: 컨테이너 stdout → `chat_panel.append_message` → `lifelog.log("CHAT", …)` → 런처 로그.
4. **세션 영속**: `user_data/interpreter/sandbox/session_*.json`(호스트) ↔ `/home/agent/.agent_state`(컨테이너).

---

## 4. 구성 요소

| 구성 | 역할 | 컨테이너/포트 | 런타임 모듈 |
|------|------|------|------|
| **Ollama** | 모델 서버(호스트 프로세스) | `:11434` | `services/ollama.py` |
| **Open WebUI** | 브라우저 채팅 UI | 로컬 | `actions/chat.py` |
| **에이전트 미니루프** | Docker 샌드박스 REPL | `llm_agent_chat_*` (이미지 `llm-agent-sandbox`) | `agent/agent_runner.py` |
| **SearXNG** | 로컬 메타검색(JSON) | `llm_searxng` (내부 8080) | `searxng_runtime.py` |
| **Tor + Privoxy** | 프록시(회로격리) | `llm_tor` (9050 SOCKS / 8118 HTTP) | `tor_runtime.py` |
| **공유 네트워크** | 컨테이너 간 이름 통신 | `llm_net` | AGENT_NET/NET_CONNECT |

- **프라이버시**: `socks5h://`(DNS 유출 차단), SearXNG `search.method: POST`, 메트릭/제목쿼리 비활성,
  Tor 회로 격리(IsolateDestAddr). 시스템 메시지에 **개인정보 외부 전송 금지** 강제(PRIVACY_GUARD).

---

## 5. 에이전트 실행 순서 (agent_chat 파이프라인)

`_run_gui_chat_unified` 는 `agent.start(cmd)` 앞에서 아래를 순서대로 수행한다(전부 최근 패치):

1. **NETMODE_LOG** — `[인터넷] Tor 경유 …` 표시
2. **Docker 게이트**(TOR_DOCKER_ORDER/TOR_QUIET) — 데몬 확인/자동시작(조용히 로그로)
3. **DOCKER_READY** — `docker ps` 성공까지 대기(재시작 직후 대비)
4. **OLLAMA_READY** — Ollama(11434) 응답까지 대기
5. **SEARXNG_AUTOSTART** — 로컬 SearXNG 기동
6. **AGENT_NET** — `llm_net` 생성 + cmd 에 `--network llm_net` + 프록시 호스트를 `llm_tor` 로 치환
7. **NET_CONNECT / NET_LOG** — 실행 중 `llm_tor`/`llm_searxng` 를 `llm_net` 에 연결(결과 `[net]` 표시)
8. **SYSMSG_FILE** — 긴 시스템 메시지를 `@FILE:`(마운트 파일)로 → WinError 206 방지
9. **PRETOOL_PATH** — `-e PYTHONPATH=/home/agent/.agent_state`
10. **PRETOOL_SYNC** — PreTool/sitecustomize 를 실제 마운트 폴더로 복사
11. **agent.start(cmd)** → 실패 시 **AGENT_RETRY**(2회) → 여전히 실패면 **START_DIAG/DIAG2**(원인 진단)

미니루프 내부: `--system_message @FILE:` 를 파일에서 읽고(SYSMSG_READ), 코드블록마다 별도
`python3 -c` 실행(sitecustomize 로 PreTool 전역 주입).

---

## 6. PreTool — 에이전트 도구 패키지

| 범주 | 함수 |
|------|------|
| 검색 | `web_search(q)` · `search_summary(q)` · `fetch_text(url)` · `net_diag()` |
| 엑셀/표 | `excel_write(path, rows, headers)` · `csv_write` · `read_table` |
| 문서 | `report_write(path, title, sections)` |
| 파일 | `move` · `copy` · `list_files` · `organize_by_ext` |
| 개발 | `run_tests(code, cases)` · `check_syntax` · `run_python` · `lint` · `outline` · `diff` · `complexity` |
| 데이터 | `calc` · `json_pretty` · `json_query` · `summarize_text` · `word_stats` |

- **순수 stdlib** — 샌드박스에서 pip 불필요.
- **import 없이 호출** — `sitecustomize` 가 `PreTool.__all__` 을 builtin 으로 주입.
- **검색 경로** — `web_search` 는 SearXNG(JSON)→SearXNG(HTML)→DuckDuckGo 3단 폴백.
- 전체 목록: `import PreTool; print(PreTool.catalog())`.

---

## 7. 데이터 저장 구조 (`user_data/`)

```
user_data/
├── settings/        user_config.json, folder_policy.json   ← launcher/settings 디렉터리 정션
├── chat/            Open WebUI DB + 캐시 (actions/chat.py 가 DATA_DIR 지정)
├── logs/            launcher_*.log  (대화 [CHAT]·네트워크 [net]·기동 [tor/docker]/[searxng])
└── interpreter/
    └── sandbox/     세션 session_*.json + PreTool/ + sitecustomize.py
                     → 컨테이너 /home/agent/.agent_state 로 마운트
```
폴더째 복사하면 다른 PC로 이식 가능. 종료해도 보존(모델 언로드·캐시 정리만 수행).

---

## 8. 현재 동작 상태 (v39)

### ✅ 해결 완료
- **에이전트 기동** — WinError 206(명령줄 초과)을 시스템 메시지 파일 전달로 해결,
  Docker 재시작 직후 실패는 재시도로 흡수.
- **PreTool** — 17+개 도구. 실제 마운트로 동기화(PRETOOL_SYNC) + PYTHONPATH → `import PreTool` 정상,
  sitecustomize 로 import 없이 전역 호출 가능.
- **SearXNG 경로** — 자동 기동 + `llm_net` 연결 확인(`[net] llm_searxng 이미 llm_net 에 연결됨`),
  `web_search` 가 `llm_searxng:8080` JSON 으로 접속. **이 경로는 완성.**
- **IO_LOG** — 입력·모델출력·코드·결과·네트워크 연결이 전부 런처 로그에 기록.
- 콘솔 깜빡임 제거 · Docker/Tor 준비 백그라운드 · 종료 시 llm_tor 자동 정리.

### ⚠️ 남은 문제 (검색 실패의 마지막 원인)
1. **`llm_tor` 의 `llm_net` 합류 레이스** — `[net] llm_tor 연결 실패: Container … is marked for
   removal and cannot be connected`. 옛 컨테이너 제거 중이라 연결 실패 → 프록시 `llm_tor:8118`
   이름 해석 불가(`gaierror -2`).
2. **8b 무검열 모델의 도구 shadow** — 모델이 PreTool 의 `web_search` 를 자기 urllib 로 재정의하고
   그 코드가 (1)의 깨진 프록시로 나가 실패. **PreTool 의 `search_summary`(→ SearXNG)를 그대로
   썼다면 성공했을 상황.**

> 인프라(기동·도구·검색엔진·네트워크·로깅)는 사실상 완성. **(1)만 해결되면 모델의 자기 urllib 도
> 프록시로 정상 동작**하여 shadow 가 무해해진다.

---

## 9. 패치 이력 (테마별 43개)

**기동 안정화** — SYSMSG_FILE/READ(WinError 206) · AGENT_RETRY · DOCKER_READY · OLLAMA_READY ·
START_DIAG/DIAG2 · MID_DOWNGRADE/ENTRY_LADDER/MODEL_DISPLAY/TIERS(모델 선택·강등·표시)

**도구(PreTool)** — PRETOOL_HINT/DEV_HINT/FORCE(안내·직접호출 지시) · PRETOOL_PATH(PYTHONPATH) ·
PRETOOL_SYNC(실제 마운트 복사) · sitecustomize(전역 주입)

**검색/네트워크** — WEBSEARCH_HINT/URLENCODE_HINT/SEARCH_RECIPE(검색 지시) · HTTP_PROXY(8118) ·
SEARXNG_AUTOSTART · AGENT_NET/NET_CONNECT/NET_LOG(공유 네트워크) ·
TOR_TOGGLE/AUTOSTART/DOCKER_ORDER/QUIET(Tor)

**UI/세션** — UNIFIED_ENTRY/ENTRY_INWINDOW · SESSION_RESUME/SESSION_HINT ·
SIDEBAR_RESTORE/STARTUP_BUTTONS/PREWARM_UI · NETMODE_LOG · IO_LOG(chat_panel v4)

**설치/정리** — MANAGE_FIX · SEARXNG_STOP/HARDEN · PRIVACY_GUARD · DEADCODE_CLEANUP · STARTUP_FIX

---

## 10. 설정 · 패치 규약

**주요 설정(`launcher/config.py`)**: `OLLAMA_PORT=11434`, `SANDBOX_IMAGE=llm-agent-sandbox`,
`MODEL_TAG`(ARA), `MODEL_TAG_FALLBACK`(gemma4:12b). 네트워크명 오버라이드: 환경변수 `LLM_NETWORK`(기본 `llm_net`),
SearXNG URL: `SEARXNG_URL`(기본 `http://llm_searxng:8080`).

**패치 규약(엄격)**: 멱등(버전 마커) · 앵커 기반 정확 치환 · MISS 시 무손상 · AST/compile 검증 ·
원자적 쓰기(tmp+os.replace, CRLF 보존) · 미니루프는 b64 → 디코드·수정·재인코드 ·
`.bat` 는 ASCII+CRLF · Windows docker subprocess 는 `CREATE_NO_WINDOW` · 자기삭제 `APPLY_*` 쌍.

---

## 11. 문제 해결 / 다음 단계

### 검색이 `Name or service not known` (llm_tor/llm_searxng 못 찾음)
컨테이너가 `llm_net` 에 안 붙은 상태. **`docker rm -f llm_tor llm_searxng` 후 `APPLY_ALL.bat`
재실행** → 깨끗한 컨테이너가 `--network llm_net` 로 생성되어 자동 합류. 재발 시 런처 로그의
`[net]` 두 줄로 확인.

### 검색이 `Network is unreachable`
`host.docker.internal` 로 컨테이너 게시 포트에 도달 불가한 케이스 → 이미 `llm_net`+컨테이너명으로
전환됨(위 항목으로 해결). Ollama(11434)만 되는 건 정상(호스트 프로세스).

### 모델이 도구를 안 쓰고 자기 코드를 짬 / 응답 불안정
8b 무검열 모델 특성. **[모델 변경]으로 `qwen2.5-coder:7b/14b` 권장**(도구 준수율↑).

### 에이전트 시작 실패
채팅에 진단이 뜬다: "Ollama 설치 모델 N개" / "이미지 없음" / "컨테이너 출력 …".
그 문구로 원인(모델 미설치/이미지/컨테이너 오류) 판별.

### 재개 시 우선 작업
1. `llm_tor` 의 `llm_net` 확실 합류(깨끗한 재시작 또는 NET_CONNECT 재시도/tor_runtime 자체 connect).
2. 모델 shadow 회피(모델 교체 또는 지시 강화; (1) 해결 시 자동 무해화).
3. `search_summary('오늘 코스피')` 결과가 오는지 런처 로그(IO_LOG)로 검증.

---

## 부록 — 알려진 제약
- Docker/컨테이너 네트워크는 실제 Windows+Docker PC에서 런처 로그(IO_LOG/NET_LOG)로 검증한다.
- 8b 무검열 모델(huihui/ARA)은 도구·지시 준수가 불안정 → 스크랩엔 `qwen2.5-coder` 권장.
- `host.docker.internal` 은 호스트 프로세스(Ollama)만 도달, 컨테이너 게시 포트엔 도달 불가
  → `llm_net` 공유 네트워크 + 컨테이너명 통신으로 전환함.
