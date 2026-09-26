# -*- coding: utf-8 -*-
"""searxng_runtime — SearXNG 컨테이너 수명주기 (SEARXNG_RUNTIME_v3).

코드베이스에서 참조되지만 누락돼 있던 모듈을 되살린다. chat.py 와 actions/searxng.py 가
기대하는 인터페이스를 그대로 제공: image_exists / container_exists / is_running /
start(env, log_path=None) / stop / remove.

settings.yml 은 socks5://host.docker.internal:9050 (Tor) 를 통해 검색하므로, start() 는
Tor 컨테이너(tor_runtime)를 먼저 best-effort 로 띄운다. Tor 이미지가 없으면 SearXNG 는
기동되지만(브라우징 가능) 검색은 실패할 수 있으니 경고만 남긴다.

호스트 UI 포트는 127.0.0.1 에만 게시한다. 컨테이너 간 검색 호출은 llm_net 내부의
llm_searxng 이름을 사용하므로 LAN 전체 인터페이스 공개는 필요하지 않다.

stdlib 만 사용. Windows/Docker Desktop 가정.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    from . import config as _config
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
CONTAINER_PORT = _c("SEARXNG_CONTAINER_PORT", 8080)
NETWORK = _c("LLM_NETWORK", "llm_net")


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
        kw["encoding"] = "utf-8"
        kw["errors"] = "replace"
    try:
        return subprocess.run(["docker"] + args, check=False, **kw)
    except Exception:
        return None


def _log(log_path, level, msg, log=None):
    """Record one line to the log file and to the caller's progress callback.

    Every caller passes ``log_path=None``, so this used to return immediately
    and throw the message away - including the ones that say exactly why search
    did not start (image missing, settings.yml missing, docker run failed). The
    Agent screen showed "검색 준비 중..." and then a generic warning with the
    reason discarded.
    """
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("[%s] SearXNG: %s\n" % (level, msg))
        except Exception:
            pass
    if log is not None:
        try:
            log("SearXNG: " + str(msg))
        except Exception:
            pass


def _cancelled(cancel_check) -> bool:
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        return False


_CLEANUP_REGISTERED = False


def _register_exit_cleanup() -> None:
    """Stop this container when the program exits.

    Every other container runtime in the product registers one; this one never
    did. The Agent path starts SearXNG through this module, so opening an Agent
    once left llm_searxng running after the window closed. The desktop Chat path
    goes through integrations.searxng.runtime, which services.close() owns, so
    the leak only showed up via Agent and the terminal launcher.
    """
    global _CLEANUP_REGISTERED
    if _CLEANUP_REGISTERED:
        return
    try:
        try:
            from .core import lifelog as _ll
        except Exception:  # pragma: no cover - package fallback
            from launcher.core import lifelog as _ll

        def _do():
            try:
                _ll.log("CLEANUP", "SearXNG 컨테이너 정리: %s" % CONTAINER)
            except Exception:
                pass
            try:
                stop()
            except Exception:
                pass

        _ll.register_cleanup(_do)
        _CLEANUP_REGISTERED = True
    except Exception:
        pass


def _cfg_dir(env) -> Path:
    """Private writable derivative of the installed shared SearXNG config.

    The source under environment is shared RX-only. Agent startup hardens the
    settings for the selected network mode, so mutating the installed source
    both fails for a second Windows account and lets one account rewrite
    another account's search route.
    """
    source = Path(env) / "searxng" / "config"
    try:
        import project_paths
        target = project_paths.user_data_dir() / "cache" / "searxng"
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        return source

    for name in ("settings.yml", "limiter.toml"):
        src = source / name
        dst = target / name
        try:
            if src.is_file():
                payload = src.read_bytes()
                if not dst.is_file() or dst.read_bytes() != payload:
                    dst.write_bytes(payload)
            elif dst.exists():
                dst.unlink()
        except OSError:
            pass
    return target


def _harden_settings(cfg, log_path=None):
    """SEARXNG_HARDEN_v2: 프라이버시 하드닝 (모든 start 마다 멱등 적용)."""
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
    txt = txt.replace("socks5h://host.docker.internal:9050", "socks5h://llm_tor:9050")
    try:
        _ap = _c("active_socks_proxy", None)
        _proxy = _ap() if callable(_ap) else None
    except Exception:
        _proxy = None
    if _proxy:
        for _old in ("socks5h://llm_tor:9050", "socks5h://llm_warp:1080"):
            if _old != _proxy:
                txt = txt.replace(_old, _proxy)
    if __import__("os").environ.get("NET_MODE", "warp").strip().lower() != "tor":
        txt = txt.replace("socks5h://llm_tor:9050", "socks5h://llm_warp:1080")
    if "method:" not in txt and "\nsearch:\n" in txt:
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


def running_mode():
    r = _run([
        "inspect", "-f",
        '{{index .Config.Labels "localai.search.mode"}}',
        CONTAINER,
    ], timeout=20)
    if not (r and r.returncode == 0):
        return None
    value = (r.stdout or "").strip()
    return value or None


def _wait_ready(timeout=BOOT_TIMEOUT, log_path=None, log=None, cancel_check=None) -> bool:
    import socket
    end = time.time() + timeout
    waited = 0
    while time.time() < end:
        if _cancelled(cancel_check):
            _log(log_path, "WARN", "사용자가 취소했습니다 — 기동 대기 중단", log)
            return False
        try:
            with socket.create_connection(("127.0.0.1", int(HOST_PORT)), timeout=2):
                return True
        except Exception:
            time.sleep(1)
            waited += 1
            if waited % 5 == 0:
                _log(log_path, "INFO", "기동 대기 중... %d/%d초" % (waited, timeout), log)
    return False


def start(env, log_path=None, with_tor=True, log=None, cancel_check=None) -> bool:
    """SearXNG 기동. 현재 네트워크 모드와 맞는 컨테이너만 재사용한다."""
    _register_exit_cleanup()
    _net_mode = __import__("os").environ.get("NET_MODE", "warp").strip().lower()
    if is_running():
        active = running_mode()
        if active == _net_mode:
            return True
        _log(log_path, "INFO",
             "기존 SearXNG 네트워크 모드가 달라 재생성합니다: %s -> %s"
             % (active or "unknown", _net_mode), log)
        remove()
    _ensure_net()
    if _net_mode != "tor":
        try:
            from . import warp_runtime  # type: ignore
        except Exception:
            warp_runtime = None
        if warp_runtime is not None:
            try:
                if not warp_runtime.start(env, log_path=log_path, log=log,
                                          cancel_check=cancel_check):
                    _log(log_path, "WARN",
                         "WARP 미기동 - 검색이 실패할 수 있습니다. "
                         "NET_MODE=tor 로 전환하거나 WARP 를 설치하세요.", log)
            except Exception as _e:
                _log(log_path, "WARN", "WARP 기동 예외: " + str(_e)[:120], log)

    if with_tor and _net_mode == "tor":
        try:
            from . import tor_runtime  # type: ignore
        except Exception:
            tor_runtime = None
        if tor_runtime is not None:
            try:
                if not tor_runtime.start(
                        env, log=lambda m: _log(log_path, "INFO", "Tor: " + str(m), log)):
                    _log(log_path, "WARN",
                         "Tor 미기동 (이미지 없음 등) — 검색이 실패할 수 있습니다. "
                         "docker pull %s 후 재시도" % getattr(tor_runtime, "TOR_IMAGE", "tor"), log)
            except Exception as e:
                _log(log_path, "WARN", "Tor 기동 예외: %r" % e, log)

    if not image_exists():
        _log(log_path, "WARN", "이미지 없음: %s (Setup / Repair 에서 받으세요)" % IMAGE, log)
        return False

    cfg = _cfg_dir(env)
    if not (cfg / "settings.yml").exists():
        _log(log_path, "WARN", "settings.yml 없음: %s (Setup / Repair 필요)" % str(cfg / "settings.yml"), log)
        return False

    _harden_settings(cfg, log_path)

    if container_exists():
        remove()

    r = _run([
        "run", "-d", "--rm",
        "--name", CONTAINER,
        "--label", "localai.search.mode=" + _net_mode,
        "--network", NETWORK,
        "-p", "127.0.0.1:%d:%d" % (int(HOST_PORT), CONTAINER_PORT),
        "-v", "%s:/etc/searxng" % str(cfg),
        "--add-host=host.docker.internal:host-gateway",
        IMAGE,
    ], timeout=45)
    if not (r and r.returncode == 0):
        _log(log_path, "ERROR", "docker run 실패: %s"
             % ((r.stderr or "").strip()[:160] if r else "docker 응답 없음"), log)
        return False

    ok = _wait_ready(log_path=log_path, log=log, cancel_check=cancel_check)
    _log(log_path, "INFO" if ok else "WARN",
         "기동 %s (port %s)" % ("완료" if ok else "타임아웃", HOST_PORT), log)
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
