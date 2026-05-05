"""searxng_runtime — SearXNG 컨테이너 시작/정지/상태 확인.

run.py 가 채팅 시작 시 자동 호출하거나, 사용자가 메뉴에서 직접 제어.
"""
from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import ui

CONTAINER = "llm_searxng"
IMAGE     = "searxng/searxng:latest"
HOST_PORT = 8888
URL       = f"http://localhost:{HOST_PORT}"


# ───────── 상태 확인 ─────────

def is_running() -> bool:
    """SearXNG 컨테이너가 실행 중인지 + HTTP 응답 가능한지."""
    try:
        # 컨테이너 상태
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or "true" not in r.stdout.lower():
            return False
        # HTTP 응답
        urllib.request.urlopen(URL, timeout=3)
        return True
    except Exception:
        return False


def container_exists() -> bool:
    """이미 만들어진 컨테이너가 있는지 (실행 여부 무관)."""
    try:
        r = subprocess.run(
            ["docker", "inspect", CONTAINER],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def image_exists() -> bool:
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ───────── 시작 / 정지 ─────────

def start(env: Path, quiet: bool = False) -> bool:
    """SearXNG 컨테이너 시작. 이미 실행 중이면 그대로 둠.

    Args:
        env: llm_environment 경로
        quiet: True면 이미 가동 중일 때 메시지 생략

    Returns:
        True if running after this call
    """
    if is_running():
        if not quiet:
            ui.ok(f"SearXNG 이미 가동 중: {URL}")
        return True

    if not image_exists():
        ui.err(f"SearXNG 이미지가 없습니다: {IMAGE}")
        ui.warn("install.py 를 다시 실행하세요")
        return False

    cfg = env / "searxng" / "config"
    if not (cfg / "settings.yml").exists():
        ui.err(f"settings.yml 없음: {cfg / 'settings.yml'}")
        ui.warn("install.py 를 다시 실행하세요")
        return False

    # 기존 컨테이너 (멈춰있는 상태) 가 있으면 start
    if container_exists():
        ui.info("기존 SearXNG 컨테이너 재시작…")
        try:
            subprocess.run(
                ["docker", "start", CONTAINER],
                check=True, capture_output=True, timeout=15,
            )
        except subprocess.CalledProcessError:
            ui.warn("재시작 실패 — 컨테이너 삭제 후 새로 만들기")
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
            return _create_new(cfg)
    else:
        if not _create_new(cfg):
            return False

    # 가동 대기
    for i in range(20):
        if is_running():
            if not quiet:
                ui.ok(f"SearXNG 가동: {URL}  ({i + 1}초)")
            return True
        time.sleep(1)

    ui.err("SearXNG 시작 타임아웃")
    return False


def _create_new(cfg: Path) -> bool:
    """새 컨테이너를 docker run -d 로 생성."""
    ui.info("SearXNG 컨테이너 생성…")
    try:
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", CONTAINER,
                "--restart", "unless-stopped",
                "-p", f"{HOST_PORT}:8080",
                "-v", f"{cfg}:/etc/searxng:rw",
                IMAGE,
            ],
            check=True, capture_output=True, timeout=20,
        )
        return True
    except subprocess.CalledProcessError as e:
        ui.err(f"컨테이너 생성 실패: {e.stderr.decode(errors='ignore')[:200]}")
        return False


def stop():
    """SearXNG 컨테이너 정지."""
    if not container_exists():
        ui.info("SearXNG 컨테이너 없음")
        return
    ui.info("SearXNG 정지…")
    try:
        subprocess.run(
            ["docker", "stop", CONTAINER],
            check=True, capture_output=True, timeout=15,
        )
        ui.ok("정지 완료")
    except subprocess.CalledProcessError:
        ui.err("정지 실패")


def remove():
    """컨테이너 삭제 (이미지는 보존)."""
    stop()
    try:
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, timeout=10)
        ui.ok("컨테이너 삭제 완료")
    except Exception:
        pass
