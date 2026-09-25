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


def test_the_status_button_actually_asks_for_a_fresh_answer(ui):
    """The poll reuses a recent answer; pressing refresh must not."""
    import time
    w, _, backend = ui
    w.refresh_health(fresh=True)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and 0 not in backend.health_calls:
        w.root.update()
        time.sleep(.01)
    assert 0 in backend.health_calls


def test_the_idle_poll_does_not_demand_a_fresh_answer(ui):
    import time
    w, _, backend = ui
    w.refresh_health()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and None not in backend.health_calls:
        w.root.update()
        time.sleep(.01)
    assert None in backend.health_calls
    assert 0 not in backend.health_calls


# ── the window has to open where the user can reach it ────────────────────

def test_the_window_never_opens_taller_than_the_screen_it_opens_on():
    """It asked for 1280x860 whatever it was opening on.

    A 1366x768 laptop - still the commonest screen this runs on - has about
    730 usable pixels of height, so the bottom 130 went under the taskbar:
    the readiness line, and on the models screen the button that applies the
    whole selection. Nothing was broken, and nothing down there could be
    clicked either, because it was not on the screen.
    """
    from core.window_size import fitted_size, centred_geometry
    for screen in ((1366, 768), (1280, 720), (1440, 900), (1920, 1080),
                   (2560, 1440), (1024, 640)):
        width, height = fitted_size(screen)
        assert width <= screen[0] and height <= screen[1], screen
        geometry = centred_geometry((width, height), screen)
        size, _, offset = geometry.partition('+')
        x, _, y = offset.partition('+')
        assert int(x) >= 0 and int(y) >= 0, geometry
        assert int(x) + width <= screen[0] + 1, geometry


def test_a_screen_smaller_than_the_minimum_still_gets_the_minimum():
    """Tk would resize it back up anyway; clamping below only moves it badly."""
    from core.window_size import fitted_size
    assert fitted_size((640, 480), minimum=(880, 560)) == (880, 560)


def test_a_big_screen_is_not_filled_edge_to_edge():
    from core.window_size import fitted_size, PREFERRED_SIZE
    assert fitted_size((3840, 2160)) == PREFERRED_SIZE


def test_the_live_window_opens_at_the_size_its_display_allows(ui):
    """Whatever the display under this test happens to be."""
    from core.window_size import fitted_size
    w, _, _ = ui
    w.root.update_idletasks()
    screen = (w.root.winfo_screenwidth(), w.root.winfo_screenheight())
    assert (w.root.winfo_width(), w.root.winfo_height()) == fitted_size(
        screen, minimum=tuple(w.root.minsize()))


# ── and the page has to get more of it than the chrome around the page ────

def test_the_activity_log_gives_its_space_back_on_a_short_window():
    """Eight lines is a fifth of a desktop window and a third of a laptop one.

    Left fixed, the log took so much of a 1366x768 screen that the list of
    twenty-five models underneath it had four pixels to show them in.
    """
    from core.window_size import activity_lines, ACTIVITY_LINES
    assert activity_lines(900) == ACTIVITY_LINES[1]
    assert activity_lines(540) == ACTIVITY_LINES[0]
    assert ACTIVITY_LINES[0] <= activity_lines(648) < ACTIVITY_LINES[1]
    # Monotonic: a taller window never gets a shorter log.
    heights = [activity_lines(h) for h in range(400, 1200, 20)]
    assert heights == sorted(heights)


def test_the_model_list_gets_more_of_its_page_than_the_text_around_it(ui):
    """The screen exists to pick from a list; the list was the smallest thing on it.

    Two header labels, a three-line download plan and a three-sentence note
    sat between the user and twenty-five checkboxes, and the checkboxes got
    what was left - ninety-nine pixels of it.
    """
    import time
    w, _, _ = ui
    w.root.geometry('1280x860')
    w.navigate('models')
    w.model_tabs.select(w.model_pages['choose'])
    for _ in range(30):
        w.root.update_idletasks(); w.root.update(); time.sleep(.01)
    pane = w.model_pages['choose']
    rows = {int(child.grid_info()['row']): child for child in pane.grid_slaves()}
    growing = [index for index in rows
               if (pane.grid_rowconfigure(index).get('weight') or 0)]
    assert len(growing) == 1, 'exactly one row absorbs the slack'
    listing = rows[growing[0]].winfo_height()
    chrome = sum(rows[index].winfo_height()
                 for index in rows if index != growing[0])
    assert listing >= 160, 'the list is %d px tall' % listing
    assert listing > chrome, 'text takes %d px, the list %d' % (chrome, listing)


def test_a_fixed_row_hands_space_back_when_its_text_shrinks(ui):
    """Those rows are labels driven by a StringVar: measured empty, filled
    with a three-line plan, then cleared. A height reserved once is wrong
    twice, and when it is wrong high the list is what pays."""
    import time
    w, _, _ = ui
    w.navigate('models')
    w.model_tabs.select(w.model_pages['choose'])

    def settle():
        for _ in range(20):
            w.root.update_idletasks(); w.root.update(); time.sleep(.01)

    settle()
    pane = w.model_pages['choose']
    rows = {int(c.grid_info()['row']): c for c in pane.grid_slaves()}
    fixed = [i for i in rows if not (pane.grid_rowconfigure(i).get('weight') or 0)]
    w.choice_storage.set('x' * 400)
    settle()
    swollen = sum(int(pane.grid_rowconfigure(i).get('minsize') or 0) for i in fixed)
    w.choice_storage.set('')
    settle()
    shrunk = sum(int(pane.grid_rowconfigure(i).get('minsize') or 0) for i in fixed)
    assert shrunk < swollen, 'the row kept %d px it no longer needs' % shrunk
