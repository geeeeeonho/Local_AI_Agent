from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from launcher.services import docker as docker_module
from launcher.services.docker import DockerService


def test_generic_run_prefixes_docker_and_preserves_common_options(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(docker_module.subprocess, "run", fake_run)

    result = DockerService.run(
        ["network", "inspect", "llm_net"],
        timeout=7,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    command, kwargs = calls[-1]
    assert command == ["docker", "network", "inspect", "llm_net"]
    assert kwargs["timeout"] == 7
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False


def test_network_primitives_build_canonical_commands(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout="true|bridge\n", stderr="")

    monkeypatch.setattr(DockerService, "run", staticmethod(fake_run))

    DockerService.network_inspect("llm_block_net", format="{{.Internal}}|{{.Driver}}")
    DockerService.network_create("llm_block_net", driver="bridge", internal=True)
    DockerService.network_connect("llm_net", "llm_searxng")

    assert calls[0][0] == [
        "network", "inspect", "--format", "{{.Internal}}|{{.Driver}}", "llm_block_net",
    ]
    assert calls[1][0] == [
        "network", "create", "--driver", "bridge", "--internal", "llm_block_net",
    ]
    assert calls[2][0] == ["network", "connect", "llm_net", "llm_searxng"]


def test_build_primitive_keeps_tag_dockerfile_and_context(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(DockerService, "run", staticmethod(fake_run))
    dockerfile = tmp_path / "Dockerfile"
    context = tmp_path / "context"

    DockerService.build_image("local-ai/sandbox:test", context, dockerfile=dockerfile)

    assert calls[-1][0] == [
        "build", "-t", "local-ai/sandbox:test", "-f", str(dockerfile), str(context),
    ]


def test_network_policy_default_docker_path_uses_docker_service():
    source = Path(__file__).resolve().parents[1] / "launcher" / "network_policy.py"
    text = source.read_text(encoding="utf-8")
    assert "DockerService.network_inspect" in text
    assert "DockerService.network_create" in text
    assert "subprocess.run(" not in text


def test_docker_maintenance_uses_common_cli_boundary():
    source = Path(__file__).resolve().parents[1] / "launcher" / "core" / "docker_maint.py"
    text = source.read_text(encoding="utf-8")
    assert "DockerService.run" in text
    assert "subprocess.run(" not in text


def test_console_image_build_uses_common_build_primitive():
    source = Path(__file__).resolve().parents[1] / "launcher" / "actions" / "docker_image.py"
    text = source.read_text(encoding="utf-8")
    assert "DockerService.build_image" in text
    assert "subprocess.run(cmd" not in text
