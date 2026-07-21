# -*- coding: utf-8 -*-
"""tor_runtime — Tor SOCKS 프록시 컨테이너 수명주기 (TOR_RUNTIME_v8).

SearXNG(settings.yml 의 socks5://host.docker.internal:9050) 와 인터프리터의 'Tor 경유'
토글이 실제로 동작하도록, 로컬에 Tor SOCKS5 프록시 컨테이너를 9050 으로 띄운다.

컨테이너는 9050 을 호스트에 게시(-p 9050:9050)하므로, 다른 컨테이너(SearXNG·샌드박스)는
host.docker.internal:9050 으로 도달한다.

주의(가상검증만, 실제 Docker 미검증):
  · 기본 이미지는 아래 TOR_IMAGE. 없으면 image_exists()=False → start()가 안내 후 False.
    사용자가 `docker pull <TOR_IMAGE>` 하거나 TOR_IMAGE 상수를 원하는 것으로 바꾸면 된다.
  · 이미지에 따라 내부 SocksPort 가 9050 이 아니면 TOR_CONTAINER_PORT 를 맞춰야 한다.

stdlib 만 사용. Windows/Docker Desktop 가정.
"""
from __future__ import annotations

import subprocess
import time

# 사용자 조정 가능 상수 --------------------------------------------------
TOR_IMAGE = "dperson/torproxy"     # SOCKS5 Tor proxy (내부 9050). 원하면 교체 가능.
TOR_CONTAINER = "llm_tor"
TOR_HOST_PORT = 9050               # 호스트/컨테이너들이 접근할 포트 (settings.yml 과 일치)
TOR_CONTAINER_PORT = 9050          # 이미지 내부 SocksPort
TOR_HTTP_PORT = 8118               # Privoxy(HTTP 프록시) — urllib 호환
BOOT_TIMEOUT = 30
# ----------------------------------------------------------------------

_CREATE_NO_WINDOW = 0x08000000  # Windows: 콘솔 창 안 띄움


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


def _has_http_port() -> bool:  # TOR_RUNTIME_v8
    """실행 중 컨테이너가 8118(Privoxy HTTP)을 게시했는지 확인."""
    r = _run(["port", TOR_CONTAINER])
    return bool(r and r.returncode == 0 and ("8118" in (r.stdout or "")))


def _socks5_handshake_ok(host, port, timeout=3) -> bool:  # TOR_HEALTHCHECK_v1
    """SOCKS5 그리팅에 유효 응답하는지(=진짜 SOCKS 프록시인지) 확인.

    TCP 연결만으로는 '누가 포트를 열었다'까지만 보장된다. Tor SOCKS 리스너는
    05 01 00 (VER=5, NMETHODS=1, NOAUTH) 에 05 00(무인증 수락) 등으로 답한다.
    포트만 점유한 죽은/다른 컨테이너를 '정상'으로 오판하지 않기 위한 강화 검사.
    """
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


def _wait_port(timeout=BOOT_TIMEOUT) -> bool:  # TOR_HEALTHCHECK_v1: TCP + SOCKS5 확인
    end = time.time() + timeout
    while time.time() < end:
        if _socks5_handshake_ok("127.0.0.1", TOR_HOST_PORT, timeout=2):
            return True
        time.sleep(1)
    return False


def _write_torrc(env):
    """TOR_RUNTIME_v2: 회로 격리(IsolateDestAddr/Port) torrc 생성. env 없으면 None."""
    # TORRC_SKIP_v1: dperson/torproxy 는 /etc/tor/torrc 마운트 시 기동 실패(자가검증 확인).
    #   torrc 를 비활성화하고 start() 가 '기본 구성'으로 동작하게 한다(= Tor 정상, 전 구간
    #   우회 유지). 회로격리(IsolateDestAddr/Port)만 포기. 다른 이미지로 교체하면 가드 제거.
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


NETWORK = "llm_net"  # TOR_RUNTIME_v8: 공유 네트워크 (tor_runtime 은 _c 헬퍼 없음)


def _ensure_net():
    """공유 네트워크 생성(멱등). 컨테이너 간 이름 통신용."""
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
            "-p", "%d:%d" % (TOR_HOST_PORT, TOR_CONTAINER_PORT),
            "-p", "%d:%d" % (TOR_HTTP_PORT, TOR_HTTP_PORT)]
    if extra:
        args += extra
    args.append(TOR_IMAGE)
    return _run(args, timeout=40)


_CLEANUP_REGISTERED = False  # TOR_RUNTIME_v8


def _register_exit_cleanup():
    """프로그램 종료 시 llm_tor 를 자동 종료/제거하도록 lifelog 에 등록 (1회)."""
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
    """Tor 컨테이너 기동. 이미 떠 있으면 True. 이미지 없으면 False.
    env 가 주어지면 회로 격리 torrc 를 먼저 시도하고, 실패하면 기본 구성으로 폴백.
    log(str) 콜백을 주면 각 단계를 자세히 보고한다(안 뜰 때 원인 추적용)."""
    def _p(m):
        if log:
            try:
                log(str(m))
            except Exception:
                pass

    if is_running():
        if _has_http_port():  # TOR_RUNTIME_v8: 8118 게시 확인
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
            _register_exit_cleanup()  # TOR_RUNTIME_v8
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
        _register_exit_cleanup()  # TOR_RUNTIME_v8
    return ok


def stop() -> None:
    _run(["stop", TOR_CONTAINER], timeout=20)


def remove() -> None:
    _run(["rm", "-f", TOR_CONTAINER], timeout=20)
