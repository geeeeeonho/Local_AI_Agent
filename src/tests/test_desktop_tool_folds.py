"""번역·자막 화면: 구획 접기와 기억, 대본으로 시간 맞추기.

화면이 길어 실행 단추·진행률 아래 구획을 한꺼번에 볼 수 없었다. 구획마다 접을 수 있고, 접은 상태는
다음에 열 때 그대로다. 실행 단추와 진행률은 스크롤 영역 밖(위)에 있어 접어도 늘 보인다.
"""
import pytest

pytest.importorskip('tkinter')

from test_desktop_ui import pump, ui  # noqa: F401  (pytest fixture)
from test_subtitles import FakeTranslator, _wav, fake_engine  # noqa: F401  (pytest fixture)


def _open_translation(w):
    w.services.translator.local_models = lambda: ['gemma4:12b']
    w.navigate('tools'); w.open_tool('translate')
    pump(w, lambda: w.translation_model.get() == 'gemma4:12b', timeout=5)


def test_translation_sections_fold_and_the_choice_is_remembered(ui):
    w, svc, _ = ui
    _open_translation(w)
    folds = w.translation_folds
    assert set(folds.sections) == {'source', 'method', 'glossary', 'preview'}
    preview = folds.sections['preview']
    assert preview.expanded and preview.body.winfo_ismapped()
    preview.button.invoke(); pump(w)
    assert not preview.expanded and not preview.body.winfo_ismapped()
    assert preview.frame.winfo_ismapped() and preview.button.cget('text').startswith('▶')   # 제목은 남는다
    assert w.translation_start_button.winfo_ismapped()          # 실행 단추는 접어도 보인다
    pump(w, lambda: svc.settings.translation_preferences().get('folded') == 'preview', timeout=4)
    # 다시 열면(새 창) 접은 상태 그대로
    preview.set_expanded(True, notify=False)
    w._translation_prefs_loaded = False
    w.translation_opened(); pump(w, lambda: not preview.expanded, timeout=4)


def test_advanced_settings_still_open_before_the_preview(ui):
    w, _, _ = ui
    _open_translation(w)
    w.toggle_translation_advanced(True); pump(w)
    body = w.translation_advanced.master
    order = body.pack_slaves()
    assert order.index(w.translation_advanced) < order.index(w.translation_folds.sections['preview'].frame)


def test_subtitle_sections_fold_and_the_script_section_starts_folded(ui, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    folds = w.subtitle_folds
    assert set(folds.sections) == {'source', 'script', 'translate', 'rules', 'hint', 'preview'}
    assert not folds.sections['script'].expanded                 # 선택 기능은 접어 둔다
    folds.sections['translate'].toggle(); pump(w)
    pump(w, lambda: set(svc.settings.subtitle_preferences().get('folded', '').split(',')) ==
         {'script', 'translate'}, timeout=4)


def test_a_chosen_script_reaches_the_subtitle_service(ui, tmp_path, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    svc.subtitles.translator = FakeTranslator()
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    media = _wav(tmp_path / 'scene.wav')
    script = tmp_path / 'scene.txt'
    script.write_text('Hello and welcome to the show.\nToday we talk about subtitles.\nAnd why rules matter.\n',
                      encoding='utf-8')
    w.subtitle_path.set(str(media)); w.analyze_subtitle_input()
    pump(w, lambda: str(w.subtitle_start_button['state']) == 'normal')
    w.subtitle_script.set(str(script))
    w.start_subtitles()
    pump(w, lambda: not w.runner.busy('tools.subtitles') and (tmp_path / 'scene.srt').exists(), timeout=15)
    pump(w, lambda: '대본: scene.txt' in w.subtitle_report_text.get('1.0', 'end'), timeout=5)
    text = (tmp_path / 'scene.srt').read_text(encoding='utf-8-sig')
    assert 'Today we talk about subtitles.' in text and 'And why rules matter.' in text


def test_a_script_with_several_files_is_refused_before_starting(ui, tmp_path, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    w._subtitle_files = [_wav(tmp_path / 'a.wav'), _wav(tmp_path / 'b.wav')]
    script = tmp_path / 's.txt'; script.write_text('a\n', encoding='utf-8')
    w.subtitle_script.set(str(script))
    w.start_subtitles(); pump(w)
    assert '하나에만' in w.subtitle_status.get() and not w.runner.busy('tools.subtitles')
