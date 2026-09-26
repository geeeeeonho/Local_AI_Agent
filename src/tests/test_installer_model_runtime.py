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
