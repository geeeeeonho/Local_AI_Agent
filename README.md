# LLM Local Setup

> Windows용 **포터블 로컬 LLM 환경**. 인터넷 없이도 동작하는 채팅·자동화 에이전트·웹 검색을
> 단일 GUI 런처에서 제공합니다. 비전문가도 `INSTALL.bat` → `RUN.bat` 두 번으로 시작할 수 있고,
> 모든 사용자 데이터(채팅·설정·로그·에이전트 세션)는 **`user_data/` 한 곳**에 모입니다.

- **실행 환경**: Windows 10/11, Python 3.12.x, (선택) Docker Desktop
- **루트 경로 예시**: `C:\Users\ghwork\Works\Local_AI`
- **구동 방식**: `python -m launcher` (GUI) / `python -m installer` (설치) — `RUN.bat`·`INSTALL.bat` 가 감싼다

---

## 1. 빠른 시작

```cmd
INSTALL.bat      :: 1회 설치 (Python·Docker 감지 → 환경 구성)
RUN.bat          :: GUI 런처 실행 (Tkinter 단일 윈도우)
RUN_TUI.bat      :: 터미널 UI 강제 (헤드리스/원격)
```

- `RUN.bat` 는 인자 없이 GUI 로 뜨고, tkinter 가 없거나 GUI 초기화가 실패하면 **자동으로 TUI 로 폴백**합니다.
- Docker 가 없으면 샌드박스 에이전트·SearXNG 는 자동으로 건너뜁니다 (Ollama·채팅은 동작).

---

## 2. 메뉴 기능

| 키 | 기능 | 설명 |
|----|------|------|
| **1** | 채팅 UI (Open WebUI) | 브라우저 기반 채팅 + 자동 웹 검색. 시작 후 **"▶ 브라우저 열기"** 버튼으로 진입 |
| **2** | 자동화 에이전트 *(통합)* | 에이전트와 GUI 대화. 내부에서 **샌드박스(권장) / 호스트 직접** 모드 선택 |
| **4** | Ollama 서비스 시작/확인 | 로컬 모델 서버 상태 확인·기동 |
| **5** | 설치된 모델 정보 | 적재 모델 목록·크기 |
| **6** | Docker 이미지 빌드/재빌드 | 샌드박스 이미지 생성 |
| **7** | SearXNG 검색 엔진 제어 | 메타 검색 컨테이너 제어 |
| **8** | 설정 관리 | 보기 / 워크스페이스 초기화 / 언어 / 로그 on·off / 전체 초기화 |
| **q** | 종료 | 종료 시 정리 hook 동작 (아래 8장) |

> [2] 는 과거 `[2] 샌드박스` + `[3] 호스트직접` 으로 나뉘어 있던 것을 **하나로 통합**(`actions/agent_chat.py`, `v7_1_unified`)했습니다. 호스트 직접 모드는 `I-UNDERSTAND` 게이트로 보호됩니다.

---

## 3. 데이터 저장 구조 — `user_data/`  ★ 핵심

모든 사용자 데이터는 프로젝트 루트의 **`user_data/`** 하위에 모입니다. 프로그램을 종료해도 보존되고,
폴더째 복사하면 다른 PC로 이전할 수 있습니다.

```
user_data/
├── settings/        설정 (user_config.json)  ← launcher/settings 가 여기를 가리킴(정션)
├── logs/            런처/세션 로그            ← lifelog 가 직접 기록
├── chat/            Open WebUI 데이터          ← webui.db(채팅·계정·설정) + uploads/ + vector_db/
└── interpreter/
    ├── sandbox/     샌드박스 에이전트 세션 (session_*.json)
    └── host/        호스트 에이전트 세션
```

### 어떻게 연결되어 있나 (배선)

| 데이터 | 실제 위치 | 연결 방식 |
|--------|-----------|-----------|
| **채팅(Open WebUI)** | `user_data/chat/` | `actions/chat.py` 가 시작 시 환경변수 `DATA_DIR` 을 지정 |
| **에이전트 세션** | `user_data/interpreter/sandbox/` | `agent_runner.py` 가 컨테이너에 마운트 + `AGENT_STATE_DIR` 전달 |
| **설정** | `user_data/settings/` | `launcher/settings` → `user_data/settings` **디렉터리 정션** (코드 변경 없음) |
| **로그** | `user_data/logs/` | `lifelog._log_dir` 을 `user_data/logs` 로 지정 |

> **정션(junction)이란?** `settings_store.py`·`lang_setup.py`·`agent_runner`·`INSTALL.bat` 는 모두
> 그대로 `launcher\settings` 경로를 쓰지만, 그 폴더 자체가 `user_data\settings` 를 가리키는 링크라
> **물리적으로는 `user_data\settings` 에 저장**됩니다. 코드 한 줄도 바꾸지 않아 회귀 위험이 없습니다.
> (`mklink /J`, 관리자 권한 불필요)

---

## 4. 전체 디렉터리 구조

```
Local_AI/
├── RUN.bat                  GUI 런처 실행
├── RUN_TUI.bat              터미널 UI 강제
├── INSTALL.bat              설치 (ASCII/CRLF)
│
├── launcher/                ← 런처 패키지 (UI + 액션)
│   ├── __main__.py          진입점: HERE=루트, ENV=llm_environment, 모드결정+자동폴백
│   ├── __init__.py          패키지 설명 + 호환 shim 안내
│   ├── config.py            상수 (OLLAMA_URL, MODEL_TAG, SANDBOX_IMAGE, WIN_CREATE_* 등)
│   ├── app.py               Application: _build_menu_items / _build_action_map / 단일윈도우 루프
│   ├── lifelog.py           전역 종료 hook + 로그 (_log_dir → user_data/logs) + cleanup 콜백
│   ├── user_data.py         ★ user_data 경로/JSON IO/세션 헬퍼 (USER_DATA_v1)
│   ├── agent_runner.py      UnifiedAgent + 미니루프 래퍼(b64) + ErrorGuard + 로그토글
│   ├── settings_store.py    영속 설정 (JSON) — 저장 위치는 정션으로 user_data/settings
│   ├── i18n.py              UI 다국어
│   ├── runtime_guard.py     자원 워치독
│   ├── searxng_runtime.py   SearXNG 런타임 제어
│   │
│   ├── presenter/           ← UI 추상화 (액션은 UI 종류에 무지)
│   │   ├── base.py          Presenter ABC, MenuItem, Option
│   │   ├── tui.py           TerminalPresenter (ANSI)
│   │   └── gui/             단일 윈도우 Tk Presenter (약 10개 모듈)
│   │       ├── presenter.py   TkPresenter 본체
│   │       ├── window.py      MainWindow + PanelHost
│   │       ├── sidebar.py     토글 사이드바
│   │       ├── statusbar.py   Ollama/Docker 상태 폴링
│   │       ├── menu_panel.py  카드 메뉴
│   │       ├── panels.py      Home / Checkbox / Log 패널
│   │       ├── chat_panel.py  에이전트 대화 패널
│   │       ├── dialogs.py     위험확인/텍스트입력
│   │       ├── widgets.py     Tooltip / 버튼
│   │       └── theme.py       다크 색상/폰트 (VS Code Dark Modern 풍)
│   │
│   ├── services/            ← 외부 자원 헬퍼 (UI 무관)
│   │   ├── ollama.py        OllamaService (is_running, env_vars …)
│   │   └── docker.py        DockerService (daemon_alive …)
│   │
│   ├── actions/             ← 메뉴 액션 (한 파일 = 한 액션)
│   │   ├── __init__.py      액션 import 묶음
│   │   ├── chat.py          [1] Open WebUI  ★ DATADIR/NOAUTH/AUTOSTOP 패치 적용
│   │   ├── agent_chat.py    [2] 통합 에이전트 진입점 (v7_1_unified)
│   │   ├── agent_sandbox.py (legacy) 샌드박스 모드 로직
│   │   ├── agent_direct.py  (legacy) 호스트 직접 모드 로직
│   │   ├── ollama.py        [4]
│   │   ├── model_info.py    [5]
│   │   ├── docker_image.py  [6]
│   │   ├── searxng.py       [7]
│   │   ├── settings.py      [8]
│   │   └── _sandbox_options.py  공유 옵션 정의
│   │
│   └── (legacy shim)        ui.py, checkbox.py, menu.py, handlers.py, gui.py
│
├── installer/               ← 설치 패키지
│   ├── __main__.py          설치 진입점 (python -m installer)
│   ├── lang_setup.py        언어 결정/저장 (user_config.json)
│   ├── i18n.py              번역 테이블 (en/ko)
│   ├── resources.py         시스템 사양 감지 → 안전한 설치 파라미터 산출
│   └── python_tools.py      Open WebUI 등 도구 설치
│
├── llm_environment/         ← 설치 후 생성되는 자원 (ENV)
│   ├── ollama_runtime/      ollama.exe
│   ├── llm_models/          *.gguf (대형 양자화 모델)
│   ├── chat_ui/             Open WebUI venv
│   ├── agent/               에이전트 venv + sandbox(Dockerfile) + workspace
│   ├── searxng/             SearXNG 설정
│   ├── scripts/             보조 스크립트
│   └── logs/                (긴급/치명 로그 launcher_fatal.log 등)
│
└── user_data/               ← ★ 통합 사용자 데이터 (3장 참고)
    ├── settings/  (정션→) logs/  chat/  interpreter/{sandbox,host}/
```

> **변경 요약**: `launcher/user_data.py` 신규 · `user_data/` 트리 신규 · `launcher/settings` 는 정션 ·
> `actions/chat.py`·`agent_runner.py`·`lifelog.py` 패치 · 네이티브 Tkinter 일반채팅은 제거(웹으로 대체).

---

## 5. 아키텍처 핵심

### Presenter 패턴
모든 액션은 `launcher/presenter/base.py` 의 `Presenter` 인터페이스만 사용합니다. 같은 액션 코드가
TUI(`tui.py`)와 단일 윈도우 GUI(`presenter/gui/`)에서 그대로 동작합니다.

```python
def run(env: Path, p: Presenter) -> None:
    p.section("샌드박스 시작")
    p.info("Docker 데몬 확인 중…")
    sel = p.show_checkbox(title="옵션", options=opts)
    if sel is None:
        return            # 사용자가 취소
    # ... 실제 작업
    p.pause()
```

### 새 메뉴 액션 추가 (3단계)
1. `launcher/actions/my_action.py` 에 `def run(env, p): ...` 작성
2. `launcher/actions/__init__.py` 에 import 추가
3. `launcher/app.py` 의 `_build_menu_items()` + `_build_action_map()` 에 한 줄씩 추가

### 단일 윈도우 GUI
`app.py._run_single_window()` 가 사이드바 클릭 → `action_runner(key)` → 패널 전환을 처리합니다.
GUI 위젯 생성은 **반드시 메인 스레드**에서만 일어나야 하며, 워커 스레드는 `root.after(0, …)` 로 마샬링합니다.

### 자동화 에이전트
- **샌드박스 모드(권장)**: Docker 컨테이너에서 경량 REPL(**미니루프**)이 모델과 대화. 화면 캡처/GUI 자동화
  API(`pyautogui`, `mss`, `PIL.ImageGrab` 등)는 **ErrorGuard** 정규식으로 차단.
- **호스트 직접 모드**: 실제 Open Interpreter 를 호스트에서 실행 (`I-UNDERSTAND` 확인 필요).
- 미니루프는 `agent_runner.py` 안에 base64 문자열(`_AGENT_REPL_SRC_B64`)로 내장됩니다.

### 메모리 절약 설계
대형 모델은 메모리 압박 시 무한루프·응답절단·자기소개만 반복 등의 증상을 보입니다. 대응책으로
컨텍스트 윈도우 축소, 시스템 메시지 압축, 모델 다운사이즈(`gemma2:9b`, `qwen2.5:7b`, `llama3.2:3b`)를 권장합니다.

---

## 6. 종료/정리(lifecycle)

`lifelog.py` 가 시작 시 4종 종료 hook(atexit / SIGINT / SIGTERM / Windows ConsoleCtrlHandler)을 설치하고,
종료 시 등록된 cleanup 콜백을 모두 실행합니다.

- `register_ollama_cleanup` — 적재 모델 정리
- `register_orphan_container_cleanup_auto` — 고아 컨테이너 정리 (이름/이미지 패턴 자동 감지)
- `register_host_process_cleanup(get_pid_fn)` — Windows `taskkill /PID … /T /F` 로 프로세스 **트리** 종료

**Open WebUI 자동 종료**: `actions/chat.py` 가 위 host-process cleanup 에 webui PID 를 등록하고,
채팅 패널을 나오거나(=`pause` 반환) 런처를 닫으면 서버 프로세스(파워셀+uvicorn)가 자동 정리됩니다.
*브라우저 탭만 닫는 것으로는 종료되지 않습니다 — 패널을 나오거나 런처를 닫으세요.*

---

## 7. 적용된 패치 / 마커 목록

모든 패치는 **멱등**(마커로 재실행 안전), **앵커 기반 정확 치환**(불일치 시 무손상 중단),
**AST 검증 후 원자적 저장**(tmp + `os.replace`)으로 만들어졌습니다.

| 영역 | 마커 / 방식 | 대상 파일 | 내용 |
|------|------------|-----------|------|
| 기반 | `USER_DATA_v1` | `launcher/user_data.py` | user_data 경로·JSON·세션 헬퍼 모듈 |
| 에이전트 | `MINILOOP_v1` (b64) | `agent_runner.py` | 경량 REPL — v9.1 파일쓰기(Python `open().write()`), v9.2 stdlib 유도(인터넷 차단), v9.3 세션 영속/복원 |
| 에이전트 | `AGENT_STATE_PERSIST_v1` | `agent_runner.py` | 샌드박스 세션 → `user_data/interpreter/sandbox` 마운트 |
| 에이전트 | `LLM_VERBOSE_LOG_v1` | `agent_runner.py` | 세션 로그 상세화 on/off 토글 |
| 로그 | `LLM_SESSION_LOG_PATH_FIX_v1` | `lifelog.py` / `agent_runner.py` | 세션 로그 경로 정규화 |
| 채팅 | `WEBUI_DATADIR_v1` | `actions/chat.py` | Open WebUI `DATA_DIR` → `user_data/chat` |
| 채팅 | `WEBUI_NOAUTH_v1` | `actions/chat.py` | `WEBUI_AUTH=False` (로그인 생략·단일 사용자) |
| 채팅 | `WEBUI_AUTOSTOP_v1` | `actions/chat.py` | 패널 종료/런처 종료 시 서버 트리 자동 종료 |
| 로그 | (라인 치환) | `lifelog.py` | `_log_dir` → `user_data/logs` |
| 설정 | (정션) | `launcher/settings` → `user_data/settings` | 코드 변경 없이 저장 위치 이전 |
| 채팅 | `GCHAT_v1` *(제거됨)* | — | 네이티브 Tkinter 일반채팅 → 웹으로 대체(revert) |

---

## 8. 유지보수 / 점검 도구 (루트의 `.bat`)

| 도구 | 역할 |
|------|------|
| `CREATE_USER_DATA.bat` | `user_data/` 골격 생성 + `user_data.py` 설치 |
| `PATCH_MINILOOP.bat` | 미니루프 REPL(v9.3) 적용 |
| `PATCH_AGENT_STATE_MOUNT.bat` | 샌드박스 세션 마운트 적용 |
| `PATCH_WEBUI_DATADIR.bat` | Open WebUI 저장 위치 → `user_data/chat` |
| `PATCH_WEBUI_NOAUTH.bat` | 로그인 생략 (단일 사용자) |
| `PATCH_WEBUI_AUTOSTOP.bat` | 채팅 자동 종료 |
| `REVERT_GENERAL_CHAT.bat` | 네이티브 일반채팅 제거 |
| `PATCH_LOGS_TO_USERDATA.bat` | 로그 → `user_data/logs` |
| `MIGRATE_SETTINGS_JUNCTION.bat` | 설정 → `user_data/settings` (정션) |
| `CHECK_WEBUI_DATA.bat` | `user_data/chat` 의 `webui.db` 내용 점검(읽기전용) |
| `VERIFY_PATCHES.bat` | **모든 패치/이전 상태를 실제 파일에서 읽어 보고** |

> 각 패치 스크립트는 `--revert` 인자로 되돌릴 수 있습니다 (예: `python PATCH_WEBUI_NOAUTH.py --revert`).
> 정션 되돌리기: `MIGRATE_SETTINGS_JUNCTION.bat` → `--revert`.

---

## 9. 개발 규약 (패치 작성 시)

- **멱등성**: 마커 문자열로 재실행 안전. 이미 적용 시 변경 없음.
- **백업 파일 금지**: `.bak` 만들지 않음 (생성됐다면 삭제).
- **무손상 중단**: 앵커가 정확히 1회가 아니면 파일을 건드리지 않고 중단.
- **원자적 저장**: 임시 파일에 쓰고 AST 검증 통과 후 `os.replace()`.
- **최소 diff·가역성**: 불필요한 변경 금지, 가능하면 추가형(additive)·되돌리기 가능.
- **배치 파일**: ASCII 전용 + CRLF, `python` 우선 후 `py -3` 폴백.
- **최상위 폴더**: 사용자용 `.bat` 진입점만, 보이는 `.py` 는 최소화.

---

## 10. 문제 해결

- **로그가 루트 `logs/` 에 보임** → `PATCH_LOGS_TO_USERDATA` 적용 후 `RUN.bat` 재시작 (그 후 `user_data/logs`).
- **로그인 화면이 계속 뜸** → `WEBUI_AUTH=False` 는 **계정이 없는 새 상태**에서만 동작. `user_data/chat/webui.db` 를 지우고 `[1]` 재시작. 일부 버전 버그면 Open WebUI 업데이트.
- **채팅 닫아도 파워셀이 남음** → 브라우저만 닫으면 서버는 안 꺼집니다. **채팅 패널을 나오거나 런처를 닫으면** 자동 종료(`WEBUI_AUTOSTOP`).
- **설정이 어디 저장되는지** → 메뉴엔 `launcher\settings\…` 로 보이지만 정션이라 실제로는 `user_data\settings`.
- **무엇이 적용됐는지 모르겠다** → `VERIFY_PATCHES.bat` 실행. `[1]~[6]` 모두 `[ O ]` 면 완료.
- **GUI 가 안 뜸 (먹통)** → 콘솔/`user_data/logs` 의 진행 로그 확인. tkinter 미설치 시 자동 TUI 폴백.

---

*이 문서는 현재까지 적용된 패치(미니루프 v9.3, Open WebUI DATA_DIR/무로그인/자동종료, logs·settings 이전)와
`user_data/` 통합 구조를 반영합니다.*