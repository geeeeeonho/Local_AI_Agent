"""The shell has to stay usable on a small screen, by keyboard, and when it fails.

Each case here stands for something that was actually wrong: a window that could
not fit a 1366x768 laptop, an error that looked exactly like progress, focus that
left no visible trace, and an empty panel host that claimed half a page.
"""
import gc

import pytest

from test_desktop_services import make


@pytest.fixture
def ui(tmp_path):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from apps.shared.window import DesktopWindow
    services, backend = make(tmp_path)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Real Tk requires DISPLAY; run with Xvfb on Linux')
    window = DesktopWindow('studio', services, root=root, start_polling=False)
    yield window, services, backend
    window.runner.shutdown()
    window._unsubscribe()
    services.close()
    try:
        root.after_cancel(window._timer)
    except tk.TclError:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_the_window_fits_a_small_laptop_screen(ui):
    w, _, _ = ui
    width, height = w.root.minsize()
    # 1366x768 minus a title bar and taskbar.
    assert width <= 1280 and height <= 700


def test_every_static_page_can_scroll_when_the_window_is_small(ui):
    w, _, _ = ui
    for key in ('home', 'settings', 'setup', 'network', 'system'):
        assert key in w.page_scrolls, key + ' cannot scroll on a short window'


def test_a_failure_is_visually_distinct_from_progress(ui):
    w, _, _ = ui
    w.log('working on it')
    assert w.message_label.cget('style') == 'Muted.TLabel'
    assert not w.activity.tag_ranges('alert')
    w.log('it failed', level='error')
    assert w.message_label.cget('style') == 'Alert.TLabel'
    assert w.activity.tag_ranges('alert')
    assert w.activity.tag_cget('alert', 'foreground') == w.theme.palette.danger


def test_a_later_success_clears_the_failure_styling(ui):
    w, _, _ = ui
    w.log('it failed', level='error')
    w.log('recovered')
    assert w.message_label.cget('style') == 'Muted.TLabel'


def test_task_failures_are_reported_as_failures(ui):
    import time
    w, _, _ = ui
    def boom():
        raise RuntimeError('nope')
    w.run_task('probe', boom)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and w.message_label.cget('style') != 'Alert.TLabel':
        w.root.update()
        time.sleep(.01)
    assert w.message_label.cget('style') == 'Alert.TLabel'
    assert 'nope' in w.message.get()


def test_navigation_and_actions_are_reachable_by_keyboard(ui):
    w, _, _ = ui
    for key, button in w.nav.items():
        assert str(button.cget('takefocus')) not in ('0', 'False'), key


def test_focus_is_visible_in_both_themes(ui):
    from tkinter import ttk
    w, _, _ = ui
    style = ttk.Style(w.root)
    for theme in ('dark', 'light'):
        w.theme.apply(theme)
        palette = w.theme.palette
        for name in ('TButton', 'Nav.TButton', 'TCheckbutton'):
            assert style.lookup(name, 'focuscolor') == palette.chat, name
        assert ('focus', palette.hover) in style.map('Nav.TButton', 'background')


def test_selection_checkboxes_are_readable_in_both_themes(ui):
    from tkinter import ttk
    w, _, _ = ui
    style = ttk.Style(w.root)
    for theme in ('dark', 'light'):
        w.theme.apply(theme)
        palette = w.theme.palette
        for name in ('TCheckbutton', 'Card.TCheckbutton'):
            assert style.lookup(name, 'foreground') == palette.fg, name
            # Clam's default indicator is a pale beige that neither theme owns.
            assert style.lookup(name, 'indicatorcolor') == palette.input, name


def test_an_unused_panel_host_claims_no_space(ui):
    w, _, _ = ui
    w.navigate('agent')
    w.root.update()
    assert not w.hosts['agent'].frame.winfo_ismapped()


def test_a_panel_host_appears_once_it_has_something_to_show(ui):
    tk = pytest.importorskip("tkinter")
    w, _, _ = ui
    w.navigate('agent')
    w.root.update()
    w.hosts['agent'].replace(lambda parent: tk.Frame(parent))
    w.root.update()
    assert w.hosts['agent'].frame.winfo_ismapped()


def test_hovering_does_not_restyle_a_whole_subtree(ui):
    w, _, _ = ui
    visited = []
    original = w.theme._style_widget
    w.theme._style_widget = lambda widget: visited.append(widget) or original(widget)
    try:
        w.theme._hovered(type('E', (), {'widget': w.pages['models']})())
    finally:
        w.theme._style_widget = original
    assert len(visited) == 1


def test_the_theme_file_is_not_reread_on_every_frame(ui):
    w, _, _ = ui
    reads = []
    w.services.settings.theme = lambda: reads.append(1) or w.theme.name
    w._polling = True
    for _ in range(150):
        w._ticks += 1
        if w._ticks % 200 == 0:
            w.sync_theme()
    assert not reads
