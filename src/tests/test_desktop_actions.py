"""사용자가 실제로 누르는 버튼들. 진짜 Tk 위젯, 주입된 런타임.

기존 UI 테스트는 화면 구성과 Chat 시작까지만 본다. Agent 시작 · 세션 종료 ·
유지보수 · 모델 설치/삭제 · 복구는 모두 워커 스레드에서 돌고 콜백으로 UI 를
되돌리는 경로라, 이름 하나만 틀려도 로그 한 줄만 남기고 조용히 아무 일도
일어나지 않는다.
"""
import time

from types import SimpleNamespace

import pytest

pytest.importorskip('tkinter')

import tkinter as tk  # noqa: E402
from test_desktop_services import make  # noqa: E402
from test_desktop_ui import pump  # noqa: E402,F401


class _Panel(tk.Frame):
    """ChatPanel 자리. 세션이 부르는 표면만 갖춘다."""

    def __init__(self, parent, callbacks):
        super().__init__(parent)
        self.callbacks = callbacks
        self.messages = []
        self.sending = False

    def enable_send(self):
        self.sending = True

    def disable_send(self):
        self.sending = False

    def append_message(self, level, message):
        self.messages.append((level, message))

    def set_current_model(self, tag):
        self.model = tag


@pytest.fixture
def ui(tmp_path):
    from apps.shared.window import DesktopWindow
    svc, backend = make(tmp_path)
    backend.run_setup = lambda options=None, log=None, cancel=None: (
        backend.calls.append(('setup',)) or 0)
    backend.create_agent_panel = lambda parent, metadata, callbacks: _Panel(parent, callbacks)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Real Tk requires DISPLAY; run with Xvfb on Linux')
    window = DesktopWindow('studio', svc, root=root, start_polling=False)
    yield window, svc, backend
    window.runner.shutdown()
    window._unsubscribe()
    svc.close()
    try:
        root.after_cancel(window._timer)
    except tk.TclError:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def settle(window, predicate=lambda: True, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        window.runner.drain()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('UI condition did not settle')


def confirmed(monkeypatch, answer=True):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, 'askyesno', lambda *a, **k: answer)


def test_agent_start_binds_the_session_panel_and_enables_sending(ui):
    w, svc, backend = ui
    w.navigate('agent')
    w.start_agent()
    settle(w, lambda: w.agent_session is not None and w.agent_panel is not None)
    assert ('agent', 'warp', None) in backend.calls
    assert w.agent_panel.sending
    assert svc.agent.opened


def test_a_second_agent_is_refused_while_one_is_active(ui):
    w, svc, backend = ui
    w.start_agent()
    settle(w, lambda: w.agent_session is not None)
    before = list(backend.calls)
    w.start_agent()
    settle(w)
    assert backend.calls == before


def test_agent_events_reach_only_the_panel_of_the_live_session(ui):
    w, svc, _ = ui
    w.start_agent()
    settle(w, lambda: w.agent_panel is not None)
    svc.events.emit('agent.event', {'session': w.agent_session.id,
                                    'level': 'info', 'message': 'mine'})
    svc.events.emit('agent.event', {'session': 'someone-else',
                                    'level': 'info', 'message': 'theirs'})
    settle(w, lambda: w.agent_panel.messages)
    assert [m for _level, m in w.agent_panel.messages] == ['mine']


def test_stop_sessions_releases_the_agent_and_the_runtime_lock(ui):
    w, svc, _ = ui
    w.start_agent()
    settle(w, lambda: w.agent_session is not None)
    assert svc.owner.owned
    w.stop_sessions()
    settle(w, lambda: w.agent_session is None)
    assert not svc.agent.opened
    assert not svc.owner.owned


def test_an_unverified_stop_keeps_the_window_and_says_so(ui):
    w, svc, backend = ui
    w.start_chat()
    settle(w, lambda: svc.chat.started)
    backend.chat_stop = lambda: False
    w.stop_sessions()
    settle(w, lambda: 'sessions.stop' in w.message.get())
    assert svc.owner.owned           # 확인되지 않은 종료는 소유를 놓지 않는다
    assert 'not verified' in w.message.get() or 'ownership' in w.message.get()


@pytest.mark.parametrize('key', ['docker_image', 'docker_clean',
                                 'settings_action', 'searxng_action'])
def test_every_maintenance_button_reaches_the_backend(ui, key):
    w, _svc, backend = ui
    w.maintenance(key)
    settle(w, lambda: ('maintenance', key) in backend.calls)


def test_maintenance_is_refused_while_a_session_is_active(ui):
    w, svc, backend = ui
    w.start_chat()
    settle(w, lambda: svc.chat.started)
    w.maintenance('docker_clean')
    settle(w)
    assert ('maintenance', 'docker_clean') not in backend.calls


def _choose(w, tags, installed=()):
    """Stand in for the catalogue: these tags are ticked, those are on disk."""
    known = set(tags) | set(installed)
    w._catalog = {'models': [{'tag': tag, 'installed': tag in installed}
                             for tag in known],
                  'recommended': [], 'extra_installed': []}
    w.choice_vars = {tag: SimpleNamespace(get=lambda tag=tag: tag in tags)
                     for tag in set(tags) | set(installed)}


def test_model_install_and_removal_go_through_setup(ui, monkeypatch):
    w, svc, backend = ui
    confirmed(monkeypatch)
    svc.settings.set_network_mode('direct')

    _choose(w, ['demo:latest'])
    w.apply_selection()          # states the plan
    w.apply_selection()          # the same plan again starts it
    settle(w, lambda: ('pull', 'demo:latest') in backend.calls)

    # Unticking an installed model is the removal path.
    _choose(w, [], installed=['demo:latest'])
    w.apply_selection()
    w.apply_selection()
    settle(w, lambda: ('remove', 'demo:latest') in backend.calls)


def test_an_unconfirmed_selection_never_touches_models(ui, monkeypatch):
    w, _svc, backend = ui
    _choose(w, ['demo:latest'])
    w.apply_selection()          # one click is only the confirmation prompt
    settle(w)
    assert not any(call[0] == 'pull' for call in backend.calls)


def test_repair_runs_the_installer_only_when_idle(ui, monkeypatch):
    w, svc, backend = ui
    confirmed(monkeypatch)
    w.repair()
    settle(w, lambda: ('setup',) in backend.calls)
    w.start_chat()
    settle(w, lambda: svc.chat.started)
    backend.calls.clear()
    w.repair()
    settle(w)
    assert ('setup',) not in backend.calls


def test_health_refresh_fills_the_network_and_system_panels(ui):
    w, _svc, _ = ui
    w.refresh_health()
    settle(w, lambda: 'Ollama' in w.health.get())
    assert 'Pinned mode' in w.network_text.get('1.0', 'end')
    shown = w.system_text.get('1.0', 'end')
    # The page says which side of the split each folder is on: a user who
    # cannot tell shared from private cannot know who can read their chats.
    assert 'Models' in shown and '공용' in shown
    assert '내 계정 전용' in shown and str(_svc.data) in shown


def test_a_burst_of_events_drops_history_instead_of_blocking(ui):
    w, svc, _ = ui
    for index in range(w.events.maxsize + 50):
        svc.events.emit('runtime.progress', {'message': str(index)})
    assert w.events.qsize() <= w.events.maxsize
    settle(w, lambda: w.events.empty())


def test_the_real_presenter_works_through_the_window_proxy(ui):
    """window 가 만들어 주는 3-속성 proxy 로 Presenter 가 동작하는가.

    유지보수 액션은 이 Presenter 의 info/warn/section 을 호출하고, 그 출력은
    Setup 화면의 PanelHost 안으로 들어가야 한다.
    """
    from integrations.desktop import DesktopBackend
    w, svc, _ = ui
    svc.system.backend = DesktopBackend(svc.env, svc.model_dir, svc.project_root)
    presenter = w.presenter('setup')
    presenter.info('hello from an action')
    presenter.warn('and a warning')
    settle(w, lambda: presenter._current_log_panel is not None)
    panel = presenter._current_log_panel
    assert panel.frame.winfo_exists()
    assert panel.frame.winfo_toplevel() is w.root     # Setup 화면 안에 들어갔다
    # proxy 의 set_message 는 이벤트로 흘러 셸 활동 로그에 쌓인다.
    activity = w.activity.get('1.0', 'end')
    assert 'hello from an action' in activity and 'and a warning' in activity
