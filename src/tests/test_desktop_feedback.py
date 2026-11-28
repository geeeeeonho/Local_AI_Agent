"""모델 카드의 설치 상태 표시와 작업 완료 알림.

예전 화면은 카드 맨 위의 옅은 글자 한 줄로만 설치 상태를 보여, '설치됨·유지'와 '설치됨·삭제 예정'을
구분하기 어려웠다. 작업 완료도 진행 기록과 같은 회색 줄이라 끝났는지 알기 어려웠다.
"""
import json

import pytest

pytest.importorskip('tkinter')   # 화면 코드는 tkinter가 있어야 불러올 수 있다

from test_desktop_models_screen import open_models, pump, ui  # noqa: F401  (pytest fixture)

from apps.shared.widgets import finished_level


def _install_catalog_model(services, tag='gemma4:12b', digest='a' * 64):
    name, _, version = tag.partition(':')
    blobs = services.model_dir / 'blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / ('sha256-' + digest)).write_bytes(b'weights')
    folder = services.model_dir / 'manifests' / 'registry.ollama.ai' / 'library' / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / version).write_text(json.dumps({'layers': [
        {'digest': 'sha256:' + digest, 'size': 7,
         'mediaType': 'application/vnd.ollama.image.model'}]}))
    return tag


def test_state_badge_sits_on_the_checkbox_line_and_the_card_border_follows_it(ui):
    w, svc, _ = ui
    installed = _install_catalog_model(svc)
    open_models(w)
    missing = next(tag for tag in w.choice_cards if tag not in w.catalog_installed())

    badge, box = w.choice_status_labels[installed][0], w.choice_checkbuttons[installed][0]
    assert str(badge.pack_info()['in']) == str(box.pack_info()['in'])   # 체크 상자와 같은 줄
    assert box.master in w.choice_cards[installed]
    cards = lambda tag: {card.cget('style') for card in w.choice_cards[tag]}
    assert cards(installed) == {'Model.CardInstalled.TFrame'}

    w.choice_vars[installed].set(False)
    w.choice_vars[missing].set(True)
    w.update_choice_summary()
    assert cards(installed) == {'Model.CardRemove.TFrame'}
    assert cards(missing) == {'Model.CardInstall.TFrame'}
    assert '삭제 예정' in w.choice_statuses[installed][0].get()

    w.choice_vars[missing].set(False)
    w.update_choice_summary()
    assert cards(missing) == {'Model.CardMissing.TFrame'}


def test_badge_wraps_in_a_narrow_card_instead_of_being_cut_off(ui):
    w, svc, _ = ui
    installed = _install_catalog_model(svc)
    open_models(w)
    w.choice_vars[installed].set(False)
    w.update_choice_summary()
    w.root.wm_geometry('1180x740')
    pump(w)
    shown = [(badge, box) for badge, box in zip(w.choice_status_labels[installed],
                                                w.choice_checkbuttons[installed]) if badge.winfo_ismapped()]
    assert shown
    for badge, box in shown:
        row = badge.pack_info()['in']
        # 한 줄로 들어가거나, 안 들어가면 두 줄로 접혀 있어야 한다(잘리지 않는다)
        assert badge.winfo_reqwidth() + box.winfo_reqwidth() <= row.winfo_width() or \
            int(str(badge.cget('wraplength')) or 0) > 0


def test_finished_jobs_are_logged_in_the_success_colour(ui):
    w, _, _ = ui
    w.log('설치 1개 · 삭제 0개 완료', level='success')
    assert w.message_label.cget('style') == 'Success.TLabel'
    w.log('models.refresh ...')
    ranges = w.activity.tag_ranges('success')
    assert len(ranges) == 2
    assert w.activity.get(ranges[0], ranges[1]).startswith('✔ 설치 1개')
    assert w.message_label.cget('style') == 'Muted.TLabel'


def test_only_user_changes_announce_completion_in_colour(ui):
    w, _, _ = ui
    w.run_task('example.change', lambda: None)
    w.run_task('example.read', lambda: None, mutate=False)
    pump(w, lambda: not w.runner.busy('example.change') and not w.runner.busy('example.read'))
    text = w.activity.get('1.0', 'end')
    ranges = w.activity.tag_ranges('success')
    coloured = ''.join(w.activity.get(a, b) for a, b in zip(ranges[::2], ranges[1::2]))
    assert 'example.change completed' in coloured
    assert 'example.read completed' in text and 'example.read' not in coloured


def test_ready_status_lines_count_as_finished_but_errors_stay_errors():
    assert finished_level('Ready') == 'success'
    assert finished_level('Ready', 'error') == 'error'
    assert finished_level('Working') == 'info'
    assert finished_level('Failed', 'error') == 'error'


def test_cards_are_three_lines_and_the_note_moves_under_the_size_when_narrow(ui):
    w, _, _ = ui
    w.root.wm_geometry('1500x1000')
    open_models(w)
    w.model_tabs.select(w.model_pages['choose'])
    pump(w)
    tag = 'devstral-small-2:24b'
    note = next(m['note'] for m in w._catalog['models'] if m['tag'] == tag)
    card = next(c for c in w.choice_cards[tag] if c.winfo_ismapped())
    # 이름·GPU / 체크·배지 / 크기·메모·설명: 카드 안에 줄(frame)이 세 개뿐이다
    rows = [child for child in card.pack_slaves() if child.winfo_class() == 'TFrame']
    assert len(rows) == 3
    label = next(child for child in card.winfo_children()
                 if child.winfo_class() == 'TLabel' and child.cget('text') == note)
    assert str(label.pack_info()['in']) == str(rows[2])          # 넓으면 크기 옆
    w.root.wm_geometry('1180x740')
    pump(w)
    for _ in range(20):
        w.root.update()
    if label.winfo_reqwidth() + sum(s.winfo_reqwidth() for s in rows[2].pack_slaves() if s is not label) \
            > rows[2].winfo_width():
        assert str(label.pack_info()['in']) == str(card)           # 좁으면 다음 줄
