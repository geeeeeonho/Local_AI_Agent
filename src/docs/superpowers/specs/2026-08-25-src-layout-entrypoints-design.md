# Local_AI_Agent src Layout and Unified Entrypoints Design

## Goal

사용자가 프로젝트 루트에서 이해해야 할 접근 지점을 `README.md`, `SETUP.bat`, `RUN.bat`, `user_data/` 중심으로 단순화한다. 프로그램 소스와 개발 보조 파일은 `src/` 아래에 모으고, 설치/관리와 GUI/TUI 실행 진입점을 각각 하나로 통합한다.

## Target layout

```text
Local_AI_Agent/
├─ .github/
├─ .gitignore
├─ README.md
├─ SETUP.bat
├─ RUN.bat
├─ src/
│  ├─ project_paths.py
│  ├─ installer/
│  ├─ launcher/
│  ├─ tools/
│  ├─ tests/
│  └─ docs/
└─ user_data/
```

`llm_environment/`는 설치 후 생성되는 런타임 환경이며 소스 트리로 취급하지 않는다. 기존처럼 프로젝트 루트 기준으로 생성한다.

## Root path contract

`src/project_paths.py`를 유일한 프로젝트 경로 정본으로 둔다.

- `SRC_ROOT`: `src/`
- `PROJECT_ROOT`: `src/`의 부모
- `USER_DATA_DIR`: `PROJECT_ROOT / "user_data"`
- `ENV_DIR`: `PROJECT_ROOT / "llm_environment"`

`launcher`와 `installer` 내부에서 `Path(__file__).resolve().parent.parent`처럼 현재 폴더 깊이에 의존해 프로젝트 루트를 추론하는 코드는 이 정본을 사용하도록 변경한다. 하위 모듈에서 특정 패키지 루트가 필요한 경우에도 프로젝트 루트와 혼동하지 않는다.

## Entrypoints

### SETUP.bat

`INSTALL.bat`과 `MANAGE.bat`을 제거하고 `SETUP.bat`으로 통합한다.

- 기본 실행: `llm_environment`가 없으면 설치, 있으면 관리 GUI
- `SETUP.bat --install`: 설치/재설치 흐름 강제
- `SETUP.bat --manage`: 관리 흐름 강제
- 관리 환경의 Python이 있으면 우선 사용하고, 없으면 시스템 `python`, 마지막으로 `py -3`을 사용
- 실행 전에 `PYTHONPATH=<repo>\src`를 설정하여 `python -m installer`가 `src/installer`를 찾도록 한다.

`src/installer/__main__.py`가 설치/관리 모드 결정을 담당한다. 기존 `manage_gui.py`와 설치 단계 구현은 내부 컴포넌트로 유지한다.

### RUN.bat

`RUN_TUI.bat`을 제거하고 `RUN.bat` 하나만 유지한다.

- `RUN.bat`: 기존 기본 GUI
- `RUN.bat --tui`: TUI 강제
- `RUN.bat --gui`: GUI 강제
- 기타 launcher 인자는 그대로 전달
- 실행 전에 `PYTHONPATH=<repo>\src`를 설정

기존 `launcher.__main__`의 GUI 실패 시 TUI fallback 동작은 유지한다.

## Source relocation

Git 추적 파일 기준으로 다음 디렉터리를 그대로 `src/` 아래로 이동한다.

- `launcher/` → `src/launcher/`
- `installer/` → `src/installer/`
- `tools/` → `src/tools/`
- `tests/` → `src/tests/`
- `docs/` → `src/docs/`

`.github/`, `.gitignore`, `README.md`, `SETUP.bat`, `RUN.bat`, `user_data/`는 루트에 남긴다.

## Tests and CI

구조 테스트는 새 계약을 검증한다.

- `SETUP.bat`, `RUN.bat` 존재
- `INSTALL.bat`, `MANAGE.bat`, `RUN_TUI.bat` 부재
- `src/launcher`, `src/installer`, `src/tools`, `src/tests`, `src/docs` 존재
- `user_data`는 루트에 유지
- 배치 파일이 `PYTHONPATH`에 `src`를 추가하고 인자를 전달
- 공통 경로 모듈이 `PROJECT_ROOT`, `ENV_DIR`, `USER_DATA_DIR`를 올바르게 계산

GitHub Actions는 `PYTHONPATH=${{ github.workspace }}\src`를 설정하고 컴파일/pytest 경로를 `src/...` 기준으로 갱신한다.

## Compatibility and safety

- `user_data`의 실제 위치와 기존 설정 파일 형식은 변경하지 않는다.
- `llm_environment`의 실제 위치도 변경하지 않는다.
- 설치/관리 기능 자체는 합치되 모델 관리, 진단, 설치 단계 구현은 불필요하게 재작성하지 않는다.
- Open Interpreter, AnythingLLM, SearXNG, Ollama 관련 런타임 동작은 구조 이동 외에는 변경하지 않는다.
- 오래된 배치 파일 이름을 가리키는 사용자 안내 문자열은 `SETUP.bat` 기준으로 갱신한다.
