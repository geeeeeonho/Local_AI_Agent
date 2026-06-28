# LLM Local Setup

> Windows용 **포터블 로컬 LLM 환경**. 인터넷 없이도 동작하는 채팅·자동화 에이전트·웹 검색을
> 단일 GUI 런처에서 제공합니다. 비전문가도 `MANAGE.bat`(설치) → `RUN.bat`(실행) 으로 시작할 수 있고,
> 모든 사용자 데이터(채팅·설정·로그·에이전트 세션)는 **`user_data/` 한 곳**에 모입니다.

- **실행 환경**: Windows 10/11, Python 3.11+ (권장 3.12.x), (선택) Docker Desktop
- **루트 경로 예시**: `C:\Users\ghwork\Works\Local_AI`
- **구동 방식**: `python -m launcher` (GUI) / `python -m installer` (설치) — `RUN.bat`·`MANAGE.bat` 가 감싼다
- **권장 사양 기준**: RAM 약 20GB 가용, VRAM 16GB. 대형 모델은 한 번에 하나만 적재(아래 8장).

---

## 0. 최근 업데이트 (이번 세션)

| 패치 | 내용 |
|------|------|
| **MANAGE.bat 통합** | `INSTALL.bat`·`DIAGNOSE.bat` 를 단일 디스패처 `MANAGE.bat` 로 합침 ([1] 설치 / [2] 모델 관리 / [3] 진단) |
| **모델 카탈로그 v3** | 다운로드 목록을 **Gemma 4 26B-A4B ARA(무검열)** + `qwen3-coder:30b` 중심으로 재구성 (3장) |
| **런타임 역할 v9** | `RUN.bat` 의 에이전트/추천이 v3 카탈로그와 정합되도록 `model_roles` 재배선 (3장) |
| **채팅 연결거부 수정** | Open WebUI 준비 전 버튼 활성화로 생기던 `ERR_CONNECTION_REFUSED` 해결 (9장) |
| **허용/금지 폴더 정책** | 에이전트가 접근할 폴더를 설정 화면에서 영구 관리. 샌드박스에선 그 외 경로 물리 차단 (4장) |
| **메모리 누적 억제** | `OLLAMA_MAX_LOADED_MODELS=1` + `OLLAMA_KEEP_ALIVE=5m` 로 모델 중복 적재 방지 (8장) |

---

## 1. 빠른 시작

```cmd
MANAGE.bat       :: 설치/유지보수 디스패처 ([1] 설치 [2] 모델 관리 [3] 진단)
RUN.bat          :: GUI 런처 실행 (Tkinter 단일 윈도우)
RUN_TUI.bat      :: 터미널 UI 강제 (헤드리스/원격)
```

처음이라면 `MANAGE.bat` → `[1] 설치` 로 환경을 구성하고, `[2] 모델 관리` 로 모델을 내려받은 뒤
`RUN.bat` 으로 사용합니다.

- `MANAGE.bat` 는 인자도 받습니다: `MANAGE.bat install` / `MANAGE.bat manage` / `MANAGE.bat diagnose`.
- `RUN.bat` 는 GUI 로 뜨고, tkinter 가 없거나 GUI 초기화가 실패하면 **자동으로 TUI 로 폴백**합니다.
- Docker 가 없으면 샌드박스 에이전트·SearXNG 는 자동으로 건너뜁니다 (Ollama·채팅은 동작).

---

## 2. 메뉴 기능

### MANAGE.bat (설치/유지보수)

| 키 | 기능 | 설명 |
|----|------|------|
| **1** | 설치 | Python·Docker 감지 → 환경 구성 (`python -m installer`) |
| **2** | 모델 관리 | 다운로드 카탈로그(3장)에서 모델 설치/삭제 (`python -m installer.manage`) |
| **3** | 진단 | Python / Docker / PATH 상태 점검 |
| **Q** | 종료 | |

### RUN.bat (GUI 런처)

| 키 | 기능 | 설명 |
|----|------|------|
| **1** | 채팅 UI (Open WebUI) | 브라우저 기반 채팅 + 자동 웹 검색. 시작 후 **"▶ 브라우저 열기"** 버튼으로 진입 |
| **2** | 자동화 에이전트 *(통합)* | 모델 역할 → **허용 폴더 정책** → 워크스페이스 → **샌드박스(권장)/호스트 직접** 선택 후 GUI 대화 |
| **4** | Ollama 서비스 시작/확인 | 로컬 모델 서버 상태 확인·기동 |
| **5** | 설치된 모델 정보 | 적재 모델 목록·크기 + 역할 표 |
| **6** | Docker 이미지 빌드/재빌드 | 샌드박스 이미지 생성 |
| **7** | SearXNG 검색 엔진 제어 | 메타 검색 컨테이너 제어 |
| **8** | 설정 관리 | 보기 / 워크스페이스 초기화 / 언어 / 로그 on·off / 전체 초기화 |
| **q** | 종료 | 종료 시 정리 hook 동작 (8장) |

> `[2]` 는 과거 `샌드박스` + `호스트직접` 으로 나뉘어 있던 것을 **하나로 통합**(`actions/agent_chat.py`)했습니다.
> 호스트 직접 모드는 격리가 없어 `I-UNDERSTAND` 게이트로 보호됩니다.

---

## 3. 모델 구성 — 다운로드 카탈로그(v3) + 런타임 역할(v9)

### 3-1. 다운로드 카탈로그 (`launcher/model_catalog.py`)

`MANAGE.bat [2] 모델 관리` 가 내려받는 목록입니다. **CORE**(권장 기본 세트, 약 50GB)와 **ADVANCED**(선택)로 나뉩니다.

| 모델 | 크기 | 용도 |
|------|------|------|
| `prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S` | ~15GB | 무검열·범용·에이전트 (MoE 활성 4B, 256K 컨텍스트) |
| `qwen3-coder:30b` | ~18GB | 코딩 에이전트 (MoE, Open Interpreter 주력) |
| `gemma4:12b` | ~7.5GB | 맥락 이해·균형·폴백 |
| `qwen2.5-coder:7b` | ~4.7GB | 코딩 롤백(저메모리) |
| `huihui_ai/qwen3-abliterated:8b` | ~5GB | 무검열 롤백(저메모리) |

> ARA 모델은 텍스트 전용 GGUF 라 인터프리터의 텍스트·툴 작업은 정상이지만, 비전 입력은 Ollama 빌드에
> 따라 제한될 수 있습니다. ADVANCED 에는 `...:Q5_K_M`, `gemma4:26b`, `devstral-small:24b`,
> `gpt-oss:20b` 등이 포함됩니다.

### 3-2. 런타임 역할 (`launcher/model_roles.py`)

`RUN.bat` 의 에이전트 선택·추천이 사용하는 역할 표입니다. **여유 메모리를 탐지해 사다리(LADDERS)를 따라
자동으로 적정 모델을 고르고**, 실제 적재에 실패하면 더 가벼운 후보로 강등합니다(probe 기반 롤백).

| 역할(키) | 기본 모델 | 메모리 부족 시 |
|----------|-----------|----------------|
| 무검열 검색/번역 `[1]` | ARA Q4_K_S | → `huihui_ai/qwen3-abliterated:8b` |
| 코딩 (Open Interpreter) `[2]` | `qwen3-coder:30b` | → `qwen2.5-coder:7b` |
| 맥락 이해 `[3]` | `gemma4:12b` | — |
| 균형(범용) `[4]` | `gemma4:12b` | — |
| 자동화 에이전트 `[5]` | ARA Q4_K_S | → `gemma4:12b` |

- 사다리 임계값(가용 메모리 기준): ARA ≈ 15.5GB, `qwen3-coder:30b` ≈ 17.0GB, `gemma4:12b` ≈ 10.0GB.
  가용의 92%만 사용하도록 안전 계수를 둡니다.
- 예: 가용 20GB → 코딩=`qwen3-coder:30b` / 에이전트=ARA. 가용 18GB 이하 → 자동으로 한 칸 강등.
- `config.MODEL_TAG` = ARA, `MODEL_TAG_FALLBACK` = `gemma4:12b` (역할 모듈을 못 읽을 때의 최종 폴백).

---

## 4. 허용/금지 폴더 정책 — `launcher/folder_policy.py`

자동화 에이전트가 접근 가능한 폴더를 **설정 화면에서 영구 관리**합니다. `[2]` 진입 시 워크스페이스 선택
직전에 **"허용 폴더 정책"** 메뉴가 뜨고, `[2] 허용/금지 폴더 설정` 에서 추가/제거합니다.

- 저장 위치: `user_data/settings/folder_policy.json` (`{"allowed":[...], "denied":[...]}`)
- **상시 허용** 폴더는 매 실행마다 컨테이너의 `/home/agent/allowed/<이름>` 으로 마운트됩니다.
  세션 워크스페이스(`/home/agent/workspace`)는 그대로 유지됩니다.
- **샌드박스 모드에선 마운트되지 않은 호스트 경로가 물리적으로 보이지 않으므로, "그 외 경로 처리 금지"가
  도커 격리로 강제됩니다.** 별도 경로 검사 코드가 필요 없습니다.
- **금지** 목록은 ⓐ 같은 폴더를 허용에 넣는 것을 차단하고(하위 경로 포함), ⓑ 호스트 직접 모드의 가드로
  쓰입니다. 존재하지 않는 폴더는 마운트에서 자동 제외됩니다.
- 호스트 직접 모드는 격리가 없어 이 제한이 "권고"에 그칩니다(위험 게이트로 가려짐).

---

## 5. 데이터 저장 구조 — `user_data/`

모든 사용자 데이터는 프로젝트 루트의 **`user_data/`** 하위에 모입니다. 종료해도 보존되고, 폴더째 복사하면
다른 PC로 이전할 수 있습니다.

```
user_data/
├── settings/        설정 (user_config.json, folder_policy.json)  ← launcher/settings 가 가리킴(정션)
├── logs/            런처/세션 로그            ← lifelog 가 직접 기록
├── chat/            Open WebUI 데이터          ← webui.db + uploads/ + vector_db/ + cache/
└── interpreter/
    ├── sandbox/     샌드박스 에이전트 세션
    └── host/        호스트 에이전트 세션
```

| 데이터 | 실제 위치 | 연결 방식 |
|--------|-----------|-----------|
| 채팅(Open WebUI) | `user_data/chat/` | `actions/chat.py` 가 환경변수 `DATA_DIR` 지정 |
| 에이전트 세션 | `user_data/interpreter/sandbox/` | `agent_runner.py` 가 컨테이너에 마운트 + `AGENT_STATE_DIR` 전달 |
| 설정·폴더정책 | `user_data/settings/` | `launcher/settings` → `user_data/settings` **디렉터리 정션** |
| 로그 | `user_data/logs/` | `lifelog._log_dir` 지정 |

> **정션(junction)**: 코드는 그대로 `launcher\settings` 경로를 쓰지만 그 폴더가 `user_data\settings` 를
> 가리키는 링크라 물리적으로는 `user_data\settings` 에 저장됩니다(`mklink /J`, 관리자 권한 불필요).

---

## 6. 디렉터리 구조 (요약)

```
Local_AI/
├── MANAGE.bat               설치/유지보수 디스패처 (install/manage/diagnose)
├── RUN.bat                  GUI 런처 실행
├── RUN_TUI.bat              터미널 UI 강제
│
├── launcher/                ← 런처 패키지 (UI + 액션)
│   ├── __main__.py          진입점: 모드 결정 + 자동 폴백 + cleanup 등록
│   ├── config.py            상수 (OLLAMA_URL, MODEL_TAG, SANDBOX_IMAGE …)
│   ├── app.py               메뉴/액션 매핑 + 단일 윈도우 루프
│   ├── lifelog.py           종료 hook + 로그 + cleanup 콜백
│   ├── user_data.py         user_data 경로/IO 헬퍼
│   ├── model_catalog.py     ★ 다운로드 카탈로그 v3 (3-1장)
│   ├── model_roles.py       ★ 런타임 역할 v9 + 메모리 사다리 (3-2장)
│   ├── folder_policy.py     ★ 허용/금지 폴더 정책 (4장)
│   ├── agent_runner.py      UnifiedAgent + 미니루프(b64) + ErrorGuard
│   ├── settings_store.py    영속 설정 (정션으로 user_data/settings)
│   ├── presenter/           UI 추상화 (base / tui / gui)
│   ├── services/            ollama.py · docker.py
│   └── actions/             chat.py[1] · agent_chat.py[2] · ollama.py[4] · model_info.py[5] …
│
├── installer/               설치 패키지 (python -m installer)
├── llm_environment/         설치 후 생성 자원 (ollama_runtime / llm_models / chat_ui / agent / searxng)
└── user_data/               ★ 통합 사용자 데이터 (5장)
```

---

## 7. 아키텍처 핵심

### Presenter 패턴
모든 액션은 `presenter/base.py` 의 `Presenter` 인터페이스만 사용합니다. 같은 액션 코드가 TUI 와
단일 윈도우 GUI 에서 그대로 동작합니다. GUI 위젯 생성은 **반드시 메인 스레드**에서만 이뤄지고, 워커
스레드는 `root.after(0, …)` 로 마샬링합니다.

### 자동화 에이전트
- **샌드박스 모드(권장)**: Docker 컨테이너에서 경량 REPL(미니루프)이 모델과 대화. 화면 캡처/GUI 자동화
  API(`pyautogui`, `mss`, `PIL.ImageGrab` 등)는 **ErrorGuard** 정규식으로 차단. 명령 컨텍스트는
  `--context_window` + `--max_tokens 512` 로 제한됩니다.
- **호스트 직접 모드**: 실제 Open Interpreter 를 호스트에서 실행 (`I-UNDERSTAND` 확인 필요, 격리 없음).
- 미니루프는 `agent_runner.py` 안에 base64 문자열로 내장됩니다.

---

## 8. 종료/정리 + 메모리 관리

`lifelog.py` 가 시작 시 4종 종료 hook(atexit / SIGINT / SIGTERM / Windows ConsoleCtrlHandler)을 설치하고,
종료 시 등록된 cleanup 콜백을 실행합니다.

- `register_ollama_cleanup` — 종료 시 적재 모델 **메모리 unload**
- `register_orphan_container_cleanup_auto` — 고아 컨테이너 정리 (이름/이미지 접두사 한정)
- `register_cache_cleanup` — `user_data/chat/cache` + `*.tmp` 정리 (임베딩/모델은 보존)
- `register_host_process_cleanup` — Windows `taskkill /T /F` 로 프로세스 **트리** 종료

**메모리 누적 억제 (이번 세션)** — `OllamaService.env_vars()` 가 Ollama 서버 기동 시 다음을 주입합니다:

- `OLLAMA_MAX_LOADED_MODELS=1` — 한 번에 한 모델만 상주. 역할 전환 시 옛 15~18GB 모델이 자동 언로드되어
  **두 모델 동시 적재로 인한 누적이 사라집니다.**
- `OLLAMA_KEEP_ALIVE=5m` — 유휴 5분 후 자동 언로드 (warmup 도 5분).
- 둘 다 `setdefault` 라 사용자가 실제 환경변수로 덮어쓰면 그 값을 존중합니다.
- ⚠ 이미 실행 중인 Ollama 에는 적용되지 않습니다 — 런처가 서버를 **새로 기동**할 때 반영되므로, 켜져 있다면
  한 번 종료 후 재시작하세요.

**Open WebUI 자동 종료**: 채팅 패널을 나오거나 런처를 닫으면 서버 프로세스가 자동 정리됩니다.
*브라우저 탭만 닫는 것으로는 종료되지 않습니다.*

---

## 9. 문제 해결

### 채팅 UI 가 "사이트에 연결할 수 없음 (ERR_CONNECTION_REFUSED)"
Open WebUI 첫 부팅이 30초를 넘으면, 과거에는 서버가 준비되기 전에 "브라우저 열기" 버튼이 활성화되어
연결 거부가 났습니다. 이번 세션에서 다음과 같이 수정했습니다:

- 준비 확인을 `/health` 우선으로 바꾸고 대기 시간을 150초로 확대.
- **버튼을 누를 때마다 응답을 재확인** — 아직 준비 안 됐으면 빈 탭을 여는 대신 "잠시 후 다시 누르세요" 안내.

여전히 안 되면 잠시 기다렸다가 다시 누르거나, `RUN.bat [4]` 로 Ollama 상태를, `MANAGE.bat [3]` 으로
Docker/Python 을 점검하세요.

### 대형 모델이 무한루프·응답 절단·자기소개만 반복
메모리 압박 신호입니다. 8장의 `OLLAMA_MAX_LOADED_MODELS=1` 이 기본 대응이며, 더 가벼운 역할
(`gemma4:12b`, `qwen2.5-coder:7b`)을 선택하거나 컨텍스트 윈도우를 줄이세요. 역할 사다리(3-2장)가
가용 메모리에 맞춰 자동 강등도 수행합니다.

### 에이전트가 의도한 폴더 밖을 건드릴까 걱정
샌드박스 모드에서는 4장의 허용 폴더만 마운트되고 나머지는 물리적으로 보이지 않습니다. 캐시/고아 정리도
`user_data` 와 프로젝트 접두사로 한정됩니다. 단, 도커 `[10]` 의 **수동 전역 prune** 은 다른 도커
프로젝트의 이미지/볼륨까지 지울 수 있으니 주의하세요(폴더가 아니라 도커 데이터 한정).
