"""warp — Cloudflare WARP SOCKS5 프록시 Docker 이미지 설치 (CONFIG_WARP_v1).

Docker 이미지 pull 만 수행(컨테이너는 만들지 않음, 이름만 예약).
실제 컨테이너 시작/정지는 launcher/warp_runtime.py 가 담당.

정본 = launcher/config.py 의 WARP_IMAGE / WARP_CONTAINER / WARP_PORT.
설치 시점엔 launcher 패키지가 임포트 불가할 수 있으므로, config 를 시도하되
실패하면 리터럴 기본값(= config 기본값과 동일)으로 폴백한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

# ── 정본 참조 (config 우선, 없으면 리터럴 폴백) ─────────────────────────────
_cfg = None
for _imp in ("launcher.config", "config"):
    try:
        _cfg = __import__(_imp, fromlist=["_"])
        break
    except Exception:
        _cfg = None


def _c(name, default):
    if _cfg is not None and hasattr(_cfg, name):
        return getattr(_cfg, name)
    return default


IMAGE = _c("WARP_IMAGE", "dublok/cloudflare-warp:latest")
CONTAINER_NAME = _c("WARP_CONTAINER", "llm_warp")
HOST_PORT = int(_c("WARP_PORT", 1080))


def _docker(*args, timeout=600):
    try:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None


def _image_present() -> bool:
    r = _docker("image", "inspect", IMAGE, timeout=30)
    return bool(r and r.returncode == 0)


def install(paths: Dict[str, Path]):
    """WARP 이미지 pull. 컨테이너는 만들지 않음. Docker 없으면 조용히 스킵."""
    probe = _docker("version", "--format", "{{.Server.Version}}", timeout=20)
    if not (probe and probe.returncode == 0):
        print("[warp] Docker 미준비 - WARP 설치 건너뜀 (Docker 설정 후 install 재실행)")
        return

    if _image_present():
        print("[warp] 이미지 이미 존재: %s" % IMAGE)
        print("[warp] WARP 준비 완료. 컨테이너: %s, 포트: %d" % (CONTAINER_NAME, HOST_PORT))
        return

    print("[warp] Docker 이미지 pull: %s (약 100MB, 1-3분)" % IMAGE)
    r = _docker("pull", IMAGE, timeout=900)
    if r and r.returncode == 0:
        print("[warp] 이미지 pull 완료")
        print("[warp] WARP 준비 완료. 컨테이너: %s, 포트: %d" % (CONTAINER_NAME, HOST_PORT))
    else:
        err = ((r.stderr if r else "docker pull 실패") or "").strip()[:200]
        print("[warp] 이미지 pull 실패: %s" % err)
        print("[warp] 수동: docker pull %s" % IMAGE)
