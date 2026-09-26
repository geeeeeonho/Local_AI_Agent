"""actions.docker_image — [6] Docker 샌드박스 이미지 빌드/재빌드."""
from __future__ import annotations

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

    try:
        code = DockerService.build_image_stream(
            config.SANDBOX_IMAGE,
            sandbox_dir,
            dockerfile=dockerfile,
            logger=p,
            timeout=1200,
            cancel_check=cancel_check,
        )
        if code == 0:
            p.ok(f"이미지 빌드 완료: {config.SANDBOX_IMAGE}")
        elif code is None and cancel_check():
            p.warn("이미지 빌드가 취소되었습니다.")
        else:
            p.error("이미지 빌드 실패" + ("" if code is None else f" (code={code})"))
    except FileNotFoundError as e:
        p.error(f"docker 명령을 찾을 수 없습니다: {e}")

    p.pause()
