from launcher.actions import ollama as ollama_action


class _Presenter:
    def __init__(self):
        self.ok_messages = []
        self.error_messages = []
        self.info_messages = []
        self.paused = False

    def section(self, _msg):
        pass

    def ok(self, msg):
        self.ok_messages.append(msg)

    def error(self, msg):
        self.error_messages.append(msg)

    def info(self, msg):
        self.info_messages.append(msg)

    def pause(self):
        self.paused = True


def test_ollama_menu_routes_reachable_server_through_managed_verification(monkeypatch, tmp_path):
    calls = []

    class _Service:
        def __init__(self, env, logger=None):
            self.env = env
            self.logger = logger

        def is_running(self):
            return True

        def ensure_running(self):
            calls.append("ensure_running")
            return False

    monkeypatch.setattr(ollama_action, "OllamaService", _Service)
    presenter = _Presenter()

    ollama_action.run(tmp_path, presenter)

    assert calls == ["ensure_running"]
    assert presenter.ok_messages == []
    assert presenter.error_messages == ["시작/검증 실패"]
    assert presenter.paused is True
