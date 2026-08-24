import json

import launcher.config as config
from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.sandbox_backend import (
    SANDBOX_OI_LABEL,
    SANDBOX_RUNTIME_LABEL,
    SandboxOpenInterpreterBackend,
    sandbox_image_supports_app_server,
    transform_legacy_sandbox_command,
)


def _legacy_command():
    return [
        "docker", "run", "--rm", "-i",
        "--name", "llm_agent_chat_test",
        "-v", "C:/work:/home/agent/workspace",
        "-v", "C:/state:/home/agent/.agent_state",
        "-v", "C:/allowed:/home/agent/allowed/0",
        "--tmpfs", "/home/agent/allowed/0/private",
        "--add-host=host.docker.internal:host-gateway",
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "AGENT_REPL_SRC=huge-legacy-payload",
        "-e", "AGENT_MODEL_LADDER=[]",
        "-e", "LITELLM_LOG=ERROR",
        "-e", "HTTP_PROXY=socks5h://llm_warp:1080",
        "-e", "NO_PROXY=old-value",
        "-e", "PYTHONPATH=/old",
        "--network", "llm_net",
        "--cpus=2.5",
        "--memory=6g",
        config.SANDBOX_IMAGE,
        "python3", "-c", "legacy-bootstrap",
        "--model", "ollama/qwen3:8b",
    ]


def test_transform_preserves_outer_security_and_replaces_only_runtime_tail():
    transformed = transform_legacy_sandbox_command(_legacy_command())
    joined = " ".join(transformed)

    assert transformed[:2] == ["docker", "run"]
    assert "C:/work:/home/agent/workspace" in transformed
    assert "C:/allowed:/home/agent/allowed/0" in transformed
    assert "/home/agent/allowed/0/private" in transformed
    assert "--add-host=host.docker.internal:host-gateway" in transformed
    assert "HTTP_PROXY=socks5h://llm_warp:1080" in transformed
    assert "--network" in transformed and "llm_net" in transformed
    assert "--cpus=2.5" in transformed
    assert "--memory=6g" in transformed

    assert "AGENT_REPL_SRC=" not in joined
    assert "AGENT_MODEL_LADDER=" not in joined
    assert "LITELLM_LOG=" not in joined
    assert "python3" not in transformed[transformed.index(config.SANDBOX_IMAGE) + 1:]
    assert "legacy-bootstrap" not in transformed

    assert "INTERPRETER_HOME=/home/agent/.agent_state/open_interpreter" in transformed
    assert "CODEX_OSS_BASE_URL=http://host.docker.internal:11434/v1" in transformed
    assert "NO_PROXY=host.docker.internal,localhost,127.0.0.1,::1,llm_searxng" in transformed
    assert "no_proxy=host.docker.internal,localhost,127.0.0.1,::1,llm_searxng" in transformed
    assert "SEARXNG_URL=http://llm_searxng:8080" in transformed
    assert "PYTHONPATH=/home/agent/.agent_state" in transformed
    assert "NO_PROXY=old-value" not in transformed
    assert "PYTHONPATH=/old" not in transformed

    tail = transformed[transformed.index(config.SANDBOX_IMAGE):]
    assert tail == [
        config.SANDBOX_IMAGE,
        "interpreter",
        "-c", "check_for_update_on_startup=false",
        "-c", 'web_search="disabled"',
        "app-server", "--listen", "stdio://",
    ]

    for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
        assert forbidden not in joined


def test_transform_rejects_non_sandbox_command():
    try:
        transform_legacy_sandbox_command(["python", "agent.py"])
    except ValueError as exc:
        assert "docker run" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_image_label_detection_requires_both_exact_labels(monkeypatch):
    import launcher.agent.sandbox_backend as module

    class Result:
        returncode = 0
        stdout = json.dumps({
            SANDBOX_RUNTIME_LABEL: "app-server",
            SANDBOX_OI_LABEL: "0.0.38",
        })
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: Result())
    assert sandbox_image_supports_app_server(config.SANDBOX_IMAGE) is True

    Result.stdout = json.dumps({
        SANDBOX_RUNTIME_LABEL: "app-server",
        SANDBOX_OI_LABEL: "0.0.37",
    })
    assert sandbox_image_supports_app_server(config.SANDBOX_IMAGE) is False


def test_sandbox_backend_uses_outer_docker_and_inner_danger_full_access(tmp_path, monkeypatch):
    import launcher.agent.sandbox_backend as module

    monkeypatch.setattr(module, "sandbox_image_supports_app_server", lambda image=None: True)
    backend = SandboxOpenInterpreterBackend(client_factory=lambda *args: None)
    cfg = AgentConfig(
        workspace=tmp_path,
        mode="sandbox",
        model="qwen3:8b",
        network_mode="block",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(command=tuple(_legacy_command())),
        instructions="coding profile",
    )
    command, env, cwd = backend._client_spec(cfg)
    assert command[0:2] == ["docker", "run"]
    assert backend._thread_sandbox_mode(cfg) == "danger-full-access"
    assert backend._thread_cwd(cfg) == "/home/agent/workspace"
    assert cwd == tmp_path.resolve()
    params = backend._thread_params(cfg)
    assert params["sandbox"] == "danger-full-access"
    assert params["approvalPolicy"] == "on-request"
    assert "Local_AI_Agent Docker sandbox" in params["developerInstructions"]
    assert "■ 현재 세션 정보" in params["developerInstructions"]
    assert str(tmp_path) in params["developerInstructions"]
    assert "/home/agent/workspace" in params["developerInstructions"]


def test_sandbox_stop_explicitly_stops_and_removes_container(tmp_path, monkeypatch):
    import launcher.agent.sandbox_backend as module

    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: calls.append(command))
    backend = SandboxOpenInterpreterBackend(client_factory=lambda *args: None)
    backend._container_name = "llm_agent_chat_test"
    backend.stop(timeout=1.0)
    assert ["docker", "stop", "-t", "2", "llm_agent_chat_test"] in calls
    assert ["docker", "rm", "-f", "llm_agent_chat_test"] in calls
