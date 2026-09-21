"""Cohesive appearance: one accent, neutral management and semantic alerts.

Assertions target rendered Tk style state, not theme-application mock calls.
Restoring the previous three-color palette or solid management/selection fills
must fail these regressions in either theme.
"""
import colorsys

import pytest

# Tk 가 없는 머신은 이 모듈만 건너뛴다. 모듈 최상단에서 tkinter 를 바로
# import 하면 수집 단계에서 저장소 전체 테스트 실행이 중단된다.
pytest.importorskip('tkinter')

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402
from test_desktop_ui import ui, pump  # noqa: E402,F401  (pytest fixtures)


def contrast(first, second):
    def luminance(value):
        channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                  for v in channels]
        return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + .05) / (dark + .05)


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_primary_features_share_one_restrained_accent(name):
    from apps.shared.themes import PALETTES
    p = PALETTES[name]
    assert p.chat == p.agent
    assert p.chat_soft == p.agent_soft
    _, _, saturation = colorsys.rgb_to_hls(*(int(p.chat[i:i + 2], 16) / 255
                                             for i in (1, 3, 5)))
    assert saturation <= .4
    _, _, management_saturation = colorsys.rgb_to_hls(
        *(int(p.manage[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    assert management_saturation <= .2


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_management_is_neutral_outlined_not_a_third_solid_accent(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    p, style = w.theme.palette, ttk.Style(w.root)
    assert style.lookup('Manage.TButton', 'background') == p.manage_soft
    assert style.lookup('Manage.TButton', 'foreground') == p.manage
    assert style.lookup('Manage.TButton', 'bordercolor') == p.border
    assert int(style.lookup('Manage.TButton', 'borderwidth')) == 1
    assert style.lookup('Manage.TButton', 'background') != style.lookup('Chat.TButton', 'background')


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_cards_and_titles_do_not_use_saturated_feature_outlines(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    p, style = w.theme.palette, ttk.Style(w.root)
    for kind in ('Chat', 'Agent', 'Manage'):
        assert style.lookup(kind + '.Card.TFrame', 'bordercolor') == p.border
        assert style.lookup(kind + '.Card.TLabel', 'foreground') == p.fg
        assert style.lookup(kind + '.CardMuted.TLabel', 'foreground') == p.muted
        assert style.lookup(kind + '.Title.TLabel', 'foreground') == p.fg


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_primary_priority_remains_in_typography_and_spacing(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    style = ttk.Style(w.root)
    assert list(w.nav)[:2] == ['chat', 'agent']
    for key in ('chat', 'agent'):
        primary = str(w.nav[key].cget('style'))
        secondary = str(w.nav['models'].cget('style'))
        def font_size(s):
            value = style.lookup(s, 'font')
            return int(w.root.tk.splitlist(value)[1])
        assert font_size(primary) > font_size(secondary)
        assert int(w.root.tk.splitlist(style.lookup(primary, 'padding'))[1]) > int(w.root.tk.splitlist(style.lookup(secondary, 'padding'))[1])


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_selection_is_a_soft_fill_not_a_large_solid_button(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    p, style = w.theme.palette, ttk.Style(w.root)
    for key in ('chat', 'agent', 'models', 'setup'):
        w.navigate(key)
        selected_style = str(w.nav[key].cget('style'))
        for state in ((), ('active',)):
            assert style.lookup(selected_style, 'background', state) == p.selected
            assert style.lookup(selected_style, 'background', state) not in (p.chat, p.manage)


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_rendered_enabled_controls_keep_legible_text(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    style = ttk.Style(w.root)
    for kind in ('Chat', 'Agent', 'Manage'):
        for suffix in ('.TButton', '.Nav.TButton'):
            for state in ((), ('active',), ('pressed',), ('focus',)):
                s = kind + suffix
                fg = style.lookup(s, 'foreground', state)
                bg = style.lookup(s, 'background', state)
                assert contrast(fg, bg) >= 4.5, (name, s, state, fg, bg)
        s = 'Selected.' + kind + '.Nav.TButton'
        assert contrast(style.lookup(s, 'foreground'), style.lookup(s, 'background')) >= 4.5


def test_warning_and_success_colors_do_not_follow_neutral_management(ui):
    w, _, _ = ui
    text = tk.Text(w.hosts['agent'].frame, bg='#252526', fg='#cccccc')
    for tag, color in (('warn', '#d7ba7d'), ('stderr', '#e1bda5'),
                       ('error', '#f48771'), ('user', '#73c991')):
        text.tag_configure(tag, foreground=color)
        text.insert('end', tag + '\n', tag)
    original = text.get('1.0', 'end-1c')
    text.pack()
    for theme in ('light', 'dark', 'light'):
        w.theme.apply(theme)
        p = w.theme.palette
        assert hasattr(p, 'warning') and hasattr(p, 'success')
        assert text.tag_cget('warn', 'foreground') == p.warning
        assert text.tag_cget('stderr', 'foreground') == p.warning
        assert text.tag_cget('error', 'foreground') == p.danger
        assert text.tag_cget('user', 'foreground') == p.success
        assert len({p.warning, p.success, p.danger, p.manage, p.chat}) == 5
        for color in (p.warning, p.success, p.danger):
            assert contrast(color, p.surface) >= 4.5
        assert text.get('1.0', 'end-1c') == original


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_scrollbars_and_separators_do_not_inherit_clam_white_state_fills(ui, name):
    w, _, _ = ui
    w.theme.apply(name)
    p, style = w.theme.palette, ttk.Style(w.root)
    for orientation in ('Vertical', 'Horizontal'):
        for state in (('disabled',), ('active',)):
            color = style.lookup(orientation + '.TScrollbar', 'background', state)
            assert color in (p.border, p.surface, p.hover), (name, state, color)
            assert style.lookup('TSeparator', 'background', state) == p.border


def test_home_management_actions_share_one_quiet_treatment(ui):
    w, _, _ = ui
    def buttons(parent):
        for child in parent.winfo_children():
            if isinstance(child, ttk.Button):
                yield child
            yield from buttons(child)
    actions = [b for b in buttons(w.pages['home'])
               if b.cget('text') in ('\ubaa8\ub378 \ubcf4\uae30', '\uc124\uce58 / \ubcf5\uad6c')]
    assert len(actions) == 2
    assert all(str(b.cget('style')) == 'Manage.TButton' for b in actions)
    parent = actions[0].master
    assert int(ttk.Style(w.root).lookup(parent.cget('style'), 'borderwidth')) == 0
