# Local_AI_Agent

Windows에서 로컬 LLM 채팅과 자동화 에이전트를 실행하기 위한 자기완결형 프로젝트입니다.

사용자 관점에서 프로젝트 루트에서 알아야 할 진입점은 두 개입니다.

- `SETUP.bat` — 최초 설치 + 이후 환경/모델 관리
- `RUN.bat` — 프로그램 실행(GUI/TUI)

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

기본은 GUI입니다.

```bat
RUN.bat --gui
RUN.bat --tui
```

GUI를 사용할 수 없는 환경에서는 런처가 TUI로 폴백할 수 있습니다.
기존 `RUN_TUI.bat`은 제거되었으며 `RUN.bat --tui`로 통합되었습니다.

## 현재 디렉터리 구조

```text
C:\
└─ LLM_Models\              Ollama 공용 모델 저장소

Local_AI_Agent/
├─ .github/                 GitHub Actions
├─ .gitignore
├─ README.md                현재 사용법
├─ SETUP.bat                설치 + 관리 통합 진입점
├─ RUN.bat                  GUI + TUI 통합 실행 진입점
│
├─ src/
│  ├─ project_paths.py      프로젝트/공용 모델 경로 정본
│  ├─ runtime_versions.py   외부 런타임 버전 정본 (Open Interpreter 등)
│  ├─ launcher/             런처 / 서비스 / Agent runtime
│  ├─ installer/            설치 / 관리 구현
│  ├─ tools/                개발·평가 도구
│  ├─ tests/                테스트
│  └─ docs/                 상세 문서와 과거 문서
│
└─ user_data/               사용자 영속 데이터
```

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

## 모델 정책

받을 수 있는 모델(`src/launcher/models/model_catalog.py`)과 런타임이 고를 수 있는
모델(`src/launcher/models/model_roles.py` 의 `TIERS`)은 **서로의 거울**이어야 합니다.

- `TIERS` 에만 있는 태그 → 사다리가 1순위로 고르지만 `SETUP.bat` 어디에서도 받을 수 없습니다.
- 카탈로그에만 있는 태그 → 받아서 디스크를 써도 런타임이 한 번도 고르지 않습니다.

둘 다 예외도 경고도 없이 지나가므로 `src/tests/test_model_catalog_tiers.py` 가 양방향을
강제합니다. 모델을 추가·교체할 때는 두 파일을 함께 고치세요.

모델 선택의 정본은 `TIERS` 하나입니다. `ROLES[*].model / fallback` 은 화면 표시용이며
임포트 시점에 `TIERS` 의 1·2단계로 덮어써집니다(직접 적지 마세요). 사용자별 재정의는
`user_data/models/registry.json` 의 `replace` / `add` 로 합니다.

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
python -m launcher --tui
python -m installer --manage
```

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
설정 메뉴 **[8] → [5] 로그 기록**을 끄면 프롬프트·모델 출력·명령·도구 인자 같은
세부 입출력이 기록되지 않습니다(수명주기와 실패 원인은 계속 남습니다).
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
