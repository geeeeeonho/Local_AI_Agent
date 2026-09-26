# Local_AI_Agent

Windows에서 로컬 LLM 채팅과 자동화 에이전트를 실행하기 위한 자기완결형 프로젝트입니다.

사용자 관점에서 프로젝트 루트의 **유일한 실행 진입점은 `RUN.bat`** 입니다.
각 Windows 사용자는 자기 체크아웃과 `RUN.bat`을 가질 수 있지만, PC의 무거운
실행환경·Ollama·모델은 한 벌만 공유하고 사용 기록은 계정별로 분리합니다.

```text
C:\LocalAI\
├─ environment\          공용 — 관리형 런타임 · 컨테이너 설정 · 스크립트
├─ ollama\               공용 — LocalAI가 관리하는 Ollama 중계기
├─ models\               공용 — 모든 Windows 계정이 함께 쓰는 모델 저장소
└─ users\
   └─ <계정>\
      ├─ user_data\      개인 — 설정 · 프로젝트 · 대화 · 벡터 저장소 · 추적 기록
      ├─ logs\           개인 — 세션/런타임 로그
      └─ workspace\      개인 — 에이전트 기본 작업 폴더
```

공용과 개인을 가르는 기준은 **누구의 데이터인가**입니다. `environment`,
`ollama`, `models`는 PC 자산이라 계정마다 다시 설치하거나 모델을 다시 받지
않습니다. 반대로 설정·대화·프로젝트·AnythingLLM 저장소·에이전트 작업 기록은
`users\<계정>` 아래에만 둡니다.

LocalAI는 Ollama를 `C:\LocalAI\ollama`에서 직접 관리하고 시작할 때
`OLLAMA_MODELS=C:\LocalAI\models`를 명시합니다. 따라서 Ollama의 사용자별
기본값인 `%USERPROFILE%\.ollama\models`로 모델이 계정마다 갈라지는 것을
피합니다. 다른 Windows 계정이 이미 공용 Ollama 중계기를 실행 중이면 그 프로세스를
임의로 종료하거나 재시작하지 않고 그대로 재사용합니다.

이번 설치 구조는 **새 설치 기준**입니다. `RUN.bat --install`은 이전 릴리스의
`C:\Ollama`, `C:\LLM_Models`, `llm_environment` 등을 자동 검색·이동·병합하지
않습니다.

## 빠른 시작

### 1. 설치 또는 관리

```bat
RUN.bat --install   :: 설치 / 재설치
RUN.bat --manage    :: 현재 Setup 관리 화면
```

두 경로의 역할은 분리되어 있습니다.

- `--install` → 현재 단일 루트 구조 기준 설치/재설치 흐름입니다. 예전 경로를 자동 이전하거나 병합하지 않습니다.
- `--manage` → 현재 데스크톱 Setup 화면. 모델·공용 저장소·네트워크·런타임 유지보수를 관리합니다. `RUN.bat --app setup`과 같은 관리 화면입니다.
- 설치기 자체가 예전 별도 관리 GUI로 자동 전환하지 않습니다.

기존 `INSTALL.bat`, `MANAGE.bat`, `SETUP.bat`은 더 이상 루트 실행기로 사용하지 않습니다.

### 2. 실행

```bat
RUN.bat
```

기본은 LocalAI Studio(GUI)입니다. 필요한 화면만 띄우려면:

```bat
RUN.bat --app studio       :: Studio
RUN.bat --app chat         :: 대화 · 문서 · Workspace
RUN.bat --app interpreter  :: Agent · 명령 · 승인
RUN.bat --app setup        :: Setup 화면
RUN.bat --tui              :: 이전 터미널 런처
```

Studio 는 Tk 가 있는 Python 3.11+ 를 씁니다. GUI를 사용할 수 없는 환경에서는
`RUN.bat --tui` 로 이전 터미널 런처를 쓸 수 있습니다.

설치와 관리는 같은 `RUN.bat`에서 선택하지만, 설치/재설치와 관리 UI는 서로 다른 책임으로 유지합니다. 기존 개별 실행기와 `RUN_TUI.bat`은 제거되었습니다.

### 첫 실행

`RUN.bat` 은 별도 프로젝트 venv를 가정하지 않고 시스템 Python 3.11+를 사용하며, 창 모드에서는 가능한 경우 `pythonw.exe`/`pyw.exe`를 씁니다. 그 프로세스에는 콘솔이 없어
`sys.stdin` 이 `None` 이고, 그때 `input()` 은 `EOFError` 가 아니라
`RuntimeError("input(): lost sys.stdin")` 를 냅니다. 언어 선택 프롬프트가 `EOFError`
만 잡고 있어서, **저장된 언어가 없는 첫 실행이 창 대신 오류 상자로 끝났습니다.**

지금은 콘솔이 있을 때만 묻습니다. 없으면 OS 가 이미 아는 값(`LANG`/`LC_*`, 로캘,
Windows UI 언어)을 이번 실행에만 씁니다 — 한국어 Windows 가 조용히 영어로 떨어지지
않습니다. **짐작한 값은 저장하지도, 환경변수로 넘기지도 않습니다.** 저장하면 그
짐작이 영구 설정이 되고, 넘기면 같은 프로세스에서 이어 도는 설치 화면이 콘솔이 있는데도
묻지 않고 그 값을 씁니다. 명시적으로 고르려면 `RUN.bat --lang ko` 를 쓰세요.

## Ollama 를 중간 매개체로 쓰기

Ollama는 LocalAI의 **로컬 모델 중계기**입니다. 모델 API는 Ollama가 제공하지만,
설치 위치와 공용 모델 저장소는 LocalAI가 명시적으로 관리합니다.

**설치 위치** — `C:\LocalAI\ollama`. 공식 설치기를 사용할 수 있으면
`OllamaSetup.exe /DIR=C:\LocalAI\ollama /VERYSILENT /NORESTART`로 설치하고,
실패할 때만 같은 폴더에 포터블 배포본을 사용합니다. Ollama Windows 앱이 만드는
로그인 자동시작(`Ollama.lnk`)은 설치 뒤 제거합니다. LocalAI가 필요할 때 공용
`ollama.exe`를 직접 관리하므로 Windows 로그인 때 별도 Tray가 먼저 11434를 잡지
않게 하기 위해서입니다. 시스템에 사용자가 별도로 설치해 둔 Ollama 파일은 자동으로
삭제하거나 옮기지 않습니다.

**모델 위치** — `C:\LocalAI\models`. LocalAI가 띄우는 Ollama에는 항상
`OLLAMA_MODELS`를 이 경로로 넘깁니다. 설치 시에는 가능한 경우 시스템 범위
`OLLAMA_MODELS`도 기록하고 모델 폴더에 `BUILTIN\Users` 읽기/실행 권한을 줘
다른 Windows 계정도 같은 모델을 읽도록 합니다.

**계정 간 공유** — 공용 Ollama가 이미 응답 중이면 어느 Windows 계정이 시작했든
재사용합니다. 계정별 런타임 상태 파일이 없다는 이유만으로 공용 프로세스를 자기
프로세스로 간주하거나 재시작하지 않습니다. 반대로 알 수 없는 위치의 Ollama가
11434 포트를 점유하면 임의 종료하지 않고 설치/실행을 중단합니다.

**개인 데이터는 공유하지 않습니다.** AnythingLLM 저장소, Open Interpreter HOME,
설정, 프로젝트, 로그와 작업공간은 현재 계정의
`C:\LocalAI\users\<계정>` 아래에서만 사용합니다.

### 모델 확인은 한 경로로만

"어떤 모델이 있나" 를 묻는 자리가 일곱 군데였고 각자 다르게 답했습니다 — 런처는
`ollama list` 를 **프로세스로 띄워 stdout 을 잘랐고**, 역할 해석기는 자체 `urlopen`
(환경에 `http_proxy` 가 있으면 루프백 요청이 프록시로 갔습니다), 설치 관리 화면은
또 다른 둘, 모델 화면은 디스크, Ollama 서비스는 양쪽을 읽어 비교했습니다. 태그 철자
정규화도, 실패의 의미도, 물어볼 호스트도 제각각이라 **같은 저장소가 한 화면에선 가득
차고 다른 화면에선 비어 보일 수 있었습니다.**

지금은 전부 한 파이프라인을 지납니다.

```text
core/models/registry.py          규칙만 (core 위쪽을 아무것도 임포트하지 않습니다)
integrations/ollama/inventory.py 그 규칙을 실제 라우터·저장소에 연결
```

규칙은 셋입니다.

1. **라우터(Ollama)가 답하면 그 답입니다.** 프롬프트를 실제로 처리할 프로세스가
   할 수 있다고 한 것이 이 컴퓨터가 쓸 수 있는 것입니다.
2. **꺼져 있으면 저장소가 답합니다.** 그 모델들은 Ollama 가 뜨는 순간 서빙됩니다.
   예전에는 서버가 꺼졌다는 이유만으로 "설치된 것 없음" 이 되어, 관리 화면이 이미
   받아 둔 모델을 다시 받으라고 권하고 역할 사다리가 없는 모델을 골랐습니다.
3. **둘 다 못 읽으면 "모름" 입니다.** "모델이 없다" 와 "확인 못 했다" 는 사용자를
   정반대로 움직입니다.

전송은 프록시와 리다이렉트를 거부하는 클라이언트 하나뿐이고, 테스트도 stub 자리가
하나입니다. 두 개의 가드 테스트가 이 상태를 지킵니다 — 트리에 `/api/tags` 가 다시
생기면 실패하고, 설치 목록을 묻겠다고 프로세스를 띄우면 실패합니다.

## 현재 디렉터리 구조

```text
C:\
└─ LocalAI\
   ├─ environment\          공용 런타임
   ├─ ollama\               공용 Ollama 중계기
   ├─ models\               공용 모델 저장소
   └─ users\
      └─ <계정>\
         ├─ user_data\      개인 상태/기록
         ├─ logs\           개인 로그
         └─ workspace\      개인 작업공간

Local_AI_Agent/
├─ README.md
├─ STUDIO.md
├─ RUN.bat                  유일한 루트 실행 진입점
└─ src/
   ├─ project_paths.py      모든 런타임 경로의 정본
   ├─ apps/
   ├─ services/
   ├─ core/
   ├─ integrations/
   ├─ launcher/
   ├─ installer/
   └─ tests/
```

체크아웃은 실행 진입점과 소스 코드이고, `C:\LocalAI`는 실제 설치/사용 데이터가
있는 런타임 루트입니다. 여러 Windows 계정이 각각 체크아웃을 가지고 있어도
공용 환경·Ollama·모델은 같은 경로를 사용합니다.

설치기는 `C:\LocalAI\environment\LOCAL_AI_AGENT_INSTALL.json`에
`runtime_root`, `environment_path`, `ollama_path`, `model_storage`,
현재 `account_path`와 설치 구성요소 상태를 기록합니다.

## 경로 정책

프로그램 내부의 경로 정본은 `src/project_paths.py` 하나입니다.

```text
SRC_ROOT            -> <checkout>/src
PROJECT_ROOT        -> <checkout>

RUNTIME_ROOT        -> C:\LocalAI
ENV_DIR             -> C:\LocalAI\environment
OLLAMA_INSTALL_DIR  -> C:\LocalAI\ollama
MODEL_STORAGE_DIR   -> C:\LocalAI\models

ACCOUNT_ROOT        -> C:\LocalAI\users\<계정>
USER_DATA_DIR       -> <ACCOUNT_ROOT>\user_data
LOGS_DIR            -> <ACCOUNT_ROOT>\logs
WORKSPACE_DIR       -> <ACCOUNT_ROOT>\workspace
```

`LOCAL_AI_ROOT`는 관리형 배포/테스트에서 전체 런타임 루트를 바꾸고,
`LLM_MODEL_DIR`만 LocalAI 자체의 명시적 모델 저장소 override로 사용합니다.
사용자 범위 `OLLAMA_MODELS`는 Ollama 프로세스 설정일 뿐 LocalAI 경로 정본으로
사용하지 않습니다. 그렇지 않으면 Windows 계정마다 공용 저장소가 다시 갈라질 수
있기 때문입니다. `LOCAL_AI_ACCOUNT`는 개인 기록을 어느 계정 폴더에 둘지
재정의합니다.

기본 설치에서는 `environment`, `ollama`, `models`에 `BUILTIN\Users` 읽기/실행 권한을
보장해 다른 계정도 같은 공용 자산을 사용할 수 있게 합니다. 모델 폴더의 다른 계정
권한은 의도적으로 **읽기/실행**입니다. 공용 모델 파일 자체는 신뢰 자산이라 모든 로컬
계정에 임의 변경 권한을 주지 않습니다. 반대로 각 `users\<계정>` 폴더는 상속을 끊어
다른 로컬 계정이 읽지 못하도록 별도로 보호합니다.

## Ollama 서비스 소유권

LocalAI가 관리하는 공용 Ollama의 정본은 **`C:\LocalAI\ollama\ollama.exe`** 입니다.
설치기와 런처는 시스템의 다른 Ollama를 대신 선택하지 않습니다.

- 11434 포트를 `C:\LocalAI\ollama`의 공용 Ollama가 사용 중이면 그대로 재사용합니다.
  다른 Windows 계정이 시작한 프로세스라도 계정별 PID 기록이 없다는 이유로 종료하거나
  재시작하지 않습니다.
- 포트 소유 프로세스의 경로를 권한 문제로 읽지 못하면, 라우터 응답과 공용 모델
  저장소의 일치 여부를 보조 근거로 사용합니다.
- `%LOCALAPPDATA%\Programs\Ollama`, `C:\Program Files\Ollama` 등 다른 위치의
  Ollama가 11434를 사용 중인 것이 확인되면 그 프로세스를 건드리지 않고 충돌로 안내합니다.
- 공용 Ollama는 특정 Studio/Chat/Agent 창의 소유물이 아닙니다. 한 계정의 창을 닫아도
  다른 계정이 사용할 수 있으므로 **창 종료 cleanup으로 Ollama를 내리지 않습니다.**
  명시적인 관리 동작에서만 필요한 경우 중지·재시작합니다.
- 모델 저장소는 `C:\LocalAI\models`이며, LocalAI가 시작하는 공용 Ollama에는
  `OLLAMA_MODELS`를 이 경로로 넘깁니다.

### 모델 저장소 확인

모델 목록은 Ollama 라우터가 실제로 제공하는 목록과 `C:\LocalAI\models`의 manifest를
함께 봅니다. 둘 다 비어 있으면 "설치된 로컬 모델 없음", 디스크에는 모델이 있는데
라우터가 0개면 "저장소를 읽지 못함", 읽을 수 없는 manifest가 있으면 "확인 불가"로
구분합니다. 이미 모델을 제공 중인 공용 서버를 단순 경로 추정만으로 재시작하지 않습니다.

### Windows 환경변수는 외부 Ollama 호환용입니다

공용 Ollama 자식 프로세스에는 실행할 때마다 `OLLAMA_MODELS=C:\LocalAI\models`를
직접 전달합니다. 따라서 LocalAI 계정 간 모델 공유는 사용자/시스템 환경변수에 의존하지
않습니다. 설치와 명시적 Ollama 관리에서는 외부 `ollama` CLI나 Tray도 같은 경로를
보기 쉽도록 Windows 환경변수 기록을 best-effort로 시도합니다.

모델 화면의 **LocalAI 계정 간 공유 여부**는 실제 공용 경로인지와
`BUILTIN\Users`가 모델을 읽을 수 있는지로 판단합니다. 사용자 범위
`OLLAMA_MODELS`가 다른 곳을 가리켜도 LocalAI가 띄우는 broker에는 공용 경로를 직접
주입하므로 LocalAI 저장소 정본이 바뀌지 않습니다.

## 모델이 없으면 준비를 시작하지 않습니다

현장 로그가 이렇게 남았습니다 — WARP 기동(45초), Docker 확인, SearXNG, AnythingLLM 까지
전부 올린 뒤 **[5/5] 에서야** "Chat에 사용할 로컬 Ollama 모델이 없습니다". 그리고 같은
일을 한 번 더. 게다가 [2/5] 는 지나가면서 "모델 저장소 일치 확인됨" 이라고 말했습니다 —
저장소와 라우터가 **둘 다 비어 있으면** 일치로 보이기 때문입니다.

- 로컬 모델이 하나도 없으면 **[1/5] 전에** 멈춥니다. Ollama 가 이미 응답 중일 때만 물어
  보고, 아직 안 떠 있으면 그건 [2/5] 가 할 일이므로 건너뜁니다. "물어보지 못함" 은
  "없음" 이 아닙니다.
- 빈 라이브러리는 "일치" 가 아니라 **"실행 중이지만 설치된 로컬 모델이 없습니다"** 로
  보고합니다. 모델이 있으면 몇 개인지 함께 말합니다.
- **클라우드 태그는 로컬 모델이 아닙니다.** Ollama 가 자기 서버로 중계하므로 선택한
  네트워크 정책 밖으로 나갑니다. 이 판정 규칙이 `core.models.registry` 와
  `integrations.ollama.client` 에 **두 벌** 있었고 한 릴리스 안에서 서로 어긋나
  `gemma4:cloud`(Ollama 가 실제로 쓰는 짧은 형태)를 한쪽만 알아봤습니다. 지금은
  `core` 에 하나만 두고 transport 가 그것을 re-export 합니다.

## 설치기가 남긴 숫자

`Setup exited with code 3221225786` 이 진단의 전부였습니다. 이 값은 `0xC000013A`,
`STATUS_CONTROL_C_EXIT` — **설치 창을 닫았을 때** Windows 가 주는 코드입니다. 이제 알려진
코드는 말로 바꿔서 보여 주고(창 닫힘·사용자 취소·권한 필요·DLL 초기화 실패), 모르는
코드는 찾아볼 수 있게 16진수를 함께 씁니다. 설치기가 끝나면 상태를 자동으로 다시
확인합니다.

## 준비됐는지, 무엇을 눌러야 하는지

준비 완료 신호가 **버튼 하나가 회색에서 풀리는 것뿐** 이었습니다. 아무도 버튼의 명암을
지켜보고 있지 않고, 설명은 아래 로그 상자 안에만 있었습니다.

Chat 과 Agent 화면에는 이제 버튼 바로 아래에 상태 한 줄이 있고, **창을 연 순간부터**
채워져 있습니다.

| 상태 | 줄 | 열기 버튼 |
| --- | --- | --- |
| 대기 | 회색 · "[Chat 시작]을 누르면 …" | 비활성 |
| 준비 중 | 파랑 · 지금 어느 단계인지 | 비활성 |
| 준비 완료 | 초록 · "[대화 화면 열기]를 누르세요 · 모델 …" | **활성 + 강조 스타일 + `→`** |
| 실패 | 빨강 · 멈춘 이유 | 비활성 |

시작 전에도 상태 점검 결과를 그 줄에 반영합니다 — Ollama 가 응답하지 않으면 그렇게,
설치된 로컬 모델이 없으면 그렇게, AnythingLLM 이미지가 없으면 그렇게 말하고, 실행 중인
Ollama 의 모델 경로도 함께 보여 줍니다. 화면이 "왜 준비가 안 됐는지" 에 대해 비어 있는
순간이 없습니다.

**그리고 갈 곳을 말하면 가는 버튼을 함께 놓습니다.** "모델 화면에서 받으세요" 라고만
하고 거기로 가는 길이 없으면 절반짜리 안내입니다. 줄이 모델 화면이나 Setup 관리를
가리키면 그 줄 오른쪽에 바로 그 버튼이 붙습니다.

## 창을 닫을 때 정리되는 것

WARP 와 Tor 는 Docker 컨테이너로 돌고, 종료 정리를 `lifelog.register_cleanup` 에
맡깁니다. 그 콜백은 프로세스 종료 hook(atexit / SIGINT / SIGTERM / Windows 콘솔
핸들러)에서만 실행됩니다. **데스크톱 셸이 그 hook 을 설치하지 않아서, 창을 닫아도
WARP·Tor 컨테이너가 계속 돌았습니다.** 터미널 런처는 처음부터 설치하고 있었고 GUI 만
빠져 있었습니다.

지금은 셸이 **컨테이너를 띄울 수 있는 어떤 코드보다 먼저** hook 을 설치합니다.
또한 `C:\LocalAI\environment\desktop-runtime.lock` 하나로 모든 Windows 계정의
공용 Docker/네트워크 변경을 직렬화합니다.

여기서 **세션 종료**와 **앱 최종 종료**를 구분합니다.

- 세션 종료는 현재 계정의 Chat/Agent/Search만 정리하고 공용 잠금을 풉니다. 이때 그
  프로세스에 남아 있는 오래된 atexit cleanup은 비활성화합니다.
- 같은 프로세스가 나중에 새 세션을 시작해 공용 잠금을 다시 얻으면 cleanup도 다시
  활성화됩니다.
- 앱 최종 종료는 공용 잠금을 가진 상태에서 WARP/Tor/SearXNG/AnythingLLM 등의 cleanup을
  끝낸 뒤 잠금을 풉니다. 다른 계정이 이미 잠금을 얻었다면 이전 프로세스의 stale cleanup은
  실행하지 않습니다.

이 순서가 필요한 이유는 A 계정이 세션을 끝낸 뒤 B 계정이 같은 이름의 공용 컨테이너를
새로 띄웠는데, 나중에 A의 atexit가 B의 컨테이너를 지우는 레이스를 막기 위해서입니다.

| 무엇 | 언제 멈추나 | 절대 건드리지 않는 것 |
| --- | --- | --- |
| AnythingLLM · SearXNG · WARP · Tor · 샌드박스 | 소유 세션/앱 최종 종료 시 | 다른 계정이 새로 소유한 공용 런타임 |
| Ollama | 일반 창 종료에서는 유지 | 다른 위치의 Ollama, 다른 계정이 사용 중인 공용 broker |
| Docker Desktop | 이 프로세스가 직접 켰고, 남의 컨테이너가 하나도 없을 때만 | 사용자가 켜 둔 Docker |

- Ollama는 머신 공용 broker라 특정 창의 cleanup에 묶지 않습니다. 저장소 불일치가
  명확하면 일반 실행에서는 거부하고 Setup의 명시적 관리 동작에서만 재시작합니다.
- Docker 데몬을 내리는 정리는 `register_cleanup(..., last=True)` 로 **맨 마지막에**
  돕니다. 컨테이너를 멈추는 콜백들보다 먼저 데몬을 내리면 그 콜백이 전부 실패합니다.
- `LOCAL_AI_KEEP_DOCKER=1` 을 두면 Docker Desktop 은 계속 켜 둡니다.
- 컨테이너를 `-d` 로 띄우는 모듈은 **모두** 자기 정리를 등록해야 합니다. 예외는
  `integrations/searxng/runtime.py` 하나인데, 그 인스턴스는 `DesktopServices.close()`
  가 직접 소유해 멈춥니다. 이 규칙은 `src/tests/test_runtime_startup_shutdown.py` 가
  강제합니다 — `launcher/searxng_runtime.py` 가 등록을 빠뜨려 Agent 를 한 번 열면
  `llm_searxng` 가 창을 닫은 뒤에도 계속 돌았습니다.

**컨테이너는 데몬보다 오래 살지 못합니다.** 창을 열어 둔 채 Docker Desktop 을 종료하면,
컨테이너 정체를 묻는 호출이 `close()` 밖으로 예외를 던지거나 "정지 확인 안 됨" 을
영원히 돌려주어 **창을 닫을 방법이 없었습니다.** 이미 데몬과 함께 죽은 컨테이너에
대해서요. 지금은 데몬이 확실히 없으면 우리가 띄운 것도 없다고 보고 정상 종료합니다.
서비스 하나가 멈추지 않아도 나머지는 계속 멈추며, 그 이유가 화면에 남습니다.

## 도커에 쌓이는 찌꺼기

컨테이너를 띄웠다가 멈추면 껍데기가 남고, 이미지를 다시 받으면 이름 없는 `<none>`
이미지가 남습니다. 정리 기능은 원래 있었지만 **`register_auto_prune` 을 터미널 런처만
불렀습니다.** 데스크톱 앱을 쓰는 사람에게는 [도커 정리] 화면의 "종료 시 자동 정리"
토글이 아무 일도 하지 않았고, Chat·Agent 세션과 이미지 다운로드가 남긴 것이 그대로
쌓였습니다.

지금은 두 가지로 나뉩니다.

| 무엇 | 언제 | 왜 |
| --- | --- | --- |
| 우리 컨테이너(exited·created·dead)와 비어 있는 우리 네트워크 | **종료할 때마다 항상** | 우리가 띄운 것은 우리가 치운다 — 설정이 아니라 예의입니다 |
| 기계 전체의 dangling 이미지 | [도커 정리] 의 토글이 켜져 있을 때만 | 누가 만들었는지 알 수 없는 이미지는 사용자가 정합니다 |
| 빌드 캐시 · 미사용 이미지 전체 · 볼륨 | [도커 정리] 에서 직접 고를 때만 | 되돌리는 데 시간이 드는 작업입니다 |

- `exited` 만 찾던 것을 `created`(docker run 이 도중에 실패)와 `dead`(데몬이 죽으며
  남김)까지 넓혔습니다. 전부 "열렸다가 닫힐 때 남는" 것들입니다.
- 남의 컨테이너·네트워크는 이름으로 구분해 건드리지 않고, 아직 컨테이너가 붙어 있는
  네트워크는 지우지 않습니다.
- 정리는 `sweep` 단계에서 돕니다: 우리 컨테이너가 멈춘 **뒤**(그 전에는 치울 게 안
  보입니다), Docker 데몬을 내리기 **전**(그 뒤에는 치울 수가 없습니다)입니다. 단계는
  `register_cleanup(fn, stage=...)` 로 의도에 따라 정하며, 등록 순서에 기대지 않습니다.

## 창이 작아져도 버튼은 버튼입니다

`pack` 은 남는 공간을 나눠 주고, 남는 게 없으면 **마지막에 배치한 것부터 빼앗습니다.**
그래서 모델 화면의 주 동작인 [선택대로 적용] 이 높이 1픽셀이 되어 있었습니다. 화면에는
보이는데 누르면 엉뚱한 곳이 눌리는 상태입니다.

- 모델 화면의 세 탭은 `grid` 로 바꿨습니다. 고정 행은 자기 높이를 먼저 확보하고
  (`rowconfigure(minsize=...)`), 목록 행 하나만 남는 공간을 받습니다.
- 확장을 요구하는 위젯은 화면당 하나입니다. 트리와 상세 상자가 같이 확장을 요구해서
  상세 상자가 26픽셀(두 줄도 안 됨)로 눌려 있었습니다.
- 설명 문구의 `wraplength` 는 전부 고정 픽셀(660·740·760·780·900)이었습니다. 창이
  그보다 좁으면 문장이 잘렸습니다 — 하필 공간이 가장 부족한 화면에서요. 이제 실제 폭에
  맞춰 다시 감깁니다.
- 활동 기록은 최소 창 크기의 1/4을 차지합니다. 접을 수 있게 했고 선택은 저장합니다.
- 스크롤 영역은 다시 그릴 때마다 `add='+'` 로 휠 핸들러를 **덧붙이고** 있었습니다.
  모델 목록은 새로고침마다 다시 그리므로, 한 칸 굴리면 여러 페이지가 넘어갔습니다.
- Treeview 처럼 스스로 스크롤하는 위젯의 휠을 페이지가 가로채지 않습니다.

이 규칙들은 `src/tests/test_desktop_ui.py` 가 실제 Tk 창을 최소 크기로 띄워
검사합니다.

## 준비 과정이 보이고, 끊을 수 있어야 합니다

Chat/Agent 준비는 최대 수 분이 걸립니다 (Docker Desktop 90초 + WARP 45초 + Tor 회로 +
SearXNG 60초 + AnythingLLM 180초). 이 시간 동안 아무 말도 없으면 사용자에게는 멈춘
창일 뿐이고, 닫으려 해도 그 대기가 끝날 때까지 기다려야 했습니다.

- 모든 긴 대기는 진행 콜백(`log`)과 취소 확인(`cancel_check`)을 받습니다. WARP 와
  SearXNG 는 진행 상황을 로그 파일과 `print` 로만 보냈는데, 데스크톱은 `pythonw.exe`
  로 돌기 때문에 둘 다 아무에게도 닿지 않았습니다. SearXNG 는 `log_path` 가 없으면
  아예 즉시 return 해서, 왜 검색이 안 켜졌는지(이미지 없음·settings.yml 없음·docker
  오류)를 계산해 놓고 버렸습니다.
- Chat 준비창은 `service=='chat'` 메시지만 보여 줬습니다. 지금은 network·Ollama·검색
  진행까지 전부 한 줄기로 보여 주고, 실패해도 그 흐름을 남깁니다.
- 창을 닫으면 진행 중인 Agent turn 을 [중단] 버튼과 같은 방식으로 끊습니다. 모델이
  몇 분씩 도는 동안 종료가 그 뒤에 줄 서 있었습니다.
- 호출과 정의가 맞는지는 `src/tests/test_call_signatures.py` 가 검사합니다.
  `searxng_runtime.start()` 를 `env` 없이 부른 코드가 `except Exception` 안에 있어,
  TypeError 가 경고 한 줄로 바뀌고 터미널 Chat 은 매번 검색이 꺼진 채 돌았습니다.

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
  LocalAI Chat 준비
    -> Network 정책 준비
    -> Ollama + 공용 모델 저장소 확인
    -> AnythingLLM 이미지/컨테이너 확인
    -> 선택 모델을 AnythingLLM Ollama 설정에 동기화
    -> AnythingLLM 컨테이너 내부에서 host.docker.internal:11434/api/tags 확인
    -> 선택 모델 존재 확인
    -> 위 단계가 모두 통과해야 Chat ready

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

Chat의 상단 `Chat: ready`는 단순히 3001 포트가 열렸다는 뜻이 아닙니다. AnythingLLM UI 응답과 함께 컨테이너에서 Host Ollama API에 실제로 접근하고, 현재 Chat에 지정된 모델이 Ollama 모델 목록에 존재하는지까지 확인한 상태입니다. 모델 선택이 바뀌면 Local AI가 관리하는 Ollama 관련 `.env` 필드만 갱신하고 설정 서명을 바꿔 AnythingLLM 컨테이너를 재생성하므로, 사용자 AnythingLLM 설정을 통째로 덮어쓰지 않습니다.

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

**증거 부재는 통과가 아닙니다.** 이 판정은 전부 Block 네트워크 안 컨테이너가 보내는
답에 달려 있는데, 그 답을 `result.get()` 으로 읽으면 `bool(None)` 이 `False` 라
**검사를 안 한 것과 거부당한 것이 똑같이 읽힙니다.** 실제로 프로브가 `{}` 만 보내도
`[OK] public raw-IP TCP and public DNS blocked: True` 를 찍고 exit 0 이었습니다.
지금은 판정이 기대는 사실이 전부 있고 타입까지 맞아야 하며, 파서도 완전한 프로브
결과가 아닌 JSON(예: 엉뚱한 로그 한 줄)은 건너뜁니다. 빠진 답은 `[FAIL]` 입니다.

### Linux Docker 에서 실제로 확인된 것

살아 있는 Docker 데몬(Linux, Docker 29.3.1)에서 이 진단을 끝까지 돌린 결과입니다.
같은 프로브가 일반 bridge 에서는 공용 DNS 와 `1.1.1.1:443` 에 **닿는다**는 기준선을
먼저 잡고 비교했습니다.

| 항목 | 결과 |
| --- | --- |
| `llm_block_net` 속성 | `Internal=true` · `Driver=bridge` |
| 공용 raw-IP TCP | 차단됨 |
| 공용 DNS | 차단됨 |
| 관리형 Host relay 포트(Tor/WARP/SearXNG) | 도달 불가 |
| `host.docker.internal` 로컬 Ollama | **도달 불가 (Linux 한정)** |

마지막 항목은 Linux 의 네트워크 구조 때문입니다. `--add-host
host.docker.internal:host-gateway` 는 언제나 기본 bridge 의 게이트웨이(`172.17.0.1`)를
가리키는데, `llm_block_net` 은 다른 서브넷(`172.18.0.0/16`)이고 internal 이라 그
주소로 가는 경로가 없습니다. 호스트 자체는 **그 네트워크의 자기 게이트웨이**
(`172.18.0.1`)로는 닿습니다 — 즉 격리는 의도대로 동작하고, 이름만 다른 곳을
가리킵니다. Windows Docker Desktop 은 `host.docker.internal` 을 Desktop 이 직접
제공하므로 동작이 다를 수 있고, 여기서는 확인할 수 없습니다. **Block 에서 로컬
Ollama 가 필요하면 자기 PC 에서 위 진단을 한 번 돌려 보세요.**

## 모델 정책

받을 수 있는 모델(`src/launcher/models/model_catalog.py`)과 런타임이 고를 수 있는
모델(`src/launcher/models/model_roles.py` 의 `TIERS`)은 **서로의 거울**이어야 합니다.

- `TIERS` 에만 있는 태그 → 사다리가 1순위로 고르지만 `RUN.bat --install` 흐름 어디에서도 받을 수 없습니다.
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
`RUN.bat --install` 을 돌리면 여유가 8GB 로 잡혀 **하 등급만 받고 상·중은 영영 못 받는**
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

Ollama 는 받은 모델을 내용 해시로만 저장합니다. `C:\LocalAI\models` 를 열면 이렇게 보입니다.

```text
C:\LocalAI\models\
  blobs\sha256-3f1c...          <- 15GB 짜리인데 어느 모델인지 알 수 없음
  manifests\registry.ollama.ai\
    library\gemma4\12b          <- 이 JSON 이 위 해시를 가리킴
```

`src/launcher/models/model_files.py` 가 manifest 를 읽어 대응을 복원하고
**`C:\LocalAI\models\MODEL_FILES.csv`** 로 저장합니다(저장소에 쓸 수 없으면
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

그리고 **확인하지 못한 것을 통과로 요약하지 않습니다.** 레지스트리가 막힌 환경에서
27개 태그를 전부 `UNKNOWN` 으로 나열한 바로 다음 줄에 "모든 태그가 확인됐습니다" 를
찍던 시기가 있었습니다. 지금은 확인된 것과 답 못 받은 것을 구분해서, 하나도 확인하지
못했으면 통과가 아니라고 명시하고 일부만 확인했으면 몇 개인지 말합니다.

Ollama 의 **cloud 태그**(`gpt-oss:20b-cloud`, `gemma4:cloud` 등)는 따로 표시하고
실패로 처리합니다. 이 태그는 받아지지 않습니다 — 로컬 데몬이 사용자 자격증명을
붙여 Ollama 서버로 요청을 넘기고, OpenAI 호환 클라이언트에서는 로컬 모델과
구분되지 않습니다. 즉 Block 의 "공용 egress 차단"과 WARP/Tor 의 경로 보장이
한꺼번에 무효가 됩니다. 그래서 설치·추론 경로에서도 이름 단계에서 거부합니다
(이미 받은 것을 지우는 건 허용). 배포 카탈로그에는 하나도 없고, 테스트가 지킵니다.

이 명령은 **공개 인터넷으로 직접 나갑니다.** 개발자용이고, 데스크톱이나 설치기가
부르지 않으며, 관리형 WARP/Tor/Block 정책을 거치지 않습니다. 공용 egress 가 없는
것이 확인 대상인 상황에서는 실행하지 마세요.

테스트:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q src\tests
```

GitHub Actions는 현재 자동 `push`/`pull_request` 실행을 끄고 수동 실행만 허용합니다. private repo의 hosted runner가 배정되기 전에 실패하는 상태라 불필요한 failure 누적을 막기 위한 조치이며, 실행할 때는 저장소의 `src`를 `PYTHONPATH`로 사용합니다.

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

실행마다 `user_data/logs/launcher_<시각>.log` 도 하나 생깁니다. 데스크톱 셸이 종료
hook 을 설치하게 되면서 이 파일이 **창을 열 때마다** 쌓이게 됐으므로, 트레이스와 같은
방식으로 최근 20개만 남깁니다. 쓰고 있는 파일과 크래시 기록(`launcher_fatal.log`)은
지우지 않습니다.

## 가만히 있을 때의 비용

상태줄 한 줄을 그리려고 10초마다 Docker 에 세 번, Windows 에서는 포트 소유자를
찾느라 PowerShell 을 두 번 — 폴링 한 번에 프로세스 다섯 개, **시간당 1,800개**였습니다.
저장소 동의 확인은 같은 타이머에서 blob 을 전부 순회했습니다. 측정해서 고친 결과:

| | 전 | 후 |
| --- | --- | --- |
| 상태 폴링 | 시간당 프로세스 1,800개 | 600개 (답을 30초 캐시, 버튼은 항상 새로 읽음) |
| 저장소 동의 확인 | blob 전부 순회 | manifest 만 (저장소 크기와 무관) |
| 모델 화면 열기 | 68ms / 스캔 2회 | 16ms / 1회 |
| `is_running()` | 폴링마다 소켓 유출 | 닫음 |
| 실행 로그 | 실행마다 1개, 영구 누적 | 최근 20개 |

유휴 창의 50ms 타이머 자체는 코어의 **0.4%** 라 그대로 뒀습니다. 처음엔 5% 로 보였는데,
재어 보니 4.6% 는 측정 루프였습니다.

## 창 크기와 클릭

**창은 열리는 화면보다 커지지 않습니다.** 예전에는 어떤 모니터에서 열든
1280x860 을 요구했습니다. 1366x768 노트북은 작업 표시줄까지 빼면 세로 730px
쯤이라 아래 130px 이 화면 밖으로 나갔고, 거기에 준비 상태 줄과 모델 화면의
[선택대로 적용] 버튼이 있었습니다. 고장 난 것은 없는데 누를 수도 없는
상태였습니다. 이제 화면 크기에 맞춰 열고 가운데 놓습니다.

**기록(활동 로그)은 창 높이에 따라 줄어듭니다.** 8줄은 데스크톱 창의 1/5 이지만
노트북 창에서는 1/3 입니다. 고정해 두었더니 그 아래 모델 목록에 4px 이 남아
25개 모델을 그 안에 보여 주게 됐습니다. 이제 최소 3줄 ~ 최대 8줄 사이에서
창 높이를 따라갑니다.

**모델 고르기 화면은 목록에 자리를 내줍니다.** 머리글 두 줄을 한 줄로 합치고,
3줄짜리 다운로드 계획은 [선택대로 적용] 옆 한 줄 요약으로 옮기고(자세한 목록은
기록에 남습니다), 세 문장짜리 안내는 한 줄로 줄였습니다. 1366x768 기준으로
목록이 72px → 145px, 1920x1080 기준 137px → 357px 이 됐습니다.

**고정 행은 글자가 줄면 자리를 돌려줍니다.** 그 행들은 `StringVar` 로 그리는
라벨이라 비어 있을 때 재고, 경로나 계획으로 채우고, 다시 비웁니다. 한 번 잡은
높이는 두 번 틀리고, 높게 틀리면 목록이 그 값을 냅니다.

점검은 실제 창을 띄워서 합니다. 모든 페이지·모든 탭의 클릭 가능한 위젯마다
(1) 명령이 붙어 있는지 (2) 24x18px 이상인지 (3) 창 안에 있는지 (4) 가운데를
눌렀을 때 그 위젯에 닿는지를 확인하고, 넘치는 스크롤 영역마다 스크롤바가
보이는지와 휠이 듣는지를 확인합니다.

## 데이터 보존

새 설치에서는 처음부터 공용 데이터와 개인 데이터를 나눠 저장합니다. 자동 이전
단계는 없습니다.

```text
C:\LocalAI\environment\          공용 실행환경
C:\LocalAI\ollama\               공용 Ollama 중계기
C:\LocalAI\models\               공용 모델
C:\LocalAI\users\<계정>\
  user_data\                      개인 설정·대화·프로젝트·벡터 저장소
  logs\                           개인 로그
  workspace\                      개인 작업 파일
```

체크아웃을 복사하거나 다시 받아도 공용 환경과 모델은 중복 생성하지 않습니다.
각 Windows 계정의 `RUN.bat`은 같은 공용 런타임을 바라보되, 설정·Agent trace·
인터프리터 세션·AnythingLLM 데이터 등은 자기 계정 폴더만 사용합니다.

## 이전 상세 README

구조 개편 전의 긴 README는 내용 유실 없이 다음 위치에 보존했습니다.

```text
src/docs/legacy/README_before_src_refactor.md
```

과거 패치 이력이나 예전 구조를 확인할 때만 참고하세요. 현재 실행 방법은 이 루트 README를 기준으로 합니다.