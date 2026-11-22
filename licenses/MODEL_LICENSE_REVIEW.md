# 모델 라이선스 확인 목록

2026-11-22 `src/launcher/models/model_catalog.py`에 등록된 Ollama 후보 **24개**의 식별자입니다. 이것은 다운로드/설치 여부와 무관한 **카탈로그**이며, 아래 모델의 라이선스를 일괄 확정한 목록이 아닙니다.

각 모델에 대해 실제 Ollama 모델 페이지 또는 Hugging Face 리포지터리의 **정확한 태그/리비전**, 기본 모델 라이선스, 재가공 모델의 배포 조건과 NOTICE를 확인해야 합니다. 특히 제3자 `abliterated`/`uncensored`/`GGUF` 모델은 상위 모델 및 파생본의 양쪽 조건을 확인하세요.

| 카탈로그 모델 식별자 | 라이선스 확인 상태 |
| --- | --- |
| `prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen3.6:27b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `gemma4:12b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen2.5-coder:7b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `huihui_ai/qwen3-abliterated:8b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `gemma4:26b-a4b-it-qat` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `gemma4:26b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `gemma4:e2b-it-qat` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `huihui_ai/gemma-4-abliterated:26b-qat` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `huihui_ai/Qwen3.6-abliterated:27b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `huihui_ai/qwen3-vl-abliterated:8b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `mannix/llama3.1-8b-abliterated:q5_K_M` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen3-coder:30b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `devstral-small-2:24b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen3.5:9b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen3.5:4b-q4_K_M` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `ministral-3:14b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `huihui_ai/qwen3.5-abliterated:9b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen2.5-coder:14b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `qwen3-vl:8b-instruct` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `gpt-oss:20b` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `bge-m3:567m` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |
| `nomic-embed-text:v1.5` | 미확인 — 정확한 배포 리비전의 라이선스 확인 필요 |

또한 `src/launcher/config.py`에서 AnythingLLM용 기본 임베딩 모델로 `Xenova/all-MiniLM-L6-v2`를 지정하고 있으므로, 이 모델의 정확한 리비전과 라이선스도 추가 점검해야 합니다.

모델을 내려받아 개인적으로 사용하는 행위와, 가중치 파일을 설치 프로그램에 **동봉·재배포**하는 행위는 구분합니다. 이 프로젝트의 일반적인 Ollama 모델 다운로드 기능은 모델 가중치를 GitHub 저장소에 포함하지 않습니다.
