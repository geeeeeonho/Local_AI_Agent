import launcher.services.ollama as ollama_module
from launcher.app import Application


def test_ollama_poller_reports_only_managed_tracked_service(monkeypatch, tmp_path):
    calls = []

    class _Service:
        def __init__(self, env):
            calls.append(("init", env))

        @staticmethod
        def is_running():
            calls.append(("raw", None))
            return True

        def is_managed_running(self):
            calls.append(("managed", None))
            return False

    monkeypatch.setattr(ollama_module, "OllamaService", _Service)

    poller = Application(tmp_path, object())._build_pollers()["ollama_check"]

    assert poller() is False
    assert calls == [("init", tmp_path), ("managed", None)]
