"""actions.model_info — [5] 설치된 모델 정보."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import config
from ..presenter.base import Presenter
from ..services.ollama import OllamaService


# Windows pythonw.exe 환경에서 콘솔 깜빡임 차단
_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = config.WIN_CREATE_NO_WINDOW


def run(env: Path, p: Presenter) -> None:
    p.section("설치된 모델 정보")

    svc = OllamaService(env, logger=p)
    if not svc.is_installed():
        p.error(f"Ollama 미설치: {svc.exe}")
        p.pause()
        return

    if not svc.ensure_running():
        p.pause()
        return

    try:
        result = subprocess.run(
            [str(svc.exe), "list"],
            env=svc.env_vars(),
            capture_output=True, text=True, check=False,
            **_NO_WINDOW_KW,
        )
        # 결과를 Presenter 로 전달 (GUI 에선 패널에 표시, TUI 에선 콘솔)
        for line in (result.stdout or "").splitlines():
            if line.strip():
                p.info(line)
        if result.stderr and result.stderr.strip():
            p.warn(result.stderr.strip())
    except Exception as e:
        p.error(f"모델 목록 조회 실패: {e}")

    p.pause()
