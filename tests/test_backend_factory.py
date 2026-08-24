from pathlib import Path

import launcher.agent.backend_factory as factory


class Managed:
    pass


class Legacy:
    pass


def test_sandbox_always_uses_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "LegacyBackend", lambda: Legacy())
    monkeypatch.setattr(factory, "OpenInterpreterBackend", lambda: Managed())
    monkeypatch.setattr(factory, "managed_interpreter_exe", lambda project_root=None: tmp_path / "interpreter.exe")
    backend = factory.create_backend("sandbox", tmp_path / "llm_environment")
    assert isinstance(backend, Legacy)


def test_host_uses_managed_backend_when_binary_exists(monkeypatch, tmp_path):
    exe = tmp_path / "interpreter.exe"
    exe.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(factory, "LegacyBackend", lambda: Legacy())
    monkeypatch.setattr(factory, "OpenInterpreterBackend", lambda: Managed())
    monkeypatch.setattr(factory, "managed_interpreter_exe", lambda project_root=None: exe)
    backend = factory.create_backend("host", tmp_path / "llm_environment")
    assert isinstance(backend, Managed)


def test_host_falls_back_to_legacy_when_managed_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "LegacyBackend", lambda: Legacy())
    monkeypatch.setattr(factory, "OpenInterpreterBackend", lambda: Managed())
    monkeypatch.setattr(factory, "managed_interpreter_exe", lambda project_root=None: tmp_path / "missing.exe")
    backend = factory.create_backend("host", tmp_path / "llm_environment")
    assert isinstance(backend, Legacy)
