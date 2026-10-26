"""The Setup page's account management: administrators act, nobody reads.

Driven through the real window with a stub backend; the Windows side of each
action is covered in test_machine_admin and test_accounts_admin.
"""
import pytest

from test_desktop_models_screen import pump, ui  # noqa: F401  (fixture)


def open_setup(w):
    w.navigate('setup')
    pump(w, lambda: bool(w.accounts_tree.get_children()))


def select(w, name):
    for iid in w.accounts_tree.get_children():
        if w.accounts_tree.item(iid)['values'][0].startswith(name):
            w.accounts_tree.selection_set(iid)
            w.root.update()
            return iid
    raise AssertionError(name)


def test_the_setup_page_lists_accounts_with_roles(ui):
    w, _, _ = ui
    open_setup(w)
    rows = [w.accounts_tree.item(iid)['values'] for iid in w.accounts_tree.get_children()]
    assert rows[0][0] == 'ghwork  (나)' and rows[0][1] == 'LocalAI 관리자'
    assert 'LocalAI 관리자입니다' in w.accounts_summary.get()


def test_buttons_follow_the_selected_account(ui):
    w, _, _ = ui
    open_setup(w)
    select(w, 'ghwork')
    state = {key: b.instate(['!disabled']) for key, b in w.account_buttons.items()}
    assert state['unadmin'] and not state['admin']
    assert not state['delete'], 'never delete the signed-in account from here'
    select(w, 'guest2')
    state = {key: b.instate(['!disabled']) for key, b in w.account_buttons.items()}
    assert state['admin'] and state['delete'] and state['allow']


def test_deleting_records_asks_first_and_a_no_touches_nothing(ui, monkeypatch):
    w, _, backend = ui
    open_setup(w)
    select(w, 'guest2')
    monkeypatch.setattr(w, 'confirm_account_delete', lambda row: False)
    w.account_action('delete')
    w.root.update()
    assert not any(call[0] == 'account' for call in backend.calls)
    monkeypatch.setattr(w, 'confirm_account_delete', lambda row: True)
    w.account_action('delete')
    pump(w, lambda: ('account', 'delete', 'S-1-5-21-1-2-3-1002', None) in backend.calls)


def test_a_non_administrator_only_sees(ui):
    w, _, backend = ui
    backend.accounts = dict(backend.accounts, is_admin=False)
    open_setup(w)
    select(w, 'guest2')
    assert not any(b.instate(['!disabled']) for b in w.account_buttons.values())
    assert '보기만' in w.accounts_summary.get()


def test_limiting_access_asks_and_then_applies(ui, monkeypatch):
    w, _, backend = ui
    open_setup(w)
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno', lambda *a, **k: True)
    w.accounts_access.set('members')
    w.set_account_access()
    pump(w, lambda: ('account', 'access', None, 'members') in backend.calls)


def test_unavailable_account_management_says_why(ui):
    w, _, backend = ui
    backend.accounts = {'available': False, 'reason': '아직 LocalAI 관리자가 정해지지 않았습니다.'}
    w.navigate('setup')
    pump(w, lambda: '관리자가 정해지지' in w.accounts_summary.get())
    assert not w.accounts_tree.get_children()


def test_the_setup_page_ollama_check_no_longer_waits_on_a_click(ui):
    w, _, backend = ui
    w.navigate('setup')
    w.ensure_ollama()
    pump(w, lambda: ('check_ollama',) in backend.calls and not w.runner.busy('models.ollama'))
