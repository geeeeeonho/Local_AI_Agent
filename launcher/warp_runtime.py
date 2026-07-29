"""warp_runtime — Cloudflare WARP SOCKS5 프록시 컨테이너 런타임 (CONFIG_WARP_v1).

Tor(llm_tor) 를 대체하는 기본 네트워크 계층. WARP 클라이언트를 SOCKS5 프록시
모드로 Docker 컨테이너(llm_warp)에 띄운다. 나가는 IP 는 Cloudflare 엣지 IP 로
바뀌어(warp=on) 실제 ISP IP 를 숨기고, Tor 출구노드 차단·저속 문제를 회피한다.

정본(single source of truth) = launcher/config.py
  주소/포트/이미지/타임아웃은 config.WARP_* 에서만 정의한다. 이 모듈은 그 값을
  '읽기만' 한다. (config 를 못 불러오는 예외 상황에서만 리터럴 기본값으로 폴백)

배치
  - llm_net 위에서 다른 컨테이너는 config.warp_socks_proxy() (llm_warp:1080) 로 접근.
  - 호스트(호스트-인터프리터 모드)는 게시포트 127.0.0.1:1080 으로 접근.

주의: dperson/torproxy 와 달리 커스텀 설정 마운트가 필요 없다(기본값으로 뜬다).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

# ── 정본 참조 (config 우선, 없으면 리터럴 폴백) ─────────────────────────────
try:
    from . import config as _cfg  # launcher.config
except Exception:
    _cfg = None


def _c(name, default):
    """config 에 name 이 있으면 그 값, 없으면 default."""
    if _cfg is not None and hasattr(_cfg, name):
        return getattr(_cfg, name)
    return default


CONTAINER = _c("WARP_CONTAINER", os.environ.get("WARP_CONTAINER", "llm_warp"))
NET = _c("LLM_NETWORK", os.environ.get("LLM_NETWORK", "llm_net"))
PROXY_PORT = int(_c("WARP_PORT", int(os.environ.get("WARP_PORT", "1080"))))
IMAGE = _c("WARP_IMAGE", os.environ.get("WARP_IMAGE", "dublok/cloudflare-warp:latest"))
LICENSE = str(_c("WARP_LICENSE", os.environ.get("WARP_LICENSE", ""))).strip()
BOOT_TIMEOUT = int(_c("WARP_BOOT_TIMEOUT", int(os.environ.get("WARP_BOOT_TIMEOUT", "45"))))


def _docker() -> str:
    return shutil.which("docker") or "docker"


def _run(args, timeout=60):
    try:
        return subprocess.run(
            [_docker(), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None


def _log(log_path, level, msg):
    line = "[%s] %s %s" % (time.strftime("%H:%M:%S"), level, msg)
    try:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def proxy_url(inside_net: bool = True) -> str:
    """SearXNG/에이전트가 쓸 WARP SOCKS5 프록시 URL.

    inside_net=True  -> config.warp_socks_proxy()  (컨테이너→컨테이너, llm_net)
    inside_net=False -> socks5h://127.0.0.1:PORT   (호스트 프로세스용)
    """
    if inside_net:
        if _cfg is not None and hasattr(_cfg, "warp_socks_proxy"):
            return _cfg.warp_socks_proxy()
        return "socks5h://%s:%d" % (CONTAINER, PROXY_PORT)
    return "socks5h://127.0.0.1:%d" % PROXY_PORT


def image_exists() -> bool:
    r = _run(["image", "inspect", IMAGE])
    return bool(r and r.returncode == 0)


def container_exists() -> bool:
    r = _run(["ps", "-a", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and CONTAINER in (r.stdout or ""))


def is_running() -> bool:
    r = _run(["ps", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and CONTAINER in (r.stdout or ""))


def _ensure_net() -> None:
    """llm_net 공유 브리지 네트워크 보장(없으면 생성)."""
    r = _run(["network", "inspect", NET])
    if r and r.returncode == 0:
        return
    _run(["network", "create", NET])


def _remove_stale() -> None:
    """'marked for removal' 등 상태 잔재 제거(존재하나 미실행 컨테이너 정리)."""
    if container_exists() and not is_running():
        _run(["rm", "-f", CONTAINER], timeout=30)


def _wait_ready(timeout=BOOT_TIMEOUT) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


_CLEANUP_REGISTERED = False  # NET_CLEANUP_v1


def _register_exit_cleanup():
    """NET_CLEANUP_v1: 프로그램 종료 시 WARP/브리지 컨테이너를 자동 정리.

    Tor 는 이미 같은 방식으로 정리되는데 WARP 는 빠져 있어서,
    런처를 닫아도 도커에 계속 띄 있었다.
    """
    global _CLEANUP_REGISTERED
    if _CLEANUP_REGISTERED:
        return
    try:
        try:
            from .core import lifelog as _ll
        except Exception:
            from launcher.core import lifelog as _ll

        def _do():
            try:
                _ll.log("CLEANUP", "WARP 컨테이너 정리: %s" % CONTAINER)
            except Exception:
                pass
            try:
                from . import http_bridge as _hb
            except Exception:
                try:
                    from launcher import http_bridge as _hb  # type: ignore
                except Exception:
                    _hb = None
            if _hb is not None:
                try:
                    _hb.stop()
                except Exception:
                    pass
            try:
                _run(["rm", "-f", CONTAINER], timeout=30)
            except Exception:
                pass
            try:
                _ll.log("OK", "WARP/브리지 정리 완료")
            except Exception:
                pass

        _ll.register_cleanup(_do)
        _CLEANUP_REGISTERED = True
        try:
            _ll.log("INFO", "WARP 종료 정리 cleanup 등록됨 (%s)" % CONTAINER)
        except Exception:
            pass
    except Exception:
        pass


def _ensure_bridge(log_path=None) -> bool:
    """BRIDGE_ENSURE_v1: urllib 용 HTTP 프록시 브리지를 보장(멱등).

    WARP 는 SOCKS5 만 제공하고 urllib 은 SOCKS 를 못 쓴다. 브리지가 없으면
    컨테이너가 llm_httpbridge 이름을 못 찾아 gaierror(-2) 가 난다.
    """
    try:
        from . import http_bridge as _hb
    except Exception:
        try:
            from launcher import http_bridge as _hb  # type: ignore
        except Exception:
            return False
    try:
        if _hb.is_running():
            return True
        ok = _hb.start(log=lambda m: _log(log_path, "INFO", str(m)))
        if not ok:
            _log(log_path, "WARN",
                 "HTTP 브리지 미기동 — 검색은 되지만 본문 수집이 실패할 수 있습니다.")
        return ok
    except Exception as _e:
        _log(log_path, "WARN", "HTTP 브리지 예외: %r" % _e)
        return False


def start(env=None, log_path=None) -> bool:
    """WARP 프록시 기동. 이미 떠 있으면 True. 이미지 없으면 False.

    BRIDGE_ENSURE_v1: 이미 실행 중이라도 브리지는 매번 확인한다.
    """
    _register_exit_cleanup()  # NET_CLEANUP_v1
    if is_running():
        _ensure_bridge(log_path)
        return True

    if not image_exists():
        _log(log_path, "WARN",
             "WARP 이미지 없음(%s) - install 재실행 또는 'docker pull %s'" % (IMAGE, IMAGE))
        return False

    _ensure_net()
    _remove_stale()

    args = [
        "run", "-d",
        "--name", CONTAINER,
        "--network", NET,
        # NET_CLEANUP_v1: 종료 시 정리하므로 자동 재시작 정책을 쓰지 않는다
        "-p", "127.0.0.1:%d:%d" % (PROXY_PORT, PROXY_PORT),
        "--sysctl", "net.ipv6.conf.all.disable_ipv6=1",
    ]
    if LICENSE:
        args += ["-e", "WARP_LICENSE=%s" % LICENSE]
    args += [IMAGE]

    r = _run(args, timeout=90)
    if not (r and r.returncode == 0):
        _run(["rm", "-f", CONTAINER], timeout=30)
        r = _run(args, timeout=90)
        if not (r and r.returncode == 0):
            _log(log_path, "WARN",
                 "WARP 기동 실패: %s" % ((r.stderr if r else "docker 없음") or "").strip()[:200])
            return False

    if _wait_ready():
        _log(log_path, "INFO", "WARP 준비됨 (%s, socks5h :%d)" % (CONTAINER, PROXY_PORT))
        # HTTP_BRIDGE_v1: urllib 용 HTTP 프록시 브리지도 함께 기동
        try:
            from . import http_bridge as _hb
        except Exception:
            try:
                from launcher import http_bridge as _hb  # type: ignore
            except Exception:
                _hb = None
        if _hb is not None:
            try:
                if not _hb.start(log=lambda m: _log(log_path, "INFO", str(m))):
                    _log(log_path, "WARN",
                         "HTTP 브리지 미기동 — 검색은 되지만 본문 수집이 실패할 수 있습니다.")
            except Exception as _e:
                _log(log_path, "WARN", "HTTP 브리지 예외: %r" % _e)
        return True

    _log(log_path, "WARN", "WARP 컨테이너는 떴으나 포트 응답 없음(부팅 지연 가능)")
    return is_running()


def stop() -> None:
    """WARP 컨테이너 정지(존재 시)."""
    if container_exists():
        _run(["stop", CONTAINER], timeout=30)


def selftest() -> str:
    """진단용: 컨테이너 내부에서 cdn-cgi/trace 로 warp=on 확인."""
    if not is_running():
        return "WARP 미기동"
    r = _run([
        "exec", CONTAINER, "sh", "-c",
        "curl -s -x socks5h://127.0.0.1:%d https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -E 'ip=|warp='" % PROXY_PORT,
    ], timeout=30)
    out = (r.stdout if r else "") or ""
    return out.strip() or "trace 실패(이미지 curl 미포함 가능)"
