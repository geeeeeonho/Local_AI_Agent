import json

from installer.steps import sandbox


def test_dockerfile_uses_pinned_standalone_interpreter_and_labels():
    text = sandbox.DOCKERFILE
    assert "rust-v0.0.38/scripts/install/install.sh" in text
    assert "OPEN_INTERPRETER_RELEASE=0.0.38" in text
    assert "OPEN_INTERPRETER_NONINTERACTIVE=1" in text
    assert "OPEN_INTERPRETER_INSTALL_DIR=/home/agent/.local/bin" in text
    assert "INTERPRETER_HOME=/home/agent/.openinterpreter-package" in text
    assert 'local-ai-agent.runtime="app-server"' in text
    assert 'local-ai-agent.open-interpreter-version="0.0.38"' in text
    assert "interpreter --version" in text
    assert "pip install --user --no-cache-dir open-interpreter" not in text


def test_current_runtime_image_requires_exact_labels(monkeypatch):
    class Result:
        returncode = 0
        stdout = json.dumps({
            "local-ai-agent.runtime": "app-server",
            "local-ai-agent.open-interpreter-version": "0.0.38",
        })
        stderr = ""

    monkeypatch.setattr(sandbox.subprocess, "run", lambda *args, **kwargs: Result())
    assert sandbox._image_has_current_runtime(sandbox.IMAGE_NAME) is True

    Result.stdout = json.dumps({
        "local-ai-agent.runtime": "app-server",
        "local-ai-agent.open-interpreter-version": "0.0.37",
    })
    assert sandbox._image_has_current_runtime(sandbox.IMAGE_NAME) is False

    Result.stdout = json.dumps({})
    assert sandbox._image_has_current_runtime(sandbox.IMAGE_NAME) is False


def test_runtime_image_detection_fails_closed_on_docker_error(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("docker unavailable")

    monkeypatch.setattr(sandbox.subprocess, "run", fail)
    assert sandbox._image_has_current_runtime(sandbox.IMAGE_NAME) is False
