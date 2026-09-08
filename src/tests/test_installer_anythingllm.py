from pathlib import Path


def test_anythingllm_install_prepares_docker_before_image_probe(monkeypatch, tmp_path):
    from installer.steps import python_tools
    from launcher import anythingllm_runtime
    from launcher.services.docker import DockerService

    calls = []
    monkeypatch.setattr(
        DockerService,
        "ensure_daemon",
        staticmethod(lambda **kwargs: calls.append("docker") or True),
    )
    monkeypatch.setattr(
        anythingllm_runtime,
        "image_exists",
        lambda: calls.append("image") or True,
    )

    assert python_tools.install_anythingllm({"env": tmp_path}) is True
    assert calls[:2] == ["docker", "image"]


def test_installer_manifest_only_records_successful_transition_components():
    root = Path(__file__).resolve().parents[1]
    source = (root / "installer" / "__main__.py").read_text(encoding="utf-8")

    assert "if python_tools.install_anythingllm(paths, profile):" in source
    assert "if python_tools.install_open_interpreter(paths, profile):" in source
