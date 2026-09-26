from pathlib import Path

from installer.core.filesystem import create_environment
from installer.steps import python_tools


def test_environment_contains_shared_binary_and_private_interpreter_home(tmp_path):
    env = tmp_path / "LocalAI" / "environment"
    account = tmp_path / "LocalAI" / "users" / "Tester"
    paths = create_environment(
        env,
        model_dir=tmp_path / "LocalAI" / "models",
        account_root=account,
    )
    assert paths["open_interpreter"] == env / "open_interpreter"
    assert paths["open_interpreter_bin"] == env / "open_interpreter" / "bin"
    assert paths["open_interpreter_home"] == account / "user_data" / "interpreter" / "host"


def test_install_script_and_release_are_pinned():
    assert python_tools.OPEN_INTERPRETER_VERSION == "0.0.38"
    assert "rust-v0.0.38" in python_tools.OPEN_INTERPRETER_INSTALL_SCRIPT


def test_managed_install_passes_product_scoped_environment(monkeypatch, tmp_path):
    env_root = tmp_path / "llm_environment"
    paths = {
        "env": env_root,
        "agent": env_root / "agent",
        "open_interpreter": env_root / "open_interpreter",
        "open_interpreter_bin": env_root / "open_interpreter" / "bin",
        "open_interpreter_home": env_root / "open_interpreter" / "home",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    downloaded = []
    calls = []

    def fake_download(url, destination):
        downloaded.append((url, Path(destination)))
        Path(destination).write_text("# installer", encoding="utf-8")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    versions = iter([None, "0.0.38"])
    monkeypatch.setattr(python_tools, "_download_file", fake_download)
    monkeypatch.setattr(python_tools.subprocess, "run", fake_run)
    monkeypatch.setattr(python_tools, "_installed_interpreter_version", lambda _exe: next(versions))

    assert python_tools.install_open_interpreter(paths) is True
    assert downloaded[0][0] == python_tools.OPEN_INTERPRETER_INSTALL_SCRIPT
    install_call = calls[0]
    env = install_call[1]["env"]
    assert env["OPEN_INTERPRETER_RELEASE"] == "0.0.38"
    assert env["OPEN_INTERPRETER_NONINTERACTIVE"] == "1"
    assert env["OPEN_INTERPRETER_INSTALL_DIR"] == str(paths["open_interpreter_bin"])
    assert env["INTERPRETER_HOME"] == str(paths["open_interpreter_home"])
    assert not any("pip" in str(part).lower() for part in install_call[0])
