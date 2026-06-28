# -*- coding: utf-8 -*-
"""docker_maint — 도커 누적 정리 헬퍼 (stdlib).

반복 빌드/실행으로 쌓이는 것: 중지된 컨테이너, dangling 이미지, 빌드 캐시,
미사용 볼륨. [10] 도커 정리 액션과 종료 시 자동정리(register_auto_prune)가 공유.

안전 정책:
  - 자동(종료 시): 우리 exited 컨테이너 + dangling 이미지만 (빠르고 안전)
  - 수동([10]):   위 + 빌드 캐시 + (위험)미사용 이미지/볼륨 선택
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Tuple

MARKER = "DOCKER_MAINT_v1"
FLAG_NAME = "docker_autoclean.flag"

_NO_WINDOW = {}
if os.name == "nt":
    _NO_WINDOW["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

# 우리 자원 식별 패턴 (config 감지 + 안전망)
_NAME_PATTERNS = ("llm_agent_", "ai_box_", "llm_ollama", "llm_openwebui",
                  "llm_searxng", "open_webui", "searxng")
_IMAGE_PATTERNS = ("llm-agent-sandbox", "llm_agent_sandbox", "ai_box_sandbox",
                   "open_webui", "openwebui", "searxng")


def _patterns() -> Tuple[tuple, tuple]:
    names = list(_NAME_PATTERNS)
    images = list(_IMAGE_PATTERNS)
    try:
        from . import config as _cfg
        pfx = getattr(_cfg, "SANDBOX_CONTAINER_PREFIX", None)
        if pfx and pfx not in names:
            names.append(pfx)
        img = getattr(_cfg, "SANDBOX_IMAGE", None)
        if img:
            base = img.split(":")[0]
            if base not in images:
                images.append(base)
    except Exception:
        pass
    return tuple(names), tuple(images)


def _run(cmd: List[str], timeout: int = 60):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **_NO_WINDOW)


def docker_available() -> bool:
    try:
        return _run(["docker", "info"], timeout=8).returncode == 0
    except Exception:
        return False


def system_df() -> str:
    """docker system df 요약 텍스트."""
    try:
        r = _run(["docker", "system", "df"], timeout=15)
        return (r.stdout or "").rstrip() if r.returncode == 0 else "(docker system df 실패)"
    except Exception as e:
        return "(조회 실패: " + repr(e) + ")"


def list_our_exited() -> List[str]:
    """우리 패턴에 매칭되는 exited 컨테이너 이름 목록."""
    names, images = _patterns()
    out: List[str] = []
    try:
        r = _run(["docker", "ps", "-a", "--filter", "status=exited",
                  "--format", "{{.Names}}\t{{.Image}}"], timeout=15)
        if r.returncode != 0:
            return out
        for line in (r.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            nm, im = parts[0].strip(), parts[1].strip()
            if any(p and p in nm for p in names) or any(p and p in im for p in images):
                out.append(nm)
    except Exception:
        pass
    return out


def prune_exited_ours() -> Tuple[int, List[str]]:
    log: List[str] = []
    cnt = 0
    for nm in list_our_exited():
        try:
            if _run(["docker", "rm", "-f", nm], timeout=10).returncode == 0:
                cnt += 1
                log.append("컨테이너 제거: " + nm)
        except Exception as e:
            log.append("실패: " + nm + " (" + repr(e) + ")")
    return cnt, log


def prune_dangling_images() -> Tuple[str, List[str]]:
    try:
        r = _run(["docker", "image", "prune", "-f"], timeout=120)
        line = ""
        for ln in (r.stdout or "").splitlines():
            if "Total reclaimed space" in ln:
                line = ln.strip()
        return (line or "dangling 이미지 정리 완료"), []
    except Exception as e:
        return "이미지 정리 실패: " + repr(e), []


def prune_build_cache() -> Tuple[str, List[str]]:
    try:
        r = _run(["docker", "builder", "prune", "-f"], timeout=180)
        line = ""
        for ln in (r.stdout or "").splitlines():
            if "Total" in ln and "reclaimed" in ln:
                line = ln.strip()
        return (line or "빌드 캐시 정리 완료"), []
    except Exception as e:
        return "빌드 캐시 정리 실패: " + repr(e), []


def prune_unused_images() -> Tuple[str, List[str]]:
    """위험: 컨테이너가 안 쓰는 모든 이미지 제거(-a)."""
    try:
        r = _run(["docker", "image", "prune", "-a", "-f"], timeout=180)
        line = ""
        for ln in (r.stdout or "").splitlines():
            if "Total reclaimed space" in ln:
                line = ln.strip()
        return (line or "미사용 이미지 정리 완료"), []
    except Exception as e:
        return "미사용 이미지 정리 실패: " + repr(e), []


def prune_volumes() -> Tuple[str, List[str]]:
    """위험: 미사용 볼륨 제거."""
    try:
        r = _run(["docker", "volume", "prune", "-f"], timeout=120)
        line = ""
        for ln in (r.stdout or "").splitlines():
            if "Total reclaimed space" in ln:
                line = ln.strip()
        return (line or "미사용 볼륨 정리 완료"), []
    except Exception as e:
        return "볼륨 정리 실패: " + repr(e), []


def safe_auto_prune() -> dict:
    """종료 시 자동 안전 정리: 우리 exited 컨테이너 + dangling 이미지."""
    cnt, _ = prune_exited_ours()
    img, _ = prune_dangling_images()
    return {"containers": cnt, "images": img}


# ── 종료 시 자동정리 (플래그 게이트) ──
def _flag_path(env) -> Path:
    return Path(env) / FLAG_NAME


def autoclean_enabled(env) -> bool:
    try:
        return _flag_path(env).exists()
    except Exception:
        return False


def set_autoclean(env, on: bool) -> None:
    p = _flag_path(env)
    try:
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("on", encoding="utf-8")
        elif p.exists():
            p.unlink()
    except Exception:
        pass


def register_auto_prune(env) -> bool:
    """플래그가 켜져 있으면 종료 시 안전 정리를 lifelog 에 등록. 등록되면 True."""
    if not autoclean_enabled(env):
        return False
    try:
        from . import lifelog as _ll

        def _do():
            try:
                res = safe_auto_prune()
                _ll.log("CLEANUP", "도커 자동정리: 컨테이너 "
                        + str(res.get("containers", 0)) + " · " + str(res.get("images", "")))
            except Exception as e:
                _ll.log("WARN", "도커 자동정리 예외: " + str(e))

        _ll.register_cleanup(_do)
        _ll.log("INFO", "도커 종료 자동정리 등록됨")
        return True
    except Exception:
        return False


__all__ = [
    "MARKER", "FLAG_NAME", "docker_available", "system_df", "list_our_exited",
    "prune_exited_ours", "prune_dangling_images", "prune_build_cache",
    "prune_unused_images", "prune_volumes", "safe_auto_prune",
    "autoclean_enabled", "set_autoclean", "register_auto_prune",
]
