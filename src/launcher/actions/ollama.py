"""actions.ollama — [4] 관리형 Ollama 서비스 시작/검증."""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import Presenter, RISK_MEDIUM
from ..services.ollama import OllamaService


def run(env: Path, p: Presenter) -> None:
    p.section("Ollama Service")

    # HTTP 응답만으로 정상 판정하지 않는다. ensure_running()이 포트 소유 프로세스와
    # 공용 모델 저장소 상태까지 확인하므로 외부 Ollama를 잘못 정상 표시하지 않는다.
    svc = OllamaService(env, logger=p)
    p.info("관리형 Ollama 상태 확인 중…")
    if not svc.ensure_running():
        p.error("시작/검증 실패")
        p.pause()
        return
    p.ok("관리형 Ollama 준비 완료")

    situation, detail = svc.inspect_store()
    p.info(svc.describe_store())
    if situation != svc.STORE_NOT_READ:
        p.pause()
        return

    # The models are installed and the server cannot see them. Restarting it
    # against the resolved store is the fix, and it is the user's call: it ends
    # a process they did not ask us to end, even one serving nothing.
    held = detail.get('on_disk') or ()
    if not p.confirm_dangerous(
        label="Ollama 를 모델 경로로 다시 시작",
        description=(
            "설치된 모델 %d개가 %s 에 있는데 실행 중인 Ollama 가 그 경로를 읽지 "
            "않습니다.\n\nOllama 는 시작할 때만 OLLAMA_MODELS 를 읽으므로, 다시 "
            "시작해야 이 모델들이 보입니다.\n\n지금 실행 중인 Ollama 를 끄고 이 "
            "경로로 다시 시작할까요?\n(진행 중인 다른 작업이 있다면 함께 끊깁니다.)"
            % (len(held), svc.model_dir)),
        risk=RISK_MEDIUM,
    ):
        p.info("그대로 둡니다. 직접 고치려면 %s 실행 후 Ollama 를 재시작하세요."
               % svc.store_fix_command())
        p.pause()
        return

    if svc.restart_for_store():
        p.ok("이제 모델이 보입니다: " + svc.describe_store())
    else:
        p.error("다시 시작하지 못했습니다. 위 메시지를 확인하세요.")
    p.pause()
