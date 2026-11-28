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


def test_subtitle_sections_fold_and_are_remembered(ui, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    folds = w.subtitle_folds
    assert set(folds.sections) == {'source', 'script', 'translate', 'rules', 'hint', 'preview'}
    assert folds.sections['script'].expanded                     # 파일 구획 옆에 나란히 보인다
    folds.sections['translate'].toggle(); pump(w)
    pump(w, lambda: svc.settings.subtitle_preferences().get('folded') == 'translate', timeout=4)


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


def test_a_script_folder_works_with_a_media_folder(ui, tmp_path, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    media = tmp_path / 'media'; media.mkdir()
    _wav(media / 'ep1.wav'); _wav(media / 'ep2.wav')
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    (scripts / 'ep1.txt').write_text('Hello and welcome to the show.\n', encoding='utf-8')
    w.subtitle_path.set(str(media)); w.analyze_subtitle_input()
    pump(w, lambda: str(w.subtitle_start_button['state']) == 'normal')
    w.subtitle_script.set(str(scripts))
    assert '대본 사용' in w.subtitle_destination.cget('text')
    w.start_subtitles()
    pump(w, lambda: not w.runner.busy('tools.subtitles') and (media / 'ep1.srt').exists(), timeout=15)
    pump(w, lambda: '대본이 없어 건너뛴 파일 (1)' in w.subtitle_report_text.get('1.0', 'end'), timeout=5)
    assert not (media / 'ep2.srt').exists()


def test_the_name_option_is_remembered(ui, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    w.subtitle_translate_name.set(True)
    pump(w, lambda: svc.settings.subtitle_preferences().get('translate_name') is True, timeout=4)


def _answers(monkeypatch, *folders):
    """폴더 선택 창에 차례로 답한다."""
    from apps.shared import subtitle_controller
    queue = [str(folder) for folder in folders]
    monkeypatch.setattr(subtitle_controller.filedialog, 'askdirectory', lambda **_kw: queue.pop(0) if queue else '')
    return queue


def test_a_folder_with_scripts_and_videos_is_ready_at_once(ui, tmp_path, fake_engine, monkeypatch):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    home = tmp_path / 'season'; home.mkdir()
    _wav(home / 'ep1.wav'); _wav(home / 'ep2.wav')
    (home / 'ep1.txt').write_text('Hello and welcome to the show.\n', encoding='utf-8')
    (home / 'ep2.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nold\n', encoding='utf-8')  # 자막이지 대본 아님
    _answers(monkeypatch, home)
    w.choose_subtitle_script_home()
    pump(w, lambda: str(w.subtitle_start_button['state']) == 'normal', timeout=5)
    assert w.subtitle_script.get() == str(home) and w.subtitle_path.get() == str(home)
    assert sorted(path.name for path in w._subtitle_files) == ['ep1.wav', 'ep2.wav']
    assert '짝지은 영상·음성 1개 / 2개' in w.subtitle_script_summary.cget('text')


def test_without_videos_in_the_script_folder_the_media_folder_is_asked_for(ui, tmp_path, fake_engine, monkeypatch):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    scripts, media = tmp_path / 'scripts', tmp_path / 'media'
    scripts.mkdir(); media.mkdir()
    (scripts / 'ep1.txt').write_text('Hello.\n', encoding='utf-8')
    _wav(media / 'ep1.wav')
    left = _answers(monkeypatch, scripts, media)
    w.choose_subtitle_script_home()
    pump(w, lambda: w.subtitle_path.get() == str(media) and w._subtitle_files, timeout=5)
    assert not left and w.subtitle_script.get() == str(scripts)
    pump(w, lambda: '짝지은 영상·음성 1개 / 1개' in w.subtitle_script_summary.cget('text'), timeout=5)


def test_media_and_script_sections_sit_side_by_side_and_stack_when_narrow(ui, fake_engine):
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    w.root.wm_geometry('1300x900')
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    source, script = (w.subtitle_folds.sections[key].frame for key in ('source', 'script'))
    pump(w, lambda: source.winfo_width() > 1 and source.winfo_y() == script.winfo_y(), timeout=5)
    assert source.winfo_x() + source.winfo_width() <= script.winfo_x()        # 겹치지 않고 좌우로
    assert abs(source.winfo_width() - script.winfo_width()) <= 2              # 반씩
    w.root.wm_geometry('900x900')
    pump(w, lambda: script.winfo_y() > source.winfo_y() + source.winfo_height() - 2, timeout=5)  # 위아래로
