import launcher.agent.backend_factory as factory


class Managed:
    pass


class ManagedSandbox:
    pass


def _patch_factories(monkeypatch):
    monkeypatch.setattr(factory, "OpenInterpreterBackend", lambda: Managed())
    monkeypatch.setattr(factory, "SandboxOpenInterpreterBackend", lambda: ManagedSandbox())


def test_sandbox_always_uses_structured_backend(monkeypatch, tmp_path):
    _patch_factories(monkeypatch)
    backend = factory.create_backend("sandbox", tmp_path / "llm_environment")
    assert isinstance(backend, ManagedSandbox)


def test_host_always_uses_managed_backend(monkeypatch, tmp_path):
    _patch_factories(monkeypatch)
    backend = factory.create_backend("host", tmp_path / "llm_environment")
    assert isinstance(backend, Managed)
