import pytest

from launcher import anythingllm_runtime as runtime


def test_block_is_a_distinct_canonical_mode(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "block")
    monkeypatch.setenv("NET_MODE", "block")
    monkeypatch.setattr(runtime._cfg, "NET_MODE", "block", raising=False)

    assert runtime.net_mode() == "block"


def test_protected_start_stops_before_container_when_proxy_stack_fails(monkeypatch):
    monkeypatch.setattr(runtime, "net_mode", lambda: "warp")
    monkeypatch.setattr(runtime, "ensure_proxy_stack", lambda **kwargs: False)
    monkeypatch.setattr(
        runtime,
        "is_running",
        lambda: pytest.fail("protected startup must fail before inspecting/reusing the container"),
    )

    assert runtime.start() is False


def test_protected_mode_fails_closed_when_network_awareness_is_disabled(monkeypatch):
    monkeypatch.setattr(runtime, "NET_AWARE", False)
    monkeypatch.setattr(runtime, "net_mode", lambda: "tor")

    assert runtime.ensure_proxy_stack() is False


def test_block_container_environment_has_mode_marker_without_proxy_routes(monkeypatch):
    monkeypatch.setattr(runtime, "net_mode", lambda: "block")

    env = runtime.proxy_env_for_container("block")

    assert env["LOCAL_AI_NETWORK_MODE"] == "block"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert not env.get(key)


def test_block_run_command_uses_internal_network_and_loopback_port(monkeypatch):
    policy = runtime._network_policy()
    monkeypatch.setattr(runtime, "net_mode", lambda: "block")
    monkeypatch.setattr(policy, "block_network_name", lambda: "llm_block_net")

    cmd = runtime.build_run_cmd(memory="2g", cpus="1")

    assert cmd[cmd.index("--network") + 1] == "llm_block_net"
    assert "127.0.0.1:%d:%d" % (runtime.HOST_PORT, runtime.CONTAINER_PORT) in cmd
    assert "LOCAL_AI_NETWORK_MODE=block" in cmd


def test_warp_run_command_keeps_shared_proxy_network(monkeypatch):
    monkeypatch.setattr(runtime, "net_mode", lambda: "warp")

    cmd = runtime.build_run_cmd(memory="2g", cpus="1")

    assert cmd[cmd.index("--network") + 1] == runtime.NETWORK


def test_block_start_fails_before_container_when_internal_network_is_unavailable(monkeypatch):
    policy = runtime._network_policy()
    monkeypatch.setattr(runtime, "register_exit_cleanup", lambda: None)
    monkeypatch.setattr(runtime, "net_mode", lambda: "block")
    monkeypatch.setattr(policy, "ensure_block_network", lambda **kwargs: False)
    monkeypatch.setattr(
        runtime,
        "is_running",
        lambda: pytest.fail("Block startup must fail before inspecting/reusing the container"),
    )

    assert runtime.start() is False


def test_protected_node_bootstrap_has_no_direct_fetch_fallback():
    source = runtime._NODE_BOOTSTRAP_JS

    assert "fetch 는 직접 나갑니다" not in source
    assert "process.exit" in source or "throw new Error" in source
