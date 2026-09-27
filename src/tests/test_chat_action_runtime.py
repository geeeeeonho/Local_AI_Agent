from pathlib import Path


class FakePresenter:
    def __init__(self, choice="direct"):
        self.choice = choice
        self.menus = []
        self.messages = []

    def show_menu(self, title, subtitle, items, last_choice=None):
        self.menus.append((title, subtitle, items, last_choice))
        return self.choice

    def info(self, message):
        self.messages.append(("info", message))

    def ok(self, message):
        self.messages.append(("ok", message))

    def warn(self, message):
        self.messages.append(("warn", message))

    def error(self, message):
        self.messages.append(("error", message))

    def is_cancelled(self):
        return False


def test_network_picker_uses_presenter_contract_and_persists_choice(monkeypatch):
    from launcher import network_policy
    from launcher.actions import chat

    presenter = FakePresenter(choice="direct")
    monkeypatch.delenv("LOCAL_AI_ANYTHINGLLM_NET", raising=False)

    assert chat._select_network_mode(presenter) == "direct"
    assert len(presenter.menus) == 1
    title, subtitle, items, _last = presenter.menus[0]
    assert title == "AnythingLLM 인터넷 모드"
    assert isinstance(subtitle, str)
    assert {item.key for item in items} == {"warp", "tor", "direct", "block"}
    assert network_policy.current_mode() is network_policy.NetworkMode.DIRECT


def test_chat_uses_managed_ollama_ownership_gate(monkeypatch, tmp_path):
    from launcher.actions import chat

    calls = []

    class FakeOllamaService:
        def __init__(self, env, logger=None):
            calls.append((Path(env), logger))

        def ensure_running(self):
            calls.append("ensure_running")
            return True

    presenter = FakePresenter()
    monkeypatch.setattr(chat, "OllamaService", FakeOllamaService)

    assert chat._ensure_ollama(tmp_path, presenter) is True
    assert calls[0] == (tmp_path, presenter)
    assert calls[1] == "ensure_running"


def test_chat_docker_gate_uses_auto_start_service(monkeypatch):
    from launcher.actions import chat
    from launcher.services.docker import DockerService

    calls = []
    monkeypatch.setattr(
        DockerService,
        "ensure_daemon",
        staticmethod(
            lambda logger=None, timeout=60, cancel_check=None: (
                calls.append((logger, timeout, cancel_check)) or True
            )
        ),
    )
    presenter = FakePresenter()

    assert chat._ensure_docker(presenter) is True
    assert calls and calls[0][0] is presenter
    assert calls[0][1] == 90
    assert callable(calls[0][2])


def test_keep_chat_running_uses_the_current_environment_name(monkeypatch):
    from launcher.actions import chat

    monkeypatch.delenv("LOCAL_AI_KEEP_CHAT", raising=False)
    assert chat._keep_chat_running() is False

    monkeypatch.setenv("LOCAL_AI_KEEP_CHAT", "1")
    assert chat._keep_chat_running() is True


def test_chat_action_uses_presenter_ok_not_nonexistent_success_method():
    root = Path(__file__).resolve().parents[1]
    source = (root / "launcher" / "actions" / "chat.py").read_text(encoding="utf-8")

    assert ".success(" not in source
    assert "p.ok(" in source
