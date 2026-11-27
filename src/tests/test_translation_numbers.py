"""번역 검증의 숫자 비교: 같은 값을 다르게 쓴 정상 번역은 통과시키고, 값이 바뀐 번역만 거절한다.

실사용 보고: 자막 번역에서 숫자가 든 줄(첫 줄)이 번역되지 않았다. 검증이 숫자를 글자로만 비교해
'300,000 → 30만', '2 → 두'처럼 정상인 번역을 계속 거절했고, [실패한 구간은 원문 유지] 때문에 그 줄이
원문으로 남았다. 아래 모의 모델은 실제 모델이 흔히 쓰는 표기를 그대로 흉내 낸다.
"""
import json
from pathlib import Path

import pytest

from services.tools.languages import ReviewError, check_output, quantities

KEPT_VALUE = [
    ('English', 'Korean', 'The city has 300,000 people.', '이 도시에는 30만 명이 산다.'),
    ('English', 'Korean', 'It cost 1.5 million dollars.', '150만 달러가 들었다.'),
    ('English', 'Korean', 'It grew 5 centimeters.', '5센티미터 자랐다.'),
    ('English', 'Korean', 'This is my 1st time.', '이번이 처음이다.'),
    ('English', 'Korean', 'Open 24/7.', '연중무휴로 엽니다.'),
    ('English', 'Korean', 'We need 2 or 3 more.', '두세 개가 더 필요해.'),
    ('English', 'Korean', 'Two of them, 2 people.', '그들 중 두 명.'),
    ('English', 'Simplified Chinese', 'About 12,000 visitors.', '大约1.2万名游客。'),
    ('English', 'Japanese', 'About 12,000 visitors.', '約1万2000人の訪問者。'),
    ('Korean', 'English', '3억 5천만 원', '350 million won'),
    ('Korean', 'English', '30만 명이 왔다.', '300,000 people came.'),
    ('Japanese', 'Korean', '身長は170センチです。', '키는 170센티입니다.'),
    ('English', 'Korean', 'Call me at 10:30.', '10시 30분에 전화해.'),
    ('English', 'German', 'It costs 1,500.50 euros.', 'Es kostet 1.500,50 Euro.'),
]
CHANGED_VALUE = [
    ('English', 'Korean', 'The city has 300,000 people.', '이 도시에는 3만 명이 산다.'),
    ('English', 'Korean', 'It is 5 inches long.', '길이가 12.7센티미터다.'),       # 단위 환산은 오역
    ('English', 'Korean', 'We need 2 more.', '세 개가 더 필요해.'),
    ('English', 'Korean', 'Room 404 is closed.', '방이 닫혀 있다.'),
    ('English', 'Korean', 'Back in the 1990s.', '1980년대에.'),
]


@pytest.mark.parametrize('source,target,text,answer', KEPT_VALUE)
def test_the_same_value_written_differently_is_accepted(source, target, text, answer):
    check_output(text, answer, source, target)


@pytest.mark.parametrize('source,target,text,answer', CHANGED_VALUE)
def test_a_changed_or_dropped_value_is_still_rejected(source, target, text, answer):
    with pytest.raises(ReviewError, match='Number changed or dropped'):
        check_output(text, answer, source, target)


def test_quantities_apply_scales_and_join_compound_numbers():
    values = {value for _digits, value in quantities('3억 5천만 원, 1万2000人, 1.5 million, 2.5k')}
    assert {3e8, 5e7, 3.5e8, 12000, 1.5e6, 2500} <= values


class NumberStyleModel:
    """숫자를 한국어 방식으로 쓰는 모의 번역 모델(실제 모델의 흔한 표기)."""
    table = {'The city has 300,000 people.': '이 도시에는 30만 명이 산다.',
             'This is my 1st time here.': '여기는 처음이야.',
             'We need 2 or 3 more chairs.': '의자가 두세 개 더 필요해.',
             'The shop is open 24/7.': '그 가게는 연중무휴야.',
             'See you tomorrow.': '내일 봐.'}

    def chat(self, name, messages, **kwargs):
        data = json.loads(messages[-1]['content'])
        if 'items' not in data:
            return '{}'
        return json.dumps({'translations': [{'id': row['id'], 'text': self.table.get(row['text'], row['text'])}
                                            for row in data['items']], 'new_terms': {}}, ensure_ascii=False)


def test_a_subtitle_with_numbers_is_translated_on_every_line(tmp_path):
    from core.tools.subtitles import Cue, parse, to_srt
    from services.tools.translation import TranslationService

    class Inference:
        def ensure_ready(self):
            return 'http://127.0.0.1:11434'

        def local_models(self):
            return ['m:1']
    lines = list(NumberStyleModel.table)
    source = tmp_path / 'talk.srt'
    source.write_text(to_srt([Cue(i * 2000, i * 2000 + 1500, (text,)) for i, text in enumerate(lines)]),
                      encoding='utf-8')
    service = TranslationService(Inference(), lambda _: NumberStyleModel(), checkpoint_dir=tmp_path / 'cp',
                                 protector=None)
    result = service.translate_file(source, model='m:1', target='한국어', kind='subtitle', keep_failed=True,
                                    source_language='English')
    assert result.kept_lines == ()                                   # 원문으로 남은 줄 없음
    texts = [cue.text for cue in parse(result.output.read_text(encoding='utf-8-sig'))]
    assert texts == [NumberStyleModel.table[line] for line in lines]


# ── 모델이 번역 대신 엉뚱한 것을 내놓을 때 ──
from services.tools.translation import _clean_answer, _validate  # noqa: E402
from services.tools.translation_memory import TranslationMemory  # noqa: E402


def _memory(source='English', target='Korean'):
    memory = TranslationMemory()
    memory.target, memory.source_language = target, source
    return memory


ODD = [
    ('Get the hell out of here!', '죄송하지만 이 내용은 번역해 드릴 수 없습니다.', 'refused'),
    ('I can\'t believe it!', "I'm sorry, but I can't help with that request.", 'refused'),
    ('Kill them all.', 'AI 언어 모델로서 폭력적인 내용은 번역할 수 없습니다.', 'refused'),
    ('Hello there.', '안녕하세요. (참고: 이 문장은 가벼운 인사말입니다.)', 'note'),
    ('He is a total couch potato.', '그는 완전 소파 감자다. (역주: 게으른 사람)', 'note'),
    ('Yes, I see.', '응, 알겠어. 알겠어. 알겠어. 알겠어. 알겠어. 알겠어. 알겠어. 알겠어.', 'repeats'),
    ('Where are you going?', '...', 'no text'),
    ('Where are you going?', 'N/A', 'placeholder'),
    ('Good morning.', '번역: 좋은 아침.', 'label'),
    ('========== [SCENE 16] Night ==========', '화자: ========== [SCENE 16] 밤 ==========', 'speaker label'),
]
NORMAL = [
    ('Get the hell out of here!', '당장 여기서 꺼져!'),                  # 비속어를 순화하지 않은 번역
    ("I'm sorry, I can't help you.", '미안, 도와줄 수 없어.'),           # 사과·거절 대사
    ("I'm sorry, but I can't translate this letter for you.", '미안하지만 이 편지는 번역해 줄 수 없어.'),
    ('No, no, no, no, no!', '아니, 아니, 아니, 아니, 아니!'),            # 실제 반복 발화
    ('Hahahahahahaha!', '하하하하하하하!'),
    ('Wow...', '와...'),
    ('Note: keep the door closed.', '참고: 문을 닫아 두세요.'),         # 원문에 있는 '참고:'
    ('答：明天出发。', 'Answer: We leave tomorrow.'),                    # 원문 머리말의 정상 번역
    ('刻印は「製造二七年」だが、同じ番号の記録は図書館では「廃止二七年」となっている。',
     '각인은 「제조 27년」이지만, 같은 번호의 기록은 도서관에서는 「폐지 27년」으로 되어 있다.'),
]


@pytest.mark.parametrize('source,answer,reason', ODD)
def test_odd_answers_are_rejected(source, answer, reason):
    with pytest.raises(ValueError, match=reason):
        _validate(source, answer, _memory(), {})


@pytest.mark.parametrize('source,answer', NORMAL)
def test_faithful_answers_that_look_odd_are_kept(source, answer):
    source_language = ('Simplified Chinese' if source.startswith('答') else
                       'Japanese' if source.startswith('刻印') else 'English')
    target = 'English' if source.startswith('答') else 'Korean'
    assert _validate(source, answer, _memory(source_language, target), {}) == answer


def test_reasoning_is_stripped_but_labels_are_left_for_validation():
    assert _clean_answer('See you.', '<think>음</think>내일 봐.') == '내일 봐.'
    assert _clean_answer('答：明天出发。', 'Answer: We leave tomorrow.') == 'Answer: We leave tomorrow.'


class RefusingModel:
    """대사에 비속어가 있으면 처음 refusals번은 거절하고, 그다음에는 번역하는 모의 모델."""
    def __init__(self, refusals):
        self.refusals = refusals

    def chat(self, name, messages, **kwargs):
        content = messages[-1]['content']
        if content.startswith('TRANSLATE_SINGLE:'):
            text = content.split('\n', 1)[1]
            reply = '죄송하지만 이 내용은 번역해 드릴 수 없습니다.' if 'hell' in text and self.refusals > 0 else '당장 꺼져!'
            self.refusals -= 1
            return json.dumps({'translation': reply}, ensure_ascii=False)
        data = json.loads(content)
        if 'items' not in data:
            return '{}'
        out = []
        for row in data['items']:
            if 'hell' in row['text'] and self.refusals > 0:
                out.append('죄송하지만 이 내용은 번역해 드릴 수 없습니다.')
            elif 'hell' in row['text']:
                out.append('당장 꺼져!')
            else:
                out.append('내일 봐.')
        if any('hell' in row['text'] for row in data['items']):
            self.refusals -= 1
        return json.dumps({'translations': [{'id': row['id'], 'text': text}
                                            for row, text in zip(data['items'], out)], 'new_terms': {}},
                          ensure_ascii=False)


@pytest.mark.parametrize('refusals,expected,kept', [(1, '당장 꺼져!', ()),
                                                     (99, 'Get the hell out!', (3,))])
def test_a_refusal_never_replaces_the_line(tmp_path, refusals, expected, kept):
    """한 번 거절하면 다시 물어 번역을 받고, 계속 거절하면 거절 문구 대신 원문을 남기고 줄을 알린다."""
    from core.tools.subtitles import Cue, parse, to_srt
    from services.tools.translation import TranslationService

    class Inference:
        def ensure_ready(self):
            return 'http://127.0.0.1:11434'

        def local_models(self):
            return ['m:1']
    source = tmp_path / 'scene.srt'
    source.write_text(to_srt([Cue(0, 1500, ('Get the hell out!',)), Cue(2000, 3500, ('See you tomorrow.',))]),
                      encoding='utf-8')
    service = TranslationService(Inference(), lambda _: RefusingModel(refusals), checkpoint_dir=tmp_path / 'cp',
                                 protector=None)
    result = service.translate_file(source, model='m:1', target='한국어', kind='subtitle', keep_failed=True,
                                    source_language='English')
    texts = [cue.text for cue in parse(result.output.read_text(encoding='utf-8-sig'))]
    assert texts == [expected, '내일 봐.'] and result.kept_lines == kept
    assert '번역해 드릴 수 없습니다' not in result.output.read_text(encoding='utf-8-sig')


def test_a_list_of_quoted_terms_is_not_mistaken_for_a_loop():
    """실측 오탐: 「」로 나뉜 구절마다 같은 말이 나오는 번역(모의 모델 출력)을 루프로 보았다."""
    source = '刻印は「製造二七年」だが、同じ番号の記録は図書館では「廃止二七年」となっている。'
    assert _validate(source, '번역「번역」번역、번역「번역」번역。', _memory('Japanese', 'Korean'), {})


class OneBadLineModel:
    """첫 답에서 한 줄만 거절 문구를 내놓는 모의 모델. 요청마다 받은 줄을 기록한다."""
    good = {'Good morning.': '좋은 아침.', 'Get the hell out!': '당장 꺼져!', 'See you tomorrow.': '내일 봐.'}

    def __init__(self):
        self.requests = []

    def chat(self, name, messages, **kwargs):
        data = json.loads(messages[-1]['content'])
        if 'items' not in data:
            return '{}'
        self.requests.append(data['items'])
        first = len(self.requests) == 1
        rows = [{'id': row['id'], 'text': '죄송하지만 이 내용은 번역해 드릴 수 없습니다.'
                 if first and 'hell' in row['text'] else self.good[row['text']]} for row in data['items']]
        return json.dumps({'translations': rows, 'new_terms': {}}, ensure_ascii=False)


def test_only_the_rejected_line_is_asked_again_with_the_reason(tmp_path):
    """한 줄이 검증에 실패해도 통과한 줄은 다시 번역하지 않는다(요청·생성량 절약). 다시 묻는 줄에는 반려 사유."""
    from core.tools.subtitles import Cue, parse, to_srt
    from services.tools.translation import TranslationService

    class Inference:
        def ensure_ready(self):
            return 'http://127.0.0.1:11434'

        def local_models(self):
            return ['m:1']
    source = tmp_path / 'scene.srt'
    source.write_text(to_srt([Cue(i * 2000, i * 2000 + 1500, (text,)) for i, text in enumerate(OneBadLineModel.good)]),
                      encoding='utf-8')
    model = OneBadLineModel()
    service = TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None)
    result = service.translate_file(source, model='m:1', target='한국어', kind='subtitle', keep_failed=True,
                                    source_language='English')
    assert [cue.text for cue in parse(result.output.read_text(encoding='utf-8-sig'))] == list(OneBadLineModel.good.values())
    assert len(model.requests) == 2 and len(model.requests[0]) == 3
    retry, = model.requests[1]
    assert retry['text'] == 'Get the hell out!' and 'refused' in retry['previous_problem']
