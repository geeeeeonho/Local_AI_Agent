"""저장 직전 제어 코드·식별자 검사가 한 줄 때문에 파일 전체를 버리지 않는다.

실측(중국어 청문회 대본, 로컬 모델 비교): 원문 'witness_id=LW-19。'를 모델이 'witness_id=LW-19.'로 끝맺자
설정값 패턴이 문장 끝 마침표까지 값으로 삼켜 'LW-19' ≠ 'LW-19.'로 판정했고, 다른 모델은 '科幻'을 'SF'로
옮겨 원문에 없던 라틴 토큰이 생겼다. 두 경우 모두 줄 단위 검증은 통과하고 저장 직전 검사에서만 걸려
파일이 통째로 저장되지 않았다.
"""
import json
import re

from core.tools.translation import code_changes

SOURCE = ('[SYSTEM] hearing_room=04 / access=GRANTED / witness_id=LW-19。门禁没有认出旧证件。\n'
          '体裁：科幻法庭对话脚本。\n'
          '林见微：好的。\n')


def test_sentence_punctuation_is_not_part_of_a_value_url_or_path():
    for before, after in [
        ('witness_id=LW-19。门禁', 'witness_id=LW-19.문이'),
        ('mode=fast：开始', 'mode=fast: 시작'),
        ('请访问 https://example.com/help。', 'https://example.com/help.에 접속하세요'),
        ('请看 https://example.com/a?b=1.', 'https://example.com/a?b=1 참고'),
        ('见 https://example.com/help', 'https://example.com/help에서 확인'),
        ('文件在 ./data/run.log。', './data/run.log.에 있다'),
    ]:
        assert code_changes(before, after, cjk=True) == ({}, {}), before
    # 값 안의 점과 확장자는 그대로 값이다
    assert code_changes('version=1.2.3', 'version=1.2') != ({}, {})
    assert code_changes('./data/run.log', './data/run.txt') != ({}, {})


class Inference:
    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return ['m:1']


class CodeModel:
    """한자를 '번역'으로 바꾸고 문장 끝 '。'를 '.'로 끝맺는 모의 모델. add_latin번째 답까지는
    '科幻'을 'SF'로 옮겨 원문에 없던 라틴 토큰을 만든다."""
    def __init__(self, add_latin=0):
        self.add_latin, self.answers, self.requests = add_latin, 0, []

    def chat(self, name, messages, **kwargs):
        try:
            data = json.loads(messages[-1]['content'])
        except ValueError:
            return '{}'
        if not isinstance(data, dict) or 'items' not in data:
            return '{}'
        self.requests.append(data['items'])
        rows = []
        for item in data['items']:
            text = item['text']
            if '科幻' in text:
                self.answers += 1
                text = text.replace('科幻', 'SF ' if self.answers <= self.add_latin else '공상과학')
            text = re.sub(r'[一-鿿]+', '번역', text).replace('。', '.').replace('：', ': ')
            rows.append({'id': item['id'], 'text': text})
        return json.dumps({'translations': rows, 'new_terms': {}}, ensure_ascii=False)


def _translate(tmp_path, model, keep_failed=True):
    from services.tools.translation import TranslationService
    source = tmp_path / 'hearing.txt'
    source.write_text(SOURCE, encoding='utf-8')
    service = TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None)
    result = service.translate_file(source, model='m:1', target='한국어', keep_failed=keep_failed,
                                    source_language='简体中文')
    return result, result.output.read_text(encoding='utf-8')


def test_value_followed_by_a_translated_full_stop_is_saved(tmp_path):
    result, text = _translate(tmp_path, CodeModel())
    assert 'witness_id=LW-19.' in text and 'hearing_room=04' in text and 'access=GRANTED' in text
    assert result.kept_lines == ()


def test_a_line_that_adds_a_latin_token_is_asked_again_with_the_reason(tmp_path):
    model = CodeModel(add_latin=1)
    result, text = _translate(tmp_path, model)
    assert 'SF' not in text and '공상과학' in text and result.kept_lines == ()
    retry = [item for items in model.requests for item in items if item.get('previous_problem')]
    assert len(retry) == 1 and 'SF' in retry[0]['previous_problem']


def test_only_the_line_that_keeps_breaking_stays_in_the_source_language(tmp_path):
    result, text = _translate(tmp_path, CodeModel(add_latin=99))
    lines = text.split('\n')
    assert lines[1] == SOURCE.split('\n')[1]                 # 그 줄만 원문 유지, 나머지는 저장
    assert 'witness_id=LW-19.' in lines[0] and '번역' in lines[2]
    assert result.kept_lines == (2,)


def test_a_speaker_with_a_qualifier_keeps_its_translated_label():
    """실측: 'MAN (on radio): Unit 12, respond.'을 '남자(무전): …'으로 옮기면 '원문에 없는 이름표'로 반려됐고,
    다시 묻자 모델이 이름표를 빼서 화자 정보가 사라졌다."""
    from services.tools.translation import _misbehaviour
    assert _misbehaviour('MAN (on radio): Unit 12, respond. Over.', '남자(무전): 12호기, 응답하라. 이상.') == ''
    assert _misbehaviour('NURSE (O.S.): Doctor!', '간호사(화면 밖): 선생님!') == ''
    assert _misbehaviour('男（無線）：応答せよ。', '남자(무전): 응답하라.') == ''
    assert 'speaker label' in _misbehaviour('Unit 12, respond. Over.', '남자(무전): 12호기, 응답하라. 이상.')
    assert 'speaker label' in _misbehaviour('Unit 12, respond. Over.', '남자: 12호기, 응답하라. 이상.')


def test_a_protected_token_with_an_extra_underscore_is_rejected():
    """실측: 모델이 '__LOCALAI_KEEP_…_0000__' 끝에 '_'를 하나 더 붙여 복원 뒤 'LW-19_'가 됐다."""
    import pytest
    from services.tools.translation import _validate
    from services.tools.translation_memory import TranslationMemory
    token = '__LOCALAI_KEEP_ab5d7af0_0000__'
    tokens = {token: 'witness_id=LW-19'}
    _validate(token + '。门禁没有认出旧证件。', token + '. 출입 시스템이 낡은 신분증을 인식하지 못했다.',
              TranslationMemory(), tokens)
    for answer in (token + '_. 출입 시스템이 낡은 신분증을 인식하지 못했다.',
                   '_' + token + '. 출입 시스템이 낡은 신분증을 인식하지 못했다.'):
        with pytest.raises(ValueError, match='protected token'):
            _validate(token + '。门禁没有认出旧证件。', answer, TranslationMemory(), tokens)
    # 원문에서부터 '_'가 붙어 있던 토큰은 그대로 받는다
    _validate('id_' + token + '。好。', 'id_' + token + '. 좋다.', TranslationMemory(), tokens)


class NameModel:
    def __init__(self):
        self.asked = []

    def chat(self, name, messages, **kwargs):
        self.asked.append(json.loads(messages[-1]['content'])['names'])
        return json.dumps({'names': {'林见微': '린젠웨이'}}, ensure_ascii=False)


def test_a_speaker_name_learned_in_the_wrong_script_is_translated_again():
    """실측: 모델이 용어를 '林见微 → Lin Jianwei'로 익히자 줄 검수는 그 용어를 거부했지만 이름표에는
    그대로 들어가, 저장 직전 검사가 'Lin'·'Jianwei'를 원문에 없던 라틴 단어로 보고 파일 전체를 막았다."""
    from services.tools.translation import _translate_names
    from services.tools.translation_memory import TranslationMemory
    memory = TranslationMemory(terms={'林见微': 'Lin Jianwei', '赫连澈': '혁련철'})
    memory.source_language, memory.target = '简体中文', 'Korean'
    model = NameModel()
    names = _translate_names(model, 'm:1', ['林见微', '赫连澈'], memory, '한국어')
    assert names == {'林见微': '린젠웨이', '赫连澈': '혁련철'}
    assert model.asked == [['林见微']]                       # 쓸 수 있는 기억 용어는 다시 묻지 않는다
    assert memory.terms['林见微'] == '린젠웨이'
