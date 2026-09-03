"""actions.ollama — [4] 관리형 Ollama 서비스 시작/검증."""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import Presenter
from ..services.ollama import OllamaService


def run(env: Path, p: Presenter) -> None:
    p.section("Ollama Service")

    # HTTP 응답만으로 정상 판정하지 않는다. ensure_running()이 포트 소유 프로세스와
    # 공용 모델 저장소 상태까지 확인하므로 외부 Ollama를 잘못 정상 표시하지 않는다.
    svc = OllamaService(env, logger=p)
    p.info("관리형 Ollama 상태 확인 중…")
    if svc.ensure_running():
        p.ok("관리형 Ollama 준비 완료")
    else:
        p.error("시작/검증 실패")
    p.pause()
