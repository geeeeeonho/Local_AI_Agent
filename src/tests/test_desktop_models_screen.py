"""One model screen: the current stack, the selection, and what is on disk.

The retained launcher split this across "installed model info" and "model
management", and the first desktop replaced the second with a free-text tag
entry. These tests hold the merged screen to the selection contract the
installer dialog already used: checked means the model should exist.
"""
import gc
import json
import time

import pytest

from test_desktop_services import make


def pump(window, predicate=lambda: True, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('UI condition did not settle')


def store_model(services, name='demo', digest='a' * 64, payload=b'weights'):
    blobs = services.model_dir / 'blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / ('sha256-' + digest)).write_bytes(payload)
    folder = services.model_dir / 'manifests' / 'registry.ollama.ai' / 'library' / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'latest').write_text(json.dumps({'layers': [
        {'digest': 'sha256:' + digest, 'size': len(payload),
         'mediaType': 'application/vnd.ollama.image.model'}]}))
    return name + ':latest'


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


def open_models(window):
    window.navigate('models')
    pump(window, lambda: window._catalog is not None and bool(window.stack_tree.get_children()))


# ── selection ────────────────────────────────────────────────────────────
def test_opening_models_offers_the_catalogue_with_the_budget_set_checked(ui):
    w, svc, _ = ui
    open_models(w)
    assert len(w.choice_vars) >= 10
    checked = {tag for tag, var in w.choice_vars.items() if var.get()}
    assert checked == set(w._catalog['recommended'])
    assert '설치 예정' in w.choice_summary.get()


def test_an_installed_model_stays_checked_so_it_is_not_silently_removed(ui):
    w, svc, _ = ui
    tag = store_model(svc)
    open_models(w)
    assert tag in w.choice_vars and w.choice_vars[tag].get()
    assert w.services.models.plan_changes(w.selected_tags(),
                                          installed=w.catalog_installed())['remove'] == []


def test_clearing_the_selection_plans_removal_of_what_is_installed(ui):
    w, svc, _ = ui
    tag = store_model(svc)
    open_models(w)
    w.set_selection('none')
    assert not any(var.get() for var in w.choice_vars.values())
    plan = w.services.models.plan_changes(w.selected_tags(), installed=w.catalog_installed())
    assert plan['install'] == [] and plan['remove'] == [tag]
    assert '삭제 예정 1개' in w.choice_summary.get()


def test_recommended_restores_the_budget_set_without_dropping_installed(ui):
    w, svc, _ = ui
    tag = store_model(svc)
    open_models(w)
    w.set_selection('none')
    w.set_selection('recommended')
    checked = {name for name, var in w.choice_vars.items() if var.get()}
    assert tag in checked
    assert set(w._catalog['recommended']) <= checked


def test_apply_pulls_and_removes_through_the_guarded_setup_service(ui, monkeypatch):
    w, svc, backend = ui
    tag = store_model(svc)
    open_models(w)
    w.set_selection('none')
    wanted = sorted(w.choice_vars)[0]
    w.choice_vars[wanted].set(True)
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno', lambda *a, **k: True)
    w.apply_selection()
    pump(w, lambda: ('pull', wanted) in backend.calls and ('remove', tag) in backend.calls)
    # Removal runs first so a disk-full store is not asked to hold both copies.
    assert backend.calls.index(('remove', tag)) < backend.calls.index(('pull', wanted))


def test_apply_stops_once_when_ollama_preflight_fails(ui, monkeypatch):
    w, svc, backend = ui
    open_models(w)
    w.set_selection('recommended')
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno', lambda *a, **k: True)
    monkeypatch.setattr(
        svc.setup, 'ensure_model_runtime',
        lambda **_kw: (_ for _ in ()).throw(RuntimeError('Ollama bootstrap failed')),
    )
    w.apply_selection()
    pump(w, lambda: not w.runner.busy())
    assert not any(call[0] in ('pull', 'remove') for call in backend.calls)
    assert 'Ollama bootstrap failed' in w.activity.get('1.0', 'end')


def test_apply_asks_before_touching_anything_and_honours_a_refusal(ui, monkeypatch):
    w, svc, backend = ui
    store_model(svc)
    open_models(w)
    w.set_selection('none')
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno', lambda *a, **k: False)
    w.apply_selection()
    pump(w, lambda: not w.runner.busy(), timeout=1)
    assert not any(call[0] in ('pull', 'remove') for call in backend.calls)


def test_no_change_needs_no_confirmation_and_no_work(ui, monkeypatch):
    w, svc, backend = ui
    open_models(w)
    w.set_selection('none')
    pump(w, lambda: True, timeout=.2)
    asked = []
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno',
                        lambda *a, **k: asked.append(1) or True)
    w.apply_selection()
    assert not asked and not any(call[0] in ('pull', 'remove') for call in backend.calls)


# ── current stack ────────────────────────────────────────────────────────
def test_the_stack_names_the_model_each_role_would_load_now(ui):
    w, _, _ = ui
    open_models(w)
    rows = [w.stack_tree.item(iid)['values'] for iid in w.stack_tree.get_children()]
    assert rows, 'no roles were reported'
    for label, model, need, on_disk in rows:
        assert label and model
        assert need.endswith('GB')
        assert on_disk in ('있음', '없음')


def test_the_requirement_shown_belongs_to_the_chosen_rung(ui):
    w, _, _ = ui
    open_models(w)
    stack = w.services.models.current_stack(free_gb=15.1)
    for role in stack['roles']:
        rung = next((r for r in role['ladder'] if r['tag'] == role['chosen']), None)
        if rung is not None:
            assert role['need_gb'] == rung['need_gb']


def test_selecting_a_role_shows_its_whole_ladder_with_disk_state(ui):
    w, _, _ = ui
    open_models(w)
    first = w.stack_tree.get_children()[0]
    w.stack_tree.selection_set(first)
    pump(w, lambda: '사다리' in w.stack_detail.get('1.0', 'end'))
    text = w.stack_detail.get('1.0', 'end')
    role = w._stack_rows[first]
    for rung in role['ladder']:
        assert rung['tag'] in text


def test_a_stopped_ollama_still_reports_the_stack_and_the_catalogue(ui):
    w, svc, backend = ui
    def refuse():
        raise RuntimeError('Ollama is not running')
    backend.inference.ensure_running = refuse
    open_models(w)
    assert w._catalog is not None
    assert w.stack_tree.get_children()


# ── disk view ────────────────────────────────────────────────────────────
def test_the_disk_tab_keeps_the_canonical_index_view(ui):
    w, svc, _ = ui
    tag = store_model(svc)
    w.refresh_models()
    pump(w, lambda: bool(w.model_tree.get_children()))
    assert w.model_tree.item(w.model_tree.get_children()[0])['values'][0] == tag
    assert (svc.model_dir / 'MODEL_INDEX.json').exists()


def test_ollama_check_never_waits_on_a_click_inside_the_model_screen(ui):
    """It ran the terminal action, whose pause() held every later change."""
    w, _, backend = ui
    open_models(w)
    w.ensure_ollama()
    pump(w, lambda: ('check_ollama',) in backend.calls and not w.runner.busy('models.ollama'))
    assert ('maintenance', 'ollama_action') not in backend.calls
    assert 'models' not in w.presenters, 'no presenter, so no [확인] to wait for'


def test_a_store_restart_is_asked_on_the_ui_thread_and_only_then_run(ui, monkeypatch):
    w, _, backend = ui
    open_models(w)
    backend.store_situation = 'unread'
    asked = []
    monkeypatch.setattr(w, 'confirm_store_restart', lambda result: asked.append(result) or True)
    w.ensure_ollama()
    pump(w, lambda: ('restart_ollama',) in backend.calls)
    assert asked and asked[0]['on_disk'] == 3

    backend.calls.clear()
    monkeypatch.setattr(w, 'confirm_store_restart', lambda result: False)
    w.ensure_ollama()
    pump(w, lambda: ('check_ollama',) in backend.calls and not w.runner.busy('models.ollama'))
    assert ('restart_ollama',) not in backend.calls


def test_a_change_queued_behind_another_says_what_it_waits_for(ui):
    import threading
    w, _, _ = ui
    gate = threading.Event()
    w.run_task('models.slow', lambda: gate.wait(5))
    w.run_task('models.next', lambda: None)
    text = w.activity.get('1.0', 'end')
    gate.set()
    pump(w, lambda: not w.runner.busy())
    assert 'models.next 대기 중' in text and 'models.slow' in text


def test_pull_progress_is_one_activity_line_per_step_not_per_chunk(ui):
    w, _, _ = ui
    lines = []
    for completed in range(0, 101):
        line = w.model_transfer_line({'model': 'gemma4:12b', 'status': 'pulling abc',
                                      'completed': completed, 'total': 100})
        if line:
            lines.append(line)
    assert len(lines) == 11, lines
    assert lines[-1].startswith('gemma4:12b · pulling abc · 100%')
    assert w.model_transfer_line({'model': 'gemma4:12b', 'status': 'success'})


def test_setup_no_longer_asks_the_user_to_type_a_model_tag(ui):
    w, _, _ = ui
    assert not hasattr(w, 'install_tag')
    assert not hasattr(w, 'change_model')


# ── where models land, and whether they fit ──────────────────────────────
def test_the_store_path_is_named_where_the_download_is_chosen(ui):
    w, svc, _ = ui
    open_models(w)
    assert str(svc.model_dir) in w.choice_storage.get()


def test_free_space_is_shown_next_to_what_the_selection_costs(ui):
    w, _, _ = ui
    open_models(w)
    assert '남은 공간' in w.choice_storage.get()
    assert '최대' in w.choice_summary.get()


def test_a_selection_that_cannot_fit_is_flagged_as_a_problem(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage',
                        lambda: dict(real(), free_bytes=1024 ** 3, total_bytes=2 * 1024 ** 3))
    w.set_selection('recommended')
    assert w.choice_storage_label.cget('style') == 'Alert.TLabel'
    assert '부족' in w.choice_storage.get()


def test_a_selection_that_fits_is_not_flagged(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage',
                        lambda: dict(real(), free_bytes=4096 * 1024 ** 3, total_bytes=8192 * 1024 ** 3))
    w.set_selection('recommended')
    assert w.choice_storage_label.cget('style') == 'Muted.TLabel'
    assert '부족' not in w.choice_storage.get()


def test_removing_only_never_warns_about_space(ui, monkeypatch):
    w, svc, _ = ui
    store_model(svc)
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage', lambda: dict(real(), free_bytes=0, total_bytes=1))
    w.set_selection('none')
    assert w.choice_storage_label.cget('style') == 'Muted.TLabel'
    assert '부족' not in w.choice_storage.get()


def test_an_unreadable_disk_says_so_instead_of_claiming_a_number(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage',
                        lambda: dict(real(), free_bytes=None, total_bytes=None))
    w.set_selection('recommended')
    assert '확인할 수 없습니다' in w.choice_storage.get()
    assert w.choice_storage_label.cget('style') == 'Muted.TLabel'


def test_a_store_that_does_not_exist_yet_is_explained_not_hidden(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage', lambda: dict(real(), exists=False))
    w.set_selection('recommended')
    assert '아직 없음' in w.choice_storage.get()


def test_the_confirmation_repeats_where_it_goes_and_whether_it_fits(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage',
                        lambda: dict(real(), free_bytes=1024 ** 3, total_bytes=2 * 1024 ** 3))
    w.set_selection('recommended')
    asked = {}
    def capture(title, message, **kw):
        asked['message'] = message
        return False
    monkeypatch.setattr('apps.shared.window.messagebox.askyesno', capture)
    w.apply_selection()
    assert str(svc.model_dir) in asked['message']
    assert '부족' in asked['message']
    assert '중간에 실패' in asked['message']


def test_the_disk_tab_reports_used_and_free_at_the_store(ui):
    w, svc, _ = ui
    store_model(svc)
    w.refresh_models()
    pump(w, lambda: bool(w.model_tree.get_children()))
    summary = w.model_summary.get()
    assert str(svc.model_dir) in summary
    assert '사용' in summary and '남은 공간' in summary


def test_the_plan_calls_its_download_size_an_upper_bound(ui):
    """Ollama shares blob layers, so summed catalogue sizes are a ceiling."""
    w, svc, _ = ui
    open_models(w)
    plan = svc.models.plan_changes(w.selected_tags(), installed=w.catalog_installed())
    assert plan['download_is_upper_bound'] is True


def test_the_screen_says_whether_other_accounts_share_the_store(ui, monkeypatch):
    w, svc, _ = ui
    open_models(w)
    real = svc.models.storage
    monkeypatch.setattr(svc.models, 'storage', lambda: dict(real(), shared=True, per_user=False))
    w.set_selection('recommended')
    assert '모든 Windows 계정' in w.choice_storage.get()
    monkeypatch.setattr(svc.models, 'storage', lambda: dict(real(), shared=False, per_user=True))
    w.set_selection('recommended')
    assert '이 계정 전용' in w.choice_storage.get()


# ── role-based accordion catalogue ─────────────────────────────────────
def test_role_groups_contain_three_recommendations_and_optional_choices(ui):
    w, _, _ = ui
    open_models(w)
    expected={'coding','agent','uncensored','office','balanced'}
    assert {key.removeprefix('role:') for key in w.catalog_groups
            if key.startswith('role:') and ':' not in key[5:]} == expected

    for name in expected:
        for number in (1,2,3):
            assert f'role:{name}:tier:{number}' in w.catalog_groups
            assert '(권장)' in w.catalog_groups[
                f'role:{name}:tier:{number}'].button.cget('text')
        assert f'role:{name}:options' in w.catalog_groups
        assert not w.catalog_groups[f'role:{name}:options'].expanded

    # Every catalogue entry is still selectable, including RAG embedders.
    tags={model['tag'] for model in w._catalog['models']}
    assert set(w.choice_vars) == tags | set(w._catalog['extra_installed'])


def test_each_role_and_its_subsections_expand_independently(ui):
    w, _, _ = ui
    open_models(w)
    coding=w.catalog_groups['role:coding']
    uncensored=w.catalog_groups['role:uncensored']
    options=w.catalog_groups['role:uncensored:options']
    middle=w.catalog_groups['role:uncensored:tier:2']

    assert coding.expanded and uncensored.expanded
    coding.button.invoke()
    assert not coding.expanded
    coding.button.invoke()
    assert uncensored.expanded and coding.expanded
    assert not options.expanded and middle.expanded
    options.button.invoke()
    middle.button.invoke()
    assert options.expanded and not middle.expanded

    before=w.selected_tags()
    uncensored.button.invoke()
    assert not uncensored.expanded
    assert before == w.selected_tags()
    uncensored.button.invoke()
    assert options.expanded and not middle.expanded

    # Refresh retains user-controlled fold state (but still loads the catalog).
    w.build_catalog_rows(w._catalog)
    assert w.catalog_groups['role:uncensored'].expanded
    assert w.catalog_groups['role:uncensored:options'].expanded
    assert not w.catalog_groups['role:uncensored:tier:2'].expanded


def test_uncensored_mid_has_trevor_recommended_and_previous_as_option(ui):
    w, _, _ = ui
    open_models(w)
    trevor='hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0'
    trevor_q4='hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q4_K_M'
    previous='huihui_ai/qwen3-abliterated:14b'
    high='prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S'

    def inside(widget, container):
        return str(widget).startswith(str(container)+'.')

    mid=w.catalog_groups['role:uncensored:tier:2'].body
    options=w.catalog_groups['role:uncensored:options'].body
    highest=w.catalog_groups['role:uncensored:tier:1'].body
    assert any(inside(box,mid) for box in w.choice_checkbuttons[trevor])
    assert any(inside(box,options) for box in w.choice_checkbuttons[previous])
    assert trevor_q4 not in w.choice_checkbuttons
    assert any(inside(box,highest) for box in w.choice_checkbuttons[high])


def test_shared_models_use_one_checkbox_variable_and_one_install_item(ui):
    w, _, _ = ui
    open_models(w)
    shared='gemma4:12b'
    assert len(w.choice_checkbuttons[shared]) > 1
    first,second=w.choice_checkbuttons[shared][:2]
    assert w.choice_vars[shared].get()
    first.invoke()
    w.root.update_idletasks()
    assert not w.choice_vars[shared].get()
    assert not second.instate(['selected'])
    assert shared not in w.selected_tags()
    second.invoke()
    assert first.instate(['selected'])
    assert shared in w.selected_tags()
    plan=w.services.models.plan_changes(
        w.selected_tags(),installed=w.catalog_installed())
    assert plan['install'].count(shared) <= 1


def test_catalog_has_responsive_four_column_roles(ui):
    w, _, _ = ui
    open_models(w)
    from apps.shared.models_view import CatalogColumns
    assert CatalogColumns.columns_for_width(1100) == 4
    assert CatalogColumns.columns_for_width(650) == 2
    assert CatalogColumns.columns_for_width(820) == 2
    assert CatalogColumns.columns_for_width(200) == 1
    assert len(w.catalog_columns.slots) >= 5
    w.catalog_columns.reflow(1100)
    assert w.catalog_columns.columns == 4
    roles = [w.catalog_groups['role:' + key].frame.master
             for key in ('coding', 'agent', 'uncensored', 'office', 'balanced')]
    assert [int(frame.grid_info()['column']) for frame in roles] == [0, 1, 2, 3, 0]
    w.catalog_columns.reflow(650)
    assert [int(frame.grid_info()['column']) for frame in roles] == [0, 1, 0, 1, 0]


def test_catalog_state_label_distinguishes_disk_from_choice(ui):
    w, svc, _ = ui
    installed = store_model(svc)
    open_models(w)
    missing = next(tag for tag in w.choice_vars if tag not in w.catalog_installed())
    assert '설치됨' in w.choice_statuses[installed][0].get()
    assert '미설치' in w.choice_statuses[missing][0].get()
    w.choice_vars[installed].set(False)
    w.choice_vars[missing].set(True)
    w.update_choice_summary()
    assert '삭제 예정' in w.choice_statuses[installed][0].get()
    assert '설치 예정' in w.choice_statuses[missing][0].get()


def test_catalog_refresh_does_not_leak_resize_handlers_or_discard_unsaved_choices(ui):
    w, _, _ = ui
    open_models(w)
    w.model_tabs.select(w.model_pages['choose'])
    pump(w)
    original_binding = w.choice_body.bind('<Configure>')
    tag = next(iter(w.choice_vars))
    w.choice_vars[tag].set(not w.choice_vars[tag].get())
    chosen = w.choice_vars[tag].get()

    for _ in range(3):
        old_frame = w.catalog_columns.frame
        w.build_catalog_rows(w._catalog)
        assert not old_frame.winfo_exists()
        assert w.choice_body.bind('<Configure>') == original_binding
        assert w.choice_vars[tag].get() == chosen

    w.root.wm_geometry('1180x740')
    pump(w)
    assert w.catalog_columns.frame.winfo_exists()


def test_status_styles_distinguish_missing_pending_and_removal(ui):
    w, svc, _ = ui
    installed = store_model(svc)
    open_models(w)
    missing = next(tag for tag in w.choice_vars if tag not in w.catalog_installed())

    assert w.choice_status_labels[installed][0].cget('style') == 'Model.StateInstalled.TLabel'
    w.choice_vars[installed].set(False)
    w.choice_vars[missing].set(False)
    w.update_choice_summary()
    assert w.choice_status_labels[installed][0].cget('style') == 'Model.StateRemove.TLabel'
    assert w.choice_status_labels[missing][0].cget('style') == 'Model.StateMissing.TLabel'

    w.choice_vars[missing].set(True)
    w.update_choice_summary()
    assert w.choice_status_labels[missing][0].cget('style') == 'Model.StateInstall.TLabel'


def test_catalog_preserves_model_notes_when_rendering_compact_cards(ui):
    w, _, _ = ui
    open_models(w)
    note_model = next(m for m in w._catalog['models'] if m.get('note'))
    card = w.choice_checkbuttons[note_model['tag']][0].master
    notes = [child.cget('text') for child in card.winfo_children()
             if isinstance(child, __import__('tkinter').ttk.Label)]
    assert note_model['note'] in notes


def test_collapse_all_does_not_collapse_tiers_or_change_selections(ui):
    w, _, _ = ui
    open_models(w)
    before = w.selected_tags()
    w.fold_catalog_roles(False)
    assert not w.catalog_groups['role:coding'].expanded
    assert w.catalog_groups['role:coding:tier:2'].expanded
    w.fold_catalog_roles(True)
    assert w.catalog_groups['role:coding'].expanded
    assert w.catalog_groups['role:coding:tier:2'].expanded
    assert w.selected_tags() == before
