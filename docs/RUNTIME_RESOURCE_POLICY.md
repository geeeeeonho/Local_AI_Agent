# LocalAI 경량 실행 및 메모리·VRAM 정책

> 대상: Windows Studio / Chat / Agent. 모델·데이터 저장 위치와 다중 사용자 보안 정책은 변경하지 않습니다.

## 시작 모드

| 구성요소 | Studio만 실행 | Chat 시작 | Agent 시작 |
|---|---|---|---|
| Tk Studio 및 경량 서비스 객체 | 실행 | 실행 | 실행 |
| Ollama 서버 | 상태 조회만 | 필요 시 실행 | 필요 시 실행 |
| AnythingLLM (Docker) | 시작하지 않음 | 실행 | 시작하지 않음 |
| Agent Host/Sandbox | 시작하지 않음 | 시작하지 않음 | 사용자가 고른 모드에 따라 실행 |
| SearXNG 웹 검색 | 시작하지 않음 | **체크박스 선택 시** 실행 | **체크박스 선택 시** 실행 |
| WARP/Tor 보안 프록시 | 시작하지 않음 | 선택한 네트워크 모드가 요구하면 실행 | 선택한 네트워크 모드가 요구하면 실행 |

**웹 검색**은 기본 선택 해제입니다. Chat 화면과 Agent 화면에서 '웹 검색 엔진도 함께 실행'을 선택하면 다음 시작 시 SearXNG를 준비합니다. 인터넷 검색과 AnythingLLM 내부 문서/RAG 검색은 별개입니다. 웹 검색 기능을 사용할 계획이라면 해당 체크박스를 선택해야 합니다.

**보안 모드에는 영향이 없습니다.** WARP 또는 Tor를 선택했다면 필수 프록시 준비 실패 시 Direct로 우회하지 않습니다. Block 모드에서는 SearXNG를 실행할 수 없습니다. Agent의 Host+Block 제한도 그대로 유지됩니다.

### 세션 종료

- Chat은 소유한 AnythingLLM 컨테이너를 종료하고 사용자가 시작한 SearXNG의 SearchRuntime 종료를 요청합니다.
- Agent가 직접 시작한 SearXNG는 Docker의 **불변 컨테이너 ID**로만 소유권을 기록하고, 모든 Chat·Agent 세션이 종료된 뒤 안전하게 정리합니다. 다른 계정이나 프로세스가 만든 동명의 컨테이너는 종료하지 않습니다.
- Agent 시작 설정을 취소하거나 세션 생성에 실패했을 때도 소유한 검색 컨테이너의 정리를 시도합니다.
- Docker Desktop 자체는 LocalAI가 시작했고 다른 컨테이너를 방해하지 않는 경우에만 종료합니다. 외부에서 이미 실행 중이던 Docker를 강제로 닫지 않습니다.
- Ollama 중계기는 모델 저장소를 공유하므로 다른 Windows 계정의 실행 세션을 고려해 데몬 생명주기를 유지합니다.

## 유휴 GUI 및 상태 점검

- Studio의 Tk 이벤트 검사: 일반 유휴 시 250ms / Agent 진행 시 100ms / 창 종료 대기 시 50ms.
- 상태 확인: Studio 유휴 중 약 60초마다. 화면의 '새로고침'으로 즉시 검사 가능합니다.
- Docker 데몬이 응답하지 않는 경우 컨테이너별 Docker CLI 검사와 이미지 검사를 생략합니다. 확인 불가능한 이미지 설치 상태는 '알 수 없음'으로 보고합니다.
- 모델 목록은 기존처럼 매 초 디스크 전체를 훑지 않습니다. 모델 상세 검사는 명시적 버튼으로 실행합니다.

## Ollama 및 VRAM

- LocalAI가 **직접 시작한** Ollama의 기본 `OLLAMA_KEEP_ALIVE`를 5분에서 **2분**으로 줄였습니다. 사용자가 명시한 `OLLAMA_KEEP_ALIVE` 환경변수는 덮어쓰지 않습니다. 다른 외부 Ollama 서비스 설정은 변경하지 않습니다.
- `OLLAMA_MAX_LOADED_MODELS=1` 기본값은 유지합니다.
- Chat에서 모델을 직접 지정한 경우 선택을 바꾸지 않습니다. 자동 선택일 때만 Ollama `/api/ps`로 **이미 적재된 모델이 없는지 먼저 확인**하고, 비어 있으면 `nvidia-smi`의 VRAM 정보를 참고해 역할 범위 내의 GPU 적재 가능성이 높은 설치 모델을 우선합니다. 하위 모델이 없으면 기존 RAM 기준 선택을 유지합니다.
- GPU를 찾지 못하거나 `/api/ps`가 지원되지 않거나 명령이 실패하면 **이전 RAM 기반 모델 선택으로 복귀**합니다. Ollama 서버가 이미 모델을 적재한 상태에서도 이전 선택을 유지합니다. GPU 정보 때문에 한 번 적재된 모델이 임의로 작은 모델로 바뀌는 문제를 피하기 위함입니다.
- Models → 현재 스택 화면에서는 여유 VRAM과 안전 여유를 제외한 예산을 **추정치**로 보여줍니다. 모델 메모리 추정치와 실제 KV 캐시·컨텍스트·드라이버 오버헤드는 다를 수 있으며, 'GPU 적합' 표시도 적재 성공 보장은 아닙니다.
- VRAM 탐지는 `nvidia-smi`만 호출하며 GPU에 모델을 적재하거나 CUDA 런타임을 올리지 않습니다. 유휴 상태에서 GPU를 반복 검사하지 않습니다.
- AnythingLLM Docker `--memory`는 **최대 사용 상한**이지 시작 시 선할당량이 아닙니다. 기본 상한만 낮추면 OOM 위험이 있으므로 유지합니다.

## 검사

```powershell
# Windows venv 환경에서 의존성 설치 후 수행
$env:PYTHONPATH = "src"
python -m pytest -q src/tests/test_gpu_memory.py src/tests/test_runtime_lightweight.py
python -m pytest -q src/tests

# PC 실제 리소스 비교: Studio만 / Chat+검색 OFF / Chat+검색 ON / 종료 3분 후
Get-Process | Where-Object { $_.ProcessName -match 'python|ollama|docker|vmmem|wsl' } |
  Select-Object ProcessName, Id, @{N='RAM_MB';E={[math]::Round($_.WorkingSet64 / 1MB)}}
& 'C:\LocalAI\ollama\ollama.exe' ps
nvidia-smi --query-gpu=memory.used,memory.free --format=csv
docker stats --no-stream
```

**검증 한계:** GitHub 소스와 격리된 단위 테스트를 기반으로 작성되었습니다. 실제 Windows 다중 사용자, Docker Desktop/WSL2, Ollama, RTX GPU의 상주 메모리와 VRAM 절감량은 테스트 PC에서 전후 측정해야 합니다. 기존 Draft PR #65(개인 데이터 보호)와는 별도 브랜치에서 변경했습니다.
