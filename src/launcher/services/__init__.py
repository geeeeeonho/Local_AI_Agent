"""services — 외부 자원 제어 (Ollama / Docker / 시스템).

UI에 무관한 순수 비즈니스 로직.
이전: handlers.py 안에 산재했던 _ensure_ollama, _check_docker_image 등.
"""
from .ollama import OllamaService
from .docker import DockerService

__all__ = ["OllamaService", "DockerService"]
