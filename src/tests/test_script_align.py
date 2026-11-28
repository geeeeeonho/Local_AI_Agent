"""대본으로 시간 맞추기: 글은 대본 그대로, 시각만 음성 인식에서.

인식은 틀린 글자·빠진 낱말·대본에 없는 말(애드리브)이 섞인다. 대본 줄 순서와 맞는 글자 조각만
증거로 써서 시각을 정하고, 못 찾은 줄은 앞뒤 사이에 놓은 뒤 검토 목록에 알린다.
"""
import random
import time

import pytest

from core.tools.script_align import align, script_lines
from core.tools.subtitles import Word, build_cues, parse, rules_for, validate
from test_subtitles import _service, _wav, fake_engine  # noqa: F401  (pytest fixture)


def _spoken(text, start=0, step=400, typo=None):
    """띄어 쓰는 언어의 인식 단어. typo={낱말: 잘못 들은 글}."""
    words, t = [], start
    for word in text.split():
        words.append(Word(t, t + step - 50, ' ' + (typo or {}).get(word, word)))
        t += step
    return words, t


def test_script_text_is_kept_and_each_line_starts_its_own_cue():
    heard, _ = _spoken('hello there how are you doing today i am fine thanks', typo={'doing': 'doin'})
    placed = align('HELLO THERE!\nHow are you doing today?\nI\'m fine, thanks.', heard)
    cues = build_cues(placed.words, rules_for('en'), boundaries=placed.boundaries)
    # 짧은 첫 줄도 다음 줄과 합치지 않는다(대본 한 줄 = 새 큐)
    assert [cue.text for cue in cues] == ['HELLO THERE!', 'How are you doing today?', "I'm fine, thanks."]
    assert cues[1].start == 800 and placed.missed == ()


def test_stage_directions_and_blank_lines_are_left_out_and_subtitles_can_be_scripts():
    assert script_lines('[문이 열린다]\n\n  안녕   하세요 \n(웃음)\n잘 가') == ['안녕 하세요', '잘 가']
    srt = '1\n00:00:01,000 --> 00:00:02,000\n첫 줄\n둘째 줄\n\n2\n00:00:03,000 --> 00:00:04,000\n다음\n'
    assert script_lines(srt) == ['첫 줄 둘째 줄', '다음']


def test_lines_not_in_the_speech_are_placed_between_their_neighbours_and_reported():
    heard, end = _spoken('one two three four')
    more, _ = _spoken('seven eight nine ten', start=end + 2000)
    placed = align('one two three four\nfive six\nseven eight nine ten', heard + more)
    assert placed.missed == (2,)
    starts = [placed.words[index].start for index in placed.line_starts]
    assert starts[0] < starts[1] < starts[2] == end + 2000       # 순서는 지키고, 들은 줄은 제자리


def test_japanese_without_spaces_and_a_misheard_word_at_a_line_start():
    heard = [Word(0, 800, 'こんにちは'), Word(800, 820, '。'), Word(1500, 1800, '切り'), Word(1800, 1900, 'の'),
             Word(1900, 2100, '街'), Word(2100, 2200, 'へ'), Word(2200, 2700, '行こう')]
    placed = align('こんにちは！\n霧の街へ行こう', heard, spaced=False)
    cues = build_cues(placed.words, rules_for('ja'), boundaries=placed.boundaries)
    assert [cue.text for cue in cues] == ['こんにちは！', '霧の街へ行こう']
    # 못 알아들은 줄 첫 글자는 앞 줄 끝이 아니라 그 줄의 다음 글자 바로 앞에 놓는다
    assert cues[1].start > 1000


def test_a_script_for_another_recording_is_refused():
    heard, _ = _spoken('completely different words were spoken in this recording')
    with pytest.raises(ValueError, match='does not match'):
        align('가나다라 마바사\n아자차카', heard)


def test_long_scripts_with_noise_intro_and_ad_libs_stay_in_order_and_fast():
    """흔한 글자가 수천 번 나오는 긴 대본: 묶음 단위로 맞춰 길이에 거의 비례해 끝난다."""
    random.seed(7)
    syllables = '가나다라마바사아자차카타파하고노도로모보소오조초코토포호구누두루무부수우주'
    word = lambda: ''.join(random.choice(syllables) for _ in range(random.randint(2, 5)))
    lines = [' '.join(word() for _ in range(random.randint(3, 7))) + '.' for _ in range(600)]
    heard, t, truth = [], 0, {}
    noisy = lambda text: ''.join(c if random.random() > 0.08 else random.choice(syllables) for c in text)
    intro, t = _spoken(' '.join(word() for _ in range(300)))                   # 대본 앞 긴 인사말
    heard += intro
    for index, line in enumerate(lines):
        if index in (50, 51, 52):
            continue                                                            # 대본에 있지만 말하지 않음
        truth[index] = t
        spoken, t = _spoken(noisy(line), start=t)
        heard += spoken
        t += 400
        if index == 100:                                                        # 대본에 없는 애드리브
            extra, t = _spoken(' '.join(word() for _ in range(40)), start=t)
            heard += extra
    began = time.monotonic()
    placed = align('\n'.join(lines), heard)
    assert time.monotonic() - began < 5
    # 말하지 않은 세 줄은 반드시, 그 밖에는 인식이 크게 틀린 짧은 줄만 검토로 알린다
    assert {51, 52, 53} <= set(placed.missed) and len(placed.missed) <= 6
    errors = sorted(abs(placed.words[placed.line_starts[i]].start - start) for i, start in truth.items())
    assert errors[len(errors) // 2] == 0 and errors[-1] < 2000
    times = [word.start for word in placed.words]
    assert times == sorted(times)


def test_cue_merging_still_works_without_a_script():
    # 경계가 없으면 예전처럼 짧은 큐를 이웃에 합친다
    words = [Word(0, 300, ' Hi.'), Word(330, 2000, ' Then we go home now')]
    assert len(build_cues(words, rules_for('en'))) == 1


def test_the_subtitle_service_uses_the_script_text_with_recognized_times(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'show.wav')
    old = '1\n00:00:00,000 --> 00:00:01,000\nこんにちは、番組へようこそ。\n'
    (tmp_path / 'show.srt').write_text(old, encoding='utf-8')
    script = tmp_path / 'script.txt'
    script.write_text('[Music]\nHello, and WELCOME to the show!\nToday we talk about subtitles.\n'
                      'And why rules matter.\nThis line is never said.\n', encoding='utf-8')
    service = _service(tmp_path, fake_engine)
    batch = service.make_many([media], Options(model='large-v3-turbo', script=str(script)))
    assert not batch.skipped                          # 옆에 인식 자막이 있어도 대본으로 새로 만든다
    result = batch.results[0][1]
    cues = parse(result.outputs[0].read_text(encoding='utf-8-sig'))
    # 대본 자막이 원래 이름을 쓰고, 있던 자막은 '원본 이름으로 저장'과 같은 규칙으로 보관한다
    assert result.outputs[0].name == 'show.srt' and not (tmp_path / 'show (2).srt').exists()
    assert result.set_aside == (tmp_path / 'show.ja.srt',)
    assert (tmp_path / 'show.ja.srt').read_text(encoding='utf-8') == old
    assert [cue.text for cue in cues][:3] == ['Hello, and WELCOME to the show!', 'Today we talk about subtitles.',
                                             'And why rules matter.']
    assert cues[1].start >= 1900 and validate(cues, rules_for('en')).ok
    assert result.script_missed == (4,) and any(reason == 'script line not heard' for _n, reason in result.review)
    assert result.removed == ()


def test_an_existing_subtitle_of_unknown_language_is_kept_as_og_and_numbers_are_added(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'show.wav')
    for name in ('show.srt', 'show.og.srt'):
        (tmp_path / name).write_text('1\n00:00:00,000 --> 00:00:01,000\n12345\n', encoding='utf-8')
    script = tmp_path / 'script.txt'
    script.write_text('Hello and welcome to the show.\n', encoding='utf-8')
    result = _service(tmp_path, fake_engine).make(media, Options(model='large-v3-turbo', script=str(script)))
    assert result.outputs == (tmp_path / 'show.srt',)
    assert result.set_aside == (tmp_path / 'show.og (2).srt',)
    assert 'Hello and welcome' in (tmp_path / 'show.srt').read_text(encoding='utf-8-sig')


def test_with_translation_the_translated_subtitle_takes_the_name_by_the_same_rule(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    media = _wav(tmp_path / 'show.wav')
    old = '1\n00:00:00,000 --> 00:00:01,000\n안녕하세요, 방송에 오신 것을 환영합니다.\n'
    (tmp_path / 'show.srt').write_text(old, encoding='utf-8')
    script = tmp_path / 'script.txt'
    script.write_text('Hello and welcome to the show.\nToday we talk about subtitles.\n', encoding='utf-8')
    result = _service(tmp_path, fake_engine).make(
        media, Options(model='large-v3-turbo', script=str(script)),
        translate=Translate(target='한국어', model='m:1', main_name=True))
    assert result.outputs == (tmp_path / 'show.en.srt',)          # 대본(원어) 자막
    assert result.translated_outputs == (tmp_path / 'show.srt',)  # 번역 자막이 원래 이름
    assert result.set_aside == (tmp_path / 'show.ko.srt',)        # 있던 한국어 자막은 보관
    assert (tmp_path / 'show.ko.srt').read_text(encoding='utf-8') == old


def test_a_script_is_checked_before_the_long_recognition_starts(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = _wav(tmp_path / 'show.wav')
    empty = tmp_path / 'empty.txt'
    empty.write_text('[지문만]\n\n', encoding='utf-8')
    service = _service(tmp_path, fake_engine)
    with pytest.raises(ValueError, match='no lines'):
        service.make(media, Options(model='large-v3-turbo', script=str(empty)))
    assert not list((tmp_path / 'user_data').rglob('*.calls'))      # 인식은 시작하지 않았다
    with pytest.raises(ValueError, match='one media file'):
        service.make_many([media, media], Options(model='large-v3-turbo', script=str(empty)))


# ── 여러 파일: 대본 폴더 ──
def test_scripts_are_matched_by_relative_path_then_by_a_unique_name(tmp_path):
    from services.tools.subtitles import match_scripts
    media_root, scripts = tmp_path / 'media', tmp_path / 'scripts'
    for name in ('1장/1화.mp4', '1장/2화.mp4', '3화.wav', '4화.wav', '5화.wav'):
        (media_root / name).parent.mkdir(parents=True, exist_ok=True); (media_root / name).write_bytes(b'')
    for name in ('1장/1화.srt', '1장/1화.txt', '2화.txt', 'x/4화.txt', 'y/4화.txt', '.숨김/5화.txt'):
        (scripts / name).parent.mkdir(parents=True, exist_ok=True); (scripts / name).write_text('a', encoding='utf-8')
    found = match_scripts(sorted(media_root.rglob('*.*')), scripts, media_root)
    named = {path.name: (value.relative_to(scripts).as_posix() if value else None) for path, value in found.items()}
    assert named == {'1화.mp4': '1장/1화.txt',      # 같은 상대 경로, .txt가 .srt보다 먼저
                     '2화.mp4': '2화.txt',          # 상대 경로는 다르지만 이름이 하나뿐
                     '3화.wav': None,               # 대본 없음
                     '4화.wav': None,               # 같은 이름이 두 곳: 어느 것인지 모른다
                     '5화.wav': None}               # 숨김 폴더는 보지 않는다


def test_a_folder_of_media_uses_each_files_script_and_skips_the_rest(tmp_path, fake_engine):
    from services.tools.subtitles import Options
    media = tmp_path / 'media'; media.mkdir()
    first, second, third = (_wav(media / name) for name in ('ep1.wav', 'ep2.wav', 'ep3.wav'))
    (media / 'ep3.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nmade before\n', encoding='utf-8')
    extra = _wav(media / 'ep4.wav')
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    (scripts / 'ep1.txt').write_text('Hello and welcome to the show.\n', encoding='utf-8')
    (scripts / 'ep2.txt').write_text('Today we talk about subtitles.\nAnd why rules matter.\n', encoding='utf-8')
    batch = _service(tmp_path, fake_engine).make_many([first, second, third, extra],
                                                      Options(model='large-v3-turbo', script=str(scripts)))
    assert [path.name for path, _ in batch.results] == ['ep1.wav', 'ep2.wav']
    assert [result.script for _, result in batch.results] == [str(scripts / 'ep1.txt'), str(scripts / 'ep2.txt')]
    assert 'Today we talk about subtitles.' in (media / 'ep2.srt').read_text(encoding='utf-8-sig')
    assert [path.name for path, _ in batch.skipped] == ['ep3.wav']     # 지난번에 만든 자막이 있음
    assert [path.name for path in batch.unmatched] == ['ep4.wav']      # 대본 없음


# ── 영상·음성 이름 번역 ──
class NamingTranslator:
    """FakeTranslator + 이름 번역(파일 번역 도구의 translated_names 계약)."""
    def __init__(self, names):
        from test_subtitles import FakeTranslator
        self.inner, self.names, self.asked = FakeTranslator(), names, []

    def translate_file(self, *args, **kwargs):
        return self.inner.translate_file(*args, **kwargs)

    def translated_names(self, paths, model, target, *, terms=None, cancelled=None):
        self.asked += [path.name for path in paths]
        return {path: self.names.get(path.stem) for path in paths}

    def abort(self):
        pass


def test_the_media_file_takes_the_translated_name_and_its_subtitles_follow(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    media = _wav(tmp_path / 'the show.wav')
    translator = NamingTranslator({'the show': '그 방송'})
    result = _service(tmp_path, fake_engine, translator).make(
        media, Options(model='large-v3-turbo'),
        translate=Translate(target='한국어', model='m:1', main_name=True, translate_name=True))
    assert not media.exists() and (tmp_path / '그 방송.wav').exists()
    assert result.source == tmp_path / '그 방송.wav' and result.renamed_from == media
    assert [path.name for path in result.outputs + result.translated_outputs] == ['그 방송.en.srt', '그 방송.srt']


def test_names_already_in_the_target_language_or_untranslatable_stay(tmp_path, fake_engine):
    from services.tools.subtitles import Options, Translate
    korean, code = _wav(tmp_path / '오늘의 방송.wav'), _wav(tmp_path / 'clip.wav')
    translator = NamingTranslator({})                    # 'clip'은 옮기지 못한다
    service = _service(tmp_path, fake_engine, translator)
    job = Translate(target='한국어', model='m:1', main_name=True, translate_name=True)
    first = service.make(korean, Options(model='large-v3-turbo'), translate=job)
    second = service.make(code, Options(model='large-v3-turbo'), translate=job)
    assert translator.asked == ['clip.wav']              # 이미 한국어인 이름은 묻지도 않는다
    assert first.renamed_from is None and second.renamed_from is None
    assert korean.exists() and code.exists() and (tmp_path / 'clip.srt').exists()


def test_a_subtitle_next_to_its_video_is_not_taken_for_a_script(tmp_path):
    from services.tools.subtitles import match_scripts
    (tmp_path / 'a.wav').write_bytes(b''); (tmp_path / 'b.wav').write_bytes(b'')
    (tmp_path / 'a.srt').write_text('x', encoding='utf-8')               # a의 기존 자막
    (tmp_path / 'b.srt').write_text('x', encoding='utf-8'); (tmp_path / 'b.txt').write_text('x', encoding='utf-8')
    found = match_scripts([tmp_path / 'a.wav', tmp_path / 'b.wav'], tmp_path, tmp_path)
    assert found == {tmp_path / 'a.wav': None, tmp_path / 'b.wav': tmp_path / 'b.txt'}
