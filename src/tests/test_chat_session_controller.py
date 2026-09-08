from pathlib import Path


class FakeService:
    def __init__(self):
        self.resumed = []
        self._session = "thread-current"

    def session_id(self):
        return self._session

    def resume(self, session_id):
        self.resumed.append(session_id)
        self._session = session_id
        return True


def _controller(**overrides):
    from launcher.agent.chat_session_controller import ChatSessionController

    posts = []
    service = overrides.pop("service", FakeService())
    controller = ChatSessionController(
        service,
        post=lambda level, text: posts.append((level, text)),
        dispatch=lambda name, fn: fn(),
        **overrides,
    )
    return controller, service, posts


def test_session_command_reports_current_thread_id():
    controller, _service, posts = _controller()

    assert controller.handle_slash("/session") is True
    assert posts[-1] == ("system", "현재 세션: thread-current")


def test_resume_command_uses_open_interpreter_thread_id():
    controller, service, posts = _controller()

    assert controller.handle_slash("/resume thread-123") is True
    assert service.resumed == ["thread-123"]
    assert posts[-1] == ("system", "세션 이어가기 완료: thread-123")


def test_model_command_delegates_controlled_restart():
    restarted = []
    controller, _service, posts = _controller(
        restart_model=lambda tag: restarted.append(tag) or True,
    )

    assert controller.handle_slash("/model qwen3:8b") is True
    assert restarted == ["qwen3:8b"]
    assert posts[-1] == ("system", "모델 변경 완료: qwen3:8b")


def test_reload_noops_when_mount_signature_is_unchanged():
    calls = []
    controller, _service, posts = _controller(
        reload_policy=lambda: calls.append("reload") or False,
    )

    assert controller.handle_slash("/reload") is True
    assert calls == ["reload"]
    assert posts[-1] == ("system", "폴더 정책 변경 없음 — 재기동하지 않습니다.")


def test_agent_chat_is_thin_orchestration_after_controller_extraction():
    root = Path(__file__).resolve().parents[1]
    source = (root / "launcher" / "actions" / "agent_chat.py").read_text(encoding="utf-8")

    assert "launcher.agent.chat_session_controller" in source
    assert "launcher.agent.setup_flow" in source
    assert "launcher.agent.runtime_config" in source
    assert "def _run_gui_chat_unified" not in source
    assert "def _select_profile" not in source
    assert "def _select_agent_model" not in source
    assert "def _build_cmd_for_mode" not in source
    assert 'c0 == "/resume"' not in source


def test_chat_panel_resumes_native_thread_ids_instead_of_legacy_session_files():
    root = Path(__file__).resolve().parents[1]
    source = (root / "launcher" / "presenter" / "gui" / "chat_panel.py").read_text(encoding="utf-8")

    assert "session_*.json" not in source
    assert "interpreter_dir(" not in source
    assert "_session_files" not in source
    assert "askstring" in source
    assert '"/resume " + thread_id' in source
