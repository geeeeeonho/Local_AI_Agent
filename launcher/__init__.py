"""launcher — 메뉴 시스템.

리팩토링 v5 구조:
    launcher.config         — 상수
    launcher.presenter.*    — UI 추상화 (TUI/GUI)
    launcher.services.*     — 외부 자원 헬퍼 (Ollama/Docker)
    launcher.actions.*      — 메뉴 액션 (8개로 분할)
    launcher.app            — Application 클래스
    launcher.__main__       — 진입점

호환성:
    launcher.ui, launcher.checkbox, launcher.menu, launcher.handlers,
    launcher.gui 는 모두 shim 으로 동작 (기존 코드 그대로 동작).
"""
