"""actions — 메뉴 항목별 액션.

각 액션 모듈은 단일 함수 `run(env, presenter, **kwargs)` 를 노출한다.
Presenter 의존만 갖고 UI 종류에 무관하게 동작.

이전: launcher/handlers.py 한 파일에 모든 액션이 들어가 있었음.
"""
from . import (
    chat, agent_sandbox, agent_direct,
    ollama as ollama_action,
    model_info, docker_image,
    searxng as searxng_action,
    settings as settings_action,
)

__all__ = [
    "chat", "agent_sandbox", "agent_direct",
    "ollama_action", "model_info", "docker_image",
    "searxng_action", "settings_action",
]
