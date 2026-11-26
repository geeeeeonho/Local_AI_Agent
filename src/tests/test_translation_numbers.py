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
