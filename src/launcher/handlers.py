"""handlers — 호환 shim.

신규 코드는 launcher.actions.* 모듈 직접 사용 권장.
기존 `from launcher import handlers; handlers.start_chat(env)` 보존.

각 함수는 내부적으로 TerminalPresenter 인스턴스를 만들어 actions.run() 호출.
"""
from __future__ import annotations

from pathlib import Path

from .presenter.tui import TerminalPresenter
from . import actions
from . import config

# 기존 상수 노출 (handlers.MODEL_TAG 등 외부에서 참조)
MODEL_TAG = config.MODEL_TAG
IMAGE_NAME = config.SANDBOX_IMAGE


def _new_presenter() -> TerminalPresenter:
    return TerminalPresenter()


# ── 메뉴 액션 함수 (기존 시그니처 보존) ──
def start_chat(env: Path) -> None:
    actions.chat.run(env, _new_presenter())


def start_agent_sandbox(env: Path) -> None:
    actions.agent_sandbox.run(env, _new_presenter())


def start_agent_direct(env: Path) -> None:
    actions.agent_direct.run(env, _new_presenter())


def start_ollama(env: Path) -> None:
    actions.ollama_action.run(env, _new_presenter())


def show_model_info(env: Path) -> None:
    actions.model_info.run(env, _new_presenter())


def rebuild_sandbox_image(env: Path) -> None:
    actions.docker_image.run(env, _new_presenter())


def manage_searxng(env: Path) -> None:
    actions.searxng_action.run(env, _new_presenter())


def manage_settings(env: Path) -> None:
    actions.settings_action.run(env, _new_presenter())


__all__ = [
    "MODEL_TAG", "IMAGE_NAME",
    "start_chat", "start_agent_sandbox", "start_agent_direct",
    "start_ollama", "show_model_info", "rebuild_sandbox_image",
    "manage_searxng", "manage_settings",
]
