"""Compact layout regressions (Tk, optional Xvfb on Linux).

Verify that default affordances remain reachable at 880x560, while advanced
controls are discoverable and keep their values when folded.
"""
from __future__ import annotations

import gc
import time
import pytest

from test_desktop_services import make


@pytest.fixture
def ui(tmp_path):
    gc.collect()
    tk=pytest.importorskip('tkinter')
    from apps.shared.window import DesktopWindow
    services,backend=make(tmp_path)
    try:
        root=tk.Tk()
    except tk.TclError:
        pytest.skip('Real Tk requires DISPLAY')
    window=DesktopWindow('studio',services,root=root,start_polling=False)
    window.root.geometry('880x560')
    window.root.update()
    yield window,services,backend
    window.runner.shutdown()
    window._unsubscribe()
    services.close()
    try:
        window.root.after_cancel(window._timer)
    except tk.TclError:
        pass
    window.root.destroy()


def settle(w, *, attempts=20):
    for _ in range(attempts):
        w.root.update()
        time.sleep(.01)


def on_screen(w, widget):
    settle(w, attempts=4)
    assert widget.winfo_ismapped(), str(widget) + ' is unmapped'
    top=w.root.winfo_rooty()
    return top<=widget.winfo_rooty() and (
        widget.winfo_rooty()+widget.winfo_height() <=
        top+w.root.winfo_height())


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


def text_button(parent, text):
    from tkinter import ttk
    return next(w for w in children(parent)
                if isinstance(w,ttk.Button) and w.cget('text') == text)


def test_fresh_default_is_soft_light_and_log_collapsed(ui):
    w,svc,_=ui
    assert w.theme.name=='light'
    assert not w._activity_visible
    assert svc.settings.activity_visible() is False
    assert svc.settings.theme()=='light'
    assert w.root.winfo_width() == 880


def test_all_primary_sidebar_actions_remain_visible_at_minimum_size(ui):
    w,_,_=ui
    for key in ('chat','agent','tools','models','setup','home'):
        assert on_screen(w,w.nav[key]),key
    assert not w.advanced_nav_visible
    assert not w.nav['settings'].winfo_ismapped()
    w.advanced_nav_toggle.invoke()
    settle(w)
    assert w.nav['settings'].winfo_ismapped()
    w.navigate('settings')
    assert w.advanced_nav_visible
    assert on_screen(w,w.nav['settings'])


def test_chat_agent_and_setup_buttons_remain_in_view(ui):
    w,_,_=ui
    for key,label in (
        ('chat','Chat 시작'),('agent','Agent 시작'),('setup','설치 / 복구 실행'),
    ):
        w.navigate(key)
        settle(w)
        assert on_screen(w,text_button(w.pages[key],label)),key


def test_model_apply_and_gpu_bars_have_real_space_at_minimum_size(ui):
    w,_,_=ui
    w.navigate('models')
    settle(w,attempts=30)
    w.model_tabs.select(w.model_pages['choose'])
    settle(w)
    assert on_screen(w,w.apply_button)
    assert w.apply_button.winfo_height()>10
    assert w.choice_scroller.canvas.winfo_height()>50
    assert 'models.gpu' in w.page_scrolls
    for key in ('used','model','projected'):
        assert key in w.gpu_bars
        assert int(w.gpu_bars[key][0]['maximum'])==100


def test_setup_options_are_folded_without_losing_values(ui):
    w,_,_=ui
    w.navigate('setup')
    settle(w)
    advanced=text_button(w.pages['setup'],'▶  설치 구성 옵션 펼치기')
    assert not w.setup_build_check.winfo_ismapped()
    advanced.invoke()
    settle(w)
    assert w.setup_build_check.winfo_ismapped()
    w.setup_search.set(False)
    advanced.invoke()
    advanced.invoke()
    assert w.setup_search.get() is False


def test_tools_hub_can_scroll_on_short_windows(ui):
    w,_,_=ui
    w.navigate('tools')
    settle(w)
    assert 'tools.hub' in w.page_scrolls
    canvas=w.page_scrolls['tools.hub'].canvas
    assert canvas.winfo_height()>60
    assert len([c for c in children(w.tool_hub) if c.winfo_class()=='TButton'])>=3
