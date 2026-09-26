from pathlib import Path


def test_model_download_uses_localai_shared_broker(monkeypatch, tmp_path):
    from installer.steps import model
    from launcher.models import model_catalog, model_files

    official = tmp_path / "LocalAI" / "ollama" / "ollama.exe"
    official.parent.mkdir()
    official.write_bytes(b"official")

    paths = {
        "env": tmp_path / "LocalAI" / "environment",
        "ollama": tmp_path / "LocalAI" / "ollama",
        "models": tmp_path / "LocalAI" / "models",
    }

    seen = {}

    monkeypatch.setattr(model.ollama, "find_existing", lambda _paths: official)
    monkeypatch.setattr(model.ollama, "env_for", lambda _paths: {})

    def installed(exe, env):
        seen["exe"] = Path(exe)
        return set()

    monkeypatch.setattr(model, "_installed", installed)
    monkeypatch.setattr(model, "_load_models", lambda: [])
    monkeypatch.setattr(model_catalog, "all_entries", lambda: [])
    monkeypatch.setattr(model_files, "refresh", lambda _path: None)

    assert model.download(paths) == []
    assert seen["exe"] == official
    assert not (paths["ollama"] / "ollama.exe").exists()



def test_official_installer_inherits_shared_model_store(monkeypatch, tmp_path):
    from installer.steps import ollama as step
    from installer import utils

    target = tmp_path / "LocalAI" / "ollama"
    target.mkdir(parents=True)
    store = tmp_path / "LocalAI" / "models"
    installer = tmp_path / "OllamaSetup.exe"

    class Handle:
        name = str(installer)
        def close(self):
            pass

    class Result:
        returncode = 0

    seen = {}
    monkeypatch.setattr(step, "_is_windows", lambda: True)
    monkeypatch.setattr(step.tempfile, "NamedTemporaryFile", lambda **kwargs: Handle())
    monkeypatch.setattr(utils, "download_with_progress",
                        lambda url, destination, label: Path(destination).write_bytes(b"setup"))

    def run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        (target / "ollama.exe").write_bytes(b"managed")
        return Result()

    monkeypatch.setattr(step.subprocess, "run", run)

    found = step.install_official(target, store)
    assert found == target / "ollama.exe"
    assert seen["env"]["OLLAMA_MODELS"] == str(store)
    assert any(str(target) in part for part in seen["command"])


def test_official_install_never_falls_back_to_external_executable(monkeypatch, tmp_path):
    from installer.steps import ollama as step
    from installer import utils

    target = tmp_path / "LocalAI" / "ollama"
    target.mkdir(parents=True)
    store = tmp_path / "LocalAI" / "models"
    installer = tmp_path / "OllamaSetup.exe"

    class Handle:
        name = str(installer)
        def close(self):
            pass

    class Result:
        returncode = 0

    monkeypatch.setattr(step, "_is_windows", lambda: True)
    monkeypatch.setattr(step.tempfile, "NamedTemporaryFile", lambda **kwargs: Handle())
    monkeypatch.setattr(utils, "download_with_progress",
                        lambda url, destination, label: Path(destination).write_bytes(b"setup"))
    monkeypatch.setattr(step.subprocess, "run", lambda *a, **k: Result())

    assert step.install_official(target, store) is None
