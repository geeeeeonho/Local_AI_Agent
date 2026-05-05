# LLM Local Setup

Bilingual installer (English / Korean) for an uncensored Gemma 4 26B local LLM environment with chat UI, sandboxed automation agent, and self-hosted search.

이중언어 (영어/한국어) 설치 프로그램. 검열 해제된 Gemma 4 26B 로컬 LLM 환경 + 채팅 UI + 샌드박스 자동화 에이전트 + 자체 호스팅 검색.

---

## Quick Start / 빠른 시작

1. Double-click `INSTALL.bat` — choose language → installs everything
   `INSTALL.bat` 더블클릭 → 언어 선택 → 모든 것 자동 설치

2. Double-click `RUN.bat` — interactive menu starts
   `RUN.bat` 더블클릭 → 메뉴 시작

That's it. / 끝.

---

## Project Structure / 프로젝트 구조

```
llm_local_setup/
├── INSTALL.bat             ← Install (double-click)
├── RUN.bat                 ← Run (double-click)
├── README.md
├── .gitignore
├── installer/              ← Install package
│   ├── __main__.py         (entry point: `python -m installer`)
│   ├── i18n.py             (translations)
│   ├── lang_setup.py       (language selection)
│   └── (other modules)
└── launcher/               ← Run package
    ├── __main__.py         (entry point: `python -m launcher`)
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
| **Ollama** (portable) | LLM serving engine. Runs the model in memory, exposes HTTP API | ~600MB |
| **Gemma 4 26B ARA** | Censorship-removed Korean/English-capable LLM (Q3_K_M) | ~14GB |
| **Open WebUI** | Browser-based chat interface (like ChatGPT, but local) | ~5GB |
| **Open Interpreter** | CLI agent that runs code from natural language | ~500MB |
| **SearXNG** | Self-hosted meta search engine | ~200MB |
| **Sandbox Docker image** | Isolated Linux env for the agent | ~1.5GB |

**Total: ~22GB**

---

## System Requirements / 시스템 요구사항

- **OS:** Windows 10 or 11
- **RAM:** 16GB+ recommended (works on 8GB but slow)
- **VRAM:** 16GB+ NVIDIA GPU recommended for fast inference
- **Disk:** 30GB+ free
- **Internet:** Required during install only (~22GB download)

The installer auto-detects your system and adjusts:
설치 프로그램이 시스템을 자동 감지해서 조정:

- pip build parallelism (low-RAM PCs use fewer workers)
- Docker memory/CPU limits
- Context window size for the model
- Auto-fallback to safer settings on errors

---

## Menu Options / 메뉴 항목

After installation, RUN.bat shows:
설치 후 RUN.bat 메뉴:

```
[1] Chat UI (Open WebUI)            ← Most common
[2] Automation Agent — Sandbox      ★ RECOMMENDED
[3] Automation Agent — Host Direct  ⚠⚠ DANGEROUS
[4] Ollama service start/check
[5] Installed model info
[6] Docker image build/rebuild
[7] SearXNG search engine control
[8] Settings (view/reset/language)
```

### Safety Hierarchy / 안전 계층

| Mode | Risk | Auto-stop on RAM crisis |
|---|---|---|
| Chat UI | Low | Yes (terminate process) |
| Sandbox agent | Low (containerized) | Yes (`docker stop`) |
| Host direct | **HIGH** | Yes (terminate process), explicit confirmation required |

---

## Language Switching / 언어 전환

Language is asked once on first install, then saved.
언어는 첫 설치 시 묻고, 이후 저장됨.

Change later via Menu [8] -> [3] Change language.
변경: 메뉴 [8] -> [3] 언어 변경.

---

## Privacy / 개인정보

Everything runs **locally on your PC**. Nothing is sent to the cloud:
모든 것이 **본인 PC에서 로컬로** 실행. 클라우드로 아무것도 안 보냄:

- ✅ No API keys / 키 없음
- ✅ No tracking / 추적 없음
- ✅ No telemetry / 텔레메트리 없음
- ✅ Search via SearXNG (no Google account linking) / SearXNG로 검색 (구글 계정 연결 X)
- ✅ Model is uncensored (ARA-abliterated) / 검열 해제 모델

`.gitignore` excludes models, configs, logs, chat history from version control.
`.gitignore`가 모델·설정·로그·채팅 기록을 git에서 제외.

---

## Troubleshooting / 문제 해결

### "Python not found" / "Python을 찾을 수 없음"
Reinstall Python with **"Add Python to PATH"** checked.
Python 재설치 시 **"Add Python to PATH"** 체크.

### "Docker daemon not responding" / "Docker 데몬 응답 없음"
Start Docker Desktop and wait until the whale icon stops animating.
Docker Desktop 시작 후 트레이의 고래 아이콘이 멈출 때까지 대기.

### Ollama port 11434 conflict / 포트 충돌
```
taskkill /F /IM ollama.exe /T
```

### Open WebUI install very slow / 매우 느린 설치
Normal — many dependencies, takes 5-15 min on first install.
정상 — 의존성이 많아 첫 설치 5~15분.

---

## Advanced / 고급

### Different model quantization / 다른 양자화

Edit `installer/model.py`:
```python
PRIMARY = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_M"  # 18GB, better quality
```

### Adjust safe-search level / SafeSearch 레벨 변경
Edit `llm_environment/searxng/config/settings.yml`:
```yaml
search:
  safe_search: 0   # 0=none, 1=moderate, 2=strict
```
Then Menu [7] -> [3] to recreate.
그 다음 메뉴 [7] -> [3]으로 재생성.

### Command-line install / 명령행 설치

```cmd
python -m installer --skip-model       # skip model download
python -m installer --skip-sandbox     # skip Docker setup
python -m installer --lang ko          # force Korean
```
