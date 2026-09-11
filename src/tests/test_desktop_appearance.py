"""Themes and Chat-first navigation: real Tk widgets and real shared settings."""
import json
import gc
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace as NS

import pytest
from test_desktop_ui import ui, pump
from test_desktop_services import make


def test_theme_default_does_not_create_settings(tmp_path):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    assert SettingsStore(path).theme() == 'dark'
    assert not path.exists()


def test_theme_persists_across_apps_without_overwriting_other_settings(tmp_path):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'schema_version': 1, 'extra': {'keep': True},
                               'appearance': {'font_size': 12}}))
    first, second = SettingsStore(path), SettingsStore(path)
    first.set_network_mode('block', app='interpreter')
    first.set_theme('light')
    assert second.theme() == 'light'
    assert second.network_mode(app='interpreter').value == 'block'
    assert json.loads(path.read_text())['appearance']['font_size'] == 12
    assert json.loads(path.read_text())['extra'] == {'keep': True}


@pytest.mark.parametrize('value', ['', 'system', 'LIGHT', False, None, 1, []])
def test_invalid_theme_is_rejected_before_writing(tmp_path, value):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    store = SettingsStore(path)
    with pytest.raises(ValueError):
        store.set_theme(value)
    assert not path.exists()


@pytest.mark.parametrize('content', ['{broken', '{"schema_version":2}',
                                    '{"appearance":null}', '{"appearance":[]}'])
def test_invalid_existing_settings_are_not_overwritten(tmp_path, content):
    from core.settings.store import SettingsStore
    path = tmp_path / 'settings.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        SettingsStore(path).set_theme('light')
    assert path.read_text() == content


def test_navigation_prioritizes_chat_agent_and_separates_management(ui):
    w, _, _ = ui
    assert list(w.nav)[:2] == ['chat', 'agent']
    assert 'projects' not in w.nav and 'projects' not in w.pages
    assert str(w.nav['chat']['style']) == 'Chat.Nav.TButton'
    assert str(w.nav['agent']['style']) == 'Agent.Nav.TButton'
    assert str(w.nav['models']['style']) == 'Manage.Nav.TButton'
    assert str(w.nav['setup']['style']) == 'Manage.Nav.TButton'
    w.navigate('models')
    assert str(w.nav['models']['style']) == 'Selected.Manage.Nav.TButton'
    assert str(w.nav['chat']['style']) == 'Chat.Nav.TButton'


def test_project_link_editor_is_inside_chat_not_a_global_page(ui, tmp_path):
    from core.projects.model import Project
    w, svc, _ = ui
    project = Project('kept', 'Kept', str(tmp_path), anythingllm_workspace='docs')
    svc.projects.save(project)
    before = svc.projects.store.path.read_bytes()
    w.navigate('projects')  # Compatibility request is routed into Chat.
    pump(w)
    assert w.current_page == 'chat'
    assert str(w.chat_tabs.select()) == str(w.chat_links_page)
    assert str(w.project_box).startswith(str(w.pages['chat']))
    assert svc.projects.store.path.read_bytes() == before
    assert svc.projects.get('kept') == project


def test_chat_workspace_management_uses_real_chat_ui_not_local_project_creation(ui, monkeypatch):
    w, svc, backend = ui
    opened = []
    monkeypatch.setattr('webbrowser.open', opened.append)
    w.session_mode.set('block')
    w.manage_chat_projects()
    pump(w, lambda: bool(opened))
    assert opened == ['http://127.0.0.1:3001']
    assert svc.projects.list() == []
    assert ('chat', '') in backend.calls
    assert not any(call[0] == 'search' for call in backend.calls)


def test_theme_switch_updates_raw_widgets_without_losing_text_or_session(ui):
    w, svc, backend = ui
    from apps.shared.widgets import set_text
    w.navigate('chat')
    set_text(w.chat_text, 'existing conversation\nkeep this')
    page, box, host = w.pages['chat'], w.chat_text, w.hosts['agent'].frame
    session = object()
    w.agent_session = session
    previous = box.cget('background')
    w.theme_choice.set('light')
    w.save_theme()
    pump(w, lambda: not w.runner.busy('appearance.save'))
    assert svc.settings.theme() == 'light'
    assert w.theme.name == 'light'
    assert box.cget('background') != previous
    assert w.pages['chat'] is page and w.chat_text is box and w.hosts['agent'].frame is host
    assert box.get('1.0', 'end-1c') == 'existing conversation\nkeep this'
    assert w.agent_session is session
    assert backend.calls == []
    assert host.cget('background') == w.theme.palette.bg
    w.agent_session = None


def test_theme_save_failure_keeps_previous_theme_and_reports_error(ui, monkeypatch):
    w, svc, _ = ui
    def locked(value):
        raise PermissionError('appearance locked')
    monkeypatch.setattr(svc.settings, 'set_theme', locked)
    old = w.theme.name
    w.theme_choice.set('light')
    w.save_theme()
    pump(w, lambda: not w.runner.busy('appearance.save'))
    assert w.theme.name == old
    assert w.theme_choice.get() == old
    assert 'appearance locked' in w.activity.get('1.0', 'end')
    assert all(not button.instate(['disabled']) for button in w.theme_buttons)


@pytest.mark.parametrize('app', ['studio', 'chat', 'interpreter', 'setup'])
def test_all_apps_restore_theme_before_display(tmp_path, app):
    gc.collect()
    from apps.shared.window import DesktopWindow
    svc, _ = make(tmp_path)
    svc.settings.set_theme('light')
    root = tk.Tk()
    w = DesktopWindow(app, svc, root=root, start_polling=False)
    try:
        root.update()
        assert w.theme.name == 'light'
        assert root.cget('background') == w.theme.palette.bg
        assert 'projects' not in w.nav
        if app == 'interpreter':
            assert w.project_boxes and str(w.project_boxes[0]).startswith(str(w.pages['agent']))
    finally:
        w.runner.shutdown()
        w._unsubscribe()
        root.after_cancel(w._timer)
        svc.close()
        root.destroy()


def test_theme_refreshes_from_another_window_without_runtime_changes(ui):
    from core.settings.store import SettingsStore
    w, svc, backend = ui
    SettingsStore(svc.settings.store.path).set_theme('light')
    w.sync_theme()
    pump(w, lambda: not w.runner.busy('appearance.sync'))
    assert w.theme.name == 'light'
    assert not backend.calls


def test_late_legacy_panel_inherits_theme_and_preserves_semantic_tags(ui):
    w, _, _ = ui
    w.theme.apply('light')
    frame = tk.Frame(w.hosts['agent'].frame, bg='#1e1e1e')
    text = tk.Text(frame, bg='#252526', fg='#cccccc')
    text.tag_configure('error', foreground='#f48771')
    text.tag_configure('warn', foreground='#d7ba7d')
    text.insert('end', 'problem', 'error')
    text.pack(); frame.pack()
    w.navigate('agent'); pump(w)
    assert frame.cget('background') == w.theme.palette.bg
    assert text.cget('background') == w.theme.palette.surface
    assert text.tag_cget('error', 'foreground') == w.theme.palette.danger
    assert text.tag_cget('warn', 'foreground') == w.theme.palette.warning
    w.theme.apply('dark')
    assert text.get('1.0', 'end-1c') == 'problem'
    assert text.tag_cget('error', 'foreground') == w.theme.palette.danger


def test_management_and_primary_treatments_are_distinct_in_both_themes(ui):
    w, _, _ = ui
    style = ttk.Style(w.root)
    for name in ('light', 'dark'):
        w.theme.apply(name)
        backgrounds = {style.lookup(s, 'background') for s in
                       ('Chat.TButton', 'Agent.TButton', 'Manage.TButton')}
        assert len(backgrounds) == 2
        assert style.lookup('Chat.TButton', 'background') == style.lookup('Agent.TButton', 'background')
        assert style.lookup('Danger.TButton', 'foreground') != style.lookup('Manage.TButton', 'foreground')


def test_connection_editor_reaches_save_at_minimum_window_size(ui):
    w, _, _ = ui
    w.root.geometry('1000x720')
    w.show_project_links()
    pump(w)
    canvas = w.page_scrolls['links'].canvas
    canvas.yview_moveto(1)
    pump(w)
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    save = next(button for button in descendants(w.chat_links_page)
                if isinstance(button, ttk.Button) and button.cget('text') == '\uc800\uc7a5')
    assert canvas.winfo_rooty() <= save.winfo_rooty()
    assert save.winfo_rooty() + save.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()


def test_home_management_controls_remain_reachable_at_minimum_size(ui):
    w, _, _ = ui
    w.root.geometry('1000x720')
    w.navigate('home')
    pump(w)
    canvas = w.page_scrolls['home'].canvas
    assert canvas.yview()[1] < 1
    canvas.yview_moveto(1)
    pump(w)
    assert canvas.yview()[1] == 1


def test_palette_text_contrast_has_a_minimum_ratio():
    from apps.shared.themes import PALETTES
    def luminance(hex_color):
        values = [int(hex_color[i:i+2], 16)/255 for i in (1, 3, 5)]
        channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(channels, (.2126,.7152,.0722)))
    for palette in PALETTES.values():
        pairs = [(palette.fg, palette.bg), (palette.muted, palette.bg),
                 (palette.danger, palette.surface)]
        for role in ('chat','agent','manage'):
            pairs += [(getattr(palette, role), getattr(palette, role+'_soft')),
                      (palette.solid_ink, getattr(palette, role))]
        for fg,bg in pairs:
            light,dark = sorted((luminance(fg),luminance(bg)), reverse=True)
            assert (light+.05)/(dark+.05) >= 4.5, (palette.name, fg, bg)


def test_shutdown_releases_unconsumed_gui_callbacks():
    import weakref
    from apps.shared.tasks import TaskRunner
    class CallbackOwner:
        def done(self, value):
            pass
    owner = CallbackOwner()
    reference = weakref.ref(owner)
    runner = TaskRunner()
    runner.submit('test', lambda: None, owner.done, owner.done)
    del owner
    runner.shutdown()
    assert not runner.busy()
    assert reference() is None
