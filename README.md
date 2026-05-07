# LLM Local Setup

Bilingual installer (English / Korean) for an uncensored Gemma 4 26B local LLM environment with chat UI, sandboxed automation agent, and self-hosted search.

이중언어 (영어/한국어) 설치 프로그램. 검열 해제된 Gemma 4 26B 로컬 LLM 환경 + 채팅 UI + 샌드박스 자동화 에이전트 + 자체 호스팅 검색.

> **🔧 Stability Patch Included** — This package includes critical fixes for Open WebUI startup, SearXNG compatibility, and Korean Windows encoding. See [Stability Patches](#stability-patches--안정성-패치) below.
>
> **🔧 안정성 패치 포함** — Open WebUI 시작 실패, SearXNG 호환성, 한국어 Windows 인코딩 문제를 해결하는 패치가 포함돼 있습니다. 아래 [안정성 패치](#stability-patches--안정성-패치) 섹션 참조.

---

## Quick Start / 빠른 시작

### Fresh install / 신규 설치

1. Double-click `INSTALL.bat` — choose language → installs everything
   `INSTALL.bat` 더블클릭 → 언어 선택 → 모든 것 자동 설치

2. Double-click `RUN.bat` — interactive menu starts
   `RUN.bat` 더블클릭 → 메뉴 시작

### Already installed but having issues? / 이미 설치했는데 문제 있나요?

Double-click **`APPLY_PATCHES.bat`** to fix Open WebUI startup, SearXNG timeout, and other stability issues. See [Stability Patches](#stability-patches--안정성-패치) below for details.

**`APPLY_PATCHES.bat`** 을 더블클릭하면 Open WebUI 시작 실패, SearXNG 타임아웃 등의 안정성 문제가 자동으로 해결됩니다. 자세한 내용은 아래 [안정성 패치](#stability-patches--안정성-패치) 섹션 참조.

---

## Project Structure / 프로젝트 구조

```
llm_local_setup/
├── INSTALL.bat                       ← Install (double-click)
├── RUN.bat                           ← Run (double-click)
├── APPLY_PATCHES.bat                 ← Apply stability patches (double-click)
├── README.md
├── .gitignore
├── apply_all_fixes.py                ← Patch tool (handlers/ollama/etc.)
├── apply_searxng_install_fix.py      ← Patch tool (limiter.toml fix)
├── apply_searxng_menu_fix.py         ← Patch tool (menu enhancement)
├── apply_url_reminder_fix.py         ← Patch tool (URL reminder)
├── installer/                        ← Install package
│   ├── __main__.py                   (entry point: `python -m installer`)
│   ├── i18n.py                       (translations)
│   ├── lang_setup.py                 (language selection)
│   └── (other modules)
└── launcher/                         ← Run package
    ├── __main__.py                   (entry point: `python -m launcher`)
    ├── i18n.py
    └── (other modules)
```

After install, an additional folder is created:
설치 후 다음 폴더가 추가됩니다:

```
└── llm_environment/
    ├── ollama_runtime/     (portable ollama.exe)
    ├── llm_models/         (model data ~14GB)
    ├── chat_ui/venv/       (Open WebUI)
    ├── agent/
    │   ├── venv/           (host direct mode)
    │   ├── sandbox/        (Docker sandbox)
    │   └── workspace/      (host <-> container shared folder)
    ├── searxng/config/     (search engine settings)
    └── logs/
        ├── chat_ui.log     ← chat session debug log (NEW)
        ├── ollama_run.log
        └── ollama_install.log
```

---

## What Each External Program Does / 외부 프로그램별 역할

The installer needs three external programs to be installed on your system. Here's what each one does and why:

설치 프로그램은 시스템에 세 가지 외부 프로그램이 설치돼 있어야 합니다. 각각의 역할:

### Python 3.11+

**English:** The programming language this installer and tools (Open WebUI, Open Interpreter) are written in. Install once on your PC like an OS-level component. Free, official site: python.org.

**한국어:** 이 설치 프로그램과 도구들(Open WebUI, Open Interpreter)이 작성된 프로그래밍 언어입니다. 운영체제처럼 PC에 한 번만 설치하면 됩니다. 무료, 공식 사이트: python.org.

**Required for:** Everything (without this, nothing works)
**필요한 경우:** 모든 기능 (없으면 아무것도 동작 안 함)

**Important:** During Python install, tick "Add Python to PATH".
**중요:** Python 설치 시 "Add Python to PATH" 체크.

### Docker Desktop

**English:** A tool that runs apps inside isolated "containers" — like mini virtual machines. We use it for:

1. **Sandbox automation agent** — when the LLM runs code, it runs inside a container, so even if the model makes mistakes, your host PC is protected.
2. **SearXNG search engine** — a self-hosted search engine that aggregates Google/Bing/DuckDuckGo without tracking you. Runs in a container so it's isolated from your system.

Without Docker, the chat UI still works, but you can't use the sandbox or search.

**한국어:** 앱을 격리된 "컨테이너" (작은 가상 머신 같은 것) 안에서 실행하는 도구. 이 환경에서는 두 가지에 사용됩니다:

1. **샌드박스 자동화 에이전트** — LLM이 코드를 실행할 때 컨테이너 안에서 돌아가서, 모델이 실수해도 호스트 PC는 보호됩니다.
2. **SearXNG 검색 엔진** — Google/Bing/DuckDuckGo 결과를 추적 없이 통합하는 자체 호스팅 검색 엔진. 컨테이너에서 격리 실행.

Docker가 없으면 채팅 UI는 동작하지만 샌드박스와 검색을 못 씁니다.

**Required for:** Sandbox agent, SearXNG search
**필요한 경우:** 샌드박스 에이전트, SearXNG 검색

**Settings during install / 설치 시 설정:**
- ✅ "Use WSL 2 instead of Hyper-V" — required (WSL 2 is a Windows feature that runs Linux fast; Docker uses it)
- ✅ "Use WSL 2 instead of Hyper-V" — 필수 (WSL 2는 Windows에서 Linux를 빠르게 돌리는 기능; Docker가 이걸 사용)

**License / 라이선스:**
- Free for personal use, students, small companies (under 250 employees AND under $10M revenue)
- 개인/학생/소규모 회사 (250명 미만 + 매출 $10M 미만) 무료

### NVIDIA GPU Drivers (optional / 선택)

**English:** If you have an NVIDIA GPU, install the latest drivers. Ollama will automatically use the GPU for fast inference. Without GPU: CPU inference, very slow (10-30s per token instead of 0.1s).

**한국어:** NVIDIA GPU가 있으면 최신 드라이버를 설치하세요. Ollama가 자동으로 GPU를 사용해서 빠른 추론을 합니다. GPU 없으면: CPU 추론, 매우 느림 (토큰당 0.1초 대신 10~30초).

---

## What Gets Installed Automatically / 자동 설치되는 것

INSTALL.bat handles these without any manual download:
INSTALL.bat이 알아서 다 받아주는 것:

| Component | What it is | Size |
|---|---|---|
| **Ollama** (portable) | LLM serving engine | ~30 MB |
| **Gemma 4 26B model** | The LLM itself (Q3_K_M quantized) | ~14 GB |
| **Open WebUI** | Browser-based chat interface | ~500 MB (with deps) |
| **Open Interpreter** | LLM-as-shell automation tool | ~100 MB |
| **SearXNG** (Docker image) | Search engine container | ~200 MB |
| **Sandbox image** | Docker image for isolated agent | ~1 GB |

Total disk usage: ~16 GB. Allow ~25 GB free for safety.
디스크 사용량 합계: 약 16 GB. 안전을 위해 25 GB 여유 권장.

---

## Menu Items / 메뉴 항목

After `RUN.bat`:
`RUN.bat` 실행 후:

| # | Item | Description |
|---|---|---|
| 1 | Chat UI | Browser-based chat (Open WebUI) at http://localhost:8080 |
| 2 | Automation agent — sandbox | **Recommended.** Isolated Docker container |
| 3 | Automation agent — host direct | **Dangerous.** Direct host access (explicit confirmation required) |
| 4 | Ollama service start/check | |
| 5 | Installed model info | |
| 6 | Docker image build/rebuild | |
| 7 | SearXNG search engine control | Start/stop/recreate + view container logs |
| 8 | Settings (view/reset/language) | |

---

## Troubleshooting / 문제 해결

### "open_webui is a package and cannot be directly executed"
Run `APPLY_PATCHES.bat`. This is a known Open WebUI launcher issue, fixed by the patch.

`APPLY_PATCHES.bat` 을 실행하세요. 알려진 Open WebUI 진입점 문제이며, 패치로 해결됩니다.

### "SearXNG 시작 타임아웃" / SearXNG startup timeout
Run `APPLY_PATCHES.bat`. The patch increases the timeout to 60s, splits container/HTTP diagnostics, and self-heals broken `limiter.toml` files automatically.

`APPLY_PATCHES.bat` 을 실행하세요. 패치가 타임아웃을 60초로 늘리고, 컨테이너/HTTP 진단을 분리하며, 깨진 `limiter.toml` 을 자동 격리합니다.

### Korean text in BAT files looks broken
The patched BAT files use ASCII-only messages + `chcp 65001`, so they look identical in any Windows codepage. Replace your old `INSTALL.bat` and `RUN.bat` with the patched versions.

패치된 BAT 파일들은 100% ASCII + `chcp 65001` 을 사용해서 어떤 Windows 코드페이지에서도 동일하게 표시됩니다. 기존 `INSTALL.bat` 과 `RUN.bat` 을 패치본으로 교체하세요.

### Where do I find logs?
- `llm_environment/logs/chat_ui.log` — chat UI session log (created by patch)
- `llm_environment/logs/ollama_run.log` — Ollama service log
- `llm_environment/logs/ollama_install.log` — Ollama install log

---

# Stability Patches / 안정성 패치

## What's Included / 포함된 내용

### Critical fixes / 핵심 수정

#### 1. Open WebUI launcher (`launcher/handlers.py`)
- **Before:** `python -m open_webui serve` → `'open_webui' is a package and cannot be directly executed`
- **After:** Uses `Scripts/open-webui.exe serve` (the pip console script). Falls back to `python -m uvicorn open_webui.main:app` if the exe is missing.

- **이전:** `python -m open_webui serve` 호출 → `'open_webui' is a package and cannot be directly executed` 오류로 시작 실패
- **이후:** pip 가 등록한 콘솔 스크립트 `Scripts/open-webui.exe serve` 사용. exe 부재 시 `python -m uvicorn open_webui.main:app` 폴백.

#### 2. SearXNG limiter.toml schema mismatch
- **Before:** Old key `pass_searx_org` collides with SearXNG 2026.x schema → worker dies immediately → 60s timeout
- **After:**
  - **New installs:** `limiter.toml` is no longer created (SearXNG uses built-in defaults — never breaks across versions)
  - **Existing installs:** Self-healing. On startup, scans `limiter.toml` for deprecated keys and auto-quarantines as `limiter.toml.broken-<timestamp>`

- **이전:** 옛 키 `pass_searx_org` 가 SearXNG 2026.x 의 새 스키마와 충돌 → worker 즉시 사망 → 60초 타임아웃
- **이후:**
  - **신규 설치:** `limiter.toml` 자체를 만들지 않음 (SearXNG 기본 스키마 사용 → 어떤 버전이든 안 깨짐)
  - **기존 설치:** 자가 치유. 시작 직전 `limiter.toml` 의 deprecated 키 자동 검사 후 `limiter.toml.broken-<타임스탬프>` 로 격리.

#### 3. SearXNG startup diagnostics (`launcher/searxng_runtime.py`)
- **Before:** 20-second timeout, then a single "timeout" line
- **After:**
  - 60-second timeout (cold start can take 25-35 seconds)
  - Container running state and HTTP responsiveness tracked separately
  - On timeout, automatically captures `docker logs --tail 50` (in console + log file)
  - Fast-fail when container starts and dies (no need to wait full 60s)

- **이전:** 20초 타임아웃, "타임아웃" 한 줄
- **이후:**
  - 60초 타임아웃 (콜드 부팅이 25~35초 걸리는 사례)
  - 컨테이너 실행 상태와 HTTP 응답 분리 추적
  - 타임아웃 시 `docker logs --tail 50` 자동 캡처 (콘솔 + 로그 파일)
  - 컨테이너가 시작 후 죽으면 60초 다 안 기다리고 즉시 실패 감지

### High-priority fixes / 우선 수정

#### 4. logs folder auto-creation
- **Before:** First run could throw `FileNotFoundError: logs/ollama_run.log`
- **After:** `mkdir(parents=True, exist_ok=True)` runs before opening any log file

- **이전:** 첫 실행 시 `FileNotFoundError: logs/ollama_run.log` 가능성
- **이후:** 로그 파일 열기 전에 `mkdir(parents=True, exist_ok=True)` 선행

#### 5. BAT files Korean Windows safety
- **Before:** Extracting the zip on Korean Windows could mangle BAT messages (cp949 ↔ utf-8 collision)
- **After:** All BAT files are 100% ASCII + start with `chcp 65001` (UTF-8 console mode)

- **이전:** 한국 Windows 에서 ZIP 압축 풀면 BAT 메시지가 cp949 ↔ utf-8 충돌로 깨질 수 있음
- **이후:** 모든 BAT 가 100% ASCII + `chcp 65001` 첫 줄

#### 6. Ollama startup polling
- **Before:** 15 seconds (too short for cold start)
- **After:** 30 seconds

- **이전:** 15초 (콜드 스타트 시 부족)
- **이후:** 30초

### URL reminder (NEW) / URL 안내 (NEW)

When the chat UI starts, lots of uvicorn / FastAPI logs flood the console. Without scrolling, the user might not see the connection URL. The patch adds a highlighted reminder right before launching Open WebUI:

채팅 UI가 시작되면 uvicorn / FastAPI 로그가 콘솔에 쏟아져, 스크롤하지 않으면 사용자가 접속 URL을 못 볼 수 있습니다. Open WebUI 시작 직전에 강조된 안내가 한 번 더 표시됩니다:

```
============================================================
  ▶  브라우저에서 접속:  http://localhost:8080
============================================================
```

### Medium fixes / 중간 우선순위

- **HTTP 2xx-only check**: SearXNG 5xx responses no longer falsely register as "ready"
- **Watchdog timer cleanup**: prevents zombie `threading.Timer` on chat exit
- **`chat_ui.log`**: new detailed session log with timestamps + container logs
- **Linux MemAvailable fallback**: very old kernels now use `MemFree + Buffers + Cached`

- **HTTP 2xx 만 통과**: SearXNG 5xx 응답이 false positive 로 처리되지 않음
- **워치독 타이머 정리**: 채팅 종료 시 좀비 `threading.Timer` 방지
- **`chat_ui.log`**: 타임스탬프 + 컨테이너 로그가 포함된 새 세션 로그
- **Linux MemAvailable 폴백**: 매우 오래된 커널은 `MemFree + Buffers + Cached`

### Low priority / 낮은 우선순위

- **Watchdog debug**: Set `LLM_GUARD_DEBUG=1` to print watchdog internal exceptions
- **SearXNG menu**: Menu [7] → [5] now shows `docker logs --tail 50`

- **워치독 디버그**: `LLM_GUARD_DEBUG=1` 환경변수 설정 시 워치독 내부 예외 출력
- **SearXNG 메뉴**: 메뉴 [7] → [5] 로 `docker logs --tail 50` 즉시 표시

---

## How to Apply / 적용 방법

### One-click / 원클릭

Double-click **`APPLY_PATCHES.bat`** in the project root (where `INSTALL.bat` lives).

프로젝트 루트(`INSTALL.bat` 있는 폴더)에서 **`APPLY_PATCHES.bat`** 더블클릭.

That's it. The BAT will:
1. Set UTF-8 console mode
2. Check Python 3.11+
3. Apply 4 patches sequentially
4. Show backup file locations on success

자동으로:
1. UTF-8 콘솔 모드 설정
2. Python 3.11+ 검사
3. 4개 패치 순차 적용
4. 백업 파일 위치 표시

### Manual / 수동

```cmd
python apply_all_fixes.py
python apply_searxng_install_fix.py
python apply_searxng_menu_fix.py        :: optional
python apply_url_reminder_fix.py        :: optional but recommended
```

All patch tools are **idempotent** — safe to run multiple times. Already-patched files are auto-detected and skipped.

모든 패치 도구는 **idempotent** — 여러 번 실행해도 안전합니다. 이미 패치된 파일은 자동 감지되어 건너뜁니다.

### What gets backed up / 자동 백업되는 파일

| File | Backup name |
|---|---|
| `launcher/handlers.py` | `handlers.py.bak`, `handlers.py.searxng.bak`, `handlers.py.urlbox.bak` |
| `installer/ollama.py` | `ollama.py.bak` |
| `installer/resources.py` | `resources.py.bak` |
| `launcher/runtime_guard.py` | `runtime_guard.py.bak` |
| `installer/searxng.py` | `searxng.py.limiter.bak` |

`launcher/searxng_runtime.py`, `INSTALL.bat`, `RUN.bat` are overwritten directly — restore from git or your own backup if needed.

`launcher/searxng_runtime.py`, `INSTALL.bat`, `RUN.bat` 은 직접 덮어씌워지므로, 필요시 git 등에서 복원하세요.

### Rollback / 롤백

```cmd
copy /Y launcher\handlers.py.bak launcher\handlers.py
copy /Y installer\ollama.py.bak installer\ollama.py
copy /Y installer\resources.py.bak installer\resources.py
copy /Y launcher\runtime_guard.py.bak launcher\runtime_guard.py
copy /Y installer\searxng.py.limiter.bak installer\searxng.py
```

---

## What Happens On First Run After Patch / 패치 후 첫 실행 시 일어나는 일

When you run `RUN.bat` → menu [1] for the first time after patching, you'll see:

패치 후 처음 `RUN.bat` → 메뉴 [1] 을 실행하면 다음과 같은 메시지가 나타납니다:

```
[INFO] Ollama 서비스 확인 중...
[ OK ] Ollama 가동 확인
[INFO] SearXNG 검색 엔진 시작 시도...
[WARN] 이전 SearXNG 설정의 한 파일이 새 버전과 호환되지 않아 격리했습니다:
[WARN]   ...searxng/config/limiter.toml.broken-20260507_xxxxxx
[INFO] SearXNG 는 안전한 기본값으로 시작합니다 (검색 기능 정상)
[INFO] 기존 SearXNG 컨테이너 재시작…
[ OK ] SearXNG 가동: http://localhost:8888  (28초)
[ OK ] 검색 자동 연결: http://localhost:8888

[INFO] 브라우저: http://localhost:8080
[INFO] 검색 사용: 채팅창 + 버튼 -> 'Web Search' 토글
[INFO] 종료: Ctrl+C
[INFO] 세션 로그: ...llm_environment\logs\chat_ui.log

============================================================
  ▶  브라우저에서 접속:  http://localhost:8080
============================================================

INFO:     Started server process [12345]
INFO:     Uvicorn running on http://0.0.0.0:8080
...
```

The `[WARN]` line about quarantine is normal on first run after patching — it means the self-healing fixed your `limiter.toml`. After this, that warning won't appear again.

`[WARN]` 격리 메시지는 패치 후 첫 실행 시 정상입니다 — 자가 치유가 `limiter.toml` 을 고쳤다는 뜻. 다음부터는 안 나옵니다.

---

## FAQ / 자주 묻는 질문

**Q. Do I need to redownload the 22GB `llm_environment/`?**
**Q. 22GB `llm_environment/` 폴더를 다시 다운로드해야 하나요?**

No. The patch only modifies code. `llm_environment/` (your installed model + venvs + Docker config) is preserved as-is.
아닙니다. 이번 패치는 코드만 수정합니다. `llm_environment/` 는 그대로 보존됩니다.

**Q. The quarantine `[WARN]` message doesn't appear. Is something wrong?**
**Q. 격리 `[WARN]` 메시지가 안 나오는데 정상인가요?**

That's normal if your `limiter.toml` either doesn't exist or has only compatible keys. The self-healing only acts when it finds problems.
정상입니다. `limiter.toml` 이 이미 없거나 호환되는 키만 있으면 격리하지 않습니다.

**Q. The chat UI starts but search doesn't work.**
**Q. 채팅 UI는 시작되는데 검색이 안 됩니다.**

Check the end of `llm_environment/logs/chat_ui.log`. If SearXNG startup failed, the container logs are included so you can see the cause.
`llm_environment/logs/chat_ui.log` 의 마지막 부분을 확인하세요. SearXNG 시작 실패 시 컨테이너 로그도 포함되어 원인을 알 수 있습니다.

**Q. Can I run `APPLY_PATCHES.bat` more than once?**
**Q. `APPLY_PATCHES.bat` 을 여러 번 실행해도 되나요?**

Yes. All patch tools are idempotent. Already-patched files are skipped. Backup files (`*.bak`) are not overwritten on subsequent runs.
네. 모든 패치 도구는 idempotent 입니다. 이미 패치된 파일은 건너뜁니다. 백업 파일(`*.bak`)도 두 번째 실행에서 덮어씌워지지 않습니다.

---

## Verified Compatibility / 검증된 호환성

- Python 3.11+ / Windows 10·11
- Docker Desktop (optional)
- SearXNG 2026.x (the version that triggered this patch)
- Open WebUI latest
- Korean / English / Japanese Windows codepages — all decode BAT files identically

- Python 3.11+ / Windows 10·11
- Docker Desktop (선택)
- SearXNG 2026.x (이번 패치를 트리거한 버전)
- Open WebUI 최신
- 한국어 / 영어 / 일본어 Windows 코드페이지 — BAT 파일 모두 동일하게 디코드
