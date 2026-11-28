"""번역 자막에 원문이 남거나 어떤 시간대 자막이 비는 경우.

* 두 글자 감탄사('はい')를 '…'로만 옮긴 답이 통과해, 화면에는 그 시간대 자막이 없는 것처럼 보였다.
* 시작이 겹치거나 틈 없이 몰린 큐는 앞 큐 끝에 밀려 1ms가 되었다(글은 있는데 보이지 않음).
  대본 맞추기에서 음성에서 찾지 못한 줄을 끼울 틈이 없을 때 생겼다.
* 원문으로 남은 줄은 번역 도구의 '파일 줄 번호'로만 알려 줘(예: 7) 어느 자막인지 찾기 어려웠다.
"""
import json
from pathlib import Path

from core.tools.subtitles import Cue, parse, retime, rules_for, to_srt
from services.tools.translation import _misbehaviour
from test_subtitles import _service, _wav, fake_engine  # noqa: F401  (pytest fixture)


def test_an_interjection_turned_into_dots_is_sent_back():
    assert _misbehaviour('はい。', '…')
    assert _misbehaviour('えっ？', '?!')
    assert not _misbehaviour('はい。', '네.')
    assert not _misbehaviour('♪～', '♪～')                     # 글자가 없는 원문은 그대로 둘 수 있다


def test_a_cue_pushed_to_nothing_is_merged_into_its_neighbour():
    rules = rules_for('ko')
    cues = retime([Cue(1000, 2000, ('하나',)), Cue(1000, 2500, ('둘',)), Cue(2600, 4000, ('셋',))], rules)
    assert [cue.text for cue in cues] == ['하나 둘', '셋']
    assert all(cue.end - cue.start >= 400 for cue in cues)
    # 앞 큐와 합칠 수 없으면(두 줄을 넘음) 뒤 큐와 합친다
    full = '가' * 16 + '\n' + '나' * 16
    cues = retime([Cue(0, 5000, tuple(full.split('\n'))), Cue(0, 900, ('짧은 말',)), Cue(5100, 6500, ('끝',))],
                  rules)
    assert any('짧은 말' in cue.text for cue in cues) and all(cue.end - cue.start >= 400 for cue in cues)


def test_unheard_script_lines_without_room_stay_visible():
    from core.tools.script_align import align
    from core.tools.subtitles import Word, build_cues
    words = [Word(i * 400, i * 400 + 350, ' ' + w) for i, w in enumerate(
        'one two three four seven eight nine ten'.split())]
    placed = align('one two three four.\nfive six.\nseven eight nine ten.', words)
    cues = build_cues(placed.words, rules_for('en'), boundaries=placed.boundaries)
    assert 'five six.' in ' '.join(cue.text for cue in cues)
    assert all(cue.end - cue.start >= 400 for cue in cues)


class KeepingTranslator:
    """둘째 큐(파일 7번째 줄)를 끝내 번역하지 못해 원문으로 남긴 번역 도구."""
    def translate_file(self, path, *, output_path, progress=None, cancelled=None, **options):
        cues = parse(Path(path).read_text(encoding='utf-8'))
        out = [Cue(c.start, c.end, (c.lines[0] if index == 1 else '번역된 문장입니다',))
               for index, c in enumerate(cues)]
        Path(output_path).write_text(to_srt(out), encoding='utf-8')
        return type('Result', (), {'kept_lines': (7,), 'audit': (), 'glossary': {}, 'revision': None,
                                   'revised': 0})()

    def abort(self):
        pass


def test_cues_left_in_the_source_language_are_named_by_number_and_time(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    from apps_report import report
    media = _wav(tmp_path / 'show.wav')
    result = _service(tmp_path, fake_engine, KeepingTranslator()).make(
        media, Options(model='large-v3-turbo'), translate=Translate(target='한국어', model='m:1'))
    assert len(result.untranslated) == 1
    number, start, text = result.untranslated[0]
    assert number == 2 and text == ' '.join(result.cues[1].lines) and start == result.cues[1].start
    assert (2, 'kept in source language') in result.review
    assert '2번' in report(result) and text[:20] in report(result)
