"""actions — 메뉴 항목별 액션.

각 액션 모듈은 단일 함수 `run(env, presenter, **kwargs)` 를 노출한다.
Presenter 의존만 갖고 UI 종류에 무관하게 동작.
"""
from . import (
    chat,
    ollama as ollama_action,
    model_info, docker_image,
    searxng as searxng_action,
    settings as settings_action,
    agent_chat,
    model_manage,
    docker_clean,
)

__all__ = [
    "chat",
    "ollama_action", "model_info", "docker_image",
    "searxng_action", "settings_action",
    "agent_chat",
    "model_manage",
    "docker_clean",
]
