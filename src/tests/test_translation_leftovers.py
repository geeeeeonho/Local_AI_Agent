"""번역문에 원어·다른 언어 조각이 남거나 원문에 없는 문장을 지어 붙였을 때의 처리.

예전에는 줄 전체를 다시 번역시키고, 그래도 남으면 그 번역을 그대로 저장하고 '검토 필요'로만 알렸다.
모델은 같은 줄을 다시 물어도 같은 조각을 남기는 일이 많아, 남은 조각만 골라 고친다.
"""
import json

from services.tools.languages import leftover_fragments
from services.tools.translation import TranslationService, _sentences

SOURCE = 'こんにちは\n霧の街へ行こう\n明日また会おう\nはい\n'


class Inference:
    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return ['m:1']


class LeakyModel:
    """'霧の街'을 계속 원어로 남기는('霧の街로 가자') 모델. 조각 요청에는 fixes로 답한다.
    extra=True면 'はい'에 원문에 없는 문장을 덧붙인다(다시 물으면 바르게 답한다)."""
    TEXT = {'こんにちは': '안녕하세요', '霧の街へ行こう': '霧の街로 가자', '明日また会おう': '내일 또 만나자',
            'はい': '네'}

    def __init__(self, fix='안개의 거리', extra=False, english=False):
        self.fix, self.extra, self.english = fix, extra, english
        self.fix_requests, self.batches, self.asked_hai = [], 0, 0

    def chat(self, name, messages, **kwargs):
        system, user = messages[0]['content'], messages[-1]['content']
        if user.startswith('TRANSLATE_SINGLE:'):
            text = user.split('\n', 1)[1]
            answer = '내일 또 meet 하자' if self.english and text == '明日また会おう' else self.TEXT.get(text, text)
            return json.dumps({'translation': answer}, ensure_ascii=False)
        try:
            data = json.loads(user)
        except ValueError:
            return '{}'
        if 'fragments left' in system:
            self.fix_requests.append(data)
            rows = [{'id': item['id'], 'fragment': fragment, 'translation': self.fix}
                    for item in data['lines'] for fragment in item['fragments']]
            return json.dumps({'fixes': rows}, ensure_ascii=False)
        if not isinstance(data, dict) or 'items' not in data:
            return '{}'
        self.batches += 1
        rows = []
        for item in data['items']:
            text = self.TEXT.get(item['text'], item['text'])
            if self.english and item['text'] == '明日また会おう':
                text = '내일 또 meet 하자'
            if self.extra and item['text'] == 'はい':
                self.asked_hai += 1
                if self.asked_hai == 1:
                    text = '네, 알겠습니다. 그럼 내일 봐요. 조심해서 가세요.'
            rows.append({'id': item['id'], 'text': text})
        return json.dumps({'translations': rows, 'new_terms': {}}, ensure_ascii=False)


def _translate(tmp_path, model, source=SOURCE):
    path = tmp_path / 'scene.txt'
    path.write_text(source, encoding='utf-8')
    service = TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None)
    result = service.translate_file(path, model='m:1', target='한국어', keep_failed=True,
                                    source_language='日本語')
    return result, result.output.read_text(encoding='utf-8')


def test_leftover_fragments_lists_every_untranslated_piece_in_order():
    found = leftover_fragments('明日', '霧の街로 가자, 내일 meet', 'Japanese', 'Korean')
    assert [(kind, fragment) for kind, fragment, _ in found] == [('script', '霧の街'), ('foreign', 'meet')]
    assert leftover_fragments('Go home', '집에 가자', 'English', 'Korean') == []
    assert leftover_fragments('Go home now', '집에 home 가자', 'English', 'Korean')[0][:2] == ('source', 'home')


def test_a_fragment_the_model_keeps_leaving_is_fixed_by_itself(tmp_path):
    model = LeakyModel()
    result, text = _translate(tmp_path, model)
    assert '안개의 거리로 가자' in text and '霧' not in text
    assert result.review_lines == () and result.kept_lines == ()
    # 조각만 물었다: 그 줄과 남은 조각 하나
    asked = [item for request in model.fix_requests for item in request['lines']]
    assert [item['fragments'] for item in asked] == [['霧の街']]


def test_a_word_from_another_language_is_fixed_the_same_way(tmp_path):
    model = LeakyModel(english=True, fix='만나')
    _result, text = _translate(tmp_path, model, source='明日また会おう\n')
    assert 'meet' not in text and '내일 또 만나 하자' in text


def test_a_bad_fix_is_not_used_and_the_line_stays_for_review(tmp_path):
    model = LeakyModel(fix='霧の街')                      # 고친다면서 또 원어로 답한다
    result, text = _translate(tmp_path, model)
    assert '霧の街로 가자' in text                        # 검사를 통과하지 못한 수정은 쓰지 않는다
    assert result.review_lines                           # 그리고 검토 목록에 남긴다


def test_extra_sentences_added_to_a_short_line_are_sent_back(tmp_path):
    source = '\n'.join(['こんにちは', '霧の街へ行こう', '明日また会おう'] * 3 + ['はい']) + '\n'
    model = LeakyModel(extra=True)
    _result, text = _translate(tmp_path, model, source=source)
    assert '조심해서 가세요' not in text and text.rstrip().endswith('네')
    assert model.asked_hai >= 2


def test_sentence_count_ignores_closing_quotes():
    assert _sentences('「行くぞ！」') == 1
    assert _sentences('네, 알겠습니다. 그럼 내일 봐요.') == 2
    assert _sentences('はい') == 1
