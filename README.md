# Local_AI_Agent

Windows에서 로컬 LLM 채팅과 자동화 에이전트를 실행하기 위한 자기완결형 프로젝트입니다.

사용자 관점에서 프로젝트 루트에서 알아야 할 진입점은 두 개입니다.

- `SETUP.bat` — 최초 설치 + 이후 환경/모델 관리
- `RUN.bat` — 프로그램 실행(GUI/TUI)

사용자 설정·로그·세션 같은 영속 데이터는 루트의 `user_data/`에 유지되고, 프로그램 소스와 개발용 파일은 `src/` 아래에 모여 있습니다.

## 빠른 시작

### 1. 설치 또는 관리

```bat
SETUP.bat
```

기본 동작은 현재 상태를 자동으로 판단합니다.

- `llm_environment/`가 없으면 → 최초 설치
- 이미 설치되어 있으면 → 관리 화면

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
Local_AI_Agent/
├─ .github/                 GitHub Actions
├─ .gitignore
├─ README.md                현재 사용법
├─ SETUP.bat                설치 + 관리 통합 진입점
├─ RUN.bat                  GUI + TUI 통합 실행 진입점
│
├─ src/
│  ├─ project_paths.py      프로젝트 경로 정본
│  ├─ launcher/             런처 / 서비스 / Agent runtime
│  ├─ installer/            설치 / 관리 구현
│  ├─ tools/                개발·평가 도구
│  ├─ tests/                테스트
│  └─ docs/                 상세 문서와 과거 문서
│
└─ user_data/               사용자 영속 데이터
```

설치 후 생성되는 `llm_environment/`도 프로젝트 루트에 위치합니다. 이 폴더는 소스가 아니라 관리되는 런타임 환경입니다.

## 경로 정책

프로그램 내부에서 프로젝트 루트를 각 파일의 `parent.parent` 깊이로 추측하지 않습니다.
`src/project_paths.py`가 다음 경로의 정본입니다.

```text
SRC_ROOT       -> <project>/src
PROJECT_ROOT   -> <project>
USER_DATA_DIR  -> <project>/user_data
ENV_DIR        -> <project>/llm_environment
```

따라서 `launcher/`와 `installer/`가 `src/` 아래로 이동해도 사용자 데이터와 설치 환경 위치는 바뀌지 않습니다.

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

## 데이터 보존

구조 개편으로 다음 위치는 이동하지 않습니다.

```text
user_data/
llm_environment/
```

특히 `user_data/settings/user_config.json`, Agent trace, 인터프리터 세션, 폴더 정책 등은 계속 프로젝트 루트의 `user_data/`를 기준으로 사용합니다.

## 이전 상세 README

구조 개편 전의 긴 README는 내용 유실 없이 다음 위치에 보존했습니다.

```text
src/docs/legacy/README_before_src_refactor.md
```

과거 패치 이력이나 예전 구조를 확인할 때만 참고하세요. 현재 실행 방법은 이 루트 README를 기준으로 합니다.
