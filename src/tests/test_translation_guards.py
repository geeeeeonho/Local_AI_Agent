"""비밀번호·코드형 낱말, 자막 시각, 앞자리 0, 모델이 덧붙인 줄바꿈에 대한 방어.

실측(영어 영화 자막, 두 모델 공통): 'The password is X7-Delta.'를 'X7-델타'로 음역해도 검사를 통과했다.
비교 실행에서 가장 많은 재요청 사유는 'Map026 Event 001'을 'Event\\n001'로 나눠 답한 줄이었다
(같은 제목 줄을 네 번까지 다시 요청).
"""
import json

from core.tools.translation import code_changes, prepare, protect
from services.tools.languages import ReviewError, check_output
from services.tools.translation import _join_added_breaks, _units


def _masked(text):
    return sorted(protect(text)[1].values())


def test_code_words_are_kept_but_ordinary_number_words_are_not():
    assert _masked("The password is X7-Delta. Don't write it down.") == ['X7-Delta']
    assert _masked('Use R2-D2, then hunter2.') == ['R2-D2', 'hunter2']
    assert _masked('Gate B12 and the PS5') == ['B12', 'PS5']
    # 서수·단위·두 글자 약어(분기·용지 크기)는 번역될 수 있다
    assert _masked('the 1st floor, 5km, Q3 and A4 paper') == []
    # 메일·주소·버전 안의 글자는 그 규칙이 통째로 맡는다
    assert _masked('mail bob2@example.com or https://example.com/x7b') == [
        'bob2@example.com', 'https://example.com/x7b']
    # 음역된 비밀번호는 저장 직전 검사에서도 바뀐 것으로 잡힌다
    assert code_changes('The password is X7-Delta.', '비밀번호는 X7-델타입니다.') != ({}, {})


def _clock_values(source, suffix):
    units, _prefixes, maps = _units(prepare(source, suffix))
    return sorted(value for mapping in maps for value in mapping.values())


def test_subtitle_clock_times_stay_as_written_but_documents_may_convert_them():
    cue = '1\n00:00:36,000 --> 00:00:38,500\nFlight 447 leaves at 6:45 from Gate B12.\n'
    assert _clock_values(cue, '.srt') == ['6:45', 'B12']
    assert _clock_values('Flight 447 leaves at 6:45 from Gate B12.\n', '.txt') == ['B12']
    vtt = 'WEBVTT\n\n00:01.000 --> 00:03.000\nMeet me at 18:30.\n'
    assert _clock_values(vtt, '.vtt') == ['18:30']


def _passes(source, answer):
    try:
        check_output(source, answer, 'English', 'Korean')
        return True
    except ReviewError:
        return False


def test_24_hour_times_may_become_12_hour_only_with_an_afternoon_marker():
    assert _passes('Meet me at 18:30.', '오후 6시 30분에 만나.')
    assert _passes('Meet me at 18:30.', '18시 30분에 만나.')
    assert not _passes('Meet me at 18:30.', '6시 30분에 만나.')       # 오전으로 읽힌다
    assert not _passes('Meet me at 18:30.', '오후 7시 30분에 만나.')
    assert _passes('At 0:15 we leave.', '자정 12시 15분에 떠난다.')


def test_leading_zero_numbers_keep_their_digits():
    assert not _passes('Enter PIN 0451.', 'PIN 451을 입력하세요.')
    assert _passes('Enter PIN 0451.', 'PIN 0451을 입력하세요.')
    assert _passes('Agent 007 is here.', '007 요원이 왔다.')
    # 시각·날짜·소수의 0은 빼고 써도 된다
    assert _passes("It's 6:05 now.", '지금 6시 5분이야.')
    assert _passes('Due 03/05.', '3월 5일 마감.')
    assert _passes('Add 0.5 cups.', '0.5컵을 넣으세요.')


def test_added_line_breaks_are_joined_instead_of_rejected():
    assert _join_added_breaks('===== Map026 Event 001 / 駅前広場 =====',
                              '===== Map026 Event\n001 / 역 앞 광장 =====') == \
        '===== Map026 Event 001 / 역 앞 광장 ====='
    assert _join_added_breaks('猫が好き', '猫が\n好き') == '猫が好き'
    # 원문이 여러 줄이면 손대지 않는다
    assert _join_added_breaks('a\nb', 'x\ny') == 'x\ny'


class Inference:
    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return ['m:1']


class BreakingModel:
    """제목 줄의 보호 토큰 뒤 공백을 줄바꿈으로 바꿔 답하는 모의 모델(실측 응답 '…_0001__\\n001 / 역 앞 광장')."""
    def __init__(self):
        self.requests = 0

    def chat(self, name, messages, **kwargs):
        try:
            data = json.loads(messages[-1]['content'])
        except ValueError:
            return '{}'
        if not isinstance(data, dict) or 'items' not in data:
            return '{}'
        self.requests += 1
        rows = [{'id': item['id'], 'text': item['text'].replace('__ 001', '__\n001').replace('駅前広場', '역 앞 광장')
                 .replace('こんにちは', '안녕하세요')} for item in data['items']]
        return json.dumps({'translations': rows, 'new_terms': {}}, ensure_ascii=False)


def test_a_line_split_by_the_model_is_saved_in_one_request(tmp_path):
    from services.tools.translation import TranslationService
    source = tmp_path / 'map.txt'
    source.write_text('===== Map026 Event 001 / 駅前広場 =====\nこんにちは\n', encoding='utf-8')
    model = BreakingModel()
    service = TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None)
    result = service.translate_file(source, model='m:1', target='한국어', keep_failed=True,
                                    source_language='日本語')
    text = result.output.read_text(encoding='utf-8')
    assert '===== Map026 Event 001 / 역 앞 광장 =====\n안녕하세요\n' == text
    assert result.kept_lines == ()
    assert model.requests == 1
