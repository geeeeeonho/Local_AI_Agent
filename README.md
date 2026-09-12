# Local_AI_Agent

Windows에서 로컬 LLM 채팅과 자동화 에이전트를 실행하기 위한 자기완결형 프로젝트입니다.

사용자 관점에서 프로젝트 루트에서 알아야 할 진입점은 다음과 같습니다.

- `SETUP.bat` — 최초 설치 + 이후 환경 복구
- `RUN.bat` — 통합 실행 (LocalAI Studio)
- `CHAT.bat` / `INTERPRETER.bat` / `STUDIO.bat` — 같은 창의 단독 실행 형태

네 진입점 모두 하나의 데스크톱 셸과 하나의 서비스 구성을 공유합니다.
화면 구성과 경계는 [STUDIO.md](STUDIO.md) 에 정리되어 있습니다.

사용자 설정·로그·세션 같은 영속 데이터는 루트의 `user_data/`에 유지되고, 프로그램 소스와 개발용 파일은 `src/` 아래에 모여 있습니다.
대용량 Ollama 모델은 프로젝트와 분리된 공용 저장소 `C:\LLM_Models`에 저장됩니다.

## 빠른 시작

### 1. 설치 또는 관리

```bat
SETUP.bat
```

기본 동작은 현재 상태를 자동으로 판단합니다.

- `llm_environment/`가 없으면 → 최초 설치
- 이전 `llm_environment/llm_models` 또는 중단된 모델 이전 작업이 남아 있으면 → 마이그레이션을 포함한 설치/업데이트 흐름
- 그 외 이미 설치되어 있으면 → 관리 화면

필요하면 모드를 명시할 수 있습니다.

```bat
SETUP.bat --install
SETUP.bat --manage
```

기존 `INSTALL.bat`과 `MANAGE.bat`은 더 이상 사용하지 않습니다.

### 2. 실행

```bat
RUN.bat
```

기본은 통합 GUI(LocalAI Studio)입니다. 필요한 화면만 열려면:

```bat
CHAT.bat            :: 대화 · 문서 · RAG (AnythingLLM)
INTERPRETER.bat     :: 코딩 · 자동화 에이전트 (Open Interpreter)
STUDIO.bat          :: 전체 화면
RUN.bat --app chat  :: 위와 동일
```

기존 터미널 런처는 그대로 남아 있습니다.

```bat
RUN.bat --tui
```

설치 플래그는 어느 런처에 주더라도 설치기로 연결됩니다.

```bat
SETUP.bat --install
SETUP.bat --manage
RUN.bat --install     :: SETUP.bat --install 과 같습니다
```

기존 `RUN_TUI.bat`은 제거되었으며 `RUN.bat --tui`로 통합되었습니다.

## 현재 디렉터리 구조

```text
C:\
└─ LLM_Models\              Ollama 공용 모델 저장소

Local_AI_Agent/
├─ .github/                 GitHub Actions
├─ .gitignore
├─ README.md                현재 사용법
├─ SETUP.bat                설치 + 복구 진입점
├─ RUN.bat                  통합 실행 진입점 (GUI + TUI)
├─ STUDIO.bat               ┐
├─ CHAT.bat                 ├ 같은 셸의 단독 실행 형태
├─ INTERPRETER.bat          ┘
├─ STUDIO.md                데스크톱 셸 사용법과 경계
│
├─ src/
│  ├─ project_paths.py      프로젝트/런타임/공용 모델 경로 정본 (유일)
│  ├─ runtime_versions.py   외부 런타임 버전 정본 (Open Interpreter 등)
│  ├─ apps/                 네 진입점과 공용 데스크톱 화면
│  ├─ core/                 UI 비의존 계약 (이벤트·설정·네트워크 정책)
│  ├─ services/             앱이 쓰는 단일 서비스 경계
│  ├─ integrations/         기존 런처 구현으로 가는 전환 어댑터
│  ├─ launcher/             런처 / 서비스 / Agent runtime
│  ├─ installer/            설치 / 관리 구현
│  ├─ tools/                개발·평가 도구
│  ├─ tests/                테스트
│  └─ docs/                 상세 문서와 과거 문서
│
└─ user_data/               사용자 영속 데이터
```

계층은 `apps → services → integrations` 이고, `core` 는 UI에 의존하지 않는
계약만 담습니다. 모든 경로는 `src/project_paths.py` 한 곳에서만 정해집니다.

설치 후 생성되는 `llm_environment/`도 프로젝트 루트에 위치합니다. 이 폴더는 소스가 아니라 관리되는 런타임 환경입니다.
설치기는 이 폴더에 `LOCAL_AI_AGENT_INSTALL.json`을 생성해 제품명, 설치 상태, 프로젝트 경로, 환경 경로, 공용 모델 저장소와 설치 구성요소를 기록합니다.

과거 버전의 `llm_environment/llm_models`가 있고 `C:\LLM_Models`가 비어 있으면 설치 과정에서 공용 저장소로 자동 이동합니다. 다른 드라이브에서 이동하는 도중 중단되어도 최종 저장소에 부분 복사본이 노출되지 않도록 `C:\LLM_Models.migrating`을 임시 staging으로 사용하고 완료 marker로 복사 완료 여부를 구분합니다. 다음 `SETUP.bat` 실행은 완료된 staging을 승격하거나 부분 staging을 버리고 원본에서 다시 시작합니다. 두 위치에 모두 모델이 이미 있으면 데이터 충돌을 피하기 위해 자동 병합하지 않고 경고만 표시합니다.

업데이트 직후 이전 모델 또는 staging이 남은 상태에서 `RUN.bat`을 먼저 실행하면 Ollama를 빈 공용 저장소로 시작하지 않고 실행을 중단하며 `SETUP.bat`으로 이전/복구를 먼저 완료하도록 안내합니다.

## 경로 정책

프로그램 내부에서 프로젝트 루트를 각 파일의 `parent.parent` 깊이로 추측하지 않습니다.
`src/project_paths.py`가 다음 경로의 정본입니다.

```text
SRC_ROOT          -> <project>/src
PROJECT_ROOT      -> <project>
USER_DATA_DIR     -> <project>/user_data
ENV_DIR           -> <project>/llm_environment
MODEL_STORAGE_DIR -> C:\LLM_Models
```

따라서 `launcher/`와 `installer/`가 `src/` 아래로 이동해도 사용자 데이터와 설치 환경 위치는 바뀌지 않습니다.
모델은 체크아웃 위치와 분리되어 같은 PC의 여러 프로젝트/사용자가 동일한 저장소를 읽어 사용할 수 있습니다. 설치기는 `BUILTIN\Users`에 기존 파일까지 포함한 읽기/실행 권한을 재귀적으로 추가하지만 모든 사용자에게 쓰기 권한을 새로 부여하지는 않습니다. 기존 ACL도 강제로 초기화하지 않으므로 모델 다운로드·삭제는 해당 계정이 이미 필요한 쓰기 권한을 가진 경우에만 가능합니다. 관리형 배포나 테스트에서만 `LLM_MODEL_DIR` 환경변수로 경로를 재정의할 수 있습니다.

## Ollama 서비스 소유권

프로그램은 `11434` 포트가 응답한다는 이유만으로 임의의 Ollama를 재사용하지 않습니다. 포트 소유 프로세스가 현재 프로젝트의 `llm_environment/ollama_runtime/ollama.exe`인지 확인하고, 관리형 Ollama가 현재 `C:\LLM_Models` 설정으로 시작된 상태인지 런타임 상태 파일로 함께 확인합니다.

- 이전 버전에서 시작된 같은 관리형 Ollama는 공용 모델 경로를 확실히 적용하기 위해 한 번 재시작할 수 있습니다.
- 별도로 설치한 Ollama나 다른 프로젝트의 Ollama가 `11434`를 사용 중이면 이를 강제 종료하지 않고 실행/설치를 중단합니다. 해당 Ollama를 종료한 뒤 다시 실행하세요.
- 설치 중 레거시 모델을 옮길 때는 먼저 현재 프로젝트의 관리형 Ollama만 종료해 Windows 파일 잠금을 피한 뒤 이동하고 다시 시작합니다.
- GUI 상태바와 서비스 메뉴도 단순 포트 응답이 아니라 관리형 프로세스 소유권과 런타임 상태를 기준으로 판단합니다.

## 버전 정책

Open Interpreter 버전은 `src/runtime_versions.py` 한 곳에서만 정의합니다.
설치 스크립트, 샌드박스 이미지 라벨, 런처의 이미지 검사가 모두 이 값을 읽습니다.
세 곳이 어긋나면 샌드박스가 조용히 사용 불가가 되므로 리터럴로 적지 마세요.

같은 이유로 저장소 안의 모듈을 가리키는 `import` 는 `src/tests/test_no_phantom_imports.py`
가 검사합니다. 선택 기능을 `try: ... except Exception: pass` 로 감싸는 자리가 많아,
경로가 틀리면 `ImportError` 가 그대로 삼켜지고 기능만 조용히 사라집니다.

## 전환 완료 아키텍처

현재 서비스 경계는 다음처럼 고정합니다.

```text
Chat / RAG
  AnythingLLM -> Ollama

Automation Agent
  Local_AI_Agent GUI
    -> AgentService
    -> Open Interpreter App Server 0.0.38
    -> Ollama
    -> native command/file execution + approvals + thread sessions

Web search
  Open Interpreter
    -> local_search MCP
    -> SearXNG
    -> Direct / WARP / Tor
```

Open Interpreter App Server와의 전송은 **JSONL over stdio**를 유지합니다. 현재 경계가 이미 프로세스 수명주기와 승인·세션 이벤트를 안정적으로 전달하므로, 단순히 계층을 바꾸기 위해 별도 SDK 전송으로 재작성하지 않습니다. App Server 메서드명과 초기화 payload는 `src/launcher/agent/app_server_protocol.py`, Host/Sandbox 승인 정책은 `src/launcher/agent/execution_policy.py`가 각각 정본입니다.

Agent UI의 역할도 분리했습니다.

- `setup_flow.py` — 프로필·모델·워크스페이스·실행 모드 선택
- `runtime_config.py` — Host/Sandbox 런타임 명령과 네트워크 표시
- `chat_session_controller.py` — `/session`, `/resume <thread-id>`, `/model`, `/reload`, 승인, 중단·재시작과 이벤트 라우팅
- `agent_chat.py` — 상위 진입과 패널 조립

이전의 로컬 `session_*.json` 목록을 세션 ID처럼 사용하는 방식은 제거했습니다. 세션 이어가기는 Open Interpreter가 제공하는 실제 thread ID를 사용합니다.

### 네트워크 모드와 fail-closed

네트워크 의미는 `src/launcher/network_policy.py` 한 곳에서 결정합니다.

- **Direct** — 프록시 없이 직접 연결. Sandbox는 로컬 `llm_searxng` 같은 보조 서비스를 찾기 위해 공유 Docker 네트워크에는 참여합니다.
- **WARP** — WARP 프록시 경유. 보호 경로 준비가 실패하면 Direct로 폴백하지 않고 시작을 중단합니다.
- **Tor** — Tor 경유. 보호 경로 준비가 실패하면 Direct로 폴백하지 않고 시작을 중단합니다.
- **Block** — Sandbox와 AnythingLLM을 Docker internal network인 `llm_block_net`에 배치해 공용 egress 경계를 만듭니다. Block에서는 공용 검색도 비활성화됩니다.

AnythingLLM Block 모드는 UI 포트도 loopback에만 바인딩합니다. Sandbox Block은 `llm_block_net`과 DNS 차단 가드를 함께 사용합니다.

**Host Block은 지원하지 않습니다.** Host 프로세스의 프록시 환경변수는 제어할 수 있어도 임의의 자식 프로세스까지 포함한 OS 수준 hard-egress를 보장하지 못하기 때문입니다. 외부 통신을 강제로 막아야 하는 작업은 Sandbox Block을 사용하세요.

실제 Windows + Docker Desktop의 raw-IP/DNS 차단은 다음 진단으로 확인할 수 있습니다.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m tools.verify_block_egress
```

`verify_block_egress`는 raw-IP 외부 접근, DNS 외부 접근, `host.docker.internal`을 통한 로컬 Ollama 접근을 분리해 확인합니다. GitHub Actions는 명령 생성과 판정 로직을 검증하지만, 호스티드 러너에서 실제 사용자의 Docker Desktop 방화벽 경로까지 검증했다고 간주하지 않습니다.

## 모델 정책

받을 수 있는 모델(`src/launcher/models/model_catalog.py`)과 런타임이 고를 수 있는
모델(`src/launcher/models/model_roles.py` 의 `TIERS`)은 **서로의 거울**이어야 합니다.

- `TIERS` 에만 있는 태그 → 사다리가 1순위로 고르지만 `SETUP.bat` 어디에서도 받을 수 없습니다.
- 카탈로그에만 있는 태그 → 받아서 디스크를 써도 런타임이 한 번도 고르지 않습니다.

둘 다 예외도 경고도 없이 지나가므로 `src/tests/test_model_catalog_tiers.py` 가 양방향을
강제합니다. 모델을 추가·교체할 때는 두 파일을 함께 고치세요.
(임베더는 `kind="embed"` 로 표시하며 역할 사다리에서 제외됩니다.)

모델 선택의 정본은 `TIERS` 하나입니다. `ROLES[*].model / fallback` 은 화면 표시용이며
임포트 시점에 `TIERS` 의 1·2단계로 덮어써집니다(직접 적지 마세요). 사용자별 재정의는
`user_data/models/registry.json` 의 `replace` / `add` 로 합니다.

### 메모리 예산과 3단계

이 프로그램은 **모델에 내줄 수 있는 메모리 상한**을 먼저 정하고 거기서 목록을 만듭니다.

```text
MEMORY_BUDGET_GB = 20        # 기본값. LLM_MEMORY_BUDGET_GB 로 조정
MAX_MODEL_GB     = 18.4      # 예산 × 0.92 (나머지는 KV 캐시·버퍼 몫)
```

`MAX_MODEL_GB`를 넘는 모델은 **카탈로그에 두지 않습니다.** 받아도 절대 못 뜨는데
목록에만 있으면 디스크만 먹고 사다리는 매번 그 아래로 떨어집니다.

예산 안에서 역할마다 정확히 **3단계**를 둡니다.

| 등급 | 상주 | 언제 |
| --- | --- | --- |
| **상** | 12~18.4GB | 다른 걸 거의 안 띄웠을 때. 실질적인 최고 품질 |
| **중** | 6~12GB | 브라우저·Docker 를 같이 쓰는 평소 상태 |
| **하** | ~6GB | 메모리가 빠듯할 때의 최후 단계 |

한 단계만 받아 두면 여유 메모리가 오르내릴 때 쓸 게 없어지고, 단계가 너무 많으면
어느 것이 실제로 도는지 알 수 없고 디스크만 먹습니다. 그래서 **세 단계 전부**가
기본 설치 세트입니다. 같은 등급의 다른 선택지는 `alts`(대안)로 두며 기본 설치에는
들어가지 않습니다 — 받아 둔 사람에게만 걸립니다.

20GB 예산에서 18GB 급(`qwen3.6:27b`, `gemma4:26b-a4b-it-qat`)은 여유 19.6GB 를
요구해 사실상 유휴 상태에서만 뜹니다. 그래서 기본단계가 아니라 상 등급의
**대안**입니다.

### 설치는 예산으로, 실행은 지금 여유로

두 판단의 입력이 다릅니다. 섞으면 조용히 망가집니다.

```text
설치 (무엇을 받을까)  ->  MEMORY_BUDGET_GB          이 PC 의 상한
실행 (무엇을 띄울까)  ->  detect_free_memory_gb()   지금 이 순간의 여유
```

예전에는 설치도 `detect_free_memory_gb()` 를 썼습니다. 브라우저를 켜 둔 채
`SETUP.bat` 을 돌리면 여유가 8GB 로 잡혀 **하 등급만 받고 상·중은 영영 못 받는**
상태가 됐습니다.

### 크기는 두 가지입니다

```text
size_gb  받는 크기(디스크)   — 설치 화면의 "몇 GB 받나"
run_gb   상주 크기(메모리)   — 등급 배정과 적재 가능 판정
```

대부분 GGUF 는 둘이 같지만 Gemma 4 E 계열은 다릅니다. `gemma4:e4b` 는 9.6GB를
받아도 활성 파라미터만 올려 **약 5GB로 돕니다**. 하나로 뭉뚱그리면 저사양 PC 에서
실제로 잘 돌아가는 모델을 "안 맞는다"고 걸러 버립니다.

### 도구 호출

Open Interpreter 는 도구 호출로 동작합니다. `coding` · `agent` 사다리에는
`tools=True` 인 모델만 들어갈 수 있고, 테스트가 이를 막습니다. 도구를 못 부르는
모델을 고르면 에이전트가 오류 없이 그냥 멈춘 것처럼 보입니다.

### 용도별 모델 그룹

`TIERS` 의 키 = `model_classes.CLASSES` 의 키 = `ROLES` 의 이름. 셋이 같은 집합이어야
하고 테스트가 이를 강제합니다.

| 그룹 | 목적 | 상 (15GB급) | 중 (9GB급) | 하 (5GB급) |
| --- | --- | --- | --- | --- |
| `coding` | 코드 작성·실행 | `devstral-small-2:24b` | `qwen2.5-coder:14b` | `qwen2.5-coder:7b` |
| `agent` | 검색·도구·자율 실행 | `prutser/…ara-abliterated:Q4_K_S` | `qwen2.5-coder:14b` | `gemma4:e4b-it-qat` |
| `uncensored` | 번역·창작 | `prutser/…ara-abliterated:Q4_K_S` | `huihui_ai/qwen3-abliterated:14b` | `huihui_ai/qwen3-abliterated:8b` |
| `office` | 요약·보고서·스캔본 OCR | `gemma4:26b` | `gemma4:12b` | `gemma4:e4b-it-qat` |
| `balanced` | 일상 대화 | `gpt-oss:20b` | `gemma4:12b` | `gemma4:e4b-it-qat` |

### Gemma 4 를 어디에 두었나

Gemma 4 는 이 예산 안에서 **범용 품질이 가장 높습니다.** 26B-A4B 가 Arena
오픈 6위(1441 Elo) · MMLU-Pro 82.6 · GPQA Diamond 84.3 으로, GPQA 에서는
gpt-oss-120B(76.2)마저 앞섭니다. MoE 활성 ~4B 라 26B 급인데도 빠르고,
전 사이즈가 이미지를 봅니다. 그래서 15개 기본단계 중 **11개가 Gemma 4 계열**입니다.

한 곳만 예외입니다. **코딩은 Gemma 4 를 쓰지 않습니다.** SWE-bench Verified
(실제 GitHub 이슈 해결)가 Gemma 4 의 약점으로 같은 체급 Qwen 에 크게 뒤지고,
Google 도 공식 벤치마크에서 이 항목을 뺐습니다. 실패 양상이 이 프로그램의 코딩
역할과 정확히 겹칩니다 — 여러 파일에 걸친 장기 과제 분해, 30턴 이상 일관된 도구
호출, 중간 실패에서의 복구. 반면 도구 사용 자체(τ2-bench 86.4, Gemma 3 27B 는
6.6)는 강해서 에이전트 역할에는 그대로 씁니다.

`gemma4:31b`(dense, Arena 오픈 3위·1452 Elo)은 **이 예산에 들어오지 않습니다.**
적재 ~20GB 로 상한 18.4GB 를 넘어, 받아도 뜨지 않습니다.

사무 그룹은 상·중 등급 후보를 **전부 이미지가 되는 모델로만** 채웁니다.
사다리는 '맞는 것 중 첫 번째' 를 자동으로 고르기 때문에, 이미지를 못 보는 후보를
위쪽에 끼워 두면 여유가 조금 모자란 순간 그게 뽑혀 스캔본을 못 읽습니다.

`uncensored` 사다리에는 `uncensored=True` 인 모델만 들어갈 수 있고, `office` 는
저사양 단계에도 이미지를 읽는 후보가 있어야 합니다. 둘 다 테스트가 막습니다.
(이름으로 판단하지 않습니다 — 가중치를 깎는 abliteration 말고 무검열 데이터로
재학습한 dolphin 계열도 있어서, 태그에 `abliterated` 가 없다는 이유로 걸러지면
안 됩니다.)

### 등급마다 후보를 여럿 둡니다

같은 메모리 등급 안에서도 무엇을 중시하느냐가 다릅니다 — 속도 / 품질 / 무검열 /
이미지. 후보가 하나뿐이면 그게 안 맞을 때 곧바로 한 등급 아래로 떨어집니다.
메모리는 남는데 품질만 깎이는 낭비입니다. **등급마다 최소 3개**를 두고 테스트가
이를 확인합니다.

기본단계(primary)가 그 등급의 **추천**이고, 나머지는 같은 등급의 대안입니다.
대안은 **실제로 설치돼 있을 때만** 선택되므로 기본 설치를 부풀리지 않습니다.
모든 항목은 `note` 로 성격을 한 줄 답니다("속도 우선", "거부율 최저", "이미지",
"한국어" …) — 후보가 여럿이면 왜 이걸 고르는지가 보여야 고를 수 있습니다.

```text
무검열 · 중 (적재 6.1~9.0GB · 후보 3개)
  ★ huihui_ai/qwen3-abliterated:14b      9.0GB  [설치됨]  다국어
  · huihui_ai/gemma-4-abliterated:12b    7.6GB  [미설치]  이미지
  · huihui_ai/qwen3-vl-abliterated:8b    6.1GB  [미설치]  이미지

★ 지금 실제 사용 · ☆ 이 여유에서의 추천(미설치) · · 같은 등급 대안
```

**후보에서 뺀 것**과 이유:

| 모델 | 왜 안 넣었나 |
| --- | --- |
| `codestral:22b` | FIM 자동완성 특화. 네이티브 도구 호출이 없어 Open Interpreter 역할에 못 쓴다 |
| `deepseek-coder-v2:16b` | 160K 컨텍스트는 매력적이지만 도구 호출이 없다(제3자 파인튜닝판만 있음) |
| `llama3-groq-tool-use:8b` | BFCL 89.06 으로 자체 호스팅 최고점이지만 컨텍스트가 8K. 도구 결과로 컨텍스트를 쓰는 이 에이전트엔 부족 |
| `gemma4:31b` · `qwen3-vl:32b` | 적재 상한 18.4GB 초과 — 이 예산에선 절대 안 뜬다 |

역할 이름을 바꾸면 `model_roles.ROLE_ALIASES` 에 옛 이름을 등록하세요.
`user_data/models/registry.json` 에 옛 키를 적어 둔 설정이 조용히 무시되지 않습니다.

### 기본 설치 세트

`model_catalog.plan_by_level()` 이 역할 × 3단계의 기본단계를 모읍니다(중복 제거).
20GB 예산에서:

| 등급 | 받기 | 모델 |
| --- | --- | --- |
| 상 | 62.0GB | `gemma4:26b`, `devstral-small-2:24b`, `prutser/…ara-abliterated:Q4_K_S`, `gpt-oss:20b` |
| 중 | 25.6GB | `qwen2.5-coder:14b`, `huihui_ai/qwen3-abliterated:14b`, `gemma4:12b` |
| 하 | 19.3GB | `gemma4:e4b-it-qat`, `huihui_ai/qwen3-abliterated:8b`, `qwen2.5-coder:7b` |
|  | **106.9GB** |  |

설치 화면은 이 표를 그대로 보여 주고 각 항목에 `[상]` `[중]` `[하]` 를 붙입니다.
용량이 부담되면 한 등급을 통째로 빼도 됩니다 — 사다리가 남은 등급으로 안전하게
내려갑니다. 디스크 사전 검사의 하한은 '하' 등급만 받았을 때 기준이고, 권장 세트가
안 들어가면 중단이 아니라 경고만 합니다.

### 목록을 직접 찍어 보기

문서에 표를 베껴 두면 카탈로그와 갈라집니다. 목록이 필요하면 항상 이걸 찍으세요.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m launcher.models            # 지금 여유 메모리 기준 전체 후보군
python -m launcher.models --plan     # 기본 설치 세트(3단계)만
python -m launcher.models --free 12  # 여유 12GB 를 가정
```

### 배선 검증

`src/tests/test_model_pipeline_e2e.py` 가 가짜 `ollama.exe` 로 진짜 저장소
레이아웃(내용 해시 blob + OCI manifest)을 만들어 놓고 사슬 전체를 한 번에 지납니다.

```text
3단계 계획 -> installer.steps.model.download() -> OLLAMA_MODELS 경로에 pull
           -> blobs/ + manifests/ 생성 -> MODEL_FILES.csv 로 파일↔모델 복원
           -> model_roles 가 '설치된 것' 을 읽어 역할별 결정
           -> AgentConfig.model -> Open Interpreter 스레드 파라미터
```

조각마다 단위 테스트가 있어도 서로 **다른 경로**를 보고 있으면 전부 통과하면서
프로그램은 "모델이 없다" 고 합니다. 그래서 설치기와 런처가 같은 `OLLAMA_MODELS`
를 쓰는지, 고른 태그가 실제 실행 파라미터까지 실리는지를 함께 확인합니다.

`CORE` 는 손으로 관리하지 않습니다. `_CORE_TAGS` 한 곳에서 정하고
`CORE`/`ADVANCED` 가 거기서 파생되며, 테스트가 `CORE == plan_by_level()` 을
확인합니다.
### 태그 대소문자

카탈로그에는 대소문자가 섞인 벤더 태그가 있습니다
(`prutser/...:Q4_K_S`, `huihui_ai/Qwen3.6-abliterated:27b`).
Ollama 가 돌려주는 이름과 대소문자만 달라도 그대로 비교하면 멀쩡히 깔린 18GB 짜리를
"미설치"로 보고 다시 받습니다. 설치 목록은 읽는 즉시
`model_catalog.canonicalize_installed()` 로 카탈로그 표기에 맞춥니다.

## 모델 파일 ↔ 이름 대응표

Ollama 는 받은 모델을 내용 해시로만 저장합니다. `C:\LLM_Models` 를 열면 이렇게 보입니다.

```text
C:\LLM_Models\
  blobs\sha256-3f1c...          <- 15GB 짜리인데 어느 모델인지 알 수 없음
  manifests\registry.ollama.ai\
    library\gemma4\12b          <- 이 JSON 이 위 해시를 가리킴
```

`src/launcher/models/model_files.py` 가 manifest 를 읽어 대응을 복원하고
**`C:\LLM_Models\MODEL_FILES.csv`** 로 저장합니다(저장소에 쓸 수 없으면
`user_data/models/` 로). 모델 설치·삭제 후 자동으로 갱신되고, **모델 → 디스크 사용량**
화면의 [인덱스 갱신] 으로도 다시 씁니다.

| 열 | 뜻 |
| --- | --- |
| `file_name` | `blobs/` 안의 실제 파일 이름 (`sha256-...`) |
| `model` | 그 파일을 쓰는 모델 (`gemma4:12b`) |
| `role` | 카탈로그의 역할 라벨 |
| `layer` | `weights`(가중치) / `template` / `params` / `license` / `projector` … |
| `size_bytes`, `size_gb` | 파일 크기 |
| `shared_with` | 이 파일을 함께 쓰는 모델 수. **2 이상이면 한 모델을 지워도 파일은 남습니다** |
| `status` | `ok` / `missing`(받다 만 파일 — 다시 pull) / `orphan`(아무도 안 쓰는 잔여물) |
| `rel_path` | 저장소 루트 기준 경로 |

Excel 에서 한글이 깨지지 않도록 UTF-8 BOM 으로 씁니다.

## 주요 구성

- **ChatService**: AnythingLLM 기반 로컬 채팅/RAG
- **AgentService**: Open Interpreter App Server 기반 Agent runtime
- **Ollama**: 로컬 모델 실행
- **SearXNG**: 로컬 웹 검색
- **Docker**: 샌드박스 및 보조 서비스
- **user_data**: 설정, 로그, 세션, AnythingLLM 데이터 등 영속 데이터

## 개발자 실행

배치 파일은 자동으로 `src`를 `PYTHONPATH`에 추가합니다.
Python 모듈을 직접 실행하려면 개발 셸에서도 `src`를 Python 경로에 포함해야 합니다.

PowerShell 예시:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m apps.studio          # 통합 GUI
python -m apps.chat            # 단독 실행 형태
python -m launcher --tui       # 기존 터미널 런처
python -m installer --manage
```

### 카탈로그 태그 점검

카탈로그는 손으로 관리하는데 Ollama 레지스트리는 그 아래에서 계속 움직입니다.
`devstral-small:24b`(라이브러리에 없던 이름)와 `qwen3.5:27b`가 실제로 그렇게 틀렸고,
둘 다 사용자가 고른 **뒤에** `pull` 단계에서야 드러났습니다. 선언한 용량도 같은 식으로
낡는데, 그 숫자가 바로 메모리 사다리가 예산을 잡는 기준입니다.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m tools.verify_model_catalog          # 사람이 읽는 요약
python -m tools.verify_model_catalog --json   # 기계용
```

manifest 만 읽고 아무것도 받지 않습니다. 404(태그 없음)만 실패로 보고하고,
응답이 없거나 차단된 경우는 `UNKNOWN` 으로 남깁니다 — 네트워크 장애를
"모델이 사라졌다"로 보고하지 않기 위해서입니다.

이 명령은 **공개 인터넷으로 직접 나갑니다.** 개발자용이고, 데스크톱이나 설치기가
부르지 않으며, 관리형 WARP/Tor/Block 정책을 거치지 않습니다. 공용 egress 가 없는
것이 확인 대상인 상황에서는 실행하지 마세요.

테스트:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q src\tests
```

GitHub Actions에서도 동일하게 저장소의 `src`를 `PYTHONPATH`로 사용합니다.

## Agent 동작 보증

Agent에 전달되는 지시는 `src/launcher/agent/instructions.py` 에서 조립되며,
프로필 역할 뒤에 다음 제약이 항상 붙습니다.

- **개인정보 보호** — 개인정보를 외부로 전송하지 않음
- **도구 실체성** — 존재하지 않는 함수·도구를 가정하지 않음
- **사실 근거** — 최신 정보는 `local_search` 로 실제 조회한 결과로만 답하고,
  출처 URL을 밝히며, 도구가 실패하면 실패를 그대로 보고하고, 확실하지 않으면
  모른다고 말함
- **경계 안내** — 샌드박스/호스트 각각의 격리 수준과 허용·금지 폴더

프롬프트만으로 강제하지 않는 부분:

- 명령·파일 변경은 `approvalPolicy: on-request` 로 사용자 승인을 거칩니다
  (호스트 모드). 샌드박스는 Docker 마운트 자체가 경계입니다.
- Open Interpreter 내장 웹 검색은 꺼져 있고, `local_search` MCP 서버만 사용합니다.
  이 서버는 사설·루프백 주소를 차단하며 리다이렉트마다 다시 검사합니다.

`src/tools/evaluate_local_search_e2e.py` 는 이 동작을 관찰 가능한 이벤트만으로
채점합니다. 검색 호출 여부뿐 아니라 **답변이 인용한 URL이 실제로 조회된
URL인지**까지 확인하므로, 검색을 한 번 호출하고 나머지를 지어낸 답변은
만점을 받을 수 없습니다.

## 로그

Agent 세션마다 `user_data/logs/agent_trace_*.jsonl` 이 하나 생성됩니다.
**Setup / Repair → 유지보수 → [기존 설정]** 의 로그 기록을 끄면 프롬프트·모델 출력·
명령·도구 인자 같은 세부 입출력이 기록되지 않습니다(수명주기와 실패 원인은 계속 남습니다).
비밀값은 항상 마스킹되며, 오래된 트레이스 파일은 자동으로 정리됩니다.

## 데이터 보존

구조 개편으로 다음 위치는 이동하지 않습니다.

```text
user_data/
llm_environment/
```

특히 `user_data/settings/user_config.json`, Agent trace, 인터프리터 세션, 폴더 정책 등은 계속 프로젝트 루트의 `user_data/`를 기준으로 사용합니다.
대용량 모델만 `C:\LLM_Models`로 분리되어 프로젝트 복사·업데이트에 따라 중복되지 않습니다.

## 이전 상세 README

구조 개편 전의 긴 README는 내용 유실 없이 다음 위치에 보존했습니다.

```text
src/docs/legacy/README_before_src_refactor.md
```

과거 패치 이력이나 예전 구조를 확인할 때만 참고하세요. 현재 실행 방법은 이 루트 README를 기준으로 합니다.