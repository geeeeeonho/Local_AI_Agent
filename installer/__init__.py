"""installer — `python -m installer` 가 사용하는 설치 모듈들.

구조:
    installer.__main__   — 설치 오케스트레이터 (진입점)
    installer.core.*     — 콘솔/사전검사/다운로드/폴더생성
    installer.utils      — core.* 재노출 shim
    installer.i18n       — 다국어 메시지 (ko/en)
    installer.lang_setup — 언어 초기화
    installer.resources  — 시스템 사양 감지 + 안전 프로필
    installer.ollama     — 포터블 Ollama 설치 + serve
    installer.model      — 역할별 모델 다운로드 (model_roles 기반, 멱등)
    installer.python_tools — Open WebUI / Open Interpreter venv (멱등)
    installer.sandbox    — Docker 에이전트 이미지 빌드 (멱등)
    installer.searxng    — SearXNG 설정 + 이미지 (멱등)
"""
