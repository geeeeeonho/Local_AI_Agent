"""이미 시각이 있는 자막 다시 맞추기와 끊김·겹침 검수 교정."""
import random

import pytest

from core.tools.subtitles import Cue, parse, rules_for, to_srt
from core.tools.subtitle_sync import resync, review
from test_subtitles import _service, _wav, fake_engine  # noqa: F401  (pytest fixture)


def _talk(seed=3, count=400):
    """실제 말소리 구간(정답)과, 그 구간에 맞는 자막을 만드는 함수."""
    rng = random.Random(seed)
    truth, t = [], 2000
    for _ in range(count):
        length = rng.randint(900, 4500)
        truth.append((t, t + length))
        t += length + rng.choice([200, 400, 800, 1500, 3000, 6000])
    speech = [(s + rng.randint(-80, 80), e + rng.randint(-80, 80)) for s, e in truth]
    extra = [(e + 300, e + 300 + rng.randint(500, 2500)) for _s, e in truth if rng.random() < 0.25]

    def subtitle(shift=0, speed=1.0, split_at=None, split_shift=0, drop=0.0):
        cues = []
        for index, (s, e) in enumerate(truth):
            if rng.random() < drop:
                continue
            offset = shift + (split_shift if split_at is not None and index >= split_at else 0)
            cues.append(Cue(int((s - offset) / speed), int((e - offset) / speed), ('x',)))
        return cues
    return truth, speech + extra, subtitle


def _errors(cues, truth):
    starts = sorted(s for s, _e in truth)
    return sorted(min(abs(cue.start - s) for s in starts) for cue in cues)


@pytest.mark.parametrize('case', ['offset', 'speed', 'split', 'already right'])
def test_offset_speed_and_a_mid_file_jump_are_found(case):
    truth, speech, subtitle = _talk()
    cues = {'offset': lambda: subtitle(shift=3200, drop=0.1),
            'speed': lambda: subtitle(shift=-7500, speed=25 / 23.976, drop=0.1),
            'split': lambda: subtitle(shift=1500, split_at=200, split_shift=8000, drop=0.1),
            'already right': lambda: subtitle(drop=0.1)}[case]()
    result = resync(cues, speech)
    errors = _errors(result.cues, truth)
    assert errors[len(errors) // 2] <= 100 and errors[int(len(errors) * 0.95)] <= 200
    assert result.after >= 0.95
    if case == 'split':
        assert len(result.splits) == 1
    if case == 'already right':
        assert result.offset_ms == 0 and result.splits == () and result.speed == 1.0
    if case == 'speed':
        assert abs(result.speed - 25 / 23.976) < 1e-6


def test_fragments_overlaps_and_awkward_breaks_are_corrected_and_reported():
    rules = rules_for('en')
    cues = [Cue(0, 2500, ('I went to the',)), Cue(2600, 5000, ('store yesterday and bought milk.',)),
            Cue(9000, 9500, ('Wait.',)), Cue(9400, 12000, ('This one overlaps the previous cue.',)),
            Cue(13000, 16000, ('A very long line that clearly goes beyond the forty two character limit here',)),
            Cue(20000, 24000, ('Yesterday I finally finished reading the very', 'long book about the')),
            Cue(24100, 28000, ('history of Rome, which my teacher gave me', 'when I was still at school.'))]
    fixed, fixes = review(cues, rules)
    texts = [cue.text.replace('\n', ' ') for cue in fixed]
    assert 'I went to the store yesterday and bought milk.' in texts
    assert all(a.end <= b.start for a, b in zip(fixed, fixed[1:]))                 # 겹침 없음
    assert all(len(line) <= rules.max_chars for cue in fixed for line in cue.lines)
    assert any(text.endswith('history of Rome,') for text in texts)                # 'the' 뒤가 아닌 쉼표 뒤
    reasons = {(fix.number, fix.reason) for fix in fixes}
    assert (2, 'merged a fragment cut mid-sentence') in reasons
    assert (3, 'fixed an overlap') in reasons
    assert (5, 'rewrapped lines') in reasons
    assert (7, 'moved an awkward break to a natural boundary') in reasons


def test_well_made_subtitles_are_left_alone():
    rules = rules_for('ko')
    cues = [Cue(0, 3000, ('안녕하세요, 오늘은', '자막 이야기를 합니다.')), Cue(3500, 6000, ('끝까지 들어 주세요.',))]
    fixed, fixes = review(cues, rules)
    assert fixes == () and [c.lines for c in fixed] == [c.lines for c in cues]


def test_a_shifted_subtitle_is_resynced_with_the_media_and_the_old_one_is_kept(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'show.wav')
    # 가짜 인식: 'Hello and welcome to the show.' 0~2초, 'Today we talk …' 2~5초. 자막은 5초 늦다.
    late = [Cue(5000, 6980, ('Hello and welcome to the show.',)),
            Cue(6980, 9950, ('Today we talk about subtitles, and why rules matter.',))]
    path = tmp_path / 'show.srt'
    path.write_text(to_srt(late), encoding='utf-8')
    result = _service(tmp_path, fake_engine).resync_file(path, media, Options(model='large-v3-turbo'))
    assert result.changed and result.kept == tmp_path / 'show.og.srt'
    assert parse(result.kept.read_text(encoding='utf-8')) == late                  # 원래 자막은 그대로 보관
    cues = parse(path.read_text(encoding='utf-8-sig'))
    assert abs(cues[0].start - 0) <= 200 and result.sync.offset_ms <= -4500
    assert result.same_language and result.sync.refined >= 1                      # 같은 언어: 글자까지 맞춤


def test_review_only_needs_no_media_and_nothing_is_written_when_nothing_changes(tmp_path):
    from services.tools.subtitles import SubtitleService
    service = SubtitleService(None, work_dir=tmp_path / 'w', store_dir=tmp_path / 'm', engine=object(),
                              access=lambda refresh: {'allowed': True})
    good = tmp_path / 'good.srt'
    good.write_text(to_srt([Cue(0, 3000, ('A complete sentence here.',)),
                            Cue(3500, 6000, ('And another one.',))]), encoding='utf-8')
    result = service.resync_file(good, sync=False)
    assert not result.changed and result.kept is None and not (tmp_path / 'good.og.srt').exists()
    bad = tmp_path / 'bad.srt'
    bad.write_text(to_srt([Cue(0, 1200, ('So we went',)), Cue(1300, 2600, ('to the market.',))]), encoding='utf-8')
    result = service.resync_file(bad, sync=False)
    assert result.changed and parse(bad.read_text(encoding='utf-8-sig'))[0].text == 'So we went to the market.'


def test_cues_over_a_long_silence_stay_put_and_the_rest_is_unaffected():
    truth, speech, subtitle = _talk(seed=4)
    cues = subtitle(shift=2000)
    cut = truth[200][0]
    quiet = [span for span in speech if not cut <= span[0] <= cut + 600_000]     # 10분 동안 말소리 없음(음악)
    result = resync(cues, quiet)
    inside = [(a, b) for a, b in zip(cues, result.cues) if cut <= a.start + 2000 <= cut + 600_000]
    assert inside and all(abs(b.start - (a.start + 2000)) <= 1000 for a, b in inside)   # 끌려가지 않는다
    assert all(a.end <= b.start + 300 for a, b in zip(result.cues, result.cues[1:]))      # 순서가 꼬이지 않는다
    errors = _errors([c for c in result.cues if c.start > cut + 650_000], truth)
    assert errors[len(errors) // 2] <= 100


@pytest.mark.parametrize('late', [8000, 30000])
def test_a_later_part_that_is_late_is_pulled_back(late):
    truth, speech, subtitle = _talk(seed=5)
    result = resync(subtitle(shift=1000, split_at=200, split_shift=-late, drop=0.1), speech)
    errors = _errors(result.cues, truth)
    assert len(result.splits) == 1 and errors[int(len(errors) * 0.95)] <= 200
