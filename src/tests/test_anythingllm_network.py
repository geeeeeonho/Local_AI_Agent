import pytest

from launcher import anythingllm_runtime as runtime


def test_block_is_a_distinct_canonical_mode(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "block")
    monkeypatch.setenv("NET_MODE", "block")
    assert runtime.net_mode() == "block"


def test_protected_start_stops_before_container_when_proxy_stack_fails(monkeypatch):
    monkeypatch.setattr(runtime, "net_mode", lambda: "warp")
    monkeypatch.setattr(runtime, "ensure_proxy_stack", lambda **kwargs: False)
    monkeypatch.setattr(
        runtime,
        "is_running",
        lambda: pytest.fail("container state must not be inspected after proxy preparation failed"),
    )

    assert runtime.start() is False


def test_block_container_environment_has_mode_marker_without_proxy_routes(monkeypatch):
    monkeypatch.setattr(runtime, "net_mode", lambda: "block")
    env = runtime.proxy_env_for_container("block")
    assert env.get("LOCAL_AI_NETWORK_MODE") == "block"
    assert not env.get("HTTP_PROXY")
    assert not env.get("HTTPS_PROXY")
    assert not env.get("ALL_PROXY")
