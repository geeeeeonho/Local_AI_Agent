"""installer — install.py 가 사용하는 모듈들.

리팩토링 v5 구조:
    installer.core.*    — 책임별 분할 (console/preflight/download/filesystem)
    installer.utils     — 호환 shim (모두 re-export)
    installer.i18n      — 다국어 (변경 없음)
    installer.ollama    — Ollama 설치 (변경 없음)
    installer.model     — 모델 다운로드 (변경 없음)
    installer.python_tools — venv 생성 (변경 없음)
    installer.sandbox   — Docker 빌드 (변경 없음)
    installer.searxng   — SearXNG 설치 (변경 없음)
    installer.resources — 시스템 사양 감지 (변경 없음)
    installer.lang_setup — 언어 초기화 (변경 없음)
"""
