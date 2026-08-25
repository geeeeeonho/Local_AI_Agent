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
    cmd = ["docker", "build", "-t", config.SANDBOX_IMAGE, str(sandbox_dir)]

    try:
        if _os.name == "nt" and is_gui_env:
            # GUI 모드: 새 콘솔창에서 빌드 (진행률 표시)
            proc = subprocess.Popen(
                cmd, creationflags=config.WIN_CREATE_NEW_CONSOLE,
            )
            p.ok(f"새 콘솔창에서 빌드 진행 중 (PID={proc.pid})")
            p.info("그 창에서 진행률을 확인하세요. 완료되면 닫으면 됩니다.")
        else:
            # 콘솔 모드: 동기 실행
            subprocess.run(cmd, check=True)
            p.ok(f"이미지 빌드 완료: {config.SANDBOX_IMAGE}")
    except subprocess.CalledProcessError:
        p.error("이미지 빌드 실패")
    except FileNotFoundError as e:
        p.error(f"docker 명령을 찾을 수 없습니다: {e}")

    p.pause()
