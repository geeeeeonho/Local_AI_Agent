"""actions.agent_direct — [3] 호스트 직접 모드 (위험).

이 모드는 컨테이너 격리 없이 호스트에 직접 접근하므로
사용자에게 명시적 키워드 확인을 요구.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import config
from ..presenter.base import Presenter, RISK_HIGH
from ..services.ollama import OllamaService


def run(env: Path, p: Presenter) -> None:
    p.section("⚠⚠ 호스트 직접 모드 ⚠⚠")
    p.error("이 모드는 호스트에 직접 접근합니다. 매우 위험합니다.")
    p.warn("위험 요소:")
    p.warn("  · 모든 파일 읽기/쓰기/삭제 가능")
    p.warn("  · 시스템 명령 실행 가능 (포맷, 종료 포함)")
    p.warn("  · 네트워크 자유 사용")
    p.warn("  · 격리 없음 — 모델 실수가 PC 에 직접 영향")
    p.info("대안: 메뉴 [2] 샌드박스가 거의 같은 일을 안전하게 합니다.")

    if not p.confirm_dangerous(
        label="호스트 직접 모드 진입",
        description=(
            "에이전트가 호스트 PC 의 모든 파일·명령에 직접 접근합니다.\n"
            "샌드박스 격리가 없어, 모델의 실수가 호스트에 그대로 반영됩니다.\n"
            "복구 불가능한 손상이 발생할 수 있습니다."
        ),
        risk=RISK_HIGH,
    ):
        p.info("취소 (권장: 메뉴 [2] 샌드박스 사용)")
        p.pause()
        return

    # ── Ollama ──
    if not OllamaService(env, logger=p).ensure_running():
        p.pause()
        return

    # ── interpreter 실행 ──
    interp = env / "agent" / "venv" / "Scripts" / "interpreter.exe"
    if not interp.exists():
        p.error(f"Open Interpreter 미설치: {interp}")
        p.pause()
        return

    p.warn("호스트 직접 모드 시작 — auto_run 비활성, 매 명령 y/n 확인")

    new_env = OllamaService(env).env_vars()

    # HOST_TOR_ENV_v1: 인터넷 연결 방식 선택(직접 vs Tor). 기본=직접(기존 동작 유지)
    try:
        from ..presenter.base import MenuItem as _MI
        _netch = p.show_menu(
            title="인터넷 연결 방식",
            subtitle="Tor 경유는 Tor 컨테이너(9050/8118)가 실행 중일 때만 동작합니다.",
            items=[
                _MI(key="direct", title="직접 연결(기본)",
                    description="프록시 없이 직접 인터넷에 연결합니다."),
                _MI(key="tor", title="Tor 경유",
                    description="127.0.0.1:8118 / 9050 프록시로 우회합니다."),
            ],
        )
        if _netch == "tor":
            from ..agent.agent_runner import build_tor_env
            new_env = build_tor_env(new_env)
            p.ok("Tor 프록시 적용됨 (127.0.0.1:8118 / 9050). Tor 가 꺼져 있으면 연결이 실패합니다.")
    except Exception as _ete:
        p.warn("인터넷 방식 선택 생략(기본 직접): %s" % _ete)

    cmd = [
        str(interp),
        "--model", f"ollama/{config.MODEL_TAG}",
        "--api_base", config.OLLAMA_URL,
    ]

    import sys as _sys
    is_gui_env = (_sys.stdout is None or
                  not getattr(_sys.stdout, 'isatty', lambda: False)())
    popen_kw = {"env": new_env}
    if os.name == "nt" and is_gui_env:
        popen_kw["creationflags"] = config.WIN_CREATE_NEW_CONSOLE

    try:
        proc = subprocess.Popen(cmd, **popen_kw)
        if is_gui_env:
            p.ok(f"새 콘솔창에서 호스트 직접 모드가 실행 중입니다 (PID={proc.pid})")
            p.warn("호스트에 직접 접근됩니다. 신중히 사용하세요.")
        else:
            proc.wait()
    except FileNotFoundError as e:
        p.error(f"interpreter 실행 파일을 찾을 수 없습니다: {e}")
    except KeyboardInterrupt:
        pass

    p.pause()
