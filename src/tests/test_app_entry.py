"""네 앱이 공유하는 진입점: 인자 해석과 경로 선택, 그리고 종료 보장.

`--help` 만 확인하던 자리다. 여기서 정하는 것은 어느 런타임을 띄울지와
실패했을 때 서비스를 정말 닫는지라, 잘못되면 창이 안 뜨거나 런타임 소유
잠금이 남는다. 창을 띄우지 않고 결정만 확인한다.
"""
import sys

import pytest

from apps.shared.entry import main, parse_args


def test_the_default_app_is_the_one_the_module_was_started_as():
    for app in ('studio', 'chat', 'interpreter', 'setup'):
        assert parse_args(app, []).app == app
    assert parse_args('chat', ['--app', 'interpreter']).app == 'interpreter'


INSTALLER_FLAGS = ['--install', '--manage', '--skip-model',
                   '--skip-sandbox', '--skip-build', '--skip-search']


@pytest.mark.parametrize('flag', INSTALLER_FLAGS)
@pytest.mark.parametrize('app', ['studio', 'chat', 'interpreter'])
def test_installer_flags_are_rejected_against_an_explicit_other_app(app, flag):
    """`--app chat --install` asks for two different programs at once."""
    with pytest.raises(SystemExit):
        parse_args('studio', ['--app', app, flag])


@pytest.mark.parametrize('flag', INSTALLER_FLAGS)
@pytest.mark.parametrize('app', ['studio', 'chat', 'interpreter'])
def test_installer_flags_alone_name_the_installer(app, flag):
    """RUN.bat forwards these to apps.studio, so rejecting them here killed a
    documented path - and under pythonw, with no console, it died in silence.
    A flag nobody contradicted names the program the user asked for."""
    assert parse_args(app, [flag]).app == 'setup'


def test_install_and_manage_cannot_be_requested_together():
    with pytest.raises(SystemExit):
        parse_args('setup', ['--install', '--manage'])


def test_gui_and_tui_cannot_be_requested_together():
    with pytest.raises(SystemExit):
        parse_args('studio', ['--gui', '--tui'])


class _Bootstrap:
    """services.system.bootstrap 대역. 어느 구 진입점으로 갔는지만 기록한다."""

    def __init__(self):
        self.calls = []

    def legacy_entry(self, module, arguments):
        self.calls.append((module, list(arguments)))
        return 0

    def initialize_language(self, root, language=None):
        self.calls.append(('language', str(root), language))


@pytest.fixture
def bootstrap(monkeypatch):
    from services.system import bootstrap as real
    fake = _Bootstrap()
    monkeypatch.setattr(real, 'legacy_entry', fake.legacy_entry)
    monkeypatch.setattr(real, 'initialize_language', fake.initialize_language)
    return fake


def test_setup_flags_reach_the_retained_installer_with_dashed_names(bootstrap):
    assert main('setup', ['--install', '--skip-model', '--lang', 'en']) == 0
    assert bootstrap.calls == [
        ('installer', ['--install', '--skip-model', '--lang', 'en'])]


def test_tui_reaches_the_retained_launcher_from_any_app(bootstrap):
    assert main('chat', ['--tui']) == 0
    assert bootstrap.calls == [('launcher', ['--tui'])]


def _window_module(monkeypatch, factory):
    """apps.shared.window 를 통째로 대역으로 갈아 끼운다.

    entry 가 창 모듈을 지연 import 하므로 Tk 없이도 분기를 확인할 수 있고,
    Tk 가 있는 CI 에서도 진짜 창이 뜨지 않는다.
    """
    from types import ModuleType
    module = ModuleType('apps.shared.window')
    module.DesktopWindow = factory
    monkeypatch.setitem(sys.modules, 'apps.shared.window', module)


def _services(monkeypatch, tmp_path):
    from services import desktop as desktop_services
    state = {'closed': 0}

    class Services:
        project_root = tmp_path

        def close(self):
            state['closed'] += 1

    monkeypatch.setattr(desktop_services, 'create_services', Services)
    return state


def test_a_failed_window_still_closes_the_services(monkeypatch, bootstrap, tmp_path):
    state = _services(monkeypatch, tmp_path)

    def broken(app, services):
        raise RuntimeError('display unavailable')

    _window_module(monkeypatch, broken)
    monkeypatch.setitem(sys.modules, 'tkinter', None)   # 오류 대화상자는 건너뛴다

    assert main('studio', []) == 3   # 창은 못 떴고, 그 사실을 종료 코드로 알린다
    assert state['closed'] == 1      # 런타임 소유 잠금을 들고 죽지 않는다


def test_keyboard_interrupt_is_reported_as_the_conventional_code(monkeypatch, bootstrap, tmp_path):
    state = _services(monkeypatch, tmp_path)

    def interrupted(app, services):
        raise KeyboardInterrupt

    _window_module(monkeypatch, interrupted)
    assert main('studio', []) == 130
    assert state['closed'] == 1


def test_a_normal_run_initializes_language_and_closes_once(monkeypatch, bootstrap, tmp_path):
    state = _services(monkeypatch, tmp_path)
    opened = []

    class Window:
        def __init__(self, app, services):
            opened.append(app)

        def run(self):
            pass

    _window_module(monkeypatch, Window)
    assert main('interpreter', ['--lang', 'ko']) == 0
    assert opened == ['interpreter']
    assert ('language', str(tmp_path), 'ko') in bootstrap.calls
    assert state['closed'] == 1
