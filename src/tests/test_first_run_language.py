"""First launch on Windows, where there is no console to answer a prompt.

RUN.bat prefers pythonw.exe for the window. A process started that way has
sys.stdin set to None, and input() then raises RuntimeError, not EOFError.
Nothing caught it, so the very first launch showed an error box instead of
the program. These cover that path and the choice it makes instead.
"""
import io
import sys
import types

import pytest


@pytest.fixture
def lang(monkeypatch, tmp_path):
    from installer import lang_setup
    saved = []
    monkeypatch.setattr(lang_setup, '_save_language',
                        lambda here, value: saved.append(value))
    monkeypatch.setattr(lang_setup, '_load_saved_language', lambda here: None)
    monkeypatch.setattr(lang_setup, 'set_language', lambda value: None)
    for key in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE', lang_setup.ENV_VAR):
        monkeypatch.delenv(key, raising=False)
    return lang_setup, saved, tmp_path


def test_a_window_with_no_console_starts_instead_of_raising(lang, monkeypatch):
    module, saved, root = lang
    monkeypatch.setattr(sys, 'stdin', None)   # exactly what pythonw.exe gives
    assert module.initialize_language(root) in ('en', 'ko')
    assert saved == [], 'a value nobody chose must not become the setting'


def test_a_guess_is_not_written_down_so_the_console_run_still_asks(lang, monkeypatch):
    module, saved, root = lang
    monkeypatch.setattr(sys, 'stdin', None)
    module.initialize_language(root)
    assert saved == []

    # Same machine, later, started from a terminal.
    monkeypatch.setattr(module, '_can_ask', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt='': '2')
    assert module.initialize_language(root) == 'ko'
    assert saved == ['ko']


def test_a_korean_machine_is_not_silently_set_to_english(lang, monkeypatch):
    module, _, root = lang
    monkeypatch.setattr(sys, 'stdin', None)
    monkeypatch.setenv('LANG', 'ko_KR.UTF-8')
    assert module.initialize_language(root) == 'ko'


@pytest.mark.parametrize('failure', [EOFError, KeyboardInterrupt, RuntimeError, OSError])
def test_no_way_of_losing_stdin_reaches_the_caller(lang, monkeypatch, failure):
    module, saved, root = lang
    monkeypatch.setattr(module, '_can_ask', lambda: True)

    def refuse(prompt=''):
        raise failure('stdin is gone')
    monkeypatch.setattr('builtins.input', refuse)
    assert module.initialize_language(root) in ('en', 'ko')
    assert saved == []


def test_a_real_terminal_is_still_asked(lang, monkeypatch):
    module, saved, root = lang
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: True))
    answers = iter(['x', '2'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    monkeypatch.setattr(module, 't', lambda key, **kw: 'saved')
    assert module.initialize_language(root) == 'ko'
    assert saved == ['ko']


def test_an_explicit_choice_still_wins_over_everything(lang, monkeypatch):
    module, saved, root = lang
    monkeypatch.setattr(sys, 'stdin', None)
    assert module.initialize_language(root, override='ko') == 'ko'
    assert saved == ['ko'], 'the user said so; that is worth writing down'


def test_the_shell_reaches_its_window_on_a_first_run_with_no_console(monkeypatch, tmp_path):
    """The whole path: no saved language, no console, and the window opens."""
    from apps.shared import entry
    from services.system import bootstrap
    monkeypatch.setattr(bootstrap, 'install_exit_hooks', lambda root: True)
    monkeypatch.setattr(bootstrap, 'run_exit_cleanups', lambda: True)
    monkeypatch.setattr('services.desktop.create_services',
                        lambda: types.SimpleNamespace(project_root=tmp_path,
                                                      close=lambda: True))
    from installer import lang_setup
    monkeypatch.setattr(lang_setup, '_load_saved_language', lambda here: None)
    monkeypatch.setattr(lang_setup, '_save_language', lambda here, value: None)
    for key in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE', lang_setup.ENV_VAR):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, 'stdin', None)
    opened = []
    pytest.importorskip('tkinter')
    monkeypatch.setattr('apps.shared.window.DesktopWindow',
                        lambda app, svc: types.SimpleNamespace(
                            run=lambda: opened.append(app)))
    assert entry.main('studio', []) == 0
    assert opened == ['studio'], 'first launch must open the window, not an error box'


# ── the same mistake everywhere else a prompt is written ─────────────────
# Every one of these already meant to survive a console-less process; they
# just named EOFError, which is not what pythonw raises.

def test_no_prompt_in_the_program_crashes_without_a_console():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    unguarded = []
    for path in sorted(root.rglob('*.py')):
        if path.parent.name == 'tests':
            continue
        source = path.read_text(encoding='utf-8')
        if 'input(' not in source:
            continue
        stack = []

        def walk(node):
            if isinstance(node, ast.Try):
                stack.append(node)
                for child in ast.iter_child_nodes(node):
                    walk(child)
                stack.pop()
                return
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'input':
                caught = set()
                for block in stack:
                    for handler in block.handlers:
                        kind = handler.type
                        if kind is None:
                            caught.add('bare')
                        elif isinstance(kind, ast.Tuple):
                            caught.update(getattr(e, 'id', '') for e in kind.elts)
                        else:
                            caught.add(getattr(kind, 'id', ''))
                if 'bare' not in caught and 'RuntimeError' not in caught:
                    unguarded.append('%s:%d' % (path.relative_to(root), node.lineno))
            for child in ast.iter_child_nodes(node):
                walk(child)

        walk(ast.parse(source))
    assert unguarded == [], \
        'input() raises RuntimeError, not EOFError, when there is no stdin: ' \
        + ', '.join(unguarded)


@pytest.mark.parametrize('failure', [RuntimeError, OSError, EOFError])
def test_the_terminal_launcher_gives_up_instead_of_raising(monkeypatch, failure):
    from launcher.presenter import tui

    def refuse(prompt=''):
        raise failure('no stdin')
    monkeypatch.setattr('builtins.input', refuse)
    assert tui.prompt('> ') == 'q'
    tui.pause('x')
