# -*- coding: utf-8 -*-
"""tor_runtime — Tor SOCKS 프록시 컨테이너 수명주기 (TOR_RUNTIME_v8).

SearXNG(settings.yml 의 socks5://host.docker.internal:9050) 와 인터프리터의 'Tor 경유'
토글이 실제로 동작하도록, 로컬에 Tor SOCKS5 프록시 컨테이너를 9050 으로 띄운다.

호스트에서 사용하는 Tor 프록시 포트는 127.0.0.1 에만 게시한다. 컨테이너끼리는
공유 llm_net 안에서 llm_tor 이름으로 직접 접근하므로 Host 전체 인터페이스 공개가
필요하지 않다.

주의(가상검증만, 실제 Docker 미검증):
  · 기본 이미지는 아래 TOR_IMAGE. 없으면 image_exists()=False → start()가 안내 후 False.
    사용자가 `docker pull <TOR_IMAGE>` 하거나 TOR_IMAGE 상수를 원하는 것으로 바꾸면 된다.
  · 이미지에 따라 내부 SocksPort 가 9050 이 아니면 TOR_CONTAINER_PORT 를 맞춰야 한다.

stdlib 만 사용. Windows/Docker Desktop 가정.
"""
from __future__ import annotations

import subprocess
import time

try:
    from . import config as _config
except Exception:  # pragma: no cover
    try:
        import config as _config  # type: ignore
    except Exception:
        _config = None


def _c(name, default):
    return getattr(_config, name, default) if _config else default


TOR_IMAGE = _c("TOR_IMAGE", "dperson/torproxy")
TOR_CONTAINER = _c("TOR_CONTAINER", "llm_tor")
TOR_HOST_PORT = _c("TOR_SOCKS_PORT", 9050)
TOR_CONTAINER_PORT = _c("TOR_SOCKS_PORT", 9050)
TOR_HTTP_PORT = _c("TOR_HTTP_PORT", 8118)
BOOT_TIMEOUT = _c("TOR_BOOT_TIMEOUT", 30)

_CREATE_NO_WINDOW = 0x08000000


def _run(args, timeout=25, capture=True):
    kw = {"timeout": timeout}
    try:
        import os
        if os.name == "nt":
            kw["creationflags"] = _CREATE_NO_WINDOW
    except Exception:
        pass
    if capture:
        kw["capture_output"] = True
        kw["text"] = True
    try:
        return subprocess.run(["docker"] + args, check=False, **kw)
    except Exception:
        return None


def image_exists() -> bool:
    r = _run(["image", "inspect", TOR_IMAGE])
    return bool(r and r.returncode == 0)


def container_exists() -> bool:
    r = _run(["ps", "-a", "--filter", "name=^/%s$" % TOR_CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and TOR_CONTAINER in (r.stdout or ""))


def is_running() -> bool:
    r = _run(["ps", "--filter", "name=^/%s$" % TOR_CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and TOR_CONTAINER in (r.stdout or ""))


def _has_http_port() -> bool:
    r = _run(["port", TOR_CONTAINER])
    return bool(r and r.returncode == 0 and ("8118" in (r.stdout or "")))


def _socks5_handshake_ok(host, port, timeout=3) -> bool:
    import socket as _s
    try:
        c = _s.create_connection((host, port), timeout=timeout)
    except Exception:
        return False
    try:
        c.sendall(b"\x05\x01\x00")
        resp = c.recv(2)
        return len(resp) == 2 and resp[0] == 0x05 and resp[1] in (0x00, 0xff)
    except Exception:
        return False
    finally:
        try:
            c.close()
        except Exception:
            pass


def _wait_port(timeout=BOOT_TIMEOUT) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _socks5_handshake_ok("127.0.0.1", TOR_HOST_PORT, timeout=2):
            return True
        time.sleep(1)
    return False


def _write_torrc(env):
    if TOR_IMAGE == "dperson/torproxy":
        return None
    if not env:
        return None
    try:
        from pathlib import Path as _P
        d = _P(env) / "tor"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "torrc"
        f.write_text(
            "SocksPort 0.0.0.0:%d IsolateDestAddr IsolateDestPort\n"
            "DataDirectory /var/lib/tor\n" % TOR_CONTAINER_PORT,
            encoding="utf-8")
        return str(f)
    except Exception:
        return None


NETWORK = _c("LLM_NETWORK", "llm_net")


def _ensure_net():
    try:
        r = _run(["network", "inspect", NETWORK], timeout=10)
        if not (r and r.returncode == 0):
            _run(["network", "create", NETWORK], timeout=15)
    except Exception:
        pass


def _run_container(extra=None):
    _ensure_net()
    args = ["run", "-d", "--rm", "--name", TOR_CONTAINER,
            "--network", NETWORK,
            "-p", "127.0.0.1:%d:%d" % (TOR_HOST_PORT, TOR_CONTAINER_PORT),
            "-p", "127.0.0.1:%d:%d" % (TOR_HTTP_PORT, TOR_HTTP_PORT)]
    if extra:
        args += extra
    args.append(TOR_IMAGE)
    return _run(args, timeout=40)


_CLEANUP_REGISTERED = False


def _register_exit_cleanup():
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
                if not (is_running() or container_exists()):
                    return
            except Exception:
                pass
            try:
                _ll.log("CLEANUP", "Tor 컨테이너 정리: %s" % TOR_CONTAINER)
            except Exception:
                pass
            try:
                stop()
            except Exception:
                pass
            try:
                remove()
            except Exception:
                pass
            try:
                _ll.log("OK", "Tor 컨테이너 정리 완료: %s" % TOR_CONTAINER)
            except Exception:
                pass

        _ll.register_cleanup(_do)
        _CLEANUP_REGISTERED = True
        try:
            _ll.log("INFO", "Tor 종료 정리 cleanup 등록됨 (%s)" % TOR_CONTAINER)
        except Exception:
            pass
    except Exception:
        pass


def start(env=None, log=None) -> bool:
    def _p(m):
        if log:
            try:
                log(str(m))
            except Exception:
                pass

    try:
        _nm_guard = str(_c("NET_MODE", "warp")).strip().lower()
    except Exception:
        import os as _os_g
        _nm_guard = _os_g.environ.get("NET_MODE", "warp").strip().lower()
    if _nm_guard != "tor":
        if log:
            try:
                log("NET_MODE=%s — Tor 기동 생략(프록시는 WARP 사용)" % _nm_guard)
            except Exception:
                pass
        return False

    if is_running():
        if _has_http_port():
            _p("Tor 이미 실행 중 (%d, HTTP 8118 확인)" % TOR_HOST_PORT)
            _register_exit_cleanup()
            return True
        _p("실행 중이나 HTTP 8118 미게시 — 재생성합니다")
        remove()
    if container_exists():
        _p("기존 %s 컨테이너 제거" % TOR_CONTAINER)
        remove()
    if not image_exists():
        _p("Tor 이미지 없음: %s — 'docker pull %s' 로 먼저 받으세요" % (TOR_IMAGE, TOR_IMAGE))
        return False

    torrc = _write_torrc(env)
    if torrc:
        _p("Tor 기동 시도 (회로격리 torrc): %s" % torrc)
        r = _run_container(["-v", "%s:/etc/tor/torrc:ro" % torrc])
        if r and r.returncode == 0 and _wait_port():
            _p("Tor 기동 완료 — 회로격리 활성 (포트 %d)" % TOR_HOST_PORT)
            _register_exit_cleanup()
            return True
        _err = ((r.stderr or "").strip()[:120] if r else "docker 응답 없음")
        _p("회로격리 기동 실패 → 기본 구성으로 폴백 (%s)" % _err)
        remove()

    _p("Tor 기동 시도 (기본 구성)")
    r = _run_container()
    if not (r and r.returncode == 0):
        _p("Tor docker run 실패: %s" % ((r.stderr or "").strip()[:160] if r else "docker 응답 없음"))
        return False
    ok = _wait_port()
    _p("Tor 기동 %s (포트 %d)" % ("완료" if ok else "타임아웃 — 포트 응답 없음", TOR_HOST_PORT))
    if ok:
        _register_exit_cleanup()
    return ok


def stop() -> None:
    _run(["stop", TOR_CONTAINER], timeout=20)


def remove() -> None:
    _run(["rm", "-f", TOR_CONTAINER], timeout=20)
