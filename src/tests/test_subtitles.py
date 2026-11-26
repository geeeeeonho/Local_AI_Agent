"""자막 만들기: 자막 문법 규칙, Whisper 결과 해석, 검증 다운로드, 서비스 전 과정, 화면.

실제 whisper.cpp 대신 같은 명령줄 계약(@응답 파일, -ojf JSON, stderr 진행률)을 지키는
작은 가짜 실행 파일을 써서, 프로세스 실행·취소·결과 해석·파일 쓰기까지 진짜 경로로 검증한다.
"""
import hashlib
import json
import os
import stat
import sys
import wave
import zipfile
from pathlib import Path

import pytest

from core.tools import speech, subtitles
from core.tools.subtitles import Cue, Word, build_cues, parse, reflow, rules_for, to_srt, to_vtt, validate


def words_of_text(text, *, step=330, length=300, spaced=True):
    out, t = [], 0
    units = text.split(' ') if spaced else list(text)
    for unit in units:
        out.append(Word(t, t + length, (' ' + unit) if spaced else unit, 0.9))
        t += step
    return out


# ── 자막 문법 ──
@pytest.mark.parametrize('code,text,spaced', [
    ('en', 'So today we are going to talk about how the new engine works, and why it matters for '
           'everyone who builds tools. It is fast. It is small.', True),
    ('ko', '오늘은 새로운 엔진이 어떻게 동작하는지 그리고 왜 도구를 만드는 모든 사람에게 중요한지 '
           '이야기하겠습니다. 빠릅니다. 작습니다.', True),
    ('ja', '今日は新しいエンジンがどのように動くのか、そしてなぜ道具を作るすべての人にとって大切なのかを話します。', False),
    ('zh', '今天我们来谈谈新的引擎是如何工作的，以及为什么它对每一个制作工具的人都很重要。它很快。', False),
])
def test_built_cues_follow_the_subtitle_rules(code, text, spaced):
    rules = rules_for(code)
    cues = build_cues(words_of_text(text, step=330 if spaced else 150, length=300 if spaced else 140,
                                    spaced=spaced), rules)
    assert cues and validate(cues, rules).ok, validate(cues, rules).errors
    # 글은 하나도 빠지거나 늘지 않는다
    joined = ''.join(''.join(cue.lines) for cue in cues).replace(' ', '')
    assert joined == text.replace(' ', '')


def test_line_lengths_are_language_specific():
    assert rules_for('ko').max_chars == 16 and rules_for('ja').max_chars == 13
    assert rules_for('en').max_chars == 42 and rules_for('zh-Hant').max_chars == 16
    assert rules_for('ja').spaced is False and rules_for('ko').spaced is True
    assert rules_for('en', max_chars=30, max_lines=1).capacity == 30


def test_one_line_when_it_fits_and_balanced_two_lines_otherwise():
    rules = rules_for('en')
    assert subtitles.wrap('A short line.', rules) == ('A short line.',)
    lines = subtitles.wrap('We went to the market, and then we walked all the way back home.', rules)
    assert len(lines) == 2 and all(len(line) <= 42 for line in lines)
    assert lines[0].endswith(',')                       # 쉼표 뒤에서 나눈다
    assert not lines[0].endswith(' the')                # 기능어를 줄 끝에 남기지 않는다


def test_japanese_lines_never_start_with_closing_punctuation():
    rules = rules_for('ja')
    for cut_text in ('東京都の新しい図書館は、来月から開館します。', 'すべての人にとって大切なのかを話します。'):
        for line in subtitles.force_wrap(cut_text, rules):
            assert line[0] not in subtitles.NO_LINE_START


def test_lines_never_break_inside_a_word_or_before_a_word_that_leans_on_it():
    ko, ja = rules_for('ko'), rules_for('ja')
    # 실측에서 나왔던 끊김: '볼 / 수 있고', '가지고 / 있지만', 'アリスタル / コス', '新 / しい'
    for text in ('이 문제는 우리가 함께 해결할 수 있는 문제라고 생각합니다',
                 '분위기를 더 많이 가지고 있지만 넓은 대로 정면이',
                 '오늘은 3 센치 정도 더 잘라서 붙여 주시면 됩니다'):
        for cue in subtitles.reflow([subtitles.Cue(0, 3000, (text,))], ko):
            for first, second in zip(cue.lines, cue.lines[1:]):
                assert subtitles.boundary_score(first, second, True) >= subtitles.BAD_BREAK, cue.lines
    for text in ('私たちは明日東京の大学で新しい研究を発表する予定です', '何千年も前に、アリスタルコスという学者が'):
        for cue in subtitles.reflow([subtitles.Cue(0, 3000, (text,))], ja):
            assert all(not (a.endswith('新') or a.endswith('アリスタル')) for a in cue.lines), cue.lines
    # 앞말에 기대는 말이 아닌 곳은 그대로 둔다(기와 지붕, 그리고 나는, 나는 수학을).
    for first, second in (('붉은 기와', '지붕과'), ('그리고', '나는'), ('나는', '수학을'), ('나와', '주말에')):
        assert subtitles.boundary_score(first, second, True) >= 0


def test_a_short_cue_keeps_two_lines_and_whole_words_instead_of_cutting():
    ko = rules_for('ko')
    cues = subtitles.reflow([subtitles.Cue(0, 1500, ('저는 지금 학교에서 친구들과 공부하고 있습니다 그리고 내일은',))], ko)
    assert all(len(cue.lines) <= 2 for cue in cues)
    assert subtitles.force_wrap('인공지능기반자연어처리시스템개발프로젝트', ko) == ('인공지능기반자연어처리시스템개발프로젝트',)
    text = ' '.join(['아주길고긴낱말이에요'] * 6)
    lines = subtitles.force_wrap(text, ko)
    assert ' '.join(lines) == text                      # 낱말 경계에서만 나눴다


def test_timing_minimum_maximum_gap_and_chaining():
    rules = rules_for('en')
    words = [Word(0, 150, ' Hi.'), Word(5000, 5200, ' Yes.'), Word(5600, 5800, ' What?')]
    cues = build_cues(words, rules)
    assert all(cue.end - cue.start >= rules.min_ms or cue is cues[-1] for cue in cues)
    for first, second in zip(cues, cues[1:]):
        assert second.start - first.end >= rules.gap_ms
    long_words = [Word(i * 400, i * 400 + 380, ' word') for i in range(60)]
    assert all(cue.end - cue.start <= rules.max_ms for cue in build_cues(long_words, rules))
    chained = subtitles.retime([Cue(0, 1000, ('a',)), Cue(1300, 2500, ('b',))], rules)
    assert chained[1].start - chained[0].end == rules.gap_ms   # 0.5초 미만 틈은 2프레임으로 잇는다


def test_reading_speed_extends_display_until_the_next_cue():
    rules = rules_for('en')
    cues = subtitles.retime([Cue(0, 400, ('This sentence has quite a few characters in it.',)),
                             Cue(9000, 9500, ('Next.',))], rules)
    assert cues[0].end >= 47 / rules.cps * 1000 - 1


def test_short_fragments_are_merged_instead_of_flashing():
    rules = rules_for('en')
    words = [Word(0, 200, ' Yes.'), Word(250, 400, ' No.'), Word(420, 600, ' Maybe'), Word(620, 900, ' later.')]
    assert [cue.lines for cue in build_cues(words, rules)] == [('Yes. No. Maybe later.',)]


def test_srt_and_webvtt_syntax_and_round_trip():
    cues = [Cue(1000, 3500, ('Hello <world> & you', 'second line')), Cue(3600, 3661001, ('a --> b',))]
    srt = to_srt(cues)
    assert srt.startswith('1\r\n00:00:01,000 --> 00:00:03,500\r\nHello <world> & you\r\nsecond line\r\n\r\n2\r\n')
    assert '01:01:01,001' in srt and '-->' not in srt.split('\r\n')[-2]
    vtt = to_vtt(cues)
    assert vtt.startswith('WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello &lt;world&gt; &amp; you\n')
    assert parse(srt)[0].lines == ('Hello <world> & you', 'second line')
    assert parse(vtt)[0].lines == ('Hello <world> & you', 'second line')
    assert [(c.start, c.end) for c in parse('﻿' + srt)] == [(1000, 3500), (3600, 3661001)]


def test_vtt_reader_skips_header_notes_and_identifiers():
    text = 'WEBVTT Kind: captions\n\nNOTE made by hand\n\nintro\n00:01.000 --> 00:02.000 align:start\nHi\n'
    assert parse(text) == [Cue(1000, 2000, ('Hi',))]


def test_reflow_rewraps_translated_text_for_the_target_language():
    long_korean = Cue(0, 4000, ('오늘은 새로운 엔진이 어떻게 동작하는지 설명하겠습니다',))
    cues = reflow([long_korean], rules_for('ko'))
    assert len(cues[0].lines) == 2 and all(len(line) <= 16 for line in cues[0].lines)
    assert validate(cues, rules_for('ko')).ok


# ── Whisper 결과 ──
def _token(text, start, end, p=0.9, dtw=-1):
    return {'text': text, 'offsets': {'from': start, 'to': end}, 'p': p, 't_dtw': dtw}


def test_parse_result_groups_tokens_into_words_and_skips_special_tokens():
    data = {'result': {'language': 'en'}, 'transcription': [{
        'offsets': {'from': 0, 'to': 3000}, 'text': ' Hello there, friend.',
        'tokens': [_token('[_BEG_]', 0, 0), _token(' Hel', 0, 200, dtw=5), _token('lo', 200, 500),
                   _token(' there', 500, 900), _token(',', 900, 950), _token(' friend', 1200, 1600),
                   _token('.', 1600, 1700), _token('[_TT_150]', 3000, 3000)]}]}
    language, segments = speech.parse_result(data)
    assert language == 'en'
    assert [w.text for w in segments[0].words] == [' Hello', ' there,', ' friend.']
    assert segments[0].words[0].start == 50                    # DTW 시각(센티초)을 우선
    assert all(a.end <= b.start for a, b in zip(segments[0].words, segments[0].words[1:]))


def test_parse_result_treats_cjk_tokens_as_units():
    data = {'result': {'language': 'ja'}, 'transcription': [{
        'offsets': {'from': 0, 'to': 2000}, 'text': '今日は晴れ。',
        'tokens': [_token('今日は', 0, 600), _token('晴れ', 600, 1200), _token('。', 1200, 1300)]}]}
    _, segments = speech.parse_result(data, spaced=False)
    assert [w.text for w in segments[0].words] == ['今日は', '晴れ。']


def _segment(text, start, end, prob=0.9):
    words = tuple(Word(start + i * 10, start + i * 10 + 5, ' ' + part, prob) for i, part in enumerate(text.split()))
    return speech.Segment(start, end, text, words, prob)


def test_cleanup_removes_only_what_is_backed_by_evidence():
    loop = 'yes ' * 12
    segments = [_segment('Hello there.', 0, 1000), _segment('[Music]', 1000, 5000),
                _segment('Again.', 5000, 6000, 0.3), _segment('Again.', 6000, 7000, 0.3),
                _segment('Again.', 7000, 8000, 0.3),
                _segment('Thank you for watching.', 9000, 11000, prob=0.3),
                _segment(loop.strip(), 12000, 16000)]
    result = speech.clean(segments)
    texts = [segment.text for segment in result.segments]
    assert texts[:3] == ['Hello there.', 'Again.', 'Again.']
    assert texts[-1].count('yes') == 2                         # 12번 되풀이: 그것만으로 루프
    reasons = {reason for _, _, reason in result.removed}
    assert reasons == {'sound description', 'repeated', 'typical hallucination'}
    assert any(reason == 'repetition loop shortened' for _, _, reason in result.flagged)


def test_real_repetition_and_disfluency_are_kept_without_other_evidence():
    """'Go! Go! Go!', '네 네 네 네 네', 말 더듬기는 실제 발화일 수 있다(원문 보존)."""
    segments = [_segment('Go!', 0, 800), _segment('Go!', 900, 1700), _segment('Go!', 1800, 2600),
                _segment('네 네 네 네 네 네', 3000, 6000), _segment('I- I- I- I- I- I think so.', 7000, 11000)]
    result = speech.clean(segments)
    assert [s.text for s in result.segments] == [s.text for s in segments]
    assert not result.removed
    assert {reason for _, _, reason in result.flagged} == {'repetition kept'}


def test_impossible_speech_rate_backs_removal_of_a_repeat():
    fast = [_segment('Again and again and again.', i * 300, i * 300 + 250) for i in range(3)]
    result = speech.clean(fast)
    assert len(result.segments) == 2 and result.removed[0][2] == 'repeated'


def test_cleanup_keeps_sounds_on_request_and_only_flags_confident_fillers():
    result = speech.clean([_segment('[Music]', 0, 2000), _segment('Thanks for watching!', 3000, 4000)],
                          keep_sounds=True)
    assert [s.text for s in result.segments] == ['[Music]', 'Thanks for watching!']
    assert result.flagged and not result.removed


# ── 재인식 판단 ──
def test_evidence_signals_and_compression_ratio():
    from core.tools import asr_review
    assert asr_review.compression_ratio('short') == 1.0
    assert asr_review.compression_ratio('na ' * 60) > speech.COMPRESSION_LIMIT
    assert asr_review.compression_ratio('The quick brown fox jumps over the lazy dog near the river bank.') < 2.0
    signals = asr_review.evidence(_segment('a b c d e f g h i j k l m n o p q r s t u v w x y z', 0, 300, 0.2)).signals
    assert 'low confidence' in signals and 'implausible speech rate' in signals


def test_candidate_replaces_only_when_clearly_better():
    from core.tools import asr_review
    span = asr_review.Range(0, 3000, 'low confidence')
    weak = [_segment('the whether is nice', 0, 2000, 0.40)]
    keep = asr_review.choose(span, weak, [_segment('the weather is nice', 0, 2000, 0.46)])
    assert not keep.accepted and 'kept original' in keep.why
    better = asr_review.choose(span, weak, [_segment('the weather is nice', 0, 2000, 0.80)])
    assert better.accepted
    looped = [_segment('na ' * 30, 0, 2000, 0.7)]
    fixed = asr_review.choose(span, looped, [_segment('nothing at all here', 0, 2000, 0.6)])
    assert fixed.accepted and fixed.why.startswith('original had')
    bad = asr_review.choose(span, weak, [_segment('la ' * 30, 0, 2000, 0.9)])
    assert not bad.accepted and 'candidate also suspicious' in bad.why
    recovered = asr_review.choose(asr_review.Range(5000, 7000, 'possible missing speech'), [],
                                  [_segment('wait for me', 5100, 6000, 0.7)])
    assert recovered.accepted and recovered.why == 'recovered missing speech'


def test_missing_speech_comes_from_vad_speech_that_nothing_was_recognized_in():
    """실측: 에너지 기준은 작은 목소리를 놓치고 음악만 잡았다. VAD가 말소리라고 한 구간만 본다."""
    from core.tools import asr_review
    vad_map = [(1000, 6000, 0, 5000), (8000, 12000, 5100, 9100), (13000, 13500, 9200, 9700)]
    words = tuple(Word(1000 + i * 1600, 2500 + i * 1600, ' ' + text) for i, text in enumerate(('first', 'second', 'third')))
    heard = [speech.Segment(1000, 6000, 'first second third', words, 0.9)]
    assert asr_review.unrecognized_speech(heard, vad_map) == [(8000, 12000)]   # 0.5초 구간은 너무 짧음
    assert asr_review.unrecognized_speech(heard, ()) == []                      # VAD 정보 없으면 추측하지 않음


def test_ranges_are_merged_padded_and_limited():
    from core.tools import asr_review
    ranges = [asr_review.Range(1000, 1200, 'a'), asr_review.Range(1800, 2400, 'b'), asr_review.Range(9000, 9100, 'c')]
    merged = asr_review.merge_ranges(ranges, total=9500)
    assert merged[0].start < 1000 and merged[0].reason == 'a' and merged[0].end >= 2700
    assert merged[-1].end <= 9500 and merged[-1].end - merged[-1].start >= 1000
    assert len(asr_review.merge_ranges([asr_review.Range(i * 5000, i * 5000 + 100, 'x') for i in range(40)])) == 24


def test_replace_range_and_shift_keep_time_order():
    from core.tools import asr_review
    original = [_segment('one', 0, 900), _segment('bad guess', 1000, 2000), _segment('three', 2100, 3000)]
    candidate = asr_review.shift([_segment('good words', 100, 600)], 1000)
    out = asr_review.replace_range(original, asr_review.Range(1000, 2000, 'x'), candidate)
    assert [s.text for s in out] == ['one', 'good words', 'three']
    assert out[1].start >= 1000 and out[1].end <= 2000


def test_similar_names_are_reported_not_merged():
    from core.tools import asr_review
    segments = [_segment('Then Katherine left.', 0, 1000), _segment('I saw Catherine there.', 1000, 2000),
                _segment('Katherine is back.', 2000, 3000), _segment('ハインリッヒとハインリヒ', 3000, 4000)]
    pairs = asr_review.similar_names(segments)
    names = {frozenset((a, b)) for a, _, b, _ in pairs}
    assert frozenset(('Katherine', 'Catherine')) in names
    assert frozenset(('ハインリッヒとハインリヒ'[:6], 'ハインリヒ')) in names or any('ハインリ' in a for a, _, _, _ in pairs)


# ── 평가 도구 ──
def test_evaluation_measures_errors_coverage_and_overcorrection(capsys, tmp_path):
    from core.tools import subtitle_eval
    reference = [Cue(0, 2000, ('the weather is nice today',)), Cue(3000, 5000, ('see you tomorrow',))]
    hypothesis = [Cue(100, 2100, ('the whether is nice today',)), Cue(6000, 7000, ('thanks for watching',))]
    report = subtitle_eval.evaluate(reference, hypothesis)
    assert round(report.wer, 2) == round(4 / 8, 2)        # 단어 1개 틀림 + 누락 2 + 추가 3 → 편집 거리
    # 기준 경계 ±0.5초(collar)를 뺀 시간으로 비교: 덮인 1초 / 기준 2초, 생성 2초
    assert report.omission == 0.5 and report.hallucination == 0.5
    assert report.timestamp_mae == 100
    change = subtitle_eval.compare(reference, hypothesis, [Cue(0, 2000, ('the weather is nice today',)),
                                                           Cue(3000, 5000, ('see you',))])
    assert change.improved == 2 and change.worsened == 0 and change.overcorrection == 0.0
    from tools import evaluate_subtitles
    ref, hyp = tmp_path / 'r.srt', tmp_path / 'h.srt'
    ref.write_text(to_srt(reference), encoding='utf-8'); hyp.write_text(to_srt(hypothesis), encoding='utf-8')
    assert evaluate_subtitles.main([str(ref), str(hyp), '--baseline', str(hyp), '--language', 'en']) == 0
    out = capsys.readouterr().out
    assert 'WER' in out and '과잉 교정' in out and '자막 규칙 위반' in out


def test_model_catalog_is_pinned_and_ordered_by_accuracy():
    assert speech.MODELS[0].key == 'large-v3' and speech.RECOMMENDED in speech.BY_KEY
    for item in speech.MODELS:
            assert len(item.sha1) == 40 and item.file.startswith('ggml-') and item.dtw
    assert speech.whisper_code('zh-Hant') == 'zh' and speech.whisper_code('auto') == 'auto'


# ── 검증 다운로드 · 설치 ──
def test_fetch_verifies_checksum_and_never_keeps_a_bad_file(tmp_path):
    from integrations.speech import download
    source = tmp_path / 'source.bin'
    source.write_bytes(b'weights' * 1000)
    good = hashlib.sha1(source.read_bytes()).hexdigest()
    target = tmp_path / 'out' / 'model.bin'
    download.fetch(source.as_uri(), target, algorithm='sha1', expected=good, limit=10 ** 6)
    assert target.read_bytes() == source.read_bytes()
    other = tmp_path / 'out' / 'other.bin'
    with pytest.raises(ValueError, match='Checksum mismatch'):
        download.fetch(source.as_uri(), other, algorithm='sha1', expected='0' * 40, limit=10 ** 6)
    assert not other.exists() and not other.with_name('other.bin.part').exists()
    with pytest.raises(ValueError, match='larger'):
        download.fetch(source.as_uri(), tmp_path / 'out' / 'big.bin', algorithm='sha1', expected=good, limit=10)
    with pytest.raises(ValueError, match='pinned checksum'):
        download.fetch(source.as_uri(), tmp_path / 'x', algorithm='sha1', expected='', limit=10)


def test_fetch_stops_when_cancelled_and_keeps_the_partial_file(tmp_path):
    from integrations.speech import download
    source = tmp_path / 'source.bin'
    source.write_bytes(os.urandom(3 * download.CHUNK))
    target = tmp_path / 'model.bin'
    calls = {'n': 0}

    def cancelled():
        calls['n'] += 1
        return calls['n'] > 1
    with pytest.raises(download.DownloadCancelled):
        download.fetch(source.as_uri(), target, algorithm='sha256',
                       expected=hashlib.sha256(source.read_bytes()).hexdigest(), limit=10 ** 8, cancelled=cancelled)
    assert not target.exists() and target.with_name('model.bin.part').stat().st_size == download.CHUNK


def test_archives_with_unsafe_paths_are_refused(tmp_path):
    from integrations.speech import install
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as handle:
        handle.writestr('../escape.exe', b'x')
    with pytest.raises(ValueError, match='Unsafe'):
        install._safe_extract(archive.read_bytes(), tmp_path / 'out')
    assert not (tmp_path / 'escape.exe').exists()


def test_ffmpeg_asset_prefers_the_newest_lgpl_release_build():
    from integrations.speech import install
    assets = {name: {'name': name} for name in (
        'ffmpeg-n7.1.2-10-gabc-win64-lgpl-7.1.zip', 'ffmpeg-n8.0.1-3-gdef-win64-lgpl-8.0.zip',
        'ffmpeg-n8.0.1-3-gdef-win64-gpl-8.0.zip', 'ffmpeg-N-121000-g0123abc-win64-lgpl.zip',
        'ffmpeg-n8.0.1-3-gdef-linux64-lgpl-8.0.tar.xz', 'checksums.sha256')}
    assert install._ffmpeg_asset(assets)['name'] == 'ffmpeg-n8.0.1-3-gdef-win64-lgpl-8.0.zip'
    with pytest.raises(ValueError, match='GitHub did not record'):
        install._asset_digest({'name': 'x', 'digest': None})


@pytest.mark.skipif(os.name == 'nt', reason='checks the non-Windows refusal')
def test_engine_install_is_skipped_outside_windows(tmp_path):
    from integrations.speech import install
    messages = []
    assert install.install(tmp_path, log=messages.append) is False
    assert 'Windows' in messages[0] and not any(tmp_path.iterdir())


# ── 서비스 전 과정 (가짜 whisper-cli) ──
FAKE_CLI = r'''#!{python}
import json, sys
args = open(sys.argv[1][1:], encoding='utf-8').read().split('\n')
def value(flag):
    return args[args.index(flag) + 1]
log = open(value('-of') + '.calls', 'a', encoding='utf-8'); log.write(json.dumps(args) + '\n'); log.close()
lang = value('-l')
if lang == 'auto':
    lang = 'en'
sentences = {{'en': [' Hello and welcome to the show.', ' Today we talk about subtitles, and why rules matter.'],
             'ko': [' 안녕하세요 방송에 오신 것을 환영합니다.', ' 오늘은 자막 규칙이 왜 중요한지 이야기합니다.']}}[lang]
import os
retry = 'retry' in value('-f')
if os.environ.get('FAKE_SCENARIO') == 'loop' and not retry:
    sentences = [' ' + 'na ' * 20] + sentences[1:]
if os.environ.get('FAKE_SCENARIO') == 'skip':
    # 첫 인식은 앞 발화(0.5~3초)만, 두 번째 VAD 구간(4~6초, 다른 언어)은 건너뜀. 재인식(언어 자동)은 영어로.
    sentences = ([' English words were spoken here.'] if retry and value('-l') == 'auto'
                 else [' 안녕하세요 반갑습니다 오늘은.'])
segments, t = [], 0
for sentence in sentences:
    tokens = []
    for word in sentence.split(' ')[1:]:
        if not word:
            continue
        tokens.append({{'text': ' ' + word, 'offsets': {{'from': t, 'to': t + 300}},
                       'p': 0.3 if word == 'na' else 0.93, 't_dtw': -1}})
        t += 330
    segments.append({{'offsets': {{'from': tokens[0]['offsets']['from'], 'to': t}}, 'text': sentence, 'tokens': tokens}})
    print('[00:00:00.000 --> 00:00:01.000]  ' + sentence.strip(), flush=True)
if os.environ.get('FAKE_VAD_LOG') and '--vad' in args:
    print('whisper_vad: vad_segment_info: orig_start: 0.50, orig_end: 3.00, vad_start: 0.00, vad_end: 2.50', file=sys.stderr)
    print('whisper_vad: vad_segment_info: orig_start: 4.00, orig_end: 6.00, vad_start: 2.60, vad_end: 4.60', file=sys.stderr)
for p in (0, 50, 100):
    print('whisper_print_progress_callback: progress = %3d%%' % p, file=sys.stderr, flush=True)
json.dump({{'result': {{'language': lang}}, 'transcription': segments}}, open(value('-of') + '.json', 'w', encoding='utf-8'))
'''


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    if os.name == 'nt':
        pytest.skip('the fake whisper-cli is a POSIX script')
    cli = tmp_path / 'bin' / 'whisper-cli'
    cli.parent.mkdir()
    cli.write_text(FAKE_CLI.format(python=sys.executable), encoding='utf-8')
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('LOCAL_AI_WHISPER_CLI', str(cli))
    monkeypatch.setenv('LOCAL_AI_FFMPEG', str(tmp_path / 'bin' / 'missing-ffmpeg'))
    from integrations.speech.engine import SpeechEngine
    engine = SpeechEngine(tmp_path / 'speech', tmp_path / 'models' / 'speech')
    model = engine.model_path('large-v3-turbo')
    model.parent.mkdir(parents=True)
    model.write_bytes(b'weights')
    return engine


def _wav(path, seconds=1):
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(b'\x00\x00' * 16000 * seconds)
    return path


class FakeTranslator:
    """번역 도구 계약만 지키는 가짜: 줄마다 '[번역]'을 붙여 새 파일로 쓴다."""
    def __init__(self):
        self.calls = []

    def translate_file(self, path, *, model, target, kind, style, output_path, progress=None, cancelled=None,
                       **options):
        self.calls.append(dict(path=Path(path), model=model, target=target, kind=kind, style=style, **options))
        cues = parse(Path(path).read_text(encoding='utf-8'))
        assert all(len(cue.lines) == 1 for cue in cues)       # 큐마다 한 줄로 합쳐 넘긴다
        translated = [Cue(c.start, c.end, ('번역된 문장입니다 ' + c.lines[0][:12] + ' 그리고 조금 더 긴 내용',))
                      for c in cues]
        Path(output_path).write_text(to_srt(translated), encoding='utf-8')
        if progress:
            progress(len(cues), len(cues))
        return type('Result', (), {'kept_lines': [], 'audit': [], 'glossary': {'Hello': '안녕'}, 'revision': None,
                                   'revised': 0})()

    def abort(self):
        pass


def _service(tmp_path, engine, translator=None, allowed=True):
    from services.tools.subtitles import SubtitleService
    return SubtitleService(translator or FakeTranslator(), work_dir=tmp_path / 'user_data' / 'tools' / 'subtitles',
                           store_dir=tmp_path / 'models', engine=engine,
                           access=lambda refresh: {'allowed': allowed, 'admin': allowed, 'reason': 'admins only'})


def test_wav_becomes_a_rule_following_srt_next_to_the_original(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / '강의 녹음.wav')
    stages, lines = [], []
    result = _service(tmp_path, fake_engine).make(
        media, Options(model='large-v3-turbo', formats=('srt', 'vtt'), prompt='자막 용어 LocalAI'),
        progress=lambda stage, fraction, note: stages.append(stage), on_text=lines.append)
    srt, vtt = result.outputs
    assert srt == tmp_path / '강의 녹음.srt' and vtt == tmp_path / '강의 녹음.vtt'   # 원본과 같은 이름
    raw = srt.read_bytes()
    assert raw.startswith(b'\xef\xbb\xbf1\r\n00:00:00,000 --> ')
    cues = parse(raw.decode('utf-8-sig'))
    assert validate(cues, rules_for('en')).ok and len(cues) >= 2
    assert vtt.read_text(encoding='utf-8-sig').startswith('WEBVTT\n')
    assert {'speech', 'write'} <= set(stages) and lines and result.language_label == 'English'
    assert media.read_bytes()[:4] == b'RIFF'                  # 원본은 그대로
    calls = (tmp_path / 'user_data').rglob('result-cpu.calls')
    args = json.loads(next(calls).read_text(encoding='utf-8').splitlines()[0])
    assert args[args.index('--prompt') + 1] == '자막 용어 LocalAI'   # 한글도 응답 파일(UTF-8)로
    assert '-ng' in args and '-dtw' in args and '-nfa' in args  # CPU, 최고 정확도 = 정밀 단어 시각


def test_only_the_suspicious_range_is_recognized_again_and_the_better_candidate_wins(
        tmp_path, fake_engine, monkeypatch):
    from services.tools.subtitles import Options
    monkeypatch.setenv('FAKE_SCENARIO', 'loop')
    media = _wav(tmp_path / 'loop.wav', seconds=10)
    result = _service(tmp_path, fake_engine).make(media, Options(model='large-v3-turbo', quality='balanced'))
    text = result.outputs[0].read_text(encoding='utf-8-sig')
    assert 'na na na na' not in text and 'Hello and welcome' in text
    assert len(result.decisions) == 1 and result.decisions[0].accepted
    assert result.decisions[0].range.reason in ('high compression ratio', 'low confidence', 'repetition loop')
    assert 'subtitles' in text                                 # 문제없는 구간은 그대로
    log = next((tmp_path / 'user_data').rglob('review-balanced.json'))
    saved = json.loads(log.read_text(encoding='utf-8'))
    assert saved['decisions'][0]['original'].startswith('na na')   # 최초 결과와 판단 근거를 보관
    calls = next((tmp_path / 'user_data').rglob('result-cpu.calls')).read_text(encoding='utf-8')
    assert len(calls.splitlines()) == 1                        # 원래 작업 폴더의 호출은 최초 인식 1번뿐
    assert not list((tmp_path / 'user_data').rglob('audio.wav')) and not list((tmp_path / 'user_data').rglob('input.wav'))


def test_fast_mode_skips_re_recognition(tmp_path, fake_engine, monkeypatch):
    from services.tools.subtitles import Options
    monkeypatch.setenv('FAKE_SCENARIO', 'loop')
    result = _service(tmp_path, fake_engine).make(_wav(tmp_path / 'f.wav', seconds=10),
                                                  Options(model='large-v3-turbo', quality='fast'))
    assert result.decisions == () and 'na na' in result.text    # 줄이기만(두 번), 바꾸지 않음


def test_existing_subtitles_are_never_overwritten_and_recognition_is_reused(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'talk.wav')
    service = _service(tmp_path, fake_engine)
    first = service.make(media, Options(model='large-v3-turbo'))
    second = service.make(media, Options(model='large-v3-turbo'))
    assert first.outputs[0].name == 'talk.srt' and second.outputs[0].name == 'talk (2).srt'
    assert second.reused and not first.reused
    calls = next((tmp_path / 'user_data').rglob('result-cpu.calls')).read_text(encoding='utf-8')
    assert len(calls.splitlines()) == 1                        # 두 번째는 다시 인식하지 않았다


def test_translation_is_chained_and_rewrapped_for_the_target_language(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    media = _wav(tmp_path / 'show.wav')
    translator = FakeTranslator()
    result = _service(tmp_path, fake_engine, translator).make(
        media, Options(model='large-v3-turbo', language='English'),
        translate=Translate(target='한국어', model='gemma4:12b', glossary='LocalAI = 로컬AI'))
    call = translator.calls[0]
    assert call['kind'] == 'subtitle' and call['style'] == 'natural' and call['source_language'] == 'English'
    assert call['glossary'] == 'LocalAI = 로컬AI'
    # 기본: 번역 자막이 원본 이름(재생기가 바로 불러옴), 원어 자막은 원어 코드
    assert [path.name for path in result.outputs + result.translated_outputs] == ['show.en.srt', 'show.srt']
    korean = parse(result.translated_outputs[0].read_text(encoding='utf-8-sig'))
    assert validate(korean, rules_for('ko')).ok
    assert any(len(cue.lines) == 2 for cue in korean)          # 번역문을 한국어 줄 길이로 다시 나눴다
    assert len(korean) > len(result.cues)                     # 두 큐 분량의 번역문은 시간 안에서 둘로
    assert not list((tmp_path / 'user_data').rglob('translate-*.srt'))


def test_same_language_translation_is_skipped(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    translator = FakeTranslator()
    result = _service(tmp_path, fake_engine, translator).make(
        _wav(tmp_path / 'ko.wav'), Options(model='large-v3-turbo', language='한국어'),
        translate=Translate(target='한국어', model='m'))
    assert result.translation_skipped and not translator.calls and result.outputs[0].name == 'ko.srt'


def test_video_needs_ffmpeg_and_bad_inputs_are_explained(tmp_path, fake_engine):
    from integrations.speech.engine import EngineMissing
    from services.tools.subtitles import Options
    service = _service(tmp_path, fake_engine)
    video = tmp_path / 'clip.mp4'
    video.write_bytes(b'not really a video')
    with pytest.raises(EngineMissing, match='ffmpeg'):
        service.make(video, Options(model='large-v3-turbo'))
    with pytest.raises(ValueError, match='Unsupported media'):
        service.make(_touch(tmp_path / 'notes.txt'), Options(model='large-v3-turbo'))
    with pytest.raises(EngineMissing, match='not installed'):
        service.make(_wav(tmp_path / 'a.wav'), Options(model='large-v3'))


def _touch(path):
    path.write_text('x', encoding='utf-8')
    return path


def test_batch_continues_after_a_failed_file(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    bad = tmp_path / 'broken.mp4'
    bad.write_bytes(b'x')
    batch = _service(tmp_path, fake_engine).make_many([bad, _wav(tmp_path / 'good.wav')], Options(model='large-v3-turbo'))
    assert [path.name for path, _ in batch.results] == ['good.wav'] and batch.failed[0][0] == bad


def test_cancelling_stops_without_writing_a_subtitle(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'stop.wav')
    with pytest.raises(InterruptedError):
        _service(tmp_path, fake_engine).make(media, Options(model='large-v3-turbo'), cancelled=lambda: True)
    assert not list(tmp_path.glob('stop.*.srt'))


def test_engine_and_model_changes_are_for_administrators_only(tmp_path, fake_engine):
    service = _service(tmp_path, fake_engine, allowed=False)
    for action in (lambda: service.install_model('small'), lambda: service.remove_model('large-v3-turbo'),
                   lambda: service.install_engine()):
        with pytest.raises(PermissionError, match='admins only'):
            action()
    assert fake_engine.model_path('large-v3-turbo').is_file()


def test_recommended_model_is_the_last_one_or_the_most_accurate(tmp_path, fake_engine):
    service = _service(tmp_path, fake_engine)
    assert service.recommend_model(('small', 'large-v3-turbo')) == 'large-v3-turbo'
    assert service.recommend_model(('small', 'large-v3-turbo'), 'small') == 'small'
    assert service.recommend_model(()) == ''


def test_folder_scan_finds_media_in_reading_order(tmp_path):
    from services.tools.subtitles import scan
    for name in ('ep10.mp4', 'ep2.mkv', 'notes.txt', '.hidden.mp4', 'sub/ep1.wav'):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'x')
    assert [p.relative_to(tmp_path).as_posix() for p in scan(tmp_path)] == ['ep2.mkv', 'ep10.mp4', 'sub/ep1.wav']


def test_subtitle_preferences_are_validated(tmp_path):
    from core.settings.store import SettingsStore
    store = SettingsStore(tmp_path / 'settings.json')
    store.set_subtitle_preferences({'model': 'large-v3', 'max_chars': 20, 'max_lines': True, 'vad': False,
                                    'unknown': 1, 'prompt': 'x' * 3000})
    assert store.subtitle_preferences() == {'model': 'large-v3', 'max_chars': 20, 'vad': False}
    store.set_translation_preferences({'target': 'English', 'glossary': 'a = b'})
    assert store.translation_preferences() == {'target': 'English', 'glossary': 'a = b'}
    assert store.subtitle_preferences()['model'] == 'large-v3'


def test_paths_are_shared_admin_locations():
    import project_paths
    assert project_paths.speech_engine_dir(Path('E')) == Path('E') / 'speech'
    assert project_paths.speech_model_dir(Path('M')) == Path('M') / 'speech'


# ── 화면 ──
def test_subtitle_tool_opens_and_starts_only_when_ready(ui, tmp_path, fake_engine):
    from test_desktop_ui import pump
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    svc.translator.local_models = lambda: ['gemma4:12b']
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: w.subtitle_model.get() != '', timeout=5)
    assert w.subtitle_model.get() == 'large-v3-turbo · 권장'
    assert str(w.subtitle_start_button['state']) == 'disabled'
    media = _wav(tmp_path / 'ui.wav')
    w.subtitle_path.set(str(media)); w.analyze_subtitle_input()
    pump(w, lambda: str(w.subtitle_start_button['state']) == 'normal')
    assert '"ui.srt"' in w.subtitle_destination.cget('text')
    w.subtitle_translate.set(True)
    pump(w, lambda: w.subtitle_llm.get() == 'gemma4:12b', timeout=5)
    svc.subtitles.translator = FakeTranslator()
    w.start_subtitles()
    pump(w, lambda: not w.runner.busy('tools.subtitles') and (tmp_path / 'ui.en.srt').exists(), timeout=15)
    pump(w, lambda: str(w.subtitle_open_button['state']) == 'normal', timeout=5)
    assert (tmp_path / 'ui.srt').exists()          # 번역 자막이 원본 이름, 원어 자막은 ui.en.srt
    assert '번역된 문장' in w.subtitle_translated_text.get('1.0', 'end')
    assert '확인하면 좋은 자막' in w.subtitle_report_text.get('1.0', 'end')


def test_translation_tool_turns_a_media_file_into_translated_subtitles(ui, tmp_path, fake_engine):
    from test_desktop_ui import pump
    w, svc, _ = ui
    svc.subtitles.engine = fake_engine
    svc.subtitles.translator = FakeTranslator()
    svc.translator.local_models = lambda: ['gemma4:12b']
    svc.settings.set_subtitle_preferences({'model': 'large-v3-turbo', 'quality': 'fast'})
    w.navigate('tools'); w.open_tool('translate')
    pump(w, lambda: w.translation_model.get() == 'gemma4:12b', timeout=5)
    media = _wav(tmp_path / 'movie.wav')
    w.translation_path.set(str(media)); w.analyze_translation_file()
    pump(w, lambda: w.translation_kind.get() == '자막' and '준비됨' in w.translation_status.get(), timeout=5)
    assert w.translation_style.get() == '자연스러운 번역'             # 번역 목적은 사용자 값 그대로
    assert '"movie.srt"(번역 자막' in w.translation_destination.cget('text') and w.translation_main_name.get()
    w.start_translation()
    pump(w, lambda: (tmp_path / 'movie.en.srt').exists() and not w.runner.busy('tools.translate'), timeout=15)
    pump(w, lambda: '완료' in w.translation_status.get(), timeout=5)
    assert (tmp_path / 'movie.srt').exists()
    # 자막용 자동 설정은 일반 번역의 기본값으로 저장하지 않는다(다른 값을 바꿔 저장해도)
    w.translation_language.set('English')
    pump(w, lambda: svc.settings.translation_preferences().get('target') == 'English', timeout=4)
    assert svc.settings.translation_preferences().get('kind') == '자동 감지'
    # 영상이 아닌 파일을 고르면 원래 유형으로 돌아간다
    text_file = tmp_path / 'plain.txt'
    text_file.write_text('こんにちは。', encoding='utf-8')
    w.translation_path.set(str(text_file)); w.analyze_translation_file()
    assert w.translation_kind.get() == '자동 감지'
    assert not w.translation_main_name.get()                  # 일반 문서는 원본을 그대로 둔다


from test_desktop_ui import ui  # noqa: E402,F401  (실제 Tk 창 fixture를 함께 쓴다)


# ── 번역 용어 수정 ──
class GlossaryModel:
    """'Sato'를 문서 메모리의 용어(없으면 '사토')로 옮기는 가짜 모델. 번역한 항목 수를 센다."""
    def __init__(self):
        self.items = 0

    def chat(self, name, messages, **kwargs):
        data = json.loads(messages[-1]['content'])
        if 'items' not in data:
            return '{}'
        terms = json.loads(data['document_memory']).get('terminology', {})
        self.items += len(data['items'])
        out = []
        for row in data['items']:
            text = row['text'].replace('Sato', terms.get('Sato', '사토'))
            for source, target in terms.items():
                text = text.replace(source, target)
            text = text.replace('smiled.', '웃었다.').replace('left.', '떠났다.').replace('The sky is blue.', '하늘이 파랗다.')
            out.append({'id': row['id'], 'text': text})
        return json.dumps({'translations': out, 'new_terms': {}}, ensure_ascii=False)


def _translator(tmp_path, model):
    from services.tools.translation import TranslationService

    class Inference:
        def ensure_ready(self):
            return 'http://127.0.0.1:11434'

        def local_models(self):
            return ['m:1']
    return TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None,
                              check_language=False)


def test_changed_terms_retranslate_only_the_lines_that_use_them(tmp_path):
    source = tmp_path / 'story.txt'
    source.write_text('Sato smiled.\nThe sky is blue.\nSato left.\n', encoding='utf-8')
    model = GlossaryModel()
    service = _translator(tmp_path, model)
    first = service.translate_file(source, model='m:1', target='한국어', kind='general')
    assert first.text.count('사토') == 2 and first.revision is not None
    before = model.items
    assert service.affected_by(first, {'Sato': '사이토'}) == [0, 2]
    revised = service.revise_terms(first, {'Sato': '사이토'})
    assert model.items - before == 2                           # 바뀐 용어가 든 두 줄만
    assert revised.revised == 2 and revised.glossary['Sato'] == '사이토'
    assert first.output.read_text(encoding='utf-8') == '사이토 웃었다.\n하늘이 파랗다.\n사이토 떠났다.\n'
    again = service.revise_terms(revised, {'Sato': '사토 씨'})   # 고친 결과를 다시 고칠 수 있다
    assert '사토 씨 떠났다.' in again.text and first.output.read_text(encoding='utf-8') == again.text
    import pytest as _pytest
    with _pytest.raises(ValueError, match='No glossary changes'):
        service.revise_terms(again, {'Sato': ' '})


# ── VAD 시각 보정 (실측에서 찾은 문제) ──
REAL_VAD_MAP = [[1670, 7200, 0, 5530], [7620, 12700, 5730, 10810], [23430, 34080, 11010, 21660]]


def test_token_times_are_mapped_back_from_the_vad_timeline():
    """whisper-cli -ojf는 VAD를 켜면 구간 시각만 원래 오디오 기준이고 토큰 시각은 무음을 잘라 낸 시간이다.
    (실측: 23.4초에 시작한 말이 12.3초에 표시되고 일부 큐가 1ms가 됐다.)"""
    data = {'result': {'language': 'ko'}, speech.VAD_MAP_KEY: REAL_VAD_MAP, 'transcription': [
        {'offsets': {'from': 7650, 'to': 12310}, 'text': ' 같은 결과를 얻었습니다.',
         'tokens': [_token(' 같은', 9500, 9800), _token(' 결과를', 9800, 10200), _token(' 얻었습니다.', 10200, 10800)]},
        {'offsets': {'from': 12310, 'to': 34080}, 'text': ' 몰 박사는 일부 환자가',
         'tokens': [_token(' 몰', 10700, 10790), _token(' 박사는', 10790, 11220), _token(' 일부', 11220, 11750),
                    _token(' 환자가', 11750, 12400)]}]}
    _, segments = speech.parse_result(data)
    first, second = segments
    assert 11000 < first.words[0].start < 12000 and first.end <= 12700
    assert [w.text for w in second.words] == [' 몰', ' 박사는', ' 일부', ' 환자가']
    assert second.words[1].start == 23430                      # 무음을 가로지르지 않고 다음 발화에서 시작
    assert 22000 < second.words[0].start < 23430               # 문장 첫 단어도 다음 발화 바로 앞으로
    assert second.start == second.words[0].start and second.end < 25000
    assert all(w.end > w.start for s in segments for w in s.words)


def test_vad_gap_times_follow_the_side_of_the_word():
    segments = [tuple(item) for item in REAL_VAD_MAP]
    assert speech.map_vad_time(3000, segments) == 1670 + 3000 * (7200 - 1670) // 5530
    assert speech.map_vad_time(10900, segments, side=1) == 23430    # 단어 시작 → 다음 발화
    assert speech.map_vad_time(10900, segments, side=-1) == 12700   # 단어 끝 → 앞 발화
    assert speech.map_vad_time(99999, segments) == 34080 and speech.map_vad_time(-5, segments) == 1670


def test_engine_keeps_the_vad_map_from_whisper_logs(tmp_path, fake_engine, monkeypatch):
    from services.tools.subtitles import Options
    monkeypatch.setenv('FAKE_VAD_LOG', '1')
    media = _wav(tmp_path / 'v.wav', seconds=6)
    fake_engine.vad_model().parent.mkdir(parents=True, exist_ok=True)
    fake_engine.vad_model().write_bytes(b'vad')
    _service(tmp_path, fake_engine).make(media, Options(model='large-v3-turbo', quality='fast'))
    saved = json.loads(next((tmp_path / 'user_data').rglob('transcript.json')).read_text(encoding='utf-8'))
    assert saved['data'][speech.VAD_MAP_KEY] == [[500, 3000, 0, 2500], [4000, 6000, 2600, 4600]]


def test_folder_translation_turns_media_into_subtitles_and_shares_the_folder_memory(tmp_path, fake_engine):
    from services.tools.subtitles import Options, SubtitleService
    folder = tmp_path / 'series'
    (folder / 'season').mkdir(parents=True)
    _wav(folder / 'ep2.wav'); _wav(folder / 'season' / 'ep10.wav')
    (folder / 'note.txt').write_text('Sato smiled.\n', encoding='utf-8')
    (folder / 'cover.png').write_bytes(b'png')
    model = GlossaryModel()
    translator = _translator(tmp_path, model)
    subtitles_service = SubtitleService(translator, work_dir=tmp_path / 'work', store_dir=tmp_path / 'models',
                                        engine=fake_engine, access=lambda refresh: {'allowed': True})
    media = subtitles_service.folder_media(Options(model='large-v3-turbo', quality='fast'))
    names = []
    result = translator.translate_folder(folder, model='m:1', target='한국어', media=media,
                                         on_file=lambda i, n, name: names.append(name))
    out = folder.with_name('series.ko')
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()) == [
        'cover.png', 'ep2.en.srt', 'ep2.srt', 'note.txt', 'season/ep10.en.srt', 'season/ep10.srt']
    assert not list(out.rglob('*.wav'))                       # 큰 영상·음성은 복사하지 않는다
    assert any(name.startswith('자막 만들기 · ') for name in names)
    korean = parse((out / 'ep2.srt').read_text(encoding='utf-8-sig'))
    assert korean and validate(korean, rules_for('ko')).ok
    assert {rel for rel, _ in result.translated} == {'ep2.wav', 'season/ep10.wav', 'note.txt'}
    assert result.memory is not None                          # 자막도 폴더 메모리를 함께 쓴다
    calls = len(list((tmp_path / 'work').rglob('result-cpu.calls')))
    again = translator.translate_folder(folder, model='m:1', target='한국어', media=media)
    assert {rel for rel, why in again.skipped} >= {'ep2.wav', 'season/ep10.wav'}
    assert len(list((tmp_path / 'work').rglob('result-cpu.calls'))) == calls   # 다시 인식하지 않음


def test_translated_subtitle_terms_can_be_revised(tmp_path, fake_engine):
    from services.tools.subtitles import Options, SubtitleService, Translate
    translator = _translator(tmp_path, GlossaryModel())
    service = SubtitleService(translator, work_dir=tmp_path / 'work', store_dir=tmp_path / 'models',
                              engine=fake_engine, access=lambda refresh: {'allowed': True})
    result = service.make(_wav(tmp_path / 'talk.wav'), Options(model='large-v3-turbo', quality='fast'),
                          translate=Translate(target='한국어', model='m:1'))
    before = result.translated_outputs[0].read_text(encoding='utf-8-sig')
    assert 'Hello' in before
    revised = service.revise_terms(result, {'Hello': '안녕하세요'})
    after = revised.translated_outputs[0].read_text(encoding='utf-8-sig')
    assert 'Hello' not in after and '안녕하세요' in after and revised.translated.revised >= 1
    assert revised.translated_outputs == result.translated_outputs     # 같은 번역 자막 파일을 고쳐 쓴다
    assert validate(parse(after), rules_for('ko')).ok


def test_translation_glossary_editor_applies_and_remembers_terms(ui, tmp_path):
    from test_desktop_ui import pump
    w, svc, _ = ui
    model = GlossaryModel()
    svc.translator = _translator(tmp_path, model)
    svc.translator.local_models = lambda: ['m:1']
    w.navigate('tools'); w.open_tool('translate')
    pump(w, lambda: w.translation_model.get() == 'm:1', timeout=5)
    source = tmp_path / 'story.txt'
    source.write_text('Sato smiled.\nThe sky is blue.\nSato left.\n', encoding='utf-8')
    w.translation_path.set(str(source)); w.analyze_translation_file()
    pump(w, lambda: '준비됨' in w.translation_status.get(), timeout=5)
    w.start_translation()
    pump(w, lambda: '번역 완료' in w.translation_status.get(), timeout=10)
    output = tmp_path / 'story.ko.txt'
    assert output.read_text(encoding='utf-8').count('사토') == 2
    editor = w.translation_terms_editor
    assert str(editor.apply_button['state']) == 'disabled'
    editor.source.set('Sato'); editor.target.set('사이토'); editor.set_term()
    assert editor.changes() == {'Sato': '사이토'} and str(editor.apply_button['state']) == 'normal'
    before = model.items
    editor._apply()
    pump(w, lambda: '용어 적용 완료' in w.translation_status.get(), timeout=10)
    assert output.read_text(encoding='utf-8') == '사이토 웃었다.\n하늘이 파랗다.\n사이토 떠났다.\n'
    assert model.items - before == 2
    assert 'Sato = 사이토' in w.translation_glossary_text.get('1.0', 'end')
    pump(w, lambda: 'Sato = 사이토' in svc.settings.translation_preferences().get('glossary', ''), timeout=4)


def test_evaluation_is_fair_to_an_utterance_split_into_several_cues():
    """실측에서 찾은 평가 오류: 긴 발화를 규칙대로 여러 큐로 나누면 큐마다 발화 전체와 비교해 오차가 부풀었다."""
    from core.tools import subtitle_eval
    reference = [Cue(1000, 9000, ('one long utterance that the subtitle rules split into three cues',))]
    hypothesis = [Cue(1100, 3500, ('one long utterance',)), Cue(3583, 6000, ('that the subtitle rules',)),
                  Cue(6083, 8900, ('split into three cues',))]
    report = subtitle_eval.evaluate(reference, hypothesis)
    assert report.timestamp_mae == 100 and report.omission == 0.0 and report.hallucination == 0.0


def test_partial_broadcast_fillers_are_recognized():
    assert speech.is_filler('자막 제공 및 자막 제공 및 광고를 포함하고 있습니다.')
    assert speech.is_filler('Thank you for watching!')
    assert not speech.is_filler('오늘은 자막을 만드는 방법과 그 규칙이 왜 중요한지 자세히 이야기해 보겠습니다.')


def test_speech_the_file_language_skipped_is_recognized_again_with_language_detection(
        tmp_path, fake_engine, monkeypatch):
    """실측: 한국어 프로그램 속 영어 발화를 Whisper가 통째로 건너뛰었다(파일 언어 ko로 고정)."""
    from services.tools.subtitles import Options
    monkeypatch.setenv('FAKE_SCENARIO', 'skip')
    monkeypatch.setenv('FAKE_VAD_LOG', '1')
    fake_engine.vad_model().parent.mkdir(parents=True, exist_ok=True)
    fake_engine.vad_model().write_bytes(b'vad')
    result = _service(tmp_path, fake_engine).make(_wav(tmp_path / 'mixed.wav', seconds=8),
                                                  Options(model='large-v3-turbo', language='한국어',
                                                          quality='balanced'))
    recovered = [d for d in result.decisions if d.range.reason == 'possible missing speech']
    assert recovered and recovered[0].accepted and 'English words' in recovered[0].candidate
    assert 'English words' in result.text and '안녕하세요' in result.text
    calls = json.loads(next((tmp_path / 'user_data').rglob('result-cpu.calls')).read_text(
        encoding='utf-8').splitlines()[0])
    assert calls[calls.index('-l') + 1] == 'ko'                # 최초 인식은 고른 언어


def test_speech_rate_follows_the_script_of_the_text_not_the_file_language():
    """실측: 중국어 파일 속 영어 문장이 중국어 기준(초당 글자 수)에 걸려 '불가능한 속도'로 기각됐다."""
    from core.tools import asr_review
    english = speech.Segment(0, 4000, 'because it is established by law as the first official language', (), 0.9)
    assert asr_review.evidence(english).plausible_rate
    chinese = speech.Segment(0, 1000, '我们今天来谈谈新的引擎是如何工作的以及为什么它对每一个', (), 0.9)
    assert not asr_review.evidence(chinese).plausible_rate        # 1초에 26자는 불가능


def test_a_confident_filler_stretched_over_silence_is_removed():
    """실측(VAD 끔): 30초 무음에 'ご視聴ありがとうございました'(확신도 0.92)."""
    result = speech.clean([speech.Segment(90000, 119980, 'ご視聴ありがとうございました', (
        Word(90000, 119980, 'ご視聴ありがとうございました', 0.92),), 0.92)])
    assert not result.segments and result.removed[0][2] == 'typical hallucination'
    kept = speech.clean([speech.Segment(0, 2500, 'ご視聴ありがとうございました', (
        Word(0, 2500, 'ご視聴ありがとうございました', 0.92),), 0.92)])
    assert kept.segments and kept.flagged                        # 실제로 말한 인사는 지우지 않고 표시만


def test_recovered_speech_is_inserted_without_touching_neighbours():
    """실측: 여유분 때문에 이웃 한국어 문장을 '원래 결과'로 보고 영어 복구를 기각했다."""
    from core.tools import asr_review
    neighbour = speech.Segment(66380, 70000, '겨울은 쌀쌀하다.', (Word(66380, 70000, ' 겨울은 쌀쌀하다.', 0.97),), 0.97)
    recovered = asr_review.shift([speech.Segment(0, 6000, 'However, most signs are in Catalan.', (
        Word(300, 1000, ' However,', 0.9), Word(1000, 3000, ' most signs are', 0.9),
        Word(3000, 6400, ' in Catalan.', 0.9)), 0.9)], 60230)
    range_ = asr_review.Range(60230, 66690, 'possible missing speech')
    assert asr_review.choose(range_, [], recovered).accepted
    out = asr_review.insert_range([neighbour], range_, recovered)
    assert [s.text for s in out] == ['However, most signs are', '겨울은 쌀쌀하다.']   # 겹치는 단어는 넣지 않음


def test_sensitive_vad_is_an_explicit_choice(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    fake_engine.vad_model().parent.mkdir(parents=True, exist_ok=True)
    fake_engine.vad_model().write_bytes(b'vad')
    service = _service(tmp_path, fake_engine)
    service.make(_wav(tmp_path / 'a.wav'), Options(model='large-v3-turbo', quality='fast'))
    service.make(_wav(tmp_path / 'b.wav'), Options(model='large-v3-turbo', quality='fast', sensitive_vad=True))
    calls = [json.loads(path.read_text(encoding='utf-8').splitlines()[0])
             for path in sorted((tmp_path / 'user_data').rglob('result-cpu.calls'), key=lambda p: p.stat().st_mtime)]
    assert '-vt' not in calls[0] and calls[1][calls[1].index('-vt') + 1] == '0.35'


def test_folder_runs_skip_media_that_already_have_subtitles(tmp_path, fake_engine):
    """폴더를 다시 돌려도 새로 추가된 파일만 인식한다(옆에 영상.srt·영상.ko.srt·영상.ass 등이 있으면 건너뜀)."""
    from services.tools.subtitles import Options, existing_subtitles, scan
    folder = tmp_path / 'videos'
    (folder / 'sub').mkdir(parents=True)
    for name in ('a.wav', 'b.wav', 'sub/c.wav', 'd.wav', 'e [1].wav'):
        _wav(folder / name)
    (folder / 'b.ko.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nx\n', encoding='utf-8')
    (folder / 'd.ass').write_text('[Script Info]', encoding='utf-8')
    (folder / 'e [1].srt').write_text('x', encoding='utf-8')
    (folder / 'a.notes.txt').write_text('not a subtitle', encoding='utf-8')
    (folder / 'ab.srt').write_text('another video', encoding='utf-8')     # 'a'로 시작할 뿐 다른 영상의 자막
    assert existing_subtitles(folder / 'a.wav') == []
    service = _service(tmp_path, fake_engine)
    first = service.make_many(scan(folder), Options(model='large-v3-turbo', quality='fast'))
    assert sorted(p.name for p, _ in first.results) == ['a.wav', 'c.wav']
    assert sorted(p.name for p, _ in first.skipped) == ['b.wav', 'd.wav', 'e [1].wav']
    assert (folder / 'a.srt').exists() and (folder / 'sub' / 'c.srt').exists()
    calls = len(list((tmp_path / 'user_data').rglob('result-cpu.calls')))
    again = service.make_many(scan(folder), Options(model='large-v3-turbo', quality='fast'))
    assert again.results == () and len(again.skipped) == 5
    assert len(list((tmp_path / 'user_data').rglob('result-cpu.calls'))) == calls
    assert not list(folder.rglob('* (2).srt'))                       # 사본을 만들지 않는다


def test_speech_models_live_in_the_models_screen_with_a_shortcut_from_subtitles(ui, tmp_path, fake_engine):
    from test_desktop_ui import pump
    from integrations.speech.engine import SpeechEngine
    w, svc, _ = ui
    empty = SpeechEngine(tmp_path / 'none', tmp_path / 'none-models')
    svc.subtitles.engine = empty
    svc.subtitles.supported = staticmethod(lambda: (True, ''))
    w.navigate('tools'); w.open_tool('subtitles')
    pump(w, lambda: 'Models' in w.subtitle_status.get() and w.subtitle_status_label.action.winfo_ismapped(),
         timeout=8)
    assert not hasattr(w, 'subtitle_model_table')              # 자막 화면에는 관리 표가 없다
    assert w.subtitle_status_label.action.cget('text') == 'Models에서 받기 →'
    w.subtitle_status_label.action.invoke()
    pump(w, lambda: w.current_page == 'models' and
         w.model_tabs.select() == str(w.model_pages['speech']), timeout=5)
    pump(w, lambda: len(w.speech_model_table.get_children()) == len(speech.MODELS), timeout=8)
    states = {key: w.speech_model_table.item(key, 'values')[3] for key in w.speech_model_table.get_children()}
    assert set(states.values()) == {'-'}
    svc.subtitles.engine = fake_engine                         # 모델을 받은 뒤: 두 화면 모두 갱신
    w.refresh_speech_status()
    pump(w, lambda: w.speech_model_table.item('large-v3-turbo', 'values')[3] == '설치됨', timeout=8)
    assert w.subtitle_model.get() == 'large-v3-turbo · 권장'
    assert not w.subtitle_status_label.action.winfo_ismapped()


# ── 첫 파일 번역 누락(실사용 보고) ──
class ColdStartInference:
    """막 켠 Ollama: 처음 몇 번은 모델 목록을 못 준다(None → 빈 목록 → 정상)."""
    def __init__(self):
        self.answers = [None, [], ['m:1']]

    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def test_the_first_translation_waits_for_a_just_started_ollama(tmp_path, monkeypatch):
    from services.tools import translation
    from services.tools.translation import TranslationService
    monkeypatch.setattr(translation.time, 'sleep', lambda seconds: None)
    source = tmp_path / 'a.txt'
    source.write_text('Sato smiled.\n', encoding='utf-8')
    service = TranslationService(ColdStartInference(), lambda _: GlossaryModel(), checkpoint_dir=tmp_path / 'cp',
                                 protector=None, check_language=False)
    assert '사토' in service.translate_file(source, model='m:1', target='한국어', kind='general').text


def test_a_failed_translation_keeps_the_subtitle_and_the_rerun_translates_only(tmp_path, fake_engine):
    from services.tools.subtitles import Options, SubtitleService, Translate
    translator = _translator(tmp_path, GlossaryModel())
    real = translator.translate_file
    calls = {'n': 0}

    def flaky(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('Selected model is not available locally')
        return real(*args, **kwargs)
    translator.translate_file = flaky
    service = SubtitleService(translator, work_dir=tmp_path / 'work', store_dir=tmp_path / 'models',
                              engine=fake_engine, access=lambda refresh: {'allowed': True})
    files = [_wav(tmp_path / 'first.wav'), _wav(tmp_path / 'second.wav')]
    job = Translate(target='한국어', model='m:1')
    batch = service.make_many(files, Options(model='large-v3-turbo', quality='fast'), translate=job)
    first, second = (result for _, result in batch.results)
    assert batch.failed == () and 'not available' in first.translation_error
    assert (tmp_path / 'first.en.srt').exists() and not (tmp_path / 'first.srt').exists()
    assert (tmp_path / 'second.srt').exists()
    recognitions = len(list((tmp_path / 'work').rglob('result-cpu.calls')))
    again = service.make_many(files, Options(model='large-v3-turbo', quality='fast'), translate=job)
    assert [p.name for p, _ in again.skipped] == ['second.wav']           # 끝난 파일만 건너뜀
    redo = again.results[0][1]
    assert redo.translated_outputs[0].name == 'first.srt' and not redo.translation_error
    assert redo.outputs[0].name == 'first.en.srt' and redo.reused        # 원어 자막·인식 결과 재사용
    assert not (tmp_path / 'first.en (2).srt').exists()
    assert len(list((tmp_path / 'work').rglob('result-cpu.calls'))) == recognitions


def test_the_old_naming_is_kept_when_the_option_is_off(tmp_path, fake_engine):
    from services.tools.subtitles import Options, SubtitleService, Translate
    service = SubtitleService(_translator(tmp_path, GlossaryModel()), work_dir=tmp_path / 'work',
                              store_dir=tmp_path / 'models', engine=fake_engine,
                              access=lambda refresh: {'allowed': True})
    result = service.make(_wav(tmp_path / 'clip.wav'), Options(model='large-v3-turbo', quality='fast'),
                          translate=Translate(target='한국어', model='m:1', main_name=False))
    assert [p.name for p in result.outputs + result.translated_outputs] == ['clip.srt', 'clip.ko.srt']


def test_a_translated_document_can_take_the_original_name(tmp_path):
    from services.tools.translation import place_as_original
    source = tmp_path / 'story.txt'
    source.write_text('Sato smiled.\n', encoding='utf-8')
    service = _translator(tmp_path, GlossaryModel())
    result = service.translate_file(source, model='m:1', target='한국어', kind='general',
                                    source_language='English')
    placed, kept = place_as_original(result, source)
    assert placed.output == source and source.read_text(encoding='utf-8') == '사토 웃었다.\n'
    assert kept.name == 'story.en.txt' and kept.read_text(encoding='utf-8') == 'Sato smiled.\n'
    assert not (tmp_path / 'story.ko.txt').exists()
    unknown = tmp_path / 'memo.txt'
    unknown.write_text('Sato left.\n', encoding='utf-8')
    other = service.translate_file(unknown, model='m:1', target='한국어', kind='general')
    assert place_as_original(replace_revision(other), unknown)[1].name == 'memo.og.txt'   # 원문 언어 모름


def replace_revision(result):
    from dataclasses import replace
    return replace(result, revision=None)
