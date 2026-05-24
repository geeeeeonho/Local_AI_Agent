"""app — Application 클래스 (메인 메뉴 루프).

이전: launcher/menu.py 의 main_loop()
변경: 액션을 dict 로 매핑 → 메뉴 항목 추가가 1줄로 가능.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

from .presenter.base import MenuItem, Presenter
from . import actions


def _build_menu_items() -> list[MenuItem]:
    """메뉴 항목 정의. 추가/삭제는 이 함수만 수정."""
    return [
        MenuItem(
            key="1", title="채팅 UI (Open WebUI)",
            description="브라우저 기반 채팅 + 자동 웹 검색",
        ),
        MenuItem(
            key="2", title="자동화 에이전트 — 샌드박스",
            description="Docker 컨테이너에서 격리 실행",
            badge="권장", badge_kind="good",
        ),
        MenuItem(
            key="3", title="자동화 에이전트 — 호스트 직접",
            description="호스트에 직접 접근. 명시적 확인 필요",
            badge="위험", badge_kind="danger",
        ),
        MenuItem(
            key="4", title="Ollama 서비스 시작/확인",
            separator_above=True,
        ),
        MenuItem(key="5", title="설치된 모델 정보"),
        MenuItem(key="6", title="Docker 이미지 빌드/재빌드"),
        MenuItem(key="7", title="SearXNG 검색 엔진 제어"),
        MenuItem(key="8", title="설정 관리 (보기/초기화/언어)"),
        MenuItem(key="q", title="종료", separator_above=True),
    ]


def _build_action_map() -> Dict[str, Callable]:
    """key -> action.run 매핑. 추가는 이 한 줄만 늘리면 됨."""
    return {
        "1": actions.chat.run,
        "2": actions.agent_sandbox.run,
        "3": actions.agent_direct.run,
        "4": actions.ollama_action.run,
        "5": actions.model_info.run,
        "6": actions.docker_image.run,
        "7": actions.searxng_action.run,
        "8": actions.settings_action.run,
    }


class Application:
    """메뉴 루프를 캡슐화한 진입 클래스."""

    def __init__(self, env: Path, presenter: Presenter):
        self.env = env
        self.p = presenter
        self.items = _build_menu_items()
        self.actions_map = _build_action_map()

    def _last_choice(self) -> str | None:
        try:
            from . import settings_store
            return settings_store.load().last_menu_choice
        except Exception:
            return None

    def _save_last_choice(self, choice: str) -> None:
        try:
            from . import settings_store
            cfg = settings_store.load()
            settings_store.update_last_menu_choice(cfg, choice)
            settings_store.save(cfg)
        except Exception:
            pass

    def run(self) -> None:
        """메인 루프.

        Presenter 가 단일 윈도우 GUI 면 _run_single_window 로 위임,
        그렇지 않으면 기존 메뉴 루프 (TUI / 모달 GUI fallback).
        """
        # 단일 윈도우 GUI 분기
        try:
            from .presenter.gui import TkPresenter
            if isinstance(self.p, TkPresenter):
                return self._run_single_window()
        except ImportError:
            pass

        # 기존 루프 (TUI 등)
        return self._run_loop()

    # ── TUI / 기존 루프 ──
    def _run_loop(self) -> None:
        while True:
            choice = self.p.show_menu(
                title="LLM 환경 실행 메뉴",
                subtitle=f"설치 위치: {self.env}",
                items=self.items,
                last_choice=self._last_choice(),
            )

            if choice in ("q", "quit", "exit"):
                return

            action = self.actions_map.get(choice)
            if action is None:
                continue

            try:
                action(self.env, self.p)
            except KeyboardInterrupt:
                print()
                continue
            except Exception as e:
                self.p.error(f"액션 실행 중 오류: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                self.p.pause()

            self._save_last_choice(choice)

    # ── 단일 윈도우 GUI ──
    def _run_single_window(self) -> None:
        """TkPresenter 의 run_app 으로 메인 루프를 위임.

        사이드바 클릭 → action_runner(key) → 패널 전환 → 결과 표시.
        """
        def action_runner(key: str):
            action = self.actions_map.get(key)
            if action is None:
                return
            action(self.env, self.p)
            self._save_last_choice(key)

        # 상태바 폴러 — 서비스 모듈을 직접 호출
        pollers = self._build_pollers()

        self.p.run_app(
            items=self.items,
            action_runner=action_runner,
            env_path_str=str(self.env),
            pollers=pollers,
        )

    def _build_pollers(self) -> dict:
        """상태바에 붙일 폴러 함수들 (예외 안전)."""
        env = self.env

        def ollama_check():
            try:
                from .services.ollama import OllamaService
                return OllamaService.is_running()
            except Exception:
                return False

        def docker_check():
            try:
                from .services.docker import DockerService
                return DockerService.daemon_alive()
            except Exception:
                return False

        def searxng_check():
            try:
                from .services.docker import DockerService
                from . import config
                return DockerService.container_running(
                    config.SEARXNG_CONTAINER
                )
            except Exception:
                return False

        return {
            "ollama_check": ollama_check,
            "docker_check": docker_check,
            "searxng_check": searxng_check,
        }
