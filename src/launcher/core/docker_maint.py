# -*- coding: utf-8 -*-
"""docker_maint — 도커 누적 정리 헬퍼 (stdlib).

반복 빌드/실행으로 쌓이는 것: 중지된 컨테이너, dangling 이미지, 빌드 캐시,
미사용 볼륨. [10] 도커 정리 액션과 종료 시 자동정리(register_exit_sweep)가 공유.

안전 정책:
  - 자동(종료 시): 우리 exited 컨테이너 + dangling 이미지만 (빠르고 안전)
  - 수동([10]):   위 + 빌드 캐시 + (위험)미사용 이미지/볼륨 선택

컨테이너 소유권은 LocalAI가 실제로 생성하는 고유 이름/접두사로만 판단한다.
공용 Docker 이미지 이름만 같다는 이유로 외부 컨테이너를 삭제하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from launcher.services.docker import DockerService

FLAG_NAME = "docker_autoclean.flag"

def _owned_container_names() -> tuple[set[str], tuple[str, ...]]:
    """Return exact names and prefixes that LocalAI itself creates."""
    exact = {
        "llm_searxng", "llm_anythingllm", "llm_tor",
        "llm_warp", "llm_httpbridge",
    }
    prefixes = {"llm_agent_"}
    try:
        from launcher import config as cfg
        for key in (
            "SEARXNG_CONTAINER", "ANYTHINGLLM_CONTAINER", "TOR_CONTAINER",
            "WARP_CONTAINER", "HTTP_BRIDGE_CONTAINER",
        ):
            value = str(getattr(cfg, key, "") or "").strip()
            if value:
                exact.add(value)
        prefix = str(getattr(cfg, "SANDBOX_CONTAINER_PREFIX", "") or "").strip()
        if prefix:
            prefixes.add(prefix)
    except Exception:
        pass
    return exact, tuple(sorted(prefixes))


def _is_owned_container(name: str) -> bool:
    exact, prefixes = _owned_container_names()
    return name in exact or any(name.startswith(prefix) for prefix in prefixes)


def _run(cmd: List[str], timeout: int = 60):
    args = list(cmd)
    if args and args[0].lower() == "docker":
        args = args[1:]
    result = DockerService.run(args, timeout=timeout, capture_output=True, text=True)
    if result is None:
        raise RuntimeError("docker command failed")
    return result


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


#: 실행 중이 아닌 컨테이너가 남는 방식은 하나가 아니다. ``exited`` 만 찾으면
#: ``docker run`` 이 도중에 실패해 남긴 ``created`` 와, 데몬이 죽으며 남긴
#: ``dead`` 가 그대로 쌓인다 — 정확히 "열렸다가 닫힐 때 남는 찌꺼기" 다.
LEFTOVER_STATES = ("exited", "created", "dead")


def list_our_leftovers(states=LEFTOVER_STATES) -> List[str]:
    """우리 패턴에 매칭되는, 실행 중이 아닌 컨테이너 이름 목록."""
    out: List[str] = []
    for state in states:
        try:
            r = _run(["docker", "ps", "-a", "--filter", "status=" + str(state),
                      "--format", "{{.Names}}\t{{.Image}}"], timeout=15)
            if r.returncode != 0:
                continue
            for line in (r.stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                nm = parts[0].strip()
                if not nm or nm in out:
                    continue
                if _is_owned_container(nm):
                    out.append(nm)
        except Exception:
            continue
    return out


def list_our_networks() -> List[str]:
    """우리가 만든 Docker 네트워크 중 지금 아무 컨테이너도 붙어 있지 않은 것."""
    wanted = []
    try:
        from launcher import config as _cfg
        value = str(getattr(_cfg, "LLM_NETWORK", "") or "").strip()
        if value:
            wanted.append(value)
    except Exception:
        return []
    try:
        # config has no BLOCK_NETWORK; the canonical name lives behind this
        # accessor, and reading the missing attribute simply skipped it.
        from launcher import network_policy
        value = str(network_policy.block_network_name() or "").strip()
        if value and value not in wanted:
            wanted.append(value)
    except Exception:
        pass
    idle: List[str] = []
    for name in wanted:
        try:
            r = _run(["docker", "network", "inspect", "--format",
                      "{{len .Containers}}", name], timeout=15)
            if r.returncode == 0 and (r.stdout or "").strip() == "0":
                idle.append(name)
        except Exception:
            continue
    return idle


def prune_our_networks() -> Tuple[int, List[str]]:
    log: List[str] = []
    count = 0
    for name in list_our_networks():
        try:
            if _run(["docker", "network", "rm", name], timeout=15).returncode == 0:
                count += 1
                log.append("네트워크 제거: " + name)
        except Exception as exc:
            log.append("실패: " + name + " (" + repr(exc) + ")")
    return count, log


def prune_exited_ours() -> Tuple[int, List[str]]:
    log: List[str] = []
    cnt = 0
    for nm in list_our_leftovers():
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


def sweep_our_leftovers() -> dict:
    """우리가 남긴 것만 치운다. 사용자의 Docker 는 건드리지 않는다.

    이건 옵션이 아니라 예의다: 이 프로그램이 컨테이너를 띄웠다가 멈췄으면 그
    껍데기도 이 프로그램이 치워야 한다. dangling 이미지나 빌드 캐시처럼 누가
    만들었는지 알 수 없는 것은 여기서 건드리지 않는다 — 그건 사용자가 [도커
    정리] 에서 직접 고르는 몫이다.
    """
    containers, _ = prune_exited_ours()
    networks, _ = prune_our_networks()
    return {"containers": containers, "networks": networks}


def safe_auto_prune() -> dict:
    """종료 시 자동 정리: 우리 찌꺼기 + (기계 공용) dangling 이미지."""
    swept = sweep_our_leftovers()
    img, _ = prune_dangling_images()
    return {"containers": swept["containers"], "networks": swept["networks"],
            "images": img}


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


_SWEEP_REGISTERED = False


def register_exit_sweep(state_root) -> bool:
    """Clean up after ourselves when the program exits.

    Two different things used to be one opt-in flag nobody could reach from the
    desktop app: tidying up *our own* leftovers, and pruning the machine's
    dangling images. The first is not a preference - a container this program
    started and stopped is this program's to remove - so it always runs. The
    second touches images we did not necessarily create, so it stays behind the
    flag the [도커 정리] screen owns.

    The sweep runs in the ``sweep`` stage: after our containers have been
    stopped (there is nothing to sweep before that) and before the Docker
    daemon is shut down (the sweep needs it).
    """
    global _SWEEP_REGISTERED
    if _SWEEP_REGISTERED:
        return True
    try:
        from launcher.core import lifelog as _ll

        def _do():
            try:
                # Read at shutdown so a same-session toggle applies immediately.
                wants_images = autoclean_enabled(state_root)
                result = safe_auto_prune() if wants_images else sweep_our_leftovers()
                _ll.log("CLEANUP", "도커 정리: 컨테이너 %s · 네트워크 %s%s" % (
                    result.get("containers", 0), result.get("networks", 0),
                    (" · " + str(result["images"])) if result.get("images") else ""))
            except Exception as exc:
                _ll.log("WARN", "도커 정리 예외: " + str(exc))

        _ll.register_cleanup(_do, stage="sweep")
        _ll.log("INFO", "도커 종료 정리 등록됨")
        _SWEEP_REGISTERED = True
        return True
    except Exception:
        return False


__all__ = [
"FLAG_NAME", "LEFTOVER_STATES", "docker_available", "system_df",
    "list_our_leftovers", "list_our_networks",
    "prune_exited_ours", "prune_our_networks", "prune_dangling_images",
    "prune_build_cache", "prune_unused_images", "prune_volumes",
    "sweep_our_leftovers", "safe_auto_prune",
    "autoclean_enabled", "set_autoclean", "register_exit_sweep",
]
