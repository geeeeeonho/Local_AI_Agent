# LLM Local Setup

Windows 환경에서 로컬 LLM (Ollama + Open WebUI + Open Interpreter + SearXNG) 을 한번에 설치/실행/관리하는 통합 런처.

---

## 빠른 시작

```cmd
:: 1. 설치 (한 번만)
INSTALL.bat

:: 2. 실행 (이후 매번)
RUN.bat
```

`RUN.bat` 은 **GUI 모드로 바로 실행**됩니다. tkinter 가 없거나 GUI 초기화에 실패하면 자동으로 터미널 모드로 폴백합니다.

터미널 모드를 강제로 쓰려면:
```cmd
RUN_TUI.bat
```

---

## 화면 구성

### 메인 화면

좌측 사이드바 + 우측 메인 패널 + 하단 상태바로 구성된 단일 윈도우 데스크탑 앱입니다.

- **사이드바** — 메뉴 항목 (실행 / 관리 / 종료)
  - 좌상단 햄버거(≡) 또는 `Ctrl+B` 로 펼침/접힘 토글
  - 접힌 상태에서 아이콘에 마우스 올리면 메뉴 이름 툴팁
- **메인 패널** — 선택한 메뉴의 작업 화면 (체크박스, 결과 로그, 폼)
  - 모달이 거의 없음 — 패널만 갈아끼우는 방식
- **상태바** — Ollama / Docker / SearXNG 가동 상태 (2초마다 자동 갱신)

### 메뉴 항목

| 키 | 항목 | 설명 |
|----|------|------|
| 1 | 채팅 UI | Open WebUI 브라우저 + 자동 웹 검색 |
| 2 | 자동화 에이전트 — 샌드박스 (★권장) | Docker 컨테이너 격리 실행 |
| 3 | 자동화 에이전트 — 호스트 직접 (⚠위험) | 격리 없음 — 명시적 키워드 확인 필요 |
| 4 | Ollama 서비스 시작/확인 | API 서버 상태 |
| 5 | 설치된 모델 정보 | 다운로드된 LLM 목록 |
| 6 | Docker 이미지 빌드/재빌드 | 샌드박스 이미지 갱신 |
| 7 | SearXNG 검색 엔진 제어 | 검색 컨테이너 시작/정지/로그 |
| 8 | 설정 관리 | 보기 / 초기화 / 언어 변경 |

### 위험도 옵션 (체크박스 패널)

샌드박스 설정 시 옵션마다 위험도가 표시됩니다:

| 표시 | 의미 | 활성화 방법 |
|------|------|-------------|
| ✓ 안전 (초록) | 시스템에 영향 없음 | 클릭만으로 토글 |
| ⓘ 주의 (회색) | 추가 위험 있음 | `ENABLE` 입력 필요 |
| ⚠ 위험 (코랄) | 시스템에 심각한 영향 가능 | `I-UNDERSTAND` 입력 필요 |

옵션을 켜는 즉시 키워드 입력 다이얼로그가 뜨고, 정확한 키워드를 입력해야만 활성화됩니다.

---

## 실행 방법

### Windows (권장)

```cmd
RUN.bat              # GUI (기본)
RUN_TUI.bat          # 터미널 강제
```

### 수동 실행

```bash
python -m launcher          # GUI
python -m launcher --tui    # 터미널 강제
python -m launcher --gui    # GUI 명시 (기본과 동일)
python -m launcher --lang ko  # 한국어 강제
python -m launcher --lang en  # 영어 강제
```

### 자동 폴백

`python -m launcher` (GUI 기본) 호출 시 다음 상황이면 자동으로 터미널 모드로 떨어집니다:
- `tkinter` 모듈이 설치되지 않음 (`ImportError`)
- DISPLAY 가 없는 헤드리스 환경 (`tk.TclError`)
- 기타 GUI 초기화 실패

콘솔에 `[WARN] GUI 사용 불가: ... / [INFO] 터미널 UI 로 폴백합니다` 가 출력되고 그대로 진행됩니다.

---

## 폴더 구조

```
프로젝트 루트/
├── INSTALL.bat            ← 최초 설치
├── RUN.bat                ← GUI 실행 (기본)
├── RUN_TUI.bat            ← 터미널 강제
├── install.py             ← 설치 스크립트
│
├── installer/             ← 설치 모듈
│   ├── core/              ← 핵심 유틸 (분할됨)
│   │   ├── console.py     ANSI / UTF-8 / 색상 출력
│   │   ├── preflight.py   Windows / Python / Disk 검사
│   │   ├── download.py    진행률 다운로드
│   │   └── filesystem.py  환경 폴더 생성
│   ├── utils.py           ← shim (core 모듈 re-export)
│   ├── i18n.py            한국어 / 영어 메시지
│   ├── lang_setup.py      언어 자동 감지
│   ├── ollama.py          Ollama 포터블 설치
│   ├── model.py           모델 다운로드
│   ├── python_tools.py    venv / pip 관리
│   ├── sandbox.py         Docker 샌드박스 빌드
│   ├── searxng.py         SearXNG 설치
│   └── resources.py       시스템 사양 감지
│
├── launcher/              ← 런처 모듈
│   ├── __main__.py        ← 진입점 (--gui/--tui 분기)
│   ├── app.py             ← Application (메인 루프)
│   ├── config.py          ← 상수 중앙화
│   │
│   ├── presenter/         ← UI 추상화 레이어
│   │   ├── base.py        Presenter ABC, MenuItem, Option
│   │   ├── tui.py         TerminalPresenter (ANSI)
│   │   └── gui/           단일 윈도우 Tk Presenter
│   │       ├── theme.py        다크 색상 / 폰트
│   │       ├── widgets.py      Tooltip / HoverCard / 버튼
│   │       ├── sidebar.py      토글 사이드바
│   │       ├── statusbar.py    Ollama/Docker 상태 폴링
│   │       ├── panels.py       Home / Checkbox / Log
│   │       ├── menu_panel.py   메인 영역 카드 메뉴
│   │       ├── dialogs.py      위험확인 / 텍스트입력
│   │       ├── window.py       MainWindow + PanelHost
│   │       └── presenter.py    TkPresenter 본체
│   │
│   ├── services/          ← 외부 자원 헬퍼 (UI 무관)
│   │   ├── ollama.py      OllamaService
│   │   └── docker.py      DockerService
│   │
│   ├── actions/           ← 메뉴 액션 (한 파일에 한 액션)
│   │   ├── chat.py             [1]
│   │   ├── agent_sandbox.py    [2]
│   │   ├── agent_direct.py     [3]
│   │   ├── ollama.py           [4]
│   │   ├── model_info.py       [5]
│   │   ├── docker_image.py     [6]
│   │   ├── searxng.py          [7]
│   │   ├── settings.py         [8]
│   │   └── _sandbox_options.py 공유 옵션 정의
│   │
│   ├── i18n.py            UI 다국어
│   ├── settings_store.py  영속 설정 (JSON)
│   ├── runtime_guard.py   자원 워치독
│   ├── searxng_runtime.py SearXNG 런타임 제어
│   │
│   └── (legacy shim)      기존 import 경로 보존
│       ui.py, checkbox.py, menu.py, handlers.py, gui.py
│
└── llm_environment/       ← 설치된 자원 (INSTALL 후 생성)
    ├── ollama_runtime/    ollama.exe
    ├── llm_models/        *.gguf
    ├── chat_ui/           Open WebUI venv
    ├── agent/
    │   ├── venv/          Open Interpreter
    │   ├── sandbox/       Dockerfile
    │   └── workspace/     호스트 ↔ 컨테이너 공유
    ├── searxng/           SearXNG 설정
    ├── scripts/           보조 스크립트
    └── logs/              세션 로그
```

---

## 아키텍처 핵심 (개발자용)

### Presenter 패턴

UI 종류에 무관한 인터페이스 (`launcher/presenter/base.py`) 를 액션이 사용합니다:

```python
# 액션은 Presenter 만 알면 됨 (UI 종류는 모름)
def run(env: Path, p: Presenter) -> None:
    p.section("샌드박스 시작")
    p.info("Docker 데몬 확인 중…")

    selected = p.show_checkbox(
        title="옵션 설정",
        options=options,
        ...
    )
    if selected is None:
        return  # 사용자가 취소

    # docker run ...
```

같은 코드가 TUI 와 GUI 모두에서 동작합니다.

### 새 메뉴 액션 추가 (3단계)

1. `launcher/actions/my_action.py` 생성:
   ```python
   from pathlib import Path
   from ..presenter.base import Presenter

   def run(env: Path, p: Presenter) -> None:
       p.section("나의 액션")
       p.info("hello")
       p.pause()
   ```
2. `launcher/actions/__init__.py` 에 import 추가
3. `launcher/app.py` 의 `_build_menu_items()` + `_build_action_map()` 에 한 줄씩 추가

GUI/TUI 모두에서 자동으로 노출됩니다.

### 단일 윈도우 GUI 동작 원리

`Presenter` 인터페이스는 동기적이지만 GUI 는 비동기 (사용자가 버튼 누를 때까지 대기). 두 패러다임을 잇는 다리는 Tk 의 `wait_variable`:

- `show_checkbox()` 는 패널을 띄우고 `wait_variable` 로 결과 대기
- 패널 안의 [실행] / [취소] 버튼이 `var.set(...)` 으로 깨움
- 그 사이에도 메인 윈도우는 살아있고 상태바도 갱신됨

---

## 호환성

이번 리팩토링에서 모든 기존 import 경로는 **shim** 으로 보존되어 있습니다:

```python
# 기존 코드 — 그대로 동작
from launcher.handlers import start_chat, start_agent_sandbox  # ok
from launcher import checkbox, ui, menu, gui                   # ok
from installer import utils                                     # ok

# 권장 (신규)
from launcher.actions import chat, agent_sandbox
from launcher.presenter import create_presenter
from launcher.services import OllamaService, DockerService
from installer.core import console, preflight, download
```

---

## 트러블슈팅

### GUI 가 안 뜨고 콘솔만 나옴

```
[WARN] GUI 사용 불가: No module named '_tkinter'
[INFO] 터미널 UI 로 폴백합니다
```

→ Python 설치 시 `tcl/tk and IDLE` 옵션이 빠짐. Python 재설치 시 체크하거나, Microsoft Store 버전 대신 [python.org 공식 인스톨러](https://www.python.org/downloads/) 사용.

### Tkinter 한글이 깨짐 / 네모로 보임

→ Windows 의 경우 `Segoe UI` 가 기본이라 정상이지만, 일부 환경에서 한글이 안 나오면 `launcher/presenter/gui/theme.py` 의 폰트를 변경:
```python
F_BASE = ("맑은 고딕", 10)  # 또는 "Malgun Gothic"
```

### 사이드바를 항상 접고 싶음 / 펼치고 싶음

런처 시작 시 `Ctrl+B` 로 토글. 마지막 상태를 기억하는 기능은 향후 추가 예정 (현재는 매번 펼쳐진 상태로 시작).

### 위험 옵션을 켤 수 없음

→ MEDIUM (`ENABLE`) / HIGH (`I-UNDERSTAND`) 키워드를 정확히 (대소문자 포함) 입력해야 합니다. 의도된 안전장치입니다.

### 콘솔 창이 같이 떠 있음

`pythonw.exe` 가 PATH 에 없으면 `python.exe` 로 실행되어 콘솔이 같이 뜹니다. 이는 GUI 동작에는 영향 없습니다. 콘솔을 숨기려면:
```cmd
where pythonw.exe
```
이 명령이 빈 결과를 내면 `pythonw.exe` 가 없는 것 — Python 재설치 또는 PATH 추가 필요.

### Open WebUI 가 죽음 / 멈춤

→ `llm_environment/logs/chat_ui.log` 확인. 자원 워치독(`runtime_guard`)이 메모리/CPU 폭주를 감지해 자동 종료할 수 있습니다.

### Docker 데몬이 응답 없음

→ Docker Desktop 이 실행 중인지 확인. 메뉴 [2] 샌드박스 / [6] 빌드 / [7] SearXNG 가 모두 Docker 필요.

### `RUN.bat` 실행 시 `'湲곕낯'은(는) 내부 또는 외부 명령...` 같은 깨진 한글 에러

→ `.bat` 파일이 UTF-8 + LF 로 저장되었는데 Windows cmd 가 시스템 코드페이지(CP949)로 읽어 한글 주석/문자열을 깨진 명령으로 해석한 것입니다. 이 프로젝트의 `.bat` 파일은 모두 **ASCII + CRLF** 로 저장되어 있어 정상이지만, 만약 사용자가 직접 수정하다가 한글을 넣었다면 다음 중 하나로 해결:
1. 한글 주석/메시지를 모두 제거 (가장 안전)
2. 또는 `chcp 65001` 호출 *이후*의 `echo` 명령에만 한글 사용 + 파일을 UTF-8 with BOM 으로 저장
3. 줄바꿈은 항상 CRLF (Windows 표준) 로 유지

확인 방법 (PowerShell):
```powershell
# 줄바꿈이 CRLF 인지 확인
(Get-Content -Raw RUN.bat) -match "`r`n"
# 비-ASCII 바이트가 있는지 확인
[System.IO.File]::ReadAllBytes("RUN.bat") | Where-Object { $_ -gt 127 }
```

### GUI 창이 뜨자마자 사라지거나 콘솔이 깜빡거리면서 닫힘

이는 GUI 초기화 중 예외가 발생해 `pythonw.exe` 가 즉시 죽는 패턴입니다. `pythonw.exe` 는 콘솔이 없어 에러를 안 보여주므로 `RUN_DEBUG.bat` 으로 실행해서 트레이스백을 확인하세요.

```cmd
:: 콘솔이 유지되며 트레이스백 표시됨
RUN_DEBUG.bat
```

자동으로 다음 위치에도 fatal 로그가 기록됩니다:
```
llm_environment/logs/launcher_fatal.log
```

흔한 원인:
- **tkinter 미설치**: Python 재설치 시 "tcl/tk and IDLE" 옵션 체크
- **DISPLAY 없는 환경 (WSL/SSH)**: `RUN_TUI.bat` 사용
- **stdin 없는 환경에서 TUI 폴백 시 무한 루프**: 안전장치로 5회 연속 EOFError 시 자동 종료 (v5.1+)
- **이전에 만든 컨테이너/프로세스 잔존**: Docker Desktop 재시작 또는 `docker ps -a` 확인

진단 후 정상 작동 확인되면 다시 `RUN.bat` 사용.

---

## 변경 이력 (리팩토링 v5)

### 구조 변경

| 영역 | 이전 | 이후 |
|------|------|------|
| `installer/utils.py` | 350+ 라인 단일 파일 | `installer/core/` 4개 모듈 + shim |
| `launcher/handlers.py` | 8개 액션이 한 파일 | `launcher/actions/` 8개 모듈 + shim |
| `launcher/ui.py` | print + ANSI 박힌 함수 | `presenter/tui.py` 통합 + shim |
| `launcher/checkbox.py` | 옵션 메뉴 로직 | `Presenter.show_checkbox` 인터페이스 |
| `launcher/gui.py` | 단일 파일 모달 GUI | `presenter/gui/` 10개 모듈 단일 윈도우 |
| Ollama/Docker 헬퍼 | 여러 파일에 중복 | `launcher/services/` 단일 진입점 |
| 상수 | 분산 | `launcher/config.py` 중앙화 |
| GUI/TUI 전환 | 불가 | `--gui` / `--tui` 플래그 |

### 신규 기능

- **단일 윈도우 GUI**: 사이드바 + 메인 패널 + 상태바
- **사이드바 토글**: 햄버거 버튼 / `Ctrl+B`
- **상태바 폴링**: Ollama / Docker / SearXNG 실시간 표시
- **자동 폴백**: GUI 실패 시 TUI 자동 전환
- **Presenter 패턴**: 액션 코드가 UI 에 무관

### 색상 정책

- 노란색 계열 미사용 (사용자 요구)
- 다크 테마 (VS Code Dark Modern 기반)
- 위험만 코랄/주황빨강 강조 (`#f48771`)
- 안전은 초록 (`#73c991`)
- 액센트는 파랑 단일 (`#0e639c`)

---

## 라이선스 / 기여

(본 README 는 리팩토링 v5 기준입니다. 추가 변경 시 최하단 "변경 이력" 섹션을 갱신하세요.)
