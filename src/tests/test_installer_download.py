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
