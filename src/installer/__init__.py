"""installer — `python -m installer` 가 사용하는 설치 모듈들.

구조:
    installer.__main__   — 설치 오케스트레이터 (진입점)
    installer.core.*     — 콘솔/사전검사/다운로드/폴더생성
    installer.utils      — core.* 재노출 shim
    installer.i18n       — 다국어 메시지 (ko/en)
    installer.lang_setup — 언어 초기화
    installer.resources  — 시스템 사양 감지 + 안전 프로필
    installer.steps.ollama — 기존/공식 Ollama 우선 + 포터블 폴백 + serve
    installer.steps.model — 역할별 모델 다운로드 (model_catalog 기반, 멱등)
    installer.steps.python_tools — AnythingLLM 이미지 + Open Interpreter 런타임
    installer.steps.sandbox — Docker 에이전트 이미지 빌드 (멱등)
    installer.steps.searxng — SearXNG 설정 + 이미지 (멱등)
"""
