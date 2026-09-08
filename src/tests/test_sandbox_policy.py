from pathlib import Path

import pytest

import launcher.config as config
from launcher.agent.backend import AgentConfig, ProcessRuntimeSpec
from launcher.agent.sandbox_backend import SandboxOpenInterpreterBackend, normalize_sandbox_command
from launcher.agent.sandbox_policy import (
    build_sandbox_docker_command,
    build_tor_env,
)


def _command(**overrides):
    kwargs = dict(
        image=config.SANDBOX_IMAGE,
        container_name="llm_agent_test",
        workspace=Path("/tmp/ws"),
        workspace_mount="/home/agent/workspace",
        memory_limit="6g",
        cpu_limit="2.5",
        block_internet=True,
        tor_proxy=False,
        network_mode="block",
    )
    kwargs.update(overrides)
    return build_sandbox_docker_command(**kwargs)


def test_command_carries_no_retired_agent_payload():
    joined = " ".join(_command())
    assert "AGENT_REPL_SRC" not in joined
    assert "AGENT_MODEL_LADDER" not in joined
    assert "python3" not in joined
    assert "--system_message" not in joined


def test_command_runs_the_app_server_directly():
    cmd = _command()
    tail = cmd[cmd.index(config.SANDBOX_IMAGE):]
    assert tail == [
        config.SANDBOX_IMAGE,
        "interpreter",
        "-c", "check_for_update_on_startup=false",
        "-c", 'web_search="disabled"',
        "app-server", "--listen", "stdio://",
    ]


def test_transform_is_a_no_op_on_a_freshly_built_command():
    cmd = _command()
    assert normalize_sandbox_command(cmd) == normalize_sandbox_command(
        normalize_sandbox_command(cmd)
    )


def test_outer_security_flags_are_present():
    cmd = _command()
    joined = " ".join(cmd)
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd and "-i" in cmd
    assert f"{Path('/tmp/ws')}:/home/agent/workspace" in cmd
    assert "--cpus=2.5" in cmd
    assert "--memory=6g" in cmd
    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in joined


def test_blocked_mode_cuts_external_dns_and_adds_no_proxy():
    cmd = _command(network_mode="block")
    assert "--dns=0.0.0.0" in cmd
    assert not any("HTTP_PROXY=" in str(token) for token in cmd)


def test_blocked_mode_uses_managed_internal_network_and_marker():
    from launcher import network_policy

    cmd = _command(network_mode="block")
    assert cmd[cmd.index("--network") + 1] == network_policy.block_network_name()
    assert "LOCAL_AI_NETWORK_MODE=block" in cmd
    assert "--dns=0.0.0.0" in cmd
    for key in ("HTTP_PROXY=", "HTTPS_PROXY=", "ALL_PROXY=", "http_proxy=", "https_proxy=", "all_proxy="):
        assert not any(str(token).startswith(key) for token in cmd)


def test_direct_mode_does_not_inherit_the_block_dns_or_network():
    from launcher import network_policy

    cmd = _command(
        network_mode="direct",
        block_internet=True,
        tor_proxy=False,
    )
    assert "LOCAL_AI_NETWORK_MODE=direct" in cmd
    assert "--dns=0.0.0.0" not in cmd
    if "--network" in cmd:
        assert cmd[cmd.index("--network") + 1] != network_policy.block_network_name()


def test_proxy_mode_replaces_dns_block_with_proxy_env_and_joins_shared_network():
    cmd = _command(block_internet=True, tor_proxy=False, network_mode="warp")
    assert "--dns=0.0.0.0" not in cmd
    assert "LOCAL_AI_NETWORK_MODE=warp" in cmd
    assert any("PROXY=" in str(token) or "proxy=" in str(token) for token in cmd)
    assert cmd[cmd.index("--network") + 1] == config.LLM_NETWORK


def test_implicit_mode_uses_canonical_current_mode_not_legacy_booleans(monkeypatch):
    from launcher import network_policy

    monkeypatch.setattr(network_policy, "current_mode", lambda: network_policy.NetworkMode.DIRECT)
    cmd = _command(network_mode=None, block_internet=True, tor_proxy=False)
    assert "LOCAL_AI_NETWORK_MODE=direct" in cmd
    assert "--dns=0.0.0.0" not in cmd


def test_sandbox_block_start_fails_before_runtime_when_internal_network_is_unavailable(monkeypatch, tmp_path):
    from launcher import network_policy

    backend = SandboxOpenInterpreterBackend(
        client_factory=lambda *args, **kwargs: pytest.fail(
            "Block startup must fail before constructing the App Server client"
        )
    )
    monkeypatch.setattr(
        backend,
        "is_running",
        lambda: pytest.fail("Block startup must fail before entering the generic backend start flow"),
    )
    monkeypatch.setattr(network_policy, "ensure_block_network", lambda **kwargs: False)

    config_obj = AgentConfig(
        workspace=tmp_path / "workspace",
        mode="sandbox",
        model="ollama/qwen3:8b",
        network_mode="block",
        profile_name="default",
        runtime_spec=ProcessRuntimeSpec(command=("docker", "run", "image")),
    )

    assert backend.start(config_obj) is False


def test_ollama_endpoint_follows_configuration(monkeypatch):
    import launcher.agent.sandbox_backend as module

    monkeypatch.setattr(config, "OLLAMA_PORT", 21434, raising=False)
    transformed = normalize_sandbox_command(_command())
    assert "CODEX_OSS_BASE_URL=http://host.docker.internal:21434/v1" in transformed
    assert module


def test_host_proxy_env_uses_selected_warp_endpoint(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    monkeypatch.setenv("NET_MODE", "warp")
    monkeypatch.setattr(config, "NET_MODE", "warp", raising=False)
    env = build_tor_env({"EXISTING": "kept"})
    assert env["EXISTING"] == "kept"
    assert env["LOCAL_AI_NETWORK_MODE"] == "warp"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8119"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:1080"
    assert "127.0.0.1" in env["NO_PROXY"]


def test_host_proxy_env_uses_selected_tor_endpoint(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "tor")
    monkeypatch.setenv("NET_MODE", "tor")
    monkeypatch.setattr(config, "NET_MODE", "tor", raising=False)
    env = build_tor_env({})
    assert env["LOCAL_AI_NETWORK_MODE"] == "tor"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8118"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:9050"


def test_host_runtime_environment_prepares_selected_proxy(monkeypatch):
    from launcher import network_policy

    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    monkeypatch.setenv("NET_MODE", "warp")
    monkeypatch.setattr(config, "NET_MODE", "warp", raising=False)
    prepared = []
    monkeypatch.setattr(
        network_policy,
        "prepare_runtime",
        lambda mode, **kwargs: prepared.append(network_policy.normalize_mode(mode).value) or False,
    )

    env = build_tor_env()
    assert prepared == ["warp"]
    # Failure never downgrades to Direct: the selected dead proxy remains set.
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8119"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:1080"


def test_host_proxy_env_does_not_mutate_the_base_mapping(monkeypatch):
    monkeypatch.setattr(config, "NET_MODE", "warp", raising=False)
    base = {"HTTP_PROXY": "original"}
    build_tor_env(base)
    assert base == {"HTTP_PROXY": "original"}
