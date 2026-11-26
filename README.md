# Local_AI_Agent

Windows에서 로컬 LLM 채팅과 자동화 에이전트를 실행하기 위한 자기완결형 프로젝트입니다.

사용자 관점에서 프로젝트 루트의 **유일한 실행 진입점은 `RUN.bat`** 입니다.
처음 설치하면 프로그램이 `C:\LocalAI\app`에 한 벌 설치되고, 모든 Windows 계정이
시작 메뉴의 **LocalAI** 항목(또는 `C:\LocalAI\app\RUN.bat`)으로 같은 프로그램을 실행합니다.
바탕화면에는 바로가기를 만들지 않습니다. 실행환경·Ollama·모델은 PC에 한 벌만 두고, 사용 기록은 계정별로 분리해 **그 계정의 Windows
키로 암호화**합니다.

```text
C:\LocalAI\
├─ app\                  공용 — 모든 계정이 실행하는 프로그램 (관리자만 갱신)
├─ machine.json          공용 — LocalAI 관리자와 사용 범위 (관리자만 수정)
├─ environment\          공용 — 관리형 런타임 · 설치 템플릿 · 스크립트
├─ ollama\               공용 — LocalAI가 관리하는 Ollama 중계기 (원시 로그 미저장)
├─ models\               공용 — 모든 계정이 사용, 설치·삭제는 LocalAI 관리자만
│  ├─ MODEL_FILES.csv
│  └─ .localai\
│     ├─ registry.json
│     └─ model-mutation.lock
└─ users\
   └─ <계정>\
      ├─ user_data\      개인 — 설정 · 프로젝트 · 대화 · 벡터 저장소 (암호화)
      ├─ logs\           개인 — 세션/런타임 로그 · 에이전트 기록 (암호화)
      └─ workspace\      개인 — 에이전트 기본 작업 폴더 (평문, 사용자 파일)
```

## 오픈소스 및 제3자 라이선스

이 프로젝트는 Ollama, AnythingLLM, Open Interpreter, SearXNG, Tor 프록시,
Cloudflare WARP Docker 이미지 등 외부 소프트웨어를 설치하거나 실행합니다.
각 구성요소는 **서로 다른 라이선스 및 이용약관**을 가지며, 이들 라이선스가
Local_AI_Agent 자체의 라이선스를 지정하는 것은 아닙니다.

- [외부 소프트웨어 목록과 라이선스 고지](licenses/THIRD_PARTY_NOTICES.md)
- [모델별 라이선스 확인 대상](licenses/MODEL_LICENSE_REVIEW.md)
- [제3자 라이선스 원문 모음](licenses/)

특히 SearXNG 및 Tor 프록시는 AGPL 계열이며, 기본 WARP Docker 이미지는
**CC-BY-NC-4.0(비상업적 이용 조건)** 입니다. Docker Desktop 및 Cloudflare WARP
서비스 이용조건도 별도로 적용됩니다. 개인·포트폴리오 목적의 사용과 외부 재배포는
구분해서 확인하세요. LLMfit은 선택형 GPU 모델 적합도 분석기로 설치/복구에 연동되며, 관련 라이선스를 함께 수록했습니다.

## 관리자와 계정 관리

- **첫 설치 계정이 LocalAI 관리자**가 됩니다. 처음 [설치 / 복구]를 실행하면 Windows
  확인 창(UAC)이 한 번 뜨고, `LocalAI-Admins` / `LocalAI-Users` 로컬 그룹 생성, 이
  계정의 관리자 등록, `C:\LocalAI` 권한 잠금, 공용 시작 메뉴 항목 생성이 한 번에 끝납니다.
  "처음 설치한 계정"은 `C:\LocalAI` 폴더를 만든 계정(소유자)입니다.
- `C:\LocalAI`는 이제 C:\ 에서 물려받던 `Authenticated Users: 수정` 권한을 끊습니다.
  관리자만 프로그램·실행환경·**모델 저장소**를 바꿀 수 있고, 다른 계정은 읽기·실행만
  합니다. 모델 설치·삭제(Models 화면, `RUN.bat --manage`의 모델 관리)는 LocalAI
  관리자 계정에서만 진행하며, 다른 계정은 설치된 모델을 그대로 사용합니다.
- LocalAI 관리자 여부는 `machine.json`에 적힌 SID만으로 정하지 않습니다. Windows가
  보고하는 `LocalAI-Admins` 그룹 구성원과 실제 그룹 SID로 확인한 뒤에만 관리자로
  인정하고, 확인되지 않는 기록은 다음 관리자 Setup에서 정책 파일에서 제외합니다.
- **Setup → LocalAI 계정 관리**에서 관리자는 이 PC의 계정 목록을 보고, 사용 허용/해제,
  관리자 지정/해제, **기록 삭제**, "허용한 계정만 사용" 전환을 할 수 있습니다. 그룹 변경과
  삭제는 UAC 승인이 필요하고, 그룹 변경은 그 계정이 다시 로그인하면 적용됩니다.
- 관리자가 아닌 계정의 Setup은 자기 개인 폴더와 자기 Docker Sandbox 이미지만
  준비합니다(빌드 파일은 `users\<계정>\user_data\sandbox-build`에 생성). 공용
  프로그램·실행환경·모델 저장소(`models\.localai` 포함)는 만들거나 쓰지 않으며,
  관리자 Setup이 먼저 실행되지 않았으면 그 사실을 알리고 중단합니다.
- 프로그램 갱신은 관리자가 **푸시된 커밋을 체크아웃한 깨끗한 Git 저장소**에서
  `RUN.bat --install`을 실행하면 `C:\LocalAI\app`에 통째로 교체됩니다
  (아래 "Git 커밋과 설치본 연결" 참고).

## 기록 암호화 — 관리자도 읽을 수 없고, 지울 수만 있습니다

Windows 관리자는 소유권을 가져와 어떤 폴더든 열 수 있습니다. 그래서 ACL만으로는
관리자를 막을 수 없고, 대신 **DPAPI**(Windows 내장, Home 포함)로 각 계정의 키로
암호화합니다. 다른 계정은 물론 관리자가 소유권을 가져오거나, 디스크를 떼어 가거나,
이 계정 비밀번호를 강제로 바꿔도 내용을 풀 수 없습니다.

| 기록 | 방식 |
|---|---|
| 설정 · 프로젝트 · 폴더 권한 정책 | 저장할 때마다 파일 전체 암호화 |
| 세션 로그 · 에이전트 기록(`agent_trace_*.jsonl`) | 줄마다 암호화 (`#LAV1 ...`) |
| AnythingLLM 대화·문서 저장소, Open Interpreter 세션 | Chat/Agent가 **멈추면** 한 파일로 봉인(`*.vault`), 시작할 때 풂 |

- 봉인은 보관 파일을 끝까지 다시 읽어 확인한 뒤에만 평문을 지웁니다. 컨테이너가 멈췄는지
  확인할 수 없으면 봉인하지 않습니다. 비정상 종료로 남은 평문은 다음 실행 때 런타임이
  멈춘 것이 확인되면 봉인합니다.
- AnythingLLM의 공개 임베딩 모델(`models\`)과 설치된 인터프리터 패키지(`packages\`)는
  봉인하지 않습니다. `workspace\`는 사용자가 직접 여는 작업 파일이라 평문입니다.
- 이전 버전이 남긴 평문 기록은 [설치 / 복구] 때 한 번 암호화로 바뀝니다.
- 내 기록 보기: `RUN.bat --records` (목록), `RUN.bat --records show <파일>`,
  `RUN.bat --records export <폴더>` (복호화 사본 — 다 본 뒤 지우세요).
- Windows에서 DPAPI 보호를 사용할 수 없으면 개인 기록을 평문으로 저장하지 않고
  오류로 중단합니다. 기존 설정 `LOCAL_AI_VAULT=off`로도 평문 저장할 수 없습니다.
- 한계: 로그인 중 계정 세션을 탈취하거나 관리자/SYSTEM 권한으로 실행 중인
  프로세스에 접근하는 공격까지 차단하는 것은 아닙니다. Chat/Agent 저장소는 실행 중
  평문으로 열리고 종료 시 봉인됩니다. 개인 작업 파일도 자동 암호화하지 않습니다.
- Ollama 중계기는 모든 계정의 요청을 처리하므로 원시 stdout/stderr를 저장하지
  않습니다. `OLLAMA_DEBUG`도 중계기에 전달하지 않습니다. 이전 릴리스의 공용
  로그는 자동 삭제하지 않으며 관리자가 중계기 종료 후 점검·정리해야 합니다.
- 계정별 경로와 DPAPI/ACL의 실제 보안 범위: [보안 및 저장소 설계](docs/ACCOUNT_DATA_SECURITY.md).

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

### LLMfit (선택형 GPU 적합도 분석)

관리자 `RUN.bat --install`은 공식 Windows LLMfit v1.1.20 배포본을 SHA-256 검증 후 `C:\\LocalAI\\environment\\llmfit\\llmfit.exe`에 설치합니다. 설치 실패 시 기존 LocalAI 추천·모델 실행은 계속 작동합니다. 별도 서버를 띄우지 않고 Models 화면을 열 때만 JSON CLI를 조회합니다. 응답은 10분 캐시하며, 모델 파일이나 Ollama 서버를 LLMfit이 직접 설치·수정하지 않습니다.

오른쪽 GPU 막대의 **현재 GPU 사용량**은 NVIDIA `nvidia-smi` 실측이고, **선택 모델 예상 사용량**은 4096토큰 컨텍스트 기준 LLMfit 분석값 또는 카탈로그 근사입니다. 두 값은 동일한 개념이 아닙니다. 모델의 GGUF 양자화가 다르면 요구량이 바뀌며, CPU 오프로딩 모델은 전체 요구 메모리를 전용 VRAM 소비량으로 오표시하지 않습니다. 이미 Ollama에 적재된 동일 모델은 예상 총량에 중복 합산하지 않습니다. 막대는 적재 성공 보장이 아니며, 설치 체크한 여러 모델을 합산하지 않습니다.

디버그 환경에서 다른 LLMfit 바이너리를 확인해야 할 때만 `LOCAL_AI_LLMFIT_EXE`를 절대 경로로 지정할 수 있습니다. 공식 배포 실행 파일과 라이선스는 각 사용자가 별도로 검증할 수 있습니다.

### 자막 만들기 (선택형 음성 엔진)

Tools → **자막 만들기**는 영상·MP3·WAV 등의 말소리를 이 PC에서 받아 적어 SRT·WebVTT 자막을 만듭니다. 음성 인식은 Ollama LLM이 아니라 별도의 Whisper 모델(whisper.cpp `v1.9.5`)이 하고, 번역 자막을 함께 고르면 기존 [파일 번역] 도구와 로컬 LLM이 번역합니다. [파일 번역]에서 영상·음성 파일을 고르면 자동으로 자막을 먼저 만든 뒤 번역합니다.

- 자막 규칙: 최대 2줄, 언어별 줄 길이(한국어·중국어 16, 일본어 13, 그 밖 42자), 표시 시간 5/6~7초, 큐 사이 2프레임, 읽기 속도. 자막은 원본 옆에 원본과 같은 이름(`영상.mp4` → `영상.srt`)으로 만들고 덮어쓰지 않습니다. 번역 자막을 함께 만들면 기본으로 번역 자막이 `영상.srt`, 원어 자막이 `영상.<원어>.srt`입니다(옵션으로 반대도 가능). 옆에 자막이 이미 있는 파일은 건너뛰고, 번역만 실패했던 파일은 다시 실행하면 번역만 합니다. [파일 번역]도 '번역본을 원본 이름으로 저장'(원본은 `이름.<원문 언어>.확장자`)을 고를 수 있습니다.
- 반복·감탄사·비속어는 그 자체로 오류로 보지 않고, 근거(낮은 확신도·압축률·불가능한 발화 속도)가 겹칠 때만 지웁니다. 의심·누락 구간만 다시 인식해 명확히 나은 후보만 반영하고 판단 기록을 남깁니다.
- 엔진(whisper.cpp·LGPL FFmpeg·Silero VAD)은 관리자 `RUN.bat --install`이 고정 버전·체크섬 검증으로 `C:\LocalAI\environment\speech`에 설치하고, 모델은 관리자가 **Models → 음성 인식 (자막)** 탭에서 골라 `C:\LocalAI\models\speech`에 받습니다(자막 화면에서 바로가기 제공). 설치 실패는 다른 기능에 영향이 없습니다.
- 폴더 단위: 자막 도구는 최상위 폴더를 고르면 하위 폴더의 각 영상·음성 옆에 만들고, [파일 번역]의 폴더 번역은 영상·음성을 복사하지 않고 자막을 만든 뒤 같은 폴더 메모리(인물·용어·줄거리)로 번역합니다.
- 용어 사전 수정: 번역이 끝나면 [용어 사전 수정] 탭에서 용어를 고쳐 적용할 수 있습니다. 그 용어가 든 줄만 다시 번역해 결과 파일을 고쳐 쓰고, 원하면 고정 용어집에도 넣어 다음 번역부터 적용합니다.
- 실제 다국어 음성(FLEURS 4개 언어)으로 측정한 결과와 도입 판단, 자세한 규칙·오탐지 정책·평가 방법(`python -m tools.evaluate_subtitles`): [자막 만들기](docs/SUBTITLES.md).

## 최초 사용자 자동 관리자 등록 및 초기 권한 오류 진단

Windows에서 새로 받은 LocalAI를 **평소처럼 `RUN.bat`으로 실행하면**, `C:\\LocalAI\\machine.json`이 없는 최초 설치에서 현재 Windows 계정을 LocalAI 관리자 후보로 자동 등록합니다. 별도 관리자 로그인이나 별도 `--install` 명령은 필요하지 않습니다.

- 처음 한 번은 **Windows UAC 승인**을 요청합니다. 이는 LocalAI 전용 관리자 역할 등록이 아니라 실제 NTFS 프로그램 파일 권한을 안전하게 바꾸는 운영체제 요구사항이므로 생략할 수 없습니다.
- 승인·보호 검증이 성공하면 `LocalAI-Admins`에 최초 설치자의 **Windows SID**를 기록하고, 실행환경 기본 폴더와 현재 계정의 개인 데이터 공간을 만든 뒤 Studio를 엽니다.
- 이미 관리자 정책이 존재하면 **다음 사용자가 자동으로 새 관리자 권한을 받을 수 없습니다.** 정책 파일이 손상되거나 읽히지 않으면 자동 등록하지 않고 관리자 복구를 요구합니다.
- 실행환경 구성요소 자체(Ollama/Chat 등)의 설치 및 업데이트는 기존 Setup → **설치 / 복구**를 이용합니다. 최초 관리자 역할 등록은 전체 구성요소 설치와 별개입니다.
- 관리자 권한으로 스크립트가 실행된 뒤 오류가 발생하면, 예전처럼 모두 ‘UAC 취소’로 표시하지 않고 Windows 그룹·루트 ACL·하위 파일 ACL 중 실패 지점을 기록합니다. `C:\\LocalAI\\.localai-admin-*.txt` 진단 파일은 실패 때만 생성하며, 시작 실패 팝업이나 Setup 진행 로그에서도 확인할 수 있습니다.
- 사용 중인 LocalAI/Ollama가 하위 파일을 잠가 ACL 복구에 실패할 수 있습니다. 이 경우 사용 중인 프로그램을 종료한 뒤 재시도하세요. **ACL 보호 실패를 무시한 설치는 허용하지 않습니다.**

## 공용 프로그램 파일 보호 (Windows)

LocalAI는 하나의 `C:\\LocalAI\\app` 프로그램을 모든 Windows 계정이 실행하되, 일반 사용자에게는 **읽기·실행 권한만** 부여합니다. `C:\\LocalAI\\environment`, `C:\\LocalAI\\ollama`, `C:\\LocalAI\\models`도 같은 정책을 따릅니다. 프로그램을 설치·업데이트하고 모델을 설치·삭제할 수 있는 계정은 LocalAI 관리자 및 Windows 관리자뿐입니다.

- 관리자 Setup은 프로그램을 복사하기 **전에** Windows UAC로 공용 루트의 상속 ACL을 차단하고, 남아 있는 **명시적 쓰기·삭제·권한 변경 허용 ACE**를 제거합니다. 보호 대상 하위 폴더는 재귀적으로 ACL과 소유권을 정리하고, 설치 프로그램이 파일을 추가한 뒤에도 다시 검증합니다.
- **UAC 승인 취소·ACL 적용/검증 실패 시 설치/업데이트를 중단**합니다. 보안 적용 없이 설치에 성공했다고 표시하지 않습니다. 일반 사용자 Setup은 본인 기록/설정만 준비하며 공용 프로그램을 덮어쓰지 않습니다.
- `C:\\LocalAI\\models`도 보호 대상입니다. 일반 계정이 manifest·blob·`registry.json`을 바꾸면 다른 계정이 실행하는 모델이 바뀌므로, 예전 설치가 남긴 `Users: 수정` 권한과 다른 계정 소유권을 관리자 Setup에서 제거합니다. `C:\\LocalAI\\users\\<계정>`에는 각 계정의 개인 권한이 유지됩니다. `environment\\desktop-runtime.lock` 파일에는 동시 실행 조정을 위한 최소 읽기/쓰기 권한만 예외로 부여합니다.
- 공용 Ollama 중계기는 시작 시 모델 파일을 정리(prune)하지 않도록 `OLLAMA_NOPRUNE=1`로 실행합니다. 읽기 전용 저장소에서도 일반 계정이 중계기를 시작할 수 있고, 아무도 요청하지 않은 모델 삭제가 일어나지 않습니다.
- 관리자 Setup은 시작할 때와 외부 설치 프로그램 실행 후에 한 번씩 보호를 다시 적용하므로 UAC 확인 창이 **두 번 이상** 뜰 수 있습니다. LocalAI 관리자가 Windows 관리자가 아니면 그때마다 Windows 관리자 자격 증명이 필요합니다.
- LocalAI 관리자를 해제하거나 계정 사용 범위를 변경할 때도 프로그램 파일 권한을 다시 보호합니다. 단, Windows 자체 관리자 권한을 소유한 사용자는 UAC 승인 후 ACL을 변경할 수 있습니다.

### Git 커밋과 설치본 연결 (변조·끼워 넣기 방지)

`C:\\LocalAI\\app`은 체크아웃 폴더를 그대로 복사하지 않고 **Git 객체에서 직접** 만듭니다.

- 배포 내용은 체크아웃 `HEAD` 커밋의 blob뿐입니다. 각 blob은 커밋이 가리키는 해시와 다시 대조하므로, 작업 폴더에서 수정된 파일이나 손상·바꿔치기된 Git 객체는 배포되지 않습니다.
- 커밋되지 않은 수정, **추적되지 않은 추가 파일**(예: 끼워 넣은 `src/sitecustomize.py`)이 배포 범위에 있으면 Setup은 배포를 중단합니다. `.gitignore`로 숨긴 파일과 체크아웃의 `__pycache__`도 복사되지 않습니다.
- 어떤 원격 브랜치에도 없는(푸시되지 않은) 커밋, 심볼릭 링크·서브모듈, 다른 위치의 객체 저장소(alternates), 저장소 하위 폴더에서 실행한 Setup은 거부합니다. 다른 Windows 계정이 소유한 체크아웃은 Git 자체의 소유권 검사(`safe.directory`)로 거부됩니다.
- Setup이 실행하는 Git 명령은 체크아웃의 `.git/config`가 지정한 프로그램(`core.fsmonitor`, hooks, 외부 diff 등)을 실행하지 않도록 강제로 끈 상태로 실행합니다.
- `VERSION.json`에는 커밋·트리 ID, 원격 주소, 파일별 Git blob ID와 SHA-256이 기록됩니다(바이트코드 포함). `RUN.bat`은 Windows `cmd.exe`용으로 CRLF로 기록하며, 기록된 변환 정보로 Git 내용과 다시 대조할 수 있습니다.
- LocalAI는 **시작할 때마다** 공용 설치본을 이 기록과 대조합니다. 파일이 바뀌었거나 없어졌거나 **추가되었으면** 실행하지 않고 관리자 재배포를 안내합니다. 무결성 기록이 없는 예전 설치본은 안내만 하고 실행합니다. 다른 버전의 Python이 남긴 바이트코드(`__pycache__\*.cpython-XY.pyc`, 현재 Python이 읽지 않는 파일)는 검사에서 제외합니다.
- 기록 파일까지 다시 계산해 덮어쓴 경우는 시작 검사로는 알 수 없으므로, 신뢰된 체크아웃의 Git 기록과 직접 대조합니다.

```powershell
cd <체크아웃>\src
python -m tools.verify_app
```

`OK ... (Git ls-tree 확인)`이면 설치본의 모든 파일이 체크아웃 `HEAD` 커밋과 같습니다. 이 검사는 아무것도 바꾸지 않습니다.

### 현재 PC의 실제 권한 확인

설치/복구 직후 PowerShell에서 다음처럼 확인할 수 있습니다. **실제 파일 ACL이 중요하며, 코드가 바뀌었다고 이미 설치된 폴더 권한이 자동으로 변경되는 것은 아닙니다.**

```powershell
icacls C:\LocalAI
icacls C:\LocalAI\app
icacls C:\LocalAI\environment
icacls C:\LocalAI\ollama
icacls C:\LocalAI\models
```

`app`, `environment`, `ollama`, `models`의 일반 사용자 권한은 `(RX)`이어야 하며 `(M)`, `(F)`, `(W)`가 있으면 안전하지 않습니다. 관리자 Setup (`RUN.bat --install`) 또는 관리자 계정의 Models → **모델 저장소 권한 보호**를 실행해 승인·복구하십시오. 원본 Git checkout 폴더 자체의 ACL은 이 보호 범위에 포함되지 않으므로, 관리자 계정만 수정할 수 있는 신뢰된 원본에서 설치해야 합니다. 이 경우에도 위의 Git 연결 검사로 커밋되지 않은 변경과 추가 파일은 배포되지 않습니다.

### 작고 편안한 기본 화면 (연회색 테마)

LocalAI Studio와 Chat, Interpreter, Setup 창은 새 사용자 기준 **밝은 회색 테마**로 시작합니다. 기본 창은 1100×720 크기로 열며 최소 880×560까지 줄일 수 있습니다. 기존에 저장한 다크/라이트 개인 설정은 자동으로 덮어쓰지 않습니다. Settings에서 언제든 바꿀 수 있습니다.

- 왼쪽에는 Chat·Agent·Tools·Models·Setup·Home의 주요 메뉴를 먼저 보이고, Network·System·Settings는 **더보기**에서 엽니다. 설치 모델 전체 목록도 필요할 때만 펼칩니다.
- Chat/Agent는 시작·열기·종료와 상태를 먼저 보여 주고, 웹 검색·세션 네트워크·연결 옵션은 **연결·웹 검색 옵션**으로 묶었습니다. Agent 시작 마법사도 현재 화면 테마를 따르며, 시작·취소 버튼을 고정하고 고급 Host·인터넷 설정을 스크롤 가능한 영역에 접어 둡니다. Setup은 실행/중단을 먼저 보여 주며 Sandbox/Search 설정과 계정/유지보수 기능을 접을 수 있습니다.
- Models에서는 권장 세트·새로고침·선택대로 적용을 우선하고, 전체 선택·해제 및 저장소 설정은 필요할 때 펼칩니다. 오른쪽 **GPU 메모리** 막대와 모델 카드의 **GPU 보기**는 설치 체크박스와 독립적으로 동작합니다.
- 작은 화면에서는 스크롤 가능한 Tools 목록, GPU 패널과 모델 테이블의 가로 스크롤을 지원합니다. 설치 진행 시 Activity 기록만 임시로 열고 다른 화면으로 이동하면 작업 공간을 되돌립니다.

### 메모리·VRAM 절약형 실행

Studio는 기본적으로 필요한 서비스만 시작합니다. Chat과 Agent의 SearXNG 웹 검색은 각 실행 화면에서 체크할 때만 실행하며, Ollama가 직접 관리되는 경우 유휴 모델 유지 시간은 기본 2분입니다. Models → 설치 · 모델 관리 오른쪽 패널에는 GPU 실측 사용량, 선택 모델의 예상 VRAM, 추가 적재 시 예상 총량을 각각 100% 막대로 표시합니다. 모델 카드의 **GPU 보기**는 설치 체크와 무관합니다. LLMfit이 없거나 모델 매핑에 실패하면 기존 카탈로그 추정값을 사용하며, 실제 모델 다운로드/적재는 기존 LocalAI/Ollama에서만 수행합니다. Windows GPU·Docker 실기기 성능 검증 방법과 한계는 [경량 실행 및 자원 정책](docs/RUNTIME_RESOURCE_POLICY.md)에 정리했습니다.

## 빠른 시작

### 1. 설치 또는 관리

```bat
RUN.bat --install   :: Setup UI를 열고 설치 / 재설치 시작
RUN.bat --manage    :: Setup UI 열기 (자동 실행 없음)
```

두 경로는 **같은 Setup UI**를 사용합니다. 차이는 `--install`이 창이 열린 뒤 설치/복구를
자동으로 시작하고, `--manage`는 사용자가 옵션을 확인한 뒤 직접 실행한다는 점뿐입니다.

**설치와 모델 관리의 사용자 UI는 하나입니다.** Setup 화면에서 Sandbox / Docker build /
Search(SearXNG+Tor) 선택을 하고, Ollama·AnythingLLM·Open Interpreter·WARP를 포함한 설치
진행 로그는 같은 창의 Activity 영역에 실시간으로 표시됩니다. 별도 설치 콘솔이나 진행창을
띄우지 않습니다. 모델 선택/설치/삭제도 **Models** 화면에서 처리하며 다운로드 모델명,
진행률과 받은 용량을 같은 창에서 확인합니다.

- `--install` → Setup UI를 열고 현재 체크 상태로 설치/복구를 자동 시작합니다.
- `--manage` → 같은 Setup UI를 열되 자동 실행하지 않습니다.
- `python -m installer` → GUI가 필요 없는 진단/자동화용 콘솔 진입점입니다.
- 새 설치는 예전 경로를 자동 검색·이동·병합하지 않습니다.


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
RUN.bat --tui              :: 터미널 런처
```

Studio 는 Tk 가 있는 Python 3.11+ 를 씁니다. GUI를 사용할 수 없는 환경에서는
`RUN.bat --tui` 로 터미널 런처를 쓸 수 있습니다.

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
`OLLAMA_MODELS`도 기록합니다. `environment`와 `ollama`는 계속
`BUILTIN\Users` 읽기/실행만 허용하며, `models`도 같습니다. 다른 Windows 계정은
같은 모델을 그대로 사용하고, 설치·삭제는 LocalAI 관리자 계정에서만 합니다.

**계정 간 공유** — 공용 Ollama가 이미 응답 중이면 어느 Windows 계정이 시작했든
재사용합니다. 계정별 런타임 상태 파일이 없다는 이유만으로 공용 프로세스를 자기
프로세스로 간주하거나 재시작하지 않습니다. 반대로 알 수 없는 위치의 Ollama가
11434 포트를 점유하면 임의 종료하지 않고 설치/실행을 중단합니다.

**개인 데이터는 공유하지 않습니다.** AnythingLLM 저장소, Open Interpreter HOME,
설정·프로젝트·대화·컨테이너 파생 설정은 `user_data`, 실행/Agent trace는 `logs`,
작업 파일은 `workspace`로 나눠 모두 현재 계정의
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
MODEL_CONTROL_DIR   -> C:\LocalAI\models\.localai
MODEL_REGISTRY_PATH -> C:\LocalAI\models\.localai\registry.json
MODEL_MUTATION_LOCK -> C:\LocalAI\models\.localai\model-mutation.lock
MODEL_FILES_PATH    -> C:\LocalAI\models\MODEL_FILES.csv

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

기본 설치에서는 `environment`, `ollama`, `models`에 `BUILTIN\Users` 읽기/실행
권한만 보장합니다. 따라서 일반 Windows 계정은 공용 모델을 사용할 수 있지만 모델과
공용 실행 바이너리를 바꿀 수는 없습니다. 모델 파일 소유자가 자기 파일에 쓰기 권한을
다시 주지 못하도록 `models`에는 `OWNER RIGHTS` 읽기/실행 항목도 둡니다.
`C:\LocalAI\users` 부모에는 자기 `users\<계정>` 폴더를 만들 수 있는 최소 권한만
주고, 생성한 계정 폴더는 즉시 상속을 끊어 해당 계정·SYSTEM·Administrators만 접근하게
합니다. 개인 설정과 잠금 파일은 `users\<계정>\user_data\runtime` 아래에서 현재 계정이
직접 쓰며, 이전 실행이 남긴 `user_data\cache\*.lock`은 런타임 정본으로 다시 사용하지
않습니다.

계정 폴더 권한은 이름(`%USERDOMAIN%\%USERNAME%`)이 아니라 현재 프로세스의 **SID**로
부여하고, ACL은 Win32 API(`GetNamedSecurityInfoW`)로 직접 읽습니다(실패 시 `icacls /save`,
`Get-Acl` 순서로 대체). 폴더 자체를 먼저 잠근 뒤 안쪽 파일은 별도로 상속 재설정하므로,
"관리자 권한으로 실행"한 이전 설치가 남긴 로그 파일 하나 때문에 잠금 전체가 실패하지
않습니다. 현재 계정 권한으로 고칠 수 없으면(예: 폴더 소유자가 Administrators) Setup이
UAC 확인 창을 한 번 띄워 폴더 소유권을 이 계정 SID로 되돌린 뒤 다시 확인합니다.
자동화 환경에서 UAC 창을 띄우지 않으려면 `LOCAL_AI_NO_ELEVATION=1`을 설정하세요. 그래도
실패하면 Setup 오류에 원인(SID·소유자·Windows 오류 코드)과 관리자 명령 프롬프트에서
실행할 `icacls` 명령 세 줄이 함께 표시됩니다. Ollama 로그(`logs\ollama_run.log`)에 쓸 수
없을 때는 Ollama 시작을 실패로 처리하지 않고, 기존 파일을 옆으로 옮기거나 다른 로그
파일에 기록합니다.

공용 실행환경과 모델 저장소 권한은 의도적으로 **읽기/실행**입니다. 모델 설치·삭제,
manifest/blob 변경, `MODEL_FILES.csv`, 공용 registry와 mutation lock은 모두
`C:\LocalAI\models` 아래에서 한 벌로 관리하며 LocalAI 관리자만 바꿉니다. Models
화면과 모델 관리 메뉴는 관리자가 아닌 계정의 변경 요청을 Ollama 시작·다운로드 전에
거절합니다. `environment` 아래 공용 Open Interpreter 바이너리 등을 새로 설치·업데이트할
때도 LocalAI 관리자 계정에서 Setup을 실행해야 합니다.

**남은 한계 — 공용 Ollama HTTP API.** Ollama의 `127.0.0.1:11434` API에는 인증이 없고,
모델 변경은 중계기 프로세스의 Windows 권한으로 실행됩니다. 중계기를 **관리자 계정이
시작한 동안**에는 같은 PC의 다른 계정이 LocalAI를 거치지 않고 API로 직접
`/api/pull`·`/api/delete`를 호출할 수 있습니다. 반대로 일반 계정이 시작한
중계기에서는 ACL 때문에 관리자 계정의 모델 설치도 실패하므로, 그때는 그 계정의
LocalAI를 종료해 중계기를 내린 뒤 관리자 계정에서 다시 시도하세요. 이 경로까지
막으려면 중계기를 모델 쓰기 권한이 없는 별도 서비스 계정으로 실행하는 구조 변경이
필요합니다.

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
`BUILTIN\Users`가 모델을 읽고 수정할 수 있는지로 판단합니다. 예전 RX-only 설치는
공유 완료로 오인하지 않고 Setup의 권한 복구 대상으로 표시합니다. 사용자 범위
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

- `TIERS` 에만 있는 태그 → 사다리가 1순위로 고르지만 **Models** 카탈로그에 없으면 UI에서 받을 수 없습니다.
- 카탈로그에만 있는 태그 → 받아서 디스크를 써도 런타임이 한 번도 고르지 않습니다.

둘 다 예외도 경고도 없이 지나가므로 `src/tests/test_model_catalog_tiers.py` 가 양방향을
강제합니다. 모델을 추가·교체할 때는 두 파일을 함께 고치세요.
(임베더는 `kind="embed"` 로 표시하며 역할 사다리에서 제외됩니다.)

모델 선택의 기본 정본은 `TIERS` 이고, 역할별 공용 재정의는
`C:\LocalAI\models\.localai\registry.json` 의 `replace` / `add` 로 합니다.
`ROLES[*].model / fallback` 은 화면 표시용이며 임포트 시점에 최종 TIERS의 1·2단계로
덮어써집니다. 예전 `user_data\models\registry.json`은 자동 병합하지 않고 이전 데이터로 남겨 둡니다.

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

3단계는 **실행 시 후보 사다리**입니다. **기본 다운로드는 상·중 5종만** 미리 체크하고,
하 단계 모델은 사용자가 Models 화면에서 직접 선택했을 때만 설치합니다.
기본 5종은 역할별 공통 모델을 재사용하며 중복 다운로드를 줄입니다.
메모리가 너무 적어 기본 세트 중 하나도 적재할 수 없다면 불가능한 모델을
억지로 선택하지 않고, 하 단계 모델을 수동 설치하도록 안내합니다.

후보 과밀을 줄이기 위해 역할별 상·중 단계 대체 모델은 최대 2개,
하 단계는 최대 1개만 표시합니다. 실험용 `qwen3.8:27b`처럼
실행 호환성을 확인하지 못한 모델은 기본 카탈로그에서 제외했습니다.
이미 설치한 모델은 별도의 설치 모델 목록에서 계속 확인·관리할 수 있습니다.

### 설치는 예산으로, 실행은 지금 여유로

두 판단의 입력이 다릅니다. 섞으면 조용히 망가집니다.

```text
설치 (무엇을 받을까)  ->  MEMORY_BUDGET_GB          이 PC 의 상한
실행 (무엇을 띄울까)  ->  detect_free_memory_gb()   지금 이 순간의 여유
```

예전 설치기 모델 선택기는 `detect_free_memory_gb()` 를 사용해 브라우저를 켜 둔 상태에
따라 선택이 달라질 수 있었습니다. 지금은 **Models** 화면이 `MEMORY_BUDGET_GB`를 기준으로
권장 체크 상태를 만들고, 실제 실행 시에만 현재 여유 메모리를 봅니다.

### 크기는 두 가지입니다

```text
size_gb  받는 크기(디스크)   — Models 화면의 "몇 GB 받나"
run_gb   상주 크기(메모리)   — 등급 배정과 적재 가능 판정
```

Gemma 4의 'effective parameter' 수는 실제 가중치 메모리를 뜻하지 않습니다.
하 단계 공용 폴백인 `qwen3.5:4b-q4_K_M`는 파일이 약 3.3GB이고,
실행 시에는 KV 캐시·컨텍스트 크기 때문에 더 많은 메모리가 필요할 수 있습니다.

### 도구 호출

Open Interpreter 는 도구 호출로 동작합니다. `coding` · `agent` 사다리에는
`tools=True` 인 모델만 들어갈 수 있고, 테스트가 이를 막습니다. 도구를 못 부르는
모델을 고르면 에이전트가 오류 없이 그냥 멈춘 것처럼 보입니다.

### 용도별 모델 그룹

`TIERS` 의 키 = `model_classes.CLASSES` 의 키 = `ROLES` 의 이름. 셋이 같은 집합이어야
하고 테스트가 이를 강제합니다.

| 그룹 | 목적 | 상 (기본 사다리) | 중 (기본 사다리) | 하 (수동 선택) |
| --- | --- | --- | --- | --- |
| `coding` | 코드 작성·실행 | `devstral-small-2:24b` | `qwen2.5-coder:14b` | `qwen2.5-coder:7b` |
| `agent` | 검색·도구·자율 실행 | `gemma4:26b-a4b-it-qat` | `gemma4:12b` | `qwen3.5:4b-q4_K_M` |
| `uncensored` | 번역·창작 | `prutser/…ara-abliterated:Q4_K_S` | `hf.co/TrevorJS/…:Q8_0` | `huihui_ai/qwen3-abliterated:8b` |
| `office` | 요약·보고서·스캔본 | `gemma4:26b-a4b-it-qat` | `gemma4:12b` | `qwen3.5:4b-q4_K_M` |
| `balanced` | 일상 대화 | `gpt-oss:20b` | `gemma4:12b` | `qwen3.5:4b-q4_K_M` |

이 표의 **사다리 기본 모델(primary)**은 기본 설치 모델과 다릅니다. 예를 들어
에이전트 상단 QAT 모델은 고급 선택에서만 받으며 기본 설치 시에는
이미 받은 중 단계 `gemma4:12b`를 다른 역할과 공유합니다.

### Gemma 4 를 어디에 두었나

Gemma 4는 사무·범용·에이전트에 공통 활용합니다. QAT 모델은 정식
도구 호출/멀티모달을 지원하지만 실제 Open Interpreter 통합 검증이
필요합니다. Abliterated ARA 모델은 Ollama 배포 페이지상 **텍스트 입력
전용**이므로 기본 에이전트나 문서 OCR 사다리에는 넣지 않았습니다.
코딩은 Devstral과 Qwen 계열을 중심으로 배치합니다.

`gemma4:31b`는 기본 20GB 모델 예산에서 실행 여유가 부족할 수 있어
기본 후보에서 제외합니다.

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
무검열 · 중 (수동 선택 후보 포함)
  ★ TrevorJS Gemma 4 12B Q8_0    12.7GB · 기본 권장
  · Huihui Qwen3.5 Abliterated 9B   7.0GB · 튜닝 후보
  · Huihui Qwen3 Abliterated 14B    9.0GB · 이전 추천 유지
```

이름·크기는 카탈로그 기준이며, 실제 선택은 현재 여유 메모리와 설치
여부에 따라 달라집니다.

**후보에서 뺀 것**과 이유:

| 모델 | 왜 안 넣었나 |
| --- | --- |
| `codestral:22b` | FIM 자동완성 특화. 네이티브 도구 호출이 없어 Open Interpreter 역할에 못 쓴다 |
| `deepseek-coder-v2:16b` | 160K 컨텍스트는 매력적이지만 도구 호출이 없다(제3자 파인튜닝판만 있음) |
| `llama3-groq-tool-use:8b` | BFCL 89.06 으로 자체 호스팅 최고점이지만 컨텍스트가 8K. 도구 결과로 컨텍스트를 쓰는 이 에이전트엔 부족 |
| `gemma4:31b` · `qwen3-vl:32b` | 적재 상한 18.4GB 초과 — 이 예산에선 절대 안 뜬다 |

공용 `models\.localai\registry.json` 은 현재 역할 키(`coding`, `agent`, `uncensored`, `office`, `balanced`)만 허용합니다.
알 수 없는 역할 키는 조용히 적용하지 않고 오류로 표시합니다.

### 기본 권장 모델 세트

`model_catalog.plan_by_level()`는 GPU 정보를 알 수 없을 때 기본 예산 20GB에서 **상 2종 + 중 3종 = 총 5종**만
권장합니다. 전용 GPU가 감지되면 VRAM 안전 여유를 제외한 범위로 기본 권장 세트를 제한하고 LLMfit의 모델 적합도 정보를 보조적으로 반영합니다. 하 단계는 모델 관리 화면에서 선택할 수 있지만 자동으로
설치하거나 기존 파일을 지우지 않습니다.

| 등급 | 모델 | 카탈로그 다운로드 크기 합계 |
| --- | --- | ---: |
| 상 | `devstral-small-2:24b`, `prutser/…ara-abliterated:Q4_K_S` | 약 30.0GB |
| 중 | `qwen2.5-coder:14b`, `gemma4:12b`, `hf.co/TrevorJS/…:Q8_0` | 약 29.3GB |
| 하 | 기본 설치 없음 (수동 선택 가능) | 0GB |
| **합계** | **5종 (기존 기본 10종에서 축소)** | **약 59.3GB** |

다운로드 양은 모델 카탈로그의 추정치이며, Ollama blob 공유와 실제
업스트림 태그 변경에 따라 달라질 수 있습니다.

`RUN.bat --manage`의 **Models → 설치 · 모델 관리** 화면에서 최종 선택을
확인하고 적용합니다. 저장된 모델이 기본 5종에서 빠지더라도
`권장 세트` 버튼은 기존 설치를 자동 삭제하지 않습니다.

**사무·문서 중간 OCR 특화 추천:** `qwen3-vl:8b-instruct`
(공식 Ollama Qwen3-VL 8B Instruct, 기본 Q4_K_M 약 6.2GB)를 추천 카드로
표시합니다. 기존 범용 중간 기본 `gemma4:12b`와 병렬로 보이지만
**체크하지 않으면 다운로드되지 않으며 기본 5종에는 포함되지 않습니다.**
`qwen3-vl:8b`는 추천 카탈로그에서 제거했습니다. 이미 설치되어 있다면
별도의 '설치된 모델' 영역에서 계속 확인·관리할 수 있습니다.
설치 후 실제 역할 선택은 기존 `TIERS` 사다리가
담당하므로, Gemma 4 12B 등이 설치되어 있다면 일반 사무 요청에서
Qwen3-VL이 자동 선택된다는 뜻은 아닙니다. **이미지 첨부를 감지해
OCR 전용 모델로 분기하는 기능은 이번 변경에 포함되지 않습니다.**

해당 비전 모델은 Ollama 0.12.7 이상을 요구합니다. 256K는 지원 컨텍스트의
최댓값으로, 6.2GB 파일이 곧 VRAM 사용량이라는 뜻은 아닙니다.
스캔 문서, 표, 한글 OCR 성능은 실제 샘플과 목표 장비에서 검증해야 합니다.

**간소화한 선택 후보:** 코딩 상 단계 대안은 `gpt-oss:20b`(16GB 카드의 GPU 예산 안)와
실험 대안 `hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ4_XS`(14.4GB, OpenAI 호환 엔드포인트의
도구 호출 응답을 설치 후 직접 확인해야 하며 다른 상 단계 코더가 없을 때만 선택됨),
무검열 중간급 대안은 `huihui_ai/qwen3-vl-abliterated:8b`를 유지합니다.
같은 구간에서 역할이 겹치던 18GB 급(`qwen3.6:27b`, `gemma4:26b`, `qwen3-coder:30b`,
무검열 26~27B)과 9B 급·경량 후보는 카탈로그 v8 에서 뺐습니다.
동일한 용도의 유사 모델이나 별도 검증이 필요한 모델은 추천 목록에서
제외하며, 이미 설치된 모델 파일은 자동으로 삭제하지 않습니다.

### 목록을 직접 찍어 보기

문서에 표를 베껴 두면 카탈로그와 갈라집니다. 목록이 필요하면 항상 이걸 찍으세요.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m launcher.models            # 지금 여유 메모리 기준 전체 후보군
python -m launcher.models --plan     # 상·중 기본 5종만
python -m launcher.models --free 12  # 여유 12GB 를 가정
```

### 배선 검증

`src/tests/test_model_pipeline_e2e.py` 가 가짜 `ollama.exe` 로 진짜 저장소
레이아웃(내용 해시 blob + OCI manifest)을 만들어 놓고 사슬 전체를 한 번에 지납니다.

```text
상·중 기본 계획 -> Models 화면의 선택 적용 -> OLLAMA_MODELS 경로에 pull
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
(`prutser/...:Q4_K_S`, `hf.co/TrevorJS/...:Q8_0`).
Ollama 가 돌려주는 이름과 대소문자만 달라도 그대로 비교하면 멀쩡히 깔린 15GB 짜리를
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
- **user_data**: 설정, 세션, AnythingLLM 데이터 등 계정별 영속 데이터
- **logs**: 실행 로그와 Agent trace를 모으는 계정별 로그 폴더

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

Agent 세션마다 `C:\\LocalAI\\users\\<계정>\\logs\\agent_trace_*.jsonl` 이 하나 생성됩니다
(Windows에서는 줄마다 이 계정의 키로 암호화 — `RUN.bat --records`로 봅니다).
**Setup / Repair → 유지보수 → [기존 설정]** 의 로그 기록을 끄면 프롬프트·모델 출력·
명령·도구 인자 같은 세부 입출력이 기록되지 않습니다(수명주기와 실패 원인은 계속 남습니다).
비밀값은 항상 마스킹되며, 오래된 트레이스 파일은 자동으로 정리됩니다.

실행마다 `C:\\LocalAI\\users\\<계정>\\logs\\launcher_<시각>.log` 도 하나 생깁니다. 데스크톱 셸이 종료
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


## Tools — 구조 보존형 파일 번역 (Studio)

Studio 사이드바의 **Tools**는 부가 기능 목록입니다. 목록에서 **파일 번역**을 열어 TXT / JSON / Markdown / SRT / VTT를 번역합니다. (도구 추가는 `src/apps/shared/tools_view.py`의 `TOOLS`에 한 줄을 더합니다.)
번역 MCP 서버를 별도 설치할 필요 없이 기존 **로컬 Ollama 모델**을 선택합니다. 외부 Ollama cloud 태그는 허용하지 않습니다.

### 사용 방법

1. **[파일 선택…]** 또는 **[폴더 선택…]**을 누릅니다. 바로 분석이 끝나고, 결과가 생길 위치가 화면에 표시됩니다.
   - 파일: 원본 옆 `이름.ko.txt`. 같은 이름이 이미 있으면 `이름.ko (2).txt`처럼 번호를 붙여 새로 만들고, 덮어쓰지 않습니다.
   - 폴더: 원본 옆 `폴더이름.ko` 폴더. 구조와 파일 이름은 원본 그대로입니다.
2. **번역 언어**와 **모델**은 지난번 선택으로 채워집니다. 처음에는 한국어와, 설치된 모델 중 번역에 무난한 모델이 자동으로 골라집니다(코딩·임베딩 전용 모델 제외).
3. **[번역 시작]**을 누릅니다. 진행률·남은 시간·현재 파일이 맨 위에 표시되고, 끝나면 **[결과 열기]**로 결과 위치를 엽니다.

원문 언어, 콘텐츠 유형, 번역 목적, 결과 위치, 폴더 맥락 공유, 이어하기, 원문 유지, 정밀 모드, 고정 용어집은 **고급 설정 ▸** 안에 접혀 있습니다. 기본값만으로 충분합니다. 모델, 언어, 고급 설정, 펼침 상태, 고정 용어집, 마지막으로 연 위치는 바꾸는 즉시 저장되고 다음에 열 때 그대로 채워집니다.

### 원본 데이터 보호 (게임·시스템 데이터)

- **제어 코드:** RPG Maker 같은 게임·메시지 제어 코드(`\N[2]`, `\V[23]`, `\C[4]`, `\I[64]`, `\FS[24]`, `\.`, `\|`, `\!`, `\>` 등)는 보호 토큰으로 바꿔 모델이 바꿀 수 없게 합니다. 번역문에서 `\`가 사라지거나 `/`가 새로 생기면 받지 않습니다.
- **시스템 태그와 내부 식별자:** 다음은 번역하지 않습니다. `[SCENE 01]`처럼 태그만 있는 줄도 번역 대상에서 뺍니다.
  - 태그: `[SYSTEM]`, `[SCENE 01]`, `[BGM:battle1]`
  - 대문자 식별자: `PENDING_REVIEW`, `MAX_HP`, `MK-04`
  - 설정 값: `status=PENDING_REVIEW`, `archive_session=MK-04`
- **번역 허용 예외:** 고정 용어집에 직접 넣은 식별자는 번역합니다. 계획 단계에서 정한 용어집의 식별자는 문장 속 고유명사로만 쓰였을 때 번역합니다(예: `the LUMEN_PROJECT team`). `status=…`, `状態: …`, `[…]`, JSON 값 전체처럼 시스템 값 자리에 한 번이라도 쓰였으면 계속 보호합니다.
- **화자 이름표:** `ハロルド：` 같은 대사 앞 이름이 번역 언어가 쓰지 않는 문자일 때 이름을 따로 번역합니다(문서당 요청 1회, 같은 이름은 항상 같은 번역). 이름이 원문 글자로 남지 않습니다.
- **추출 텍스트의 키와 인자:** `[BTL_001.enemy]`, `[MENU_001.help]` 같은 줄머리 키, `[祭りの手掛かり_01]=ON` 같은 스위치 키, `%1`·`%2`(RPG Maker 인자), `%0.3f`(printf), `%%TOKEN%%`, `\\N[n]`처럼 역슬래시가 겹친 코드를 보호합니다. 식별자 바로 뒤에 한중일 글자가 붙어도(`CELOG-001を`) 보호합니다.
- **한중일 원문 문서의 라틴 토큰:** 원문이 일본어·중국어·한국어인 문서에서는 라틴 문자가 든 토큰(필드명 `frame_id`, 장비·버전 `Nereid-C4`, `HX-TLM/2.6`, `R3.2`, 상태값 `HOLDOVER`, 단위 `μGal`, `m/s²`, `0x04`)을 모두 원형 그대로 둡니다.
- **`json` 코드 블록:** TXT·MD 안의 ```` ```json ```` 코드 블록은 JSON 규칙을 따릅니다. 키, 불리언, 숫자, 식별자 값은 그대로 두고 설명 문장 값만 번역합니다.
- **RPG Maker MV/MZ JSON:** 화면에 보이는 문장만 번역하고, 게임 동작에 쓰이는 값은 건드리지 않습니다.
  - 번역: 대사(401·405), 선택지(102·402), 화자 이름(101), 이름 변경(320·324·325)
  - 그대로 둠: 스크립트(355·655), 플러그인 명령(356·357), 주석(108·408), 그림·소리 파일 이름, `note` 메타데이터
- **응답 오염 차단:** 모델 응답은 `{id, text}` 구조로 받아 id로 맞춥니다. 번역문 안에 `id: 0, text:` 같은 요청 형식이 섞이면 무조건 거부합니다(검토 표시로 넘기지 않음). 끝까지 실패하면 원문을 유지합니다.
- **화자명 중복 제거:** 모델이 대사 앞에 화자 이름표를 덧붙이면 걷어냅니다.
- **저장 직전 문서 전체 검사:** 원문과 번역문의 제어 코드·태그·변수·식별자 목록이 하나라도 다르면 결과를 저장하지 않습니다.
- **용어 일관성 보정:** 이미 정해진 한중일 인명·용어와 다르게 옮긴 구간은 다시 요청합니다. 용어가 정해지기 전에 번역된 구간은 마지막에 그 용어를 넣어 한 번 더 번역하고, 실패하면 기존 번역을 유지합니다.
- **용어 일관성:** 모델이 처음 옮긴 고유명사·용어(`new_terms`)를 문서 메모리에 쌓아 이후 배치와 폴더의 다음 파일에서 같은 번역을 쓰게 합니다. 원문과 번역문에 실제로 있는 것만, 최대 240개까지 쌓습니다. 배운 용어는 체크포인트에 바로 저장해 중단·재개 후에도 유지됩니다.

### 추출·전달과 최종 검수

- **같은 문장은 한 번만 번역:** 보호 처리 후 똑같은 구간은 한 번만 모델에 보내고 나머지는 그 번역을 재사용합니다. 테스트 데이터셋 기준 전체의 10%(CommonEvents는 54%)가 이에 해당하고, 반복되는 대사·메시지의 표기가 자동으로 통일됩니다.
- **구조에서 얻은 문맥 전달:**
  - RPG Maker JSON의 대사(401)에는 직전 대화 시작(101)의 화자를 붙입니다.
  - 아이템 설명, 퀘스트 문장, 이벤트 대사에는 소속 항목 이름(`name`, `title`, `displayName`)을 붙입니다.
  - 추출 TXT는 파일 맨 위 `#` 주석이 아니라 가장 가까운 구획 줄(`===== [BTL_001] 廃機関区 =====`)을 절 문맥으로 씁니다.
- **최종 원문 대조 검수:** 저장 직전에 모델 없이 계산만으로 원문과 번역문을 줄 단위로 대조합니다. 확인 항목은 다음과 같습니다.
  - 번역 안 된 줄(원문과 같음)
  - 원문 문자 잔류나 다른 언어 단어 섞임
  - 정해진 인명·용어와 다른 표기
  - 이 문서의 원문 대비 번역문 길이 비율(중앙값)에서 크게 벗어난 줄: 30% 미만이면 잘림, 3.5배 초과면 덧붙임 의심
- **반려와 수정:** 문제가 있는 줄만 반려해 사유를 붙여 한 번 더 번역합니다. 다시 번역한 결과도 검수를 통과해야 채택하고, 고쳐지지 않으면 기존 번역을 두고 "확인 필요"로 보고합니다.
- **결과 표시:** 상태 줄과 검토 탭에 재사용 수, 자동 수정 수, 확인이 필요한 줄 번호와 사유가 나옵니다.
- **병렬 LLM 검수를 넣지 않은 이유:** 구간마다 LLM 검수를 병렬로 돌리는 방식은 기본으로 쓰지 않습니다. 로컬 Ollama는 GPU 하나를 나눠 쓰므로 병렬로 보내도 전체 속도가 늘지 않고, 같은 모델이 검수하면 같은 약점을 공유하며, 비용이 두 배가 됩니다. 배치마다 저장 전에 하는 기계 검증과 마지막 원문 대조로 의심 줄만 골라 다시 번역합니다.

### 메모리·처리 최적화

- **분석 결과 재사용:** 분석 결과(유형·구간 수·표본·고유명사)는 파일 크기와 수정 시각 기준으로 기억합니다. 분석 뒤 [번역 시작]을 누르면 폴더를 다시 읽지 않습니다(40개×1MB 폴더에서 약 11초 → 0초).
- **폴더 메모리 생성:** 문서 전문을 들고 있지 않습니다. 파일당 표본 30개와 고유명사 상위 200개만 남기므로, 40개×1MB 폴더의 최대 메모리 사용량이 약 284MB에서 34MB로 줄었습니다.
- **폴더 결과:** 번역문 전문은 파일로 저장하고, 화면용으로는 앞부분 미리보기만 남깁니다.
- **반복 확인 줄이기:** Ollama 준비 여부와 모델 확인은 60초 동안 다시 묻지 않습니다(폴더 번역 중 파일마다 반복하지 않음).
- **모델 재적재 방지:** 문맥 창 크기(`num_ctx`)를 작업 시작 때 가장 큰 배치에 맞춰 정하고(기본 12,288, 정밀 모드 20,480) 작업 내내 한 값으로 유지합니다. 이 값이 바뀌면 Ollama가 모델을 다시 올리므로(수 초~수십 초), 계획·요약·번역 요청이 모두 같은 값을 씁니다. `keep_alive`를 30분으로 지정해 파일 사이나 잠깐 쉬는 동안 모델이 내려가지 않게 합니다.
- **요청 수 줄이기:** 한 요청에 담는 구간을 최대 20개로 늘렸습니다(글자 수 상한 2,600자는 그대로). 자막처럼 짧은 줄이 많은 파일은 요청 수가 절반으로 줄었습니다.
- **프롬프트 캐시:** 지시문은 작업 내내 같게 두고, 배치마다 바뀌는 내용은 뒤쪽에 두어 Ollama가 앞부분 계산을 재사용하게 합니다.
- 번역문을 생성하는 양 자체는 줄이지 않았으므로 번역 품질과는 무관한 최적화입니다.
- **작업 기록 정리:** 폴더 작업 기록은 파일별 기록 개수 정리 대상에서 빼서 진행 중에 지워지지 않게 했습니다.

### 폴더 번역

**[폴더 선택…]**으로 폴더를 고르면 하위 폴더까지 모든 TXT·JSON·MD·SRT·VTT를 번역합니다.
- **결과 위치:** 결과는 원본 옆의 `폴더이름.언어코드` 폴더(예: `docs` → `docs.ko`)에 만듭니다. 폴더 구조와 파일 이름은 원본 그대로이고, 결과 폴더는 직접 고를 수도 있습니다.
- **번역하지 않는 파일:** 그림 같은 다른 파일과 이미 번역 언어로 된 파일은 그대로 복사해 결과 폴더를 완성합니다.
- **건너뛰는 항목:** 숨김 파일·폴더와 바로가기(심볼릭 링크)는 건너뜁니다.
- **실패와 중단:** 파일 하나가 실패해도 나머지는 계속 번역하고, 완료 후 파일별 결과(번역·건너뜀·실패·검토 필요 줄)를 보여 줍니다. Ollama 연결 끊김처럼 모든 파일에 해당하는 오류가 나면 즉시 멈춥니다.
- **이어서 하기:** 다시 실행하면 결과 폴더에 이미 있는 파일은 건너뛰고 남은 파일만 번역합니다. 중간에 멈춘 파일은 체크포인트에서 이어서 번역합니다.
- **한도:** 한 번에 최대 2000개 파일까지 번역합니다.
- **폴더 전체를 한 작품으로 번역 (기본 켬):** 소설의 장, 대본 회차, 문서 묶음처럼 이어지는 파일들을 하나의 맥락으로 번역합니다.
  - 폴더 전체의 분산 표본과 모든 파일에서 반복되는 고유명사로 **폴더 메모리**(요약, 문체, 용어집, 인물 말투)를 한 번 만들고, 모든 파일이 이것을 함께 씁니다. 같은 이름은 모든 파일에서 같은 번역이 됩니다.
  - 파일은 이름의 자연 순서(`1장 → 2장 → 10장`)로 번역합니다. 각 파일이 끝나면 그때까지의 줄거리를 요약해 다음 파일로 넘깁니다(파일당 요청 1회). 앞 파일의 마지막 번역 문장도 다음 파일 첫머리의 문맥으로 넘깁니다.
  - 중단 후 다시 실행해도 폴더 메모리와 줄거리 흐름을 이어 씁니다.
  - 끄면 파일마다 따로 메모리를 만들어 번역합니다. 서로 관계없는 파일 묶음에 쓰세요.
  - 고정 용어집은 두 방식 모두 모든 파일에 적용됩니다.

### 줄바꿈·코드·변수 보존

- **줄바꿈:** 줄 단위로 번역하고 줄 사이 공백, 들여쓰기, 줄끝 공백, CRLF는 원문 그대로 둡니다. JSON 문자열 안의 `\n`도 유지합니다.
- **코드:** 다음은 모델에 보내지 않습니다.
  - Markdown: 코드 블록(```), 들여쓴 코드 블록, 여러 줄 HTML 주석
  - TXT: 셸 명령(`&&`, `./`, `--옵션` 포함), JSON `"키": 값` 줄
- **변수·서식:** 아래 항목은 보호 토큰으로 바꿔 모델이 바꿀 수 없게 합니다.
  - 인라인 코드, URL, 이메일, HTML 태그와 주석, 엔터티
  - 변수: `{x}`, `{{x}}`, `${x}`, `%s`, `%1$s`, `%(x)s`, `%{x}`, `:name`, `@:key`, `$t(x)`, `[[x]]`, `{0}`, `<0>…</0>`
  - ICU 선택자(`{n, plural, one {…} other {…}}`): 안쪽 문장만 번역합니다.
  - Markdown 링크 대상, 각주 `[^1]`, 참조 정의 라벨 `[id]:`, 수식 `$…$`
  - 자막 서식 `{\an8}`, 파일 경로
- **번역 후 검증:** 보호 토큰 밖의 `{ } [ ] < > ** ~~` 개수가 번역 전후로 같아야 합니다(굵게·취소선이 사라지는 것 방지). 다르면 다시 요청합니다.
- **알려진 한계:** 머리말(front matter) 내용은 번역하지 않습니다. 코드 블록 안의 주석도 번역하지 않습니다.

### 지원 언어

- **번역 언어(14):** 한국어, English, 日本語, 简体中文, 繁體中文, Español, Français, Deutsch, Português, Italiano, Русский, Tiếng Việt, ไทย, Bahasa Indonesia.
- **원문 언어:** 기본은 자동 감지(문자 체계와 기능어 빈도)이며 직접 고를 수도 있습니다. 위 언어 외에 아랍어·히브리어·힌디어·그리스어·우크라이나어도 원문으로 감지합니다. 오른쪽에서 왼쪽으로 쓰는 언어는 화면 표시 문제로 번역 언어 목록에서 뺐습니다.
- 원문과 번역 언어가 같으면 시작하지 않습니다. 언어 추가는 `src/services/tools/languages.py`의 `LANGUAGES`에 한 줄을 더하면 목록·감지·검사·출력 파일 접미사에 함께 반영됩니다.
- **언어쌍과 무관한 번역문 검사:** 특정 언어쌍 규칙이 아니라 문자 체계와 원문과의 유사도로 판단합니다.
  - 번역 언어가 쓰지 않는 문자가 남았는지 봅니다(가나, 한자, 키릴, 태국 문자 등).
  - 간체/번체가 섞였는지 봅니다.
  - 원문에 없던 다른 언어 단어가 섞였는지 봅니다.
  - 같은 라틴 문자끼리 번역할 때 원문 기능어(the, der, mon 등)나 원문 단어가 남은 부분 미번역을 잡습니다.
  - 원문을 거의 그대로 돌려준 줄을 잡습니다.
  - 원문의 숫자가 바뀌거나 빠졌는지 봅니다.
  - 명령어, 파일명, 도메인(`docker compose`, `config.yaml`, `example.com`), 대문자로 시작하는 이름·상표는 번역하지 않아도 정상으로 봅니다.

### 번역 품질 보조 (인명·동음이의어·관용구)

- **원문 언어 감지와 언어쌍 지침:** 모든 언어쌍에 공통 규칙(이름은 원어 발음, 관용구는 뜻, 숫자 유지, 말투 일관)과 원문 언어별·번역 언어별 주의점을 보냅니다. 일본어→한국어 등은 인명을 원어 발음으로 적기, 한자어 동음이의어는 문맥상 뜻으로 고르기, 관용구는 뜻으로 옮기기, 전문(伝聞)/추측 구분 유지 같은 지침을 함께 보냅니다. 고전 일본어 표지가 보이면 고전 의미로 해석하도록 알립니다. 지침에는 오류 **유형**만 넣고 특정 문장의 정답은 넣지 않습니다.
- **기계적 오류 자동 검출·재시도:** 번역문에 가나·원문 한자가 남거나(`会場까지`), 원문에 없던 영어 단어가 섞이거나(`장비 nearby`), 모델이 보호 토큰 모양을 흉내 낸 가짜 토큰(`__LOCALAI_KEEP_계산_0000__`)을 만들면 다시 요청합니다. 끝까지 일부 단어만 남은 줄은 받아들이되 **검토 필요 줄**로 알려 줍니다.
- **줄머리 시간표시**(`[00:01:23.456]`, `00:01:23,456`)는 번역 대상에서 빼고 그대로 보존하며, 이런 줄이 많으면 자막 유형으로 감지합니다.
- **일본어 인명 후보 추출:** 경칭(さん·先生 등)이 붙거나 문장 첫머리에서 조사가 붙어 반복되는 한자·가타카나 이름을 용어집 후보로 모델에 전달합니다(이전에는 라틴 문자 이름만 추출).
- **고정 용어집(사용자 입력):** 한 줄에 `원문 = 번역`(예: `佐藤 = 사토`, `記述 = 서술`). 입력한 용어는 반드시 지켜야 하며, 지키지 않은 응답은 재시도합니다. 용어집을 바꾸면 이어하기 기록과 별도의 새 작업으로 처리합니다.
- **정밀 모드:** 모델의 추론(thinking)을 켜서 관용구·뉘앙스를 한 번 더 검토하게 합니다. 지원 모델에서만 동작하며 여러 배 느립니다.
- 관용구·뉘앙스·고전 표현의 정확도는 결국 **모델 능력**에 크게 좌우됩니다. 소형 모델에서는 지침만으로 한계가 있으니 중요한 문서는 큰 모델·정밀 모드를 권장합니다.

### 긴 문서 및 메모리 관리

- 입력 상한 **32MiB**, 작업당 처리 구간 최대 **80,000개**입니다. 매우 큰 입력은 조용히 잘라내지 않고 명확한 오류를 반환합니다.
- 긴 단일 문장을 최대 1,400자 단위로 나누고, 최대 10개 구간/약 2,600자씩 **배치 번역**합니다. 모델이 잘못된 JSON을 반환하면 재시도하거나 작은 배치로 분할합니다.
- **Ollama 호출:** 응답을 스트리밍으로 받으므로 느린 CPU·대형 모델도 생성이 이어지는 한 시간 초과로 끊기지 않습니다(토큰 사이 최대 10분). 일시적 연결 오류는 잠시 후 재시도하고, 시간 초과가 반복되면 배치를 반으로 나눕니다.
  요청마다 JSON 출력 형식(`format`), 추론 끄기(`think:false`), 프롬프트 길이에 맞춘 문맥 창(`num_ctx` 4K~16K)과 출력 상한을 지정합니다. 이 옵션을 모르는 구버전 Ollama는 옵션 없이 한 번 다시 요청합니다. 그래도 붙는 `<think>` 블록·`Translation:` 같은 앞말·코드펜스는 걷어냅니다.
- **문서 전역 메모리:** 앞·중간·끝의 분산 표본과 문서 전체에서 반복되는 고유명사를 분석해 문서 요약, 문체, 용어집, 화자 정보를 한 번 만듭니다. 한 번에 전체 원문을 모델에 보내지는 않습니다.
- **진행형 메모리:** 최근 번역 구간과 주기적으로 압축한 줄거리·설명 요약을 다음 번역에 전달합니다. 각 호출에는 현재 구간과 연관된 용어와 화자, 장·절 제목만 선별해 전달합니다. 문맥 길이가 문서 길이와 함께 무한히 늘어나지 않습니다.
- **자동 일관성 검사:** 선택된 고정 식별자 용어와 코드/변수 보호 토큰을 검증합니다. 불일치·빈 번역·과도한 축약·구조 변형은 재시도하거나 오류로 중단하며 결과 파일을 게시하지 않습니다.
- **작업 복구:** Windows 계정별 비공개 `user_data/tools/translation/` 아래 SQLite 체크포인트에 완료 구간·문서 메모리를 저장합니다. Windows에서는 번역 문장과 메모리를 DPAPI(현재 계정 전용)로 암호화해 저장합니다. 동일 파일·내용·설정으로 다시 실행하면 미완료 구간부터 이어집니다. 완료한 작업 기록은 자동 삭제하며, 오래된 미완료 기록은 21일/최대 24개를 기준으로 정리합니다.
- 입력이 번역 중 변경되면 게시를 거부합니다. 결과 파일은 먼저 임시 파일에 완성하고 원본과 별도 경로에 게시합니다.

### 주의 사항

자동 유형 판별과 자유 형식 TXT의 코드 보호는 보수적인 휴리스틱이며 완벽하지 않습니다.
코드/명령 줄 판별은 일반·코드 문서에만 적용하고 **자막·대본·소설에는 적용하지 않습니다**(`if you want it`, `Hello (laughs)` 같은 대사를 코드로 오인하지 않도록). Markdown 제목·하위 목록·표는 번역하고, 목록 밖의 들여쓴 코드 블록·링크 대상 경로·자막 서식 태그(`{\an8}`)는 보호합니다.
JSON은 식별자 성격의 키(`status`, `color`, `userId`, `image_url` 등)와 열거형처럼 보이는 값(`active`, `dark-mode`, `en_US`, `#fff`, 날짜, 버전)을 번역하지 않습니다. 따라서 소문자 한 단어 값(예: `"save"`)은 번역되지 않을 수 있습니다.
`Note:`, `Warning:`, `Step 1:` 같은 라벨은 화자로 보지 않으며, 일본어·중국어 대본의 전각 콜론(`：`)은 화자로 인식합니다. 번역 모델의 표현 품질·인물 말투 일관성도 100% 보장할 수 없습니다. 특히 복잡한 코드/마크업, 자막 길이 제한, 미묘한 문학적 표현은 결과를 검토하세요.
UTF-8(BOM 포함), UTF-16(BOM 포함), CP949 입력을 처리합니다. CP949 입력의 결과는 더 넓은 문자 표현이 가능한 UTF-8로 저장합니다. 한국어로 보이지 않는 레거시 인코딩(Shift-JIS 등)은 깨진 글자를 번역하지 않도록 거부하므로 UTF-8로 저장한 뒤 다시 시도하세요.
모의 모델 회귀 테스트는 `src/tests/test_translation_dataset.py`(번역 테스트 데이터셋 14개 파일을 폴더 단위로 중단 후 재개까지 번역해 무결성·이름 일관성 검증), `src/tests/test_translation_report_regression.py`(테스트 보고서 사례: 일본어 대사 TXT, RPG Maker JSON, UI JSON, 중국어 장문을 중단 후 재개까지 포함해 검증), `src/tests/test_translation_simple.py`, `src/tests/test_translation_long_memory.py`, `src/tests/test_translation_tools.py`에 있습니다. 실제 Windows Tk 및 Ollama 통합 검증은 별도로 필요합니다.

**테스트 작성 원칙: 가급적 아주 간단하게.** 테스트 하나에 동작 하나, 몇 줄짜리 입력, 가짜 모델만 사용합니다(네트워크·실제 Ollama 없음). 복잡한 시나리오는 테스트를 키우기보다 여러 개로 쪼갭니다. 새 번역 테스트는 `test_translation_simple.py`의 형식을 따르세요.

```bash
python -m pytest -q src/tests/test_translation_simple.py
```

이 구현은 번역 MCP 서버와 독립적이며, 추후 필요한 경우 선택적 MCP 어댑터로 확장할 수 있습니다.
