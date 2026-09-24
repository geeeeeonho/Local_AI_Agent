"""Prepare the Docker image used by the optional Tor network mode."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.progress import LogAdapter
from installer import utils


def install(paths: Dict[str, Path]) -> bool:
    """Ensure the configured Tor image exists; do not start a container."""
    del paths
    try:
        from launcher import config
        from launcher.services.docker import DockerService
    except Exception as exc:
        utils.warn("Tor 설치 구성요소를 불러오지 못했습니다: " + repr(exc))
        return False

    image = str(config.TOR_IMAGE)
    try:
        if not DockerService.ensure_daemon(logger=LogAdapter(utils.info), timeout=90):
            utils.warn("Docker Desktop 미준비 - Tor 이미지 설치를 건너뜁니다.")
            return False
        if DockerService.image_exists(image):
            utils.ok("Tor 이미지 이미 준비됨: " + image)
            return True
        utils.info("Tor 이미지 pull: " + image)
        if DockerService.pull_image(image):
            utils.ok("Tor 이미지 준비 완료: " + image)
            return True
    except Exception as exc:
        utils.warn("Tor 이미지 준비 실패: " + repr(exc))
        return False

    utils.warn("Tor 이미지 pull 실패: " + image)
    return False
