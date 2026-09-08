"""actions.docker_image — [6] Docker 샌드박스 이미지 빌드/재빌드."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config
from ..presenter.base import Presenter
from ..services.docker import DockerService


def run(env: Path, p: Presenter) -> None:
    p.section("Docker 샌드박스 이미지 빌드")

    sandbox_dir = env / "agent" / "sandbox"
    dockerfile = sandbox_dir / "Dockerfile"

    if not dockerfile.exists():
        p.error(f"Dockerfile 없음: {dockerfile}")
        p.warn("install 을 다시 실행하세요")
        p.pause()
        return

    cancel_check = getattr(p, "is_cancelled", lambda: False)
    if not DockerService.ensure_daemon(
        logger=p, timeout=60, cancel_check=cancel_check,
    ):
        p.pause()
        return

    p.warn("빌드 시작 (5~10분 소요)…")

    import os as _os, sys as _sys
    is_gui_env = (_sys.stdout is None or
                  not getattr(_sys.stdout, 'isatty', lambda: False)())

    try:
        if _os.name == "nt" and is_gui_env:
            # GUI 모드에서는 사용자가 진행률을 볼 수 있도록 새 콘솔만 presentation
            # 계층에서 유지한다. 일반 build primitive는 DockerService가 소유한다.
            cmd = ["docker", "build", "-t", config.SANDBOX_IMAGE, str(sandbox_dir)]
            proc = subprocess.Popen(
                cmd, creationflags=config.WIN_CREATE_NEW_CONSOLE,
            )
            p.ok(f"새 콘솔창에서 빌드 진행 중 (PID={proc.pid})")
            p.info("그 창에서 진행률을 확인하세요. 완료되면 닫으면 됩니다.")
        else:
            result = DockerService.build_image(
                config.SANDBOX_IMAGE,
                sandbox_dir,
                dockerfile=dockerfile,
                capture_output=False,
            )
            if result is None or result.returncode != 0:
                p.error("이미지 빌드 실패")
            else:
                p.ok(f"이미지 빌드 완료: {config.SANDBOX_IMAGE}")
    except FileNotFoundError as e:
        p.error(f"docker 명령을 찾을 수 없습니다: {e}")

    p.pause()
