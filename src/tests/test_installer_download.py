from pathlib import Path


def test_download_with_progress_works_under_pythonw(monkeypatch, tmp_path):
    from installer.core import download

    seen = {}

    def fake_urlretrieve(url, destination, reporthook=None):
        seen["url"] = url
        seen["reporthook"] = reporthook
        Path(destination).write_bytes(b"installer")
        return str(destination), None

    monkeypatch.setattr(download.urllib.request, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(download.sys, "stdout", None)

    target = tmp_path / "OllamaSetup.exe"
    download.download_with_progress("https://example.invalid/OllamaSetup.exe", target, "Ollama")

    assert target.read_bytes() == b"installer"
    assert seen["reporthook"] is None



def test_official_ollama_download_failure_returns_to_portable_fallback(monkeypatch, tmp_path):
    from installer.steps import ollama

    class Temp:
        name = str(tmp_path / "OllamaSetup.exe")
        def close(self):
            pass

    monkeypatch.setattr(ollama, "_is_windows", lambda: True)
    monkeypatch.setattr(ollama.tempfile, "NamedTemporaryFile", lambda **_kw: Temp())
    monkeypatch.setattr(
        ollama.utils, "download_with_progress",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("network unavailable")),
    )

    assert ollama.install_official(tmp_path / "Ollama") is None
    assert not (tmp_path / "OllamaSetup.exe").exists()


def test_install_uses_portable_when_official_ollama_is_unavailable(monkeypatch, tmp_path):
    from installer.steps import ollama

    portable = tmp_path / "runtime"
    portable.mkdir()
    paths = {"ollama": portable, "models": tmp_path / "models"}
    calls = []

    monkeypatch.setattr(ollama, "find_existing", lambda _paths: None)
    monkeypatch.setattr(ollama, "install_official", lambda target, models: None)

    def install_portable(_paths):
        calls.append("portable")
        (portable / "ollama.exe").write_bytes(b"portable")

    monkeypatch.setattr(ollama, "install_portable", install_portable)

    result = ollama.install(paths)
    assert result == portable / "ollama.exe"
    assert calls == ["portable"]
