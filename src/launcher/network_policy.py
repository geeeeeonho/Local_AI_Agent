"""Canonical product network policy for Local_AI_Agent.

This module owns the meaning of the four user-visible network modes. Runtime
modules own service-specific health checks, while generic Docker CLI mechanics
are delegated to :class:`launcher.services.docker.DockerService`.

Host and container endpoints are deliberately separate. WARP in particular
uses a Host-published HTTP bridge on 127.0.0.1:8119 while containers reach the
same bridge as llm_httpbridge:8118.
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Callable

from core.calls import invoke


class NetworkMode(str, Enum):
    WARP = "warp"
    TOR = "tor"
    DIRECT = "direct"
    BLOCK = "block"


_LEGACY_ALIASES = {
    "none": NetworkMode.DIRECT,
    "off": NetworkMode.DIRECT,
}


def _config():
    try:
        from . import config
    except Exception:  # pragma: no cover - package fallback for legacy entrypoints
        import launcher.config as config
    return config


def normalize_mode(value=None) -> NetworkMode:
    """Return one canonical mode.

    Unknown legacy input falls back to the configured/default WARP posture.
    Internal callers should persist only ``NetworkMode.value`` values.
    """
    if isinstance(value, NetworkMode):
        return value
    if value is None:
        cfg = _config()
        value = (
            os.environ.get("LOCAL_AI_NETWORK_MODE")
            or os.environ.get("NET_MODE")
            or getattr(cfg, "NET_MODE", "warp")
            or "warp"
        )
    raw = str(value).strip().lower()
    if raw in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[raw]
    try:
        return NetworkMode(raw)
    except ValueError:
        return NetworkMode.WARP


def current_mode() -> NetworkMode:
    return normalize_mode(None)


def set_mode(value) -> NetworkMode:
    """Persist the selected mode to all current compatibility boundaries."""
    mode = normalize_mode(value)
    os.environ["NET_MODE"] = mode.value
    os.environ["LOCAL_AI_NETWORK_MODE"] = mode.value
    try:
        _config().NET_MODE = mode.value
    except Exception:
        pass
    return mode


def display_label(value) -> str:
    mode = normalize_mode(value)
    return {
        NetworkMode.WARP: "WARP 경유 (빠름)",
        NetworkMode.TOR: "Tor 경유 (최고 익명)",
        NetworkMode.DIRECT: "직접 연결 (IP 노출)",
        NetworkMode.BLOCK: "차단 (관리형 웹 접근 비활성)",
    }[mode]


def allows_public_egress(value) -> bool:
    return normalize_mode(value) is not NetworkMode.BLOCK


def block_network_name() -> str:
    """Return the product-managed Docker network used for hard Block mode."""
    return str(getattr(_config(), "BLOCK_NETWORK", "llm_block_net") or "llm_block_net")


def quiesce_block_relays(log: Callable[[str], None] | None = None) -> bool:
    """Stop product-managed Host relays before entering Block mode.

    ``--internal`` intentionally keeps the Docker Host gateway reachable so the
    sandbox can use Host Ollama. A previously running WARP/Tor/SearXNG relay
    could otherwise turn that same Host gateway into an indirect public-egress
    path. Block preparation therefore stops every product-managed relay and
    strictly re-checks Docker state before the internal network is accepted.

    Docker state inspection failure is treated as unsafe: Block startup must
    fail closed rather than assume a relay is absent.
    """
    cfg = _config()
    relays = [
        ("SearXNG", str(getattr(cfg, "SEARXNG_CONTAINER", "llm_searxng"))),
        ("HTTP bridge", str(getattr(cfg, "HTTP_BRIDGE_CONTAINER", "llm_httpbridge"))),
        ("WARP", str(getattr(cfg, "WARP_CONTAINER", "llm_warp"))),
        ("Tor", str(getattr(cfg, "TOR_CONTAINER", "llm_tor"))),
    ]

    def _say(message: str) -> None:
        if log is None:
            return
        try:
            log(message)
        except Exception:
            pass

    try:
        from .services.docker import DockerService
    except Exception as exc:
        _say("Block relay 정리 준비 실패: " + type(exc).__name__)
        return False

    def _running(name: str) -> bool | None:
        try:
            result = DockerService.run(
                ["ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
                timeout=10,
            )
        except Exception:
            return None
        if result is None or getattr(result, "returncode", 1) != 0:
            return None
        return name in str(getattr(result, "stdout", "") or "").split()

    for label, name in relays:
        state = _running(name)
        if state is None:
            _say("Block relay 상태를 확인할 수 없습니다: " + label)
            return False
        if not state:
            continue
        _say("Block 진입 전 관리형 relay 종료: " + label)
        try:
            stopped = DockerService.stop_container(name, timeout=5)
        except Exception:
            stopped = False
        if not stopped:
            _say("Block relay 종료 실패: " + label)
            return False

    for label, name in relays:
        state = _running(name)
        if state is None:
            _say("Block relay 종료 상태를 검증할 수 없습니다: " + label)
            return False
        if state:
            _say("Block relay가 아직 실행 중입니다: " + label)
            return False
    return True


def ensure_block_network(run=None, log: Callable[[str], None] | None = None) -> bool:
    """Ensure Block mode uses an externally isolated Docker bridge.

    A pre-existing network with the managed name is accepted only when Docker
    reports both ``Internal=true`` and ``Driver=bridge``. Unsafe properties are
    never mutated in place or silently replaced: startup callers can therefore
    fail closed instead of accidentally joining a routable network.

    Production calls also quiesce all product-managed Host egress relays before
    accepting the network. ``run`` remains an injection seam for pure topology
    contract tests/diagnostics and deliberately skips that live-service side
    effect. Production calls use the canonical :class:`DockerService` network
    primitives.
    """
    name = block_network_name()
    format_string = "{{.Internal}}|{{.Driver}}"

    def _say(message: str) -> None:
        if log is None:
            return
        try:
            log(message)
        except Exception:
            pass

    if run is None and not quiesce_block_relays(log=log):
        _say("Block 진입 전 관리형 relay를 안전하게 종료하지 못했습니다.")
        return False

    try:
        if run is not None:
            inspect_cmd = [
                "docker", "network", "inspect", "--format", format_string, name,
            ]
            inspected = run(inspect_cmd, timeout=20)
            if getattr(inspected, "returncode", 1) != 0:
                created = run(
                    [
                        "docker", "network", "create", "--driver", "bridge",
                        "--internal", name,
                    ],
                    timeout=30,
                )
                if getattr(created, "returncode", 1) != 0:
                    _say("Block 네트워크 생성 실패: " + name)
                    return False
                inspected = run(inspect_cmd, timeout=20)
        else:
            from .services.docker import DockerService

            inspected = DockerService.network_inspect(
                name,
                format=format_string,
                timeout=20,
            )
            if getattr(inspected, "returncode", 1) != 0:
                created = DockerService.network_create(
                    name,
                    driver="bridge",
                    internal=True,
                    timeout=30,
                )
                if getattr(created, "returncode", 1) != 0:
                    _say("Block 네트워크 생성 실패: " + name)
                    return False
                inspected = DockerService.network_inspect(
                    name,
                    format=format_string,
                    timeout=20,
                )

        if getattr(inspected, "returncode", 1) != 0:
            _say("Block 네트워크 검사 실패: " + name)
            return False
        properties = str(getattr(inspected, "stdout", "") or "").strip().lower()
        if properties != "true|bridge":
            _say("Block 네트워크가 안전한 internal bridge가 아닙니다: " + name)
            return False
        return True
    except Exception as exc:
        _say("Block 네트워크 준비 실패: " + type(exc).__name__)
        return False


def _no_proxy() -> str:
    cfg = _config()
    base = str(getattr(cfg, "NO_PROXY_HOSTS", "host.docker.internal,localhost,127.0.0.1,::1"))
    values = [part.strip() for part in base.split(",") if part.strip()]
    for required in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
        if required not in values:
            values.append(required)
    return ",".join(values)


def _proxy_env(mode: NetworkMode, *, http_proxy: str, socks_proxy: str) -> dict[str, str]:
    env = {"LOCAL_AI_NETWORK_MODE": mode.value}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[key] = http_proxy
    for key in ("ALL_PROXY", "all_proxy"):
        env[key] = socks_proxy
    no_proxy = _no_proxy()
    env["NO_PROXY"] = no_proxy
    env["no_proxy"] = no_proxy
    return env


def host_proxy_env(value) -> dict[str, str]:
    """Environment for processes running directly on the Host OS."""
    mode = normalize_mode(value)
    cfg = _config()
    if mode is NetworkMode.WARP:
        http_port = int(getattr(cfg, "HTTP_BRIDGE_HOST_PORT", 8119))
        socks_port = int(getattr(cfg, "WARP_PORT", 1080))
        return _proxy_env(
            mode,
            http_proxy=f"http://127.0.0.1:{http_port}",
            socks_proxy=f"socks5h://127.0.0.1:{socks_port}",
        )
    if mode is NetworkMode.TOR:
        http_port = int(getattr(cfg, "TOR_HTTP_PORT", 8118))
        socks_port = int(getattr(cfg, "TOR_SOCKS_PORT", 9050))
        return _proxy_env(
            mode,
            http_proxy=f"http://127.0.0.1:{http_port}",
            socks_proxy=f"socks5h://127.0.0.1:{socks_port}",
        )
    return {"LOCAL_AI_NETWORK_MODE": mode.value}


def container_proxy_env(value) -> dict[str, str]:
    """Environment for managed containers on ``LLM_NETWORK``."""
    mode = normalize_mode(value)
    cfg = _config()
    if mode is NetworkMode.WARP:
        bridge = str(getattr(cfg, "HTTP_BRIDGE_CONTAINER", "llm_httpbridge"))
        bridge_port = int(getattr(cfg, "HTTP_BRIDGE_PORT", 8118))
        warp = str(getattr(cfg, "WARP_CONTAINER", "llm_warp"))
        socks_port = int(getattr(cfg, "WARP_PORT", 1080))
        return _proxy_env(
            mode,
            http_proxy=f"http://{bridge}:{bridge_port}",
            socks_proxy=f"socks5h://{warp}:{socks_port}",
        )
    if mode is NetworkMode.TOR:
        tor = str(getattr(cfg, "TOR_CONTAINER", "llm_tor"))
        http_port = int(getattr(cfg, "TOR_HTTP_PORT", 8118))
        socks_port = int(getattr(cfg, "TOR_SOCKS_PORT", 9050))
        return _proxy_env(
            mode,
            http_proxy=f"http://{tor}:{http_port}",
            socks_proxy=f"socks5h://{tor}:{socks_port}",
        )
    return {"LOCAL_AI_NETWORK_MODE": mode.value}


def prepare_runtime(value, *, env_path=None, log: Callable[[str], None] | None = None,
                    cancel: Callable[[], bool] | None = None) -> bool:
    """Ensure the selected protected proxy runtime is ready.

    The selected product mode is persisted separately through :func:`set_mode`.
    Runtime preparation itself is side-effect free with respect to global mode,
    which prevents one readiness probe from changing later policy decisions.
    """
    mode = normalize_mode(value)
    if mode in (NetworkMode.DIRECT, NetworkMode.BLOCK):
        return True
    try:
        if mode is NetworkMode.WARP:
            try:
                from . import warp_runtime as runtime
            except Exception:  # pragma: no cover
                from launcher import warp_runtime as runtime
        else:
            try:
                from . import tor_runtime as runtime
            except Exception:  # pragma: no cover
                from launcher import tor_runtime as runtime
        # WARP used to be called without ``log`` and the TypeError fallback hid
        # that its progress never reached the caller at all.
        return bool(invoke(runtime.start, env_path, log=log, cancel_check=cancel))
    except Exception as exc:
        if log is not None:
            try:
                log("network runtime preparation failed: %s" % type(exc).__name__)
            except Exception:
                pass
        return False


__all__ = [
    "NetworkMode",
    "normalize_mode",
    "current_mode",
    "set_mode",
    "display_label",
    "allows_public_egress",
    "block_network_name",
    "quiesce_block_relays",
    "ensure_block_network",
    "host_proxy_env",
    "container_proxy_env",
    "prepare_runtime",
]
