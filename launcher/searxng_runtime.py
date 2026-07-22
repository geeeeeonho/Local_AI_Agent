# -*- coding: utf-8 -*-
"""searxng_runtime — SearXNG 컨테이너 수명주기 (SEARXNG_RUNTIME_v3).

코드베이스에서 참조되지만 누락돼 있던 모듈을 되살린다. chat.py 와 actions/searxng.py 가
기대하는 인터페이스를 그대로 제공: image_exists / container_exists / is_running /
start(env, log_path=None) / stop / remove.

settings.yml 은 socks5://host.docker.internal:9050 (Tor) 를 통해 검색하므로, start() 는
Tor 컨테이너(tor_runtime)를 먼저 best-effort 로 띄운다. Tor 이미지가 없으면 SearXNG 는
기동되지만(브라우징 가능) 검색은 실패할 수 있으니 경고만 남긴다.

주의: 실제 Docker 미검증(가상검증). 컨테이너 구성:
  docker run -d --rm --name llm_searxng -p {HOST_PORT}:8080
    -v "{env}/searxng/config:/etc/searxng"
    --add-host=host.docker.internal:host-gateway  searxng/searxng:latest

stdlib 만 사용. Windows/Docker Desktop 가정.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    from . import config as _config  # 패키지 컨텍스트
except Exception:  # pragma: no cover
    try:
        import config as _config  # type: ignore
    except Exception:
        _config = None


def _c(name, default):
    return getattr(_config, name, default) if _config else default


IMAGE = _c("SEARXNG_IMAGE", "searxng/searxng:latest")
CONTAINER = _c("SEARXNG_CONTAINER", "llm_searxng")
HOST_PORT = _c("SEARXNG_HOST_PORT", 8888)
BOOT_TIMEOUT = _c("SEARXNG_BOOT_TIMEOUT", 60)
CONTAINER_PORT = 8080  # SearXNG 공식 이미지 기본 리슨 포트
NETWORK = _c("LLM_NETWORK", "llm_net")  # SEARXNG_NET_v1: 공유 네트워크


def _ensure_net():
    try:
        r = _run(["network", "inspect", NETWORK], timeout=10)
        if not (r and r.returncode == 0):
            _run(["network", "create", NETWORK], timeout=15)
    except Exception:
        pass

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


def _log(log_path, level, msg):
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[%s] SearXNG: %s\n" % (level, msg))
    except Exception:
        pass


def _cfg_dir(env) -> Path:
    return Path(env) / "searxng" / "config"


def _harden_settings(cfg, log_path=None):
    """SEARXNG_HARDEN_v2: 프라이버시 하드닝 (모든 start 마다 멱등 적용).
       ① socks5:// -> socks5h:// (원격 DNS, DNS 유출 방지)
       ② search.method: POST (검색어가 URL/referrer 에 안 남음)
       ③ general.enable_metrics: false (내부 메트릭 수집 off)
       ④ ui.query_in_title: false (검색어가 페이지 제목에 안 남음)"""
    try:
        _lt = Path(cfg) / "limiter.toml"
        if _lt.exists():
            _lt.unlink()
            _log(log_path, "INFO", "호환 안 되는 limiter.toml 제거 (이미지 기본값 사용)")
    except Exception:
        pass
    sp = Path(cfg) / "settings.yml"
    try:
        txt = sp.read_text(encoding="utf-8")
    except Exception:
        return
    orig = txt
    txt = txt.replace("socks5://host.docker.internal:9050",
                      "socks5h://host.docker.internal:9050")
    # SEARXNG_TOR_HOST_v1: 컨테이너→컨테이너는 게시포트 대신 llm_net 컨테이너명으로
    txt = txt.replace("socks5h://host.docker.internal:9050", "socks5h://llm_tor:9050")
    if "method:" not in txt and (nl := "\n") and "\nsearch:\n" in txt:
        txt = txt.replace("\nsearch:\n", "\nsearch:\n  method: \"POST\"\n", 1)
    if "enable_metrics:" not in txt and "\ngeneral:\n" in txt:
        txt = txt.replace("\ngeneral:\n", "\ngeneral:\n  enable_metrics: false\n", 1)
    if "query_in_title:" not in txt:
        txt = txt.rstrip() + "\n\nui:\n  query_in_title: false\n"
    if txt != orig:
        try:
            sp.write_text(txt, encoding="utf-8")
            _log(log_path, "INFO", "프라이버시 하드닝 적용 (socks5h·POST·no-metrics·no-title)")
        except Exception:
            pass


def image_exists() -> bool:
    r = _run(["image", "inspect", IMAGE])
    return bool(r and r.returncode == 0)


def container_exists() -> bool:
    r = _run(["ps", "-a", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and CONTAINER in (r.stdout or ""))


def is_running() -> bool:
    r = _run(["ps", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"])
    return bool(r and r.returncode == 0 and CONTAINER in (r.stdout or ""))


def _wait_ready(timeout=BOOT_TIMEOUT) -> bool:
    import socket
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", int(HOST_PORT)), timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def start(env, log_path=None, with_tor=True) -> bool:
    """SearXNG 기동. 이미 떠 있으면 True. 이미지/설정 없으면 False."""
    if is_running():
        return True
    _ensure_net()  # SEARXNG_NET_v1

    # settings.yml 이 Tor(9050) 를 요구하므로 Tor 를 먼저 best-effort 로 기동
    if with_tor:
        try:
            from . import tor_runtime  # type: ignore
        except Exception:
            tor_runtime = None
        if tor_runtime is not None:
            try:
                if not tor_runtime.start(env, log=lambda m: _log(log_path, "INFO", "Tor: " + str(m))):
                    _log(log_path, "WARN",
                         "Tor 미기동 (이미지 없음 등) — 검색이 실패할 수 있습니다. "
                         "docker pull %s 후 재시도" % getattr(tor_runtime, "TOR_IMAGE", "tor"))
            except Exception as e:
                _log(log_path, "WARN", "Tor 기동 예외: %r" % e)

    if not image_exists():
        _log(log_path, "WARN", "SearXNG 이미지 없음: %s (MANAGE/INSTALL 에서 pull 필요)" % IMAGE)
        return False

    cfg = _cfg_dir(env)
    if not (cfg / "settings.yml").exists():
        _log(log_path, "WARN", "settings.yml 없음: %s (INSTALL 필요)" % str(cfg / "settings.yml"))
        return False

    _harden_settings(cfg, log_path)  # SEARXNG_HARDEN_v1

    if container_exists():
        remove()

    r = _run([
        "run", "-d", "--rm",
        "--name", CONTAINER,
        "--network", NETWORK,
        "-p", "%d:%d" % (int(HOST_PORT), CONTAINER_PORT),
        "-v", "%s:/etc/searxng" % str(cfg),
        "--add-host=host.docker.internal:host-gateway",
        IMAGE,
    ], timeout=45)
    if not (r and r.returncode == 0):
        _log(log_path, "ERROR", "docker run 실패: %s" % ((r.stderr or "").strip() if r else "no docker"))
        return False

    ok = _wait_ready()
    _log(log_path, "INFO" if ok else "WARN",
         "기동 %s (port %s)" % ("완료" if ok else "타임아웃", HOST_PORT))
    return ok or is_running()


def stop() -> None:
    """SearXNG 종료 + (함께 띄운) Tor 도 정리."""
    _run(["stop", CONTAINER], timeout=20)
    try:
        from . import tor_runtime  # type: ignore
        tor_runtime.stop()
    except Exception:
        pass


def remove() -> None:
    _run(["rm", "-f", CONTAINER], timeout=20)
