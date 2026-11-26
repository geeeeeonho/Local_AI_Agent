# 제3자 소프트웨어 및 라이선스 고지

이 문서는 **Local_AI_Agent**의 소스 코드 및 설치/실행 경로에서 확인한 외부 소프트웨어의 라이선스를 안내합니다. 2026-11-22 기준 `main` 코드의 참조·기본값을 조사한 결과이며, 사용자 PC에 실제 설치된 프로그램이나 Docker 이미지/모델의 전체 의존성 목록(SBOM)을 보증하지 않습니다.

이 폴더의 LICENSE 파일은 각 프로젝트의 원문을 유지합니다. **이 파일들의 라이선스가 곧 Local_AI_Agent 자체의 라이선스라는 뜻은 아닙니다.** 프로젝트 자체의 라이선스는 저장소 소유자가 별도로 정해야 합니다.

## 소프트웨어

| 구성요소 | 현재 연결 방식 | 라이선스 | 고지 / 공식 출처 |
| --- | --- | --- | --- |
| Ollama | Windows 공식 설치기 또는 포터블 배포본 | MIT | [ollama-LICENSE](ollama-LICENSE) · [원본](https://github.com/ollama/ollama) |
| AnythingLLM | `mintplexlabs/anythingllm:latest` Docker 이미지 | MIT | [anythingllm-LICENSE](anythingllm-LICENSE) · [원본](https://github.com/Mintplex-Labs/anything-llm) |
| Open Interpreter | `rust-v0.0.38` standalone 실행 파일 및 샌드박스 | Apache-2.0 | [open-interpreter-LICENSE](open-interpreter-LICENSE) · [NOTICE](open-interpreter-NOTICE) · [해당 태그](https://github.com/openinterpreter/openinterpreter/tree/rust-v0.0.38) |
| SearXNG | `searxng/searxng:latest` Docker 이미지 | AGPL-3.0-or-later | [searxng-LICENSE](searxng-LICENSE) · [원본](https://github.com/searxng/searxng) |
| dperson/torproxy | `dperson/torproxy` Docker 이미지 | AGPL-3.0 | [torproxy-LICENSE](torproxy-LICENSE) · [원본](https://github.com/dperson/torproxy) |
| Cloudflare WARP 이미지 | `dublok/cloudflare-warp:latest` Docker 이미지 | CC-BY-NC-4.0 | [cloudflare-warp-LICENSE](cloudflare-warp-LICENSE) · [원본](https://github.com/ErcinDedeoglu/cloudflare-warp) |
| LLMfit | **도입 예정**, 현재 설치/실행 코드에 포함되지 않음 | MIT | [llmfit-LICENSE](llmfit-LICENSE) · [원본](https://github.com/AlexsJones/llmfit) |
| whisper.cpp | 자막 만들기: `v1.9.5` 공식 Windows x64 빌드(CPU, NVIDIA GPU는 CUDA 12.4 빌드). GitHub 자산 SHA-256 digest 검증 | MIT | [whisper.cpp-LICENSE](whisper.cpp-LICENSE) · [해당 태그](https://github.com/ggml-org/whisper.cpp/tree/v1.9.5) |
| FFmpeg | 자막 만들기: 영상·음성에서 오디오 추출. BtbN `autobuild-2026-10-31-12-59`의 **LGPL** Windows x64 빌드(checksums.sha256 + GitHub digest 검증) | LGPL-2.1-or-later | 설치 시 배포본의 LICENSE를 `environment\speech\ffmpeg\LICENSE.txt`로 함께 둡니다 · [빌드](https://github.com/BtbN/FFmpeg-Builds) · [FFmpeg 라이선스](https://ffmpeg.org/legal.html) |
| Silero VAD | 자막 만들기: 음성 구간 감지 모델(whisper.cpp가 변환한 ggml 형식, 고정 커밋·SHA-256) | MIT | [silero-vad-LICENSE](silero-vad-LICENSE) · [원본](https://github.com/snakers4/silero-vad) |

### 독립 실행환경 또는 이용약관이 별도로 적용되는 항목

- **Docker Desktop:** 오픈소스 Docker 구성요소와 달리 Docker Desktop 배포·사용에는 Docker의 별도 구독·서비스 약관이 적용됩니다. 개인 사용과 특정 비상업적 사용의 무료 사용 조건은 공식 약관을 확인하세요. [Docker Subscription Service Agreement](https://www.docker.com/legal/docker-subscription-service-agreement/).
- **Cloudflare WARP 클라이언트와 네트워크 서비스:** 위 CC-BY-NC-4.0은 `dublok/cloudflare-warp` 컨테이너 프로젝트에 대한 고지입니다. 컨테이너 안의 Cloudflare WARP 공식 클라이언트와 서비스에는 별도의 Cloudflare 약관이 적용됩니다. 이미지 라이선스만으로 서비스 이용이 무제한 허용되는 것은 아닙니다. [Cloudflare 약관](https://www.cloudflare.com/website-terms/).
- **Python 3.11 및 샌드박스 운영체제 패키지:** Dockerfile에 `python:3.11-slim`, Debian 패키지(`git`, `curl`, `wget` 등)를 사용합니다. 이 문서는 각각의 시스템 패키지에 포함된 제3자 저작권/라이선스 텍스트를 대신하지 않습니다.
- **음성 인식 모델(Whisper):** 자막 만들기의 `ggml-large-v3*.bin` 등은 OpenAI Whisper 가중치(MIT, [openai-whisper-LICENSE](openai-whisper-LICENSE))를 whisper.cpp 형식으로 변환한 파일이며 Hugging Face `ggerganov/whisper.cpp`에서 받고 whisper.cpp 표의 SHA-1로 검증합니다. 관리자가 Tools → 자막 만들기에서 받을 때만 내려받습니다.
- **FFmpeg LGPL:** LGPL 빌드를 별도 실행 파일로 호출할 뿐 LocalAI 코드와 링크하지 않습니다. 설치 패키지에 FFmpeg를 미리 넣어 재배포하는 경우 LGPL의 소스 제공·고지 의무를 검토하세요.
- **임베딩 모델:** AnythingLLM 설정에는 `Xenova/all-MiniLM-L6-v2`가 기본값으로 포함됩니다. 모델 허브의 해당 리비전 라이선스/NOTICE를 별도 확인해야 합니다.

## 배포 방식에 따른 유의사항

- **MIT/Apache-2.0:** 관련 실행 파일/코드의 재배포 시 저작권·라이선스 표시를 유지하고, Apache-2.0 구성요소의 NOTICE 및 필요한 변경 고지를 보존합니다.
- **AGPL-3.0 계열:** 해당 프로그램을 수정하거나 재배포하거나 네트워크로 제공하는 경우 라이선스의 소스 제공·고지 의무를 검토합니다. 별도 컨테이너로 실행한다는 사실만으로 모든 의무가 면제되는 것은 아닙니다.
- **CC-BY-NC-4.0:** `dublok/cloudflare-warp`는 비상업적 조건에 따라 사용해야 하며, 상업적으로 이용하려면 별도의 허가/대체 구현 검토가 필요합니다.
- **외부 설치와 재배포는 다릅니다:** 설치 프로그램이 실행 중 외부 소프트웨어를 다운로드하는 형태와 프로그램 설치 패키지에 해당 바이너리·이미지를 미리 포함하여 재배포하는 형태는 라이선스 준수 범위가 다릅니다.
- **`:latest` 이미지의 가변성:** 실제로 내려받은 이미지의 버전/다이제스트, 내장 패키지, 제3자 고지는 달라질 수 있습니다. 향후 재배포 시 정확한 이미지를 고정해 별도로 검사해야 합니다.
- 이 목록은 법률 자문이나 모든 전이 의존성에 대한 완전한 라이선스 감사가 아닙니다.

## 모델은 소프트웨어와 별도로 관리

Ollama의 MIT 라이선스는 Ollama로 다운로드하는 **모델 가중치에 자동으로 적용되지 않습니다.** `src/launcher/models/model_catalog.py`의 추천 항목은 설치 완료의 증거가 아니며, 공식 모델, GGUF 재패키징, `abliterated`/파생 가중치에는 서로 다른 조건이 있을 수 있습니다. 모델별 태그·정확한 원본 리비전·라이선스를 확인하기 전까지 **재배포 허가를 일괄 확정하지 않습니다.**

현재 코드에 등록된 모델의 점검 목록은 [MODEL_LICENSE_REVIEW.md](MODEL_LICENSE_REVIEW.md)를 참고하세요.

## 유지보수

새 도구·Docker 이미지·모델을 추가할 때는 다음을 함께 갱신합니다.

1. 원본 저장소/모델 리비전 및 라이선스 종류 확인
2. 재배포 시 필요한 공식 LICENSE·NOTICE 보관
3. 비상업 조건, 소스 공개 의무, 서비스 별도 약관 기록
4. 버전·이미지 다이제스트 및 실제 설치된 전이 의존성의 배포 전 검사
