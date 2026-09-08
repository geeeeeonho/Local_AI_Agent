import importlib

import pytest


def _policy():
    try:
        return importlib.import_module("launcher.network_policy")
    except ModuleNotFoundError as exc:
        pytest.fail(f"canonical network policy module is missing: {exc}")


def test_network_mode_has_exactly_four_canonical_values():
    policy = _policy()
    assert {mode.value for mode in policy.NetworkMode} == {
        "warp", "tor", "direct", "block",
    }


def test_legacy_none_alias_normalizes_to_direct():
    policy = _policy()
    assert policy.normalize_mode("none") is policy.NetworkMode.DIRECT
    assert policy.normalize_mode("DIRECT") is policy.NetworkMode.DIRECT


def test_host_warp_uses_published_bridge_and_socks_ports():
    policy = _policy()
    env = policy.host_proxy_env("warp")
    assert env["LOCAL_AI_NETWORK_MODE"] == "warp"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8119"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8119"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:1080"
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "localhost" in env["NO_PROXY"]


def test_host_tor_uses_privoxy_and_tor_socks_ports():
    policy = _policy()
    env = policy.host_proxy_env("tor")
    assert env["LOCAL_AI_NETWORK_MODE"] == "tor"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8118"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8118"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:9050"


def test_container_warp_uses_named_http_bridge_and_warp_socks():
    policy = _policy()
    env = policy.container_proxy_env("warp")
    assert env["LOCAL_AI_NETWORK_MODE"] == "warp"
    assert env["HTTP_PROXY"] == "http://llm_httpbridge:8118"
    assert env["HTTPS_PROXY"] == "http://llm_httpbridge:8118"
    assert env["ALL_PROXY"] == "socks5h://llm_warp:1080"


def test_container_tor_uses_named_privoxy_and_tor_socks():
    policy = _policy()
    env = policy.container_proxy_env("tor")
    assert env["LOCAL_AI_NETWORK_MODE"] == "tor"
    assert env["HTTP_PROXY"] == "http://llm_tor:8118"
    assert env["HTTPS_PROXY"] == "http://llm_tor:8118"
    assert env["ALL_PROXY"] == "socks5h://llm_tor:9050"


@pytest.mark.parametrize("mode", ["direct", "block"])
def test_non_proxy_modes_carry_mode_marker_but_no_proxy_routes(mode):
    policy = _policy()
    for builder in (policy.host_proxy_env, policy.container_proxy_env):
        env = builder(mode)
        assert env == {"LOCAL_AI_NETWORK_MODE": mode}


def test_display_labels_are_derived_from_canonical_mode():
    policy = _policy()
    assert "WARP" in policy.display_label("warp")
    assert "Tor" in policy.display_label("tor")
    assert "직접" in policy.display_label("direct")
    block_label = policy.display_label("block")
    assert "차단" in block_label
    assert "완전" not in block_label


def test_set_mode_updates_environment_and_legacy_config(monkeypatch):
    policy = _policy()
    import launcher.config as config

    monkeypatch.delenv("NET_MODE", raising=False)
    monkeypatch.delenv("LOCAL_AI_NETWORK_MODE", raising=False)
    old = config.NET_MODE
    try:
        result = policy.set_mode("tor")
        assert result is policy.NetworkMode.TOR
        assert config.NET_MODE == "tor"
        assert policy.current_mode() is policy.NetworkMode.TOR
        assert __import__("os").environ["NET_MODE"] == "tor"
        assert __import__("os").environ["LOCAL_AI_NETWORK_MODE"] == "tor"
    finally:
        config.NET_MODE = old


def test_prepare_runtime_does_not_require_proxy_for_direct_or_block(monkeypatch):
    policy = _policy()
    assert policy.prepare_runtime("direct") is True
    assert policy.prepare_runtime("block") is True


def test_block_network_name_defaults_to_managed_internal_network(monkeypatch):
    policy = _policy()
    import launcher.config as config

    monkeypatch.delattr(config, "BLOCK_NETWORK", raising=False)
    assert policy.block_network_name() == "llm_block_net"


def test_block_network_is_created_as_internal_bridge():
    policy = _policy()
    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    inspections = iter([
        Result(returncode=1, stderr="not found"),
        Result(returncode=0, stdout="true|bridge\n"),
    ])

    def fake_run(args, timeout=20):
        calls.append(list(args))
        if args[:3] == ["docker", "network", "inspect"]:
            return next(inspections)
        if args[:3] == ["docker", "network", "create"]:
            return Result(returncode=0, stdout="network-id\n")
        raise AssertionError("unexpected command: %r" % (args,))

    assert policy.ensure_block_network(run=fake_run) is True
    assert [
        "docker", "network", "create", "--driver", "bridge", "--internal",
        policy.block_network_name(),
    ] in calls


def test_existing_non_internal_block_network_fails_closed():
    policy = _policy()

    class Result:
        returncode = 0
        stdout = "false|bridge\n"
        stderr = ""

    calls = []

    def fake_run(args, timeout=20):
        calls.append(list(args))
        return Result()

    assert policy.ensure_block_network(run=fake_run) is False
    assert not any(args[:3] == ["docker", "network", "create"] for args in calls)


def test_existing_non_bridge_block_network_fails_closed():
    policy = _policy()

    class Result:
        returncode = 0
        stdout = "true|overlay\n"
        stderr = ""

    assert policy.ensure_block_network(run=lambda args, timeout=20: Result()) is False


def test_running_warp_is_not_ready_when_http_bridge_cannot_be_prepared(monkeypatch):
    from launcher import warp_runtime

    monkeypatch.setattr(warp_runtime, "is_running", lambda: True)
    monkeypatch.setattr(warp_runtime, "_ensure_bridge", lambda log_path=None: False)

    assert warp_runtime.start() is False


def test_fresh_warp_is_not_ready_when_http_bridge_start_fails(monkeypatch):
    from launcher import http_bridge, warp_runtime

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(warp_runtime, "is_running", lambda: False)
    monkeypatch.setattr(warp_runtime, "image_exists", lambda: True)
    monkeypatch.setattr(warp_runtime, "_ensure_net", lambda: None)
    monkeypatch.setattr(warp_runtime, "_remove_stale", lambda: None)
    monkeypatch.setattr(warp_runtime, "_run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(warp_runtime, "_wait_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(warp_runtime, "_register_exit_cleanup", lambda: None)
    monkeypatch.setattr(http_bridge, "start", lambda log=None: False)

    assert warp_runtime.start() is False
