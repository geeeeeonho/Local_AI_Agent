"""Cloudflare WARP SOCKS5 + HTTP bridge runtime.

A successful ``start()`` means the complete product proxy path is ready:
WARP SOCKS5 responds on the Host-published port *and* the managed HTTP-to-SOCKS
bridge is running. Callers can therefore fail closed without re-implementing
WARP health semantics.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

try:
    from . import config as _cfg
except Exception:  # pragma: no cover
    _cfg = None


def _c(name, default):
    if _cfg is not None and hasattr(_cfg, name):
        return getattr(_cfg, name)
    return default


CONTAINER = _c("WARP_CONTAINER", os.environ.get("WARP_CONTAINER", "llm_warp"))
NET = _c("LLM_NETWORK", os.environ.get("LLM_NETWORK", "llm_net"))
PROXY_PORT = int(_c("WARP_PORT", int(os.environ.get("WARP_PORT", "1080"))))
IMAGE = _c("WARP_IMAGE", os.environ.get("WARP_IMAGE", "dublok/cloudflare-warp:latest"))
LICENSE = str(_c("WARP_LICENSE", os.environ.get("WARP_LICENSE", ""))).strip()
BOOT_TIMEOUT = int(_c("WARP_BOOT_TIMEOUT", int(os.environ.get("WARP_BOOT_TIMEOUT", "45"))))
_CREATE_NO_WINDOW = 0x08000000


def _docker() -> str:
    return shutil.which("docker") or "docker"


def _run(args, timeout=60):
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        return subprocess.run([_docker(), *args], **kwargs)
    except Exception:
        return None


def _log(log_path, level, message):
    line = "[%s] %s %s" % (time.strftime("%H:%M:%S"), level, message)
    try:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def proxy_url(inside_net: bool = True) -> str:
    if inside_net:
        if _cfg is not None and hasattr(_cfg, "warp_socks_proxy"):
            return _cfg.warp_socks_proxy()
        return "socks5h://%s:%d" % (CONTAINER, PROXY_PORT)
    return "socks5h://127.0.0.1:%d" % PROXY_PORT


def image_exists() -> bool:
    result = _run(["image", "inspect", IMAGE])
    return bool(result and result.returncode == 0)


def container_exists() -> bool:
    result = _run([
        "ps", "-a", "--filter", "name=^/%s$" % CONTAINER,
        "--format", "{{.Names}}",
    ])
    return bool(result and result.returncode == 0 and CONTAINER in (result.stdout or ""))


def is_running() -> bool:
    result = _run([
        "ps", "--filter", "name=^/%s$" % CONTAINER,
        "--format", "{{.Names}}",
    ])
    return bool(result and result.returncode == 0 and CONTAINER in (result.stdout or ""))


def _ensure_net() -> None:
    result = _run(["network", "inspect", NET])
    if result and result.returncode == 0:
        return
    _run(["network", "create", NET])


def _remove_stale() -> None:
    if container_exists() and not is_running():
        _run(["rm", "-f", CONTAINER], timeout=30)


def _socks5_alive(host, port, timeout=3) -> bool:
    try:
        client = socket.create_connection((host, port), timeout=timeout)
    except Exception:
        return False
    try:
        client.settimeout(timeout)
        client.sendall(b"\x05\x01\x00")
        data = b""
        while len(data) < 2:
            chunk = client.recv(2 - len(data))
            if not chunk:
                return False
            data += chunk
        return data[0:1] == b"\x05"
    except Exception:
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def _wait_ready(timeout=BOOT_TIMEOUT, log_path=None) -> bool:
    end = time.time() + timeout
    waited = 0
    while time.time() < end:
        if _socks5_alive("127.0.0.1", PROXY_PORT):
            if waited:
                _log(log_path, "INFO", "WARP SOCKS5 응답 확인 (%d초 대기)" % waited)
            return True
        time.sleep(1)
        waited += 1
        if waited % 10 == 0:
            _log(log_path, "INFO", "WARP 등록 대기 중... %d/%d초" % (waited, timeout))
    _log(log_path, "WARN", "WARP SOCKS5 가 %d초 안에 응답하지 않았습니다." % timeout)
    return False


_CLEANUP_REGISTERED = False


def _register_exit_cleanup():
    global _CLEANUP_REGISTERED
    if _CLEANUP_REGISTERED:
        return
    try:
        try:
            from .core import lifelog as lifelog
        except Exception:
            from launcher.core import lifelog as lifelog

        def _cleanup():
            try:
                from . import http_bridge
                http_bridge.stop()
            except Exception:
                pass
            try:
                _run(["rm", "-f", CONTAINER], timeout=30)
            except Exception:
                pass

        lifelog.register_cleanup(_cleanup)
        _CLEANUP_REGISTERED = True
    except Exception:
        pass


def _ensure_bridge(log_path=None) -> bool:
    try:
        try:
            from . import http_bridge
        except Exception:  # pragma: no cover
            from launcher import http_bridge
    except Exception:
        return False
    try:
        if http_bridge.is_running():
            return True
        ok = bool(http_bridge.start(log=lambda message: _log(log_path, "INFO", str(message))))
        if not ok:
            _log(log_path, "WARN", "HTTP 브리지 미기동 — 보호 모드를 시작하지 않습니다.")
        return ok
    except Exception as exc:
        _log(log_path, "WARN", "HTTP 브리지 예외: %s" % type(exc).__name__)
        return False


def start(env=None, log_path=None) -> bool:
    """Start the complete WARP path and fail closed on bridge failure."""
    del env  # kept for the historic runtime API
    _register_exit_cleanup()

    if is_running():
        return _ensure_bridge(log_path)

    if not image_exists():
        _log(log_path, "WARN", "WARP 이미지 없음(%s)" % IMAGE)
        return False

    _ensure_net()
    _remove_stale()
    args = [
        "run", "-d",
        "--name", CONTAINER,
        "--network", NET,
        "-p", "127.0.0.1:%d:%d" % (PROXY_PORT, PROXY_PORT),
        "--sysctl", "net.ipv6.conf.all.disable_ipv6=1",
    ]
    if LICENSE:
        args += ["-e", "WARP_LICENSE=%s" % LICENSE]
    args.append(IMAGE)

    result = _run(args, timeout=90)
    if not (result and result.returncode == 0):
        _run(["rm", "-f", CONTAINER], timeout=30)
        result = _run(args, timeout=90)
        if not (result and result.returncode == 0):
            _log(log_path, "WARN", "WARP 기동 실패")
            return False

    if not _wait_ready(log_path=log_path):
        _log(log_path, "WARN", "WARP SOCKS5 준비 실패 — 보호 모드를 시작하지 않습니다.")
        return False

    _log(log_path, "INFO", "WARP SOCKS5 준비됨 (%s:%d)" % (CONTAINER, PROXY_PORT))
    if not _ensure_bridge(log_path):
        return False
    return True


def stop() -> None:
    if container_exists():
        _run(["stop", CONTAINER], timeout=30)


def selftest() -> str:
    if not is_running():
        return "WARP 미기동"
    result = _run([
        "exec", CONTAINER, "sh", "-c",
        "curl -s -x socks5h://127.0.0.1:%d https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -E 'ip=|warp='"
        % PROXY_PORT,
    ], timeout=30)
    output = (result.stdout if result else "") or ""
    return output.strip() or "trace 실패(이미지 curl 미포함 가능)"
