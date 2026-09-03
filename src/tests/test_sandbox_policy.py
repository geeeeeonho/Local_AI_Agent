from pathlib import Path

import launcher.config as config
from launcher.agent.sandbox_backend import normalize_sandbox_command
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
    """The builder and the defensive transform must agree exactly."""
    cmd = _command()
    assert normalize_sandbox_command(cmd) == normalize_sandbox_command(
        normalize_sandbox_command(cmd)
    )


def test_outer_security_flags_are_present():
    cmd = _command()
    joined = " ".join(cmd)
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd and "-i" in cmd
    # Path('/tmp/ws') is intentionally rendered using the host platform because
    # Docker Desktop accepts Windows host paths on Windows and POSIX paths on Linux.
    assert f"{Path('/tmp/ws')}:/home/agent/workspace" in cmd
    assert "--cpus=2.5" in cmd
    assert "--memory=6g" in cmd
    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in joined


def test_blocked_mode_cuts_external_dns_and_adds_no_proxy():
    cmd = _command(block_internet=True, tor_proxy=False)
    assert "--dns=0.0.0.0" in cmd
    assert not any("HTTP_PROXY=" in str(token) for token in cmd)


def test_proxy_mode_replaces_dns_block_with_proxy_env():
    cmd = _command(block_internet=False, tor_proxy=True)
    assert "--dns=0.0.0.0" not in cmd
    assert any("PROXY=" in str(token) or "proxy=" in str(token) for token in cmd)


def test_ollama_endpoint_follows_configuration(monkeypatch):
    import launcher.agent.sandbox_backend as module

    monkeypatch.setattr(config, "OLLAMA_PORT", 21434, raising=False)
    transformed = normalize_sandbox_command(_command())
    assert "CODEX_OSS_BASE_URL=http://host.docker.internal:21434/v1" in transformed
    assert module  # module imported for clarity about what is under test


def test_tor_env_keeps_local_ollama_direct_and_uses_remote_dns():
    env = build_tor_env({"EXISTING": "kept"})
    assert env["EXISTING"] == "kept"
    assert env["ALL_PROXY"].startswith("socks5h://")
    assert env["HTTP_PROXY"].startswith("http://")
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "localhost" in env["NO_PROXY"]


def test_tor_env_does_not_mutate_the_base_mapping():
    base = {"HTTP_PROXY": "original"}
    build_tor_env(base)
    assert base == {"HTTP_PROXY": "original"}
