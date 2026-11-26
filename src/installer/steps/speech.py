"""자막 도구의 음성 엔진(whisper.cpp · ffmpeg · VAD) — 선택형 구성요소.

LLMfit처럼 실패해도 Ollama·Chat·Agent·번역 설치에는 영향을 주지 않는다. 고정 버전과
체크섬 검증은 integrations.speech.install이 맡고, 여기서는 설치 흐름에 연결만 한다.
음성 인식 모델(수백 MB~3GB)은 설치기에서 받지 않고 Tools → 자막 만들기에서 관리자가 고른다.
"""
from __future__ import annotations

from pathlib import Path

import project_paths


def install(paths, *, log=None):
    from integrations.speech import install as speech_install
    return speech_install.install(project_paths.speech_engine_dir(Path(paths["env"])), log=log)
