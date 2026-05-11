"""installer.core.filesystem — 환경 폴더 구조 생성."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from .console import section, ok


def create_environment(env: Path) -> Dict[str, Path]:
    """llm_environment/ 트리 생성 후 경로 dict 반환.

    구조:
        env/
        ├── ollama_runtime/  ollama.exe
        ├── llm_models/      *.gguf 모델
        ├── chat_ui/         Open WebUI venv
        ├── agent/
        │   ├── venv/        Open Interpreter
        │   ├── sandbox/     Dockerfile
        │   └── workspace/   호스트<->컨테이너 공유
        ├── searxng/         SearXNG 설정
        ├── scripts/         보조 스크립트
        └── logs/            세션 로그
    """
    try:
        from ..i18n import t
        section(t("install.create_dirs"))
    except Exception:
        section("Creating environment folders")

    paths = {
        "env":       env,
        "ollama":    env / "ollama_runtime",
        "models":    env / "llm_models",
        "chat":      env / "chat_ui",
        "agent":     env / "agent",
        "sandbox":   env / "agent" / "sandbox",
        "workspace": env / "agent" / "workspace",
        "searxng":   env / "searxng",
        "scripts":   env / "scripts",
        "logs":      env / "logs",
    }
    for name, p in paths.items():
        p.mkdir(parents=True, exist_ok=True)
        ok(f"  {name:<10} → {p}")
    return paths
