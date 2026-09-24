from pathlib import Path


def test_model_download_uses_detected_ollama_not_only_portable_slot(monkeypatch, tmp_path):
    from installer.steps import model
    from launcher.models import model_catalog, model_files

    official = tmp_path / "Ollama" / "ollama.exe"
    official.parent.mkdir()
    official.write_bytes(b"official")

    paths = {
        "env": tmp_path / "llm_environment",
        "ollama": tmp_path / "llm_environment" / "ollama_runtime",
        "models": tmp_path / "Ollama" / "models",
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
