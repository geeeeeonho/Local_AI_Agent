"""actions.ollama — [4] Ollama 서비스 시작/확인."""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import Presenter
from ..services.ollama import OllamaService


def run(env: Path, p: Presenter) -> None:
    p.section("Ollama Service")

    svc = OllamaService(env, logger=p)
    if svc.is_running():
        p.ok(f"이미 가동 중 (포트 11434)")
        p.pause()
        return

    p.info("시작 중…")
    if svc.ensure_running():
        p.ok("시작 완료")
    else:
        p.error("시작 실패")
    p.pause()
