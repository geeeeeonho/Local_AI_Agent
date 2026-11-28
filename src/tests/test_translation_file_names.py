"""'파일 이름도 번역' 옵션.

이름 속 번호·코드는 지키고 낱말만 옮기며, 정한 이름은 기록해 두어 중단 후 다시 실행해도 같은 결과
경로로 이어진다. 이름을 옮기지 못하면 예전 규칙('이름.ko.txt')을 쓰고, 원본은 절대 덮어쓰지 않는다.
"""
import json

from services.tools.translation import (TranslationService, safe_file_stem, translate_file_names,
                                        unique_path)

NAMES = {'霧の旧市街': '안개의 구시가지', '港の収集品': '항구의 수집품', '駅前広場': '역 앞 광장'}


def _rename(text, names):
    for source, value in names.items():
        text = text.replace(source, value)
    return text


class Model:
    """이름 요청과 본문 요청에 모두 답하는 모의 모델. names를 바꾸면 다음 이름 답이 달라진다."""
    def __init__(self, names=None, broken=False):
        self.names, self.broken = dict(names or NAMES), broken
        self.name_requests = []

    def chat(self, name, messages, **kwargs):
        system, user = messages[0]['content'], messages[-1]['content']
        try:
            data = json.loads(user)
        except ValueError:
            return '{}'
        if system.startswith('Translate each file name'):
            self.name_requests.append(data)
            rows = [{'id': item['id'],
                     'name': 'x' if self.broken else _rename(item['name'], self.names)}
                    for item in data['files']]
            return json.dumps({'names': rows}, ensure_ascii=False)
        if not isinstance(data, dict) or 'items' not in data:
            return '{}'
        rows = [{'id': item['id'], 'text': '안녕하세요'} for item in data['items']]
        return json.dumps({'translations': rows, 'new_terms': {}}, ensure_ascii=False)


class Inference:
    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return ['m:1']


def _service(tmp_path, model):
    return TranslationService(Inference(), lambda _: model, checkpoint_dir=tmp_path / 'cp', protector=None)


def test_names_are_made_safe_for_every_file_system():
    assert safe_file_stem('a/b:c*d?') == 'a_b_c_d_'
    assert safe_file_stem('  끝에 점.  ') == '끝에 점'
    assert safe_file_stem('CON') == 'CON_'
    assert len(safe_file_stem('가' * 300)) == 120


def test_codes_and_numbers_in_a_name_are_kept_and_bad_answers_are_dropped():
    model = Model()
    names = translate_file_names(model, 'm:1', ['Map014_霧の旧市街', 'v2_01', 'Items_港の収集品'], '한국어',
                                 terms={'港の収集品': '항구의 수집품', '無関係': '무관'})
    assert names['Map014_霧の旧市街'] == 'Map014_안개의 구시가지'
    assert names['v2_01'] is None                      # 코드·번호뿐인 이름은 묻지도 않는다
    assert names['Items_港の収集品'].endswith('항구의 수집품')
    sent = model.name_requests[0]
    assert len(sent['files']) == 2                     # 한 요청에 묶어 보낸다
    assert sent['terminology'] == {'港の収集品': '항구의 수집품'}
    assert 'Map014' not in json.dumps(sent['files'], ensure_ascii=False)   # 코드는 보호 토큰으로 보낸다
    # 보호 토큰을 잃은 답은 쓰지 않는다
    assert translate_file_names(Model(broken=True), 'm:1', ['Map014_霧の旧市街'], '한국어') == {
        'Map014_霧の旧市街': None}


def test_unique_path_numbers_taken_names(tmp_path):
    (tmp_path / '이름.txt').write_text('x', encoding='utf-8')
    assert unique_path(tmp_path / '이름.txt').name == '이름 (2).txt'
    assert unique_path(tmp_path / '새.txt', avoid=(tmp_path / '새.txt',)).name == '새 (2).txt'


def test_single_file_gets_its_translated_name_and_keeps_it_on_resume(tmp_path):
    source = tmp_path / 'Map014_霧の旧市街.txt'
    source.write_text('こんにちは\n', encoding='utf-8')
    model = Model()
    result = _service(tmp_path, model).translate_file(source, model='m:1', target='한국어',
                                                      translate_name=True, source_language='日本語')
    assert result.output.name == 'Map014_안개의 구시가지.txt'
    assert source.read_text(encoding='utf-8') == 'こんにちは\n'          # 원본은 그대로
    # 다시 정해도 처음 정한 이름을 쓴다(모델 답이 달라져도 이어하기 경로가 바뀌지 않는다)
    result.output.unlink()
    other = Model(names={'霧の旧市街': '전혀 다른 이름'})
    again = _service(tmp_path, other).translate_file(source, model='m:1', target='한국어',
                                                     translate_name=True, source_language='日本語')
    assert again.output.name == 'Map014_안개의 구시가지.txt'
    assert other.name_requests == []


def test_a_name_that_cannot_be_translated_falls_back_to_the_language_code(tmp_path):
    source = tmp_path / '霧.txt'
    source.write_text('こんにちは\n', encoding='utf-8')
    result = _service(tmp_path, Model(broken=True)).translate_file(
        source, model='m:1', target='한국어', translate_name=True, source_language='日本語')
    assert result.output.name == '霧.ko.txt'


def test_folder_translates_file_names_only_and_splits_clashing_names(tmp_path):
    folder = tmp_path / '資料'
    (folder / '章').mkdir(parents=True)
    for name in ('駅前広場.txt', '駅前広場 .txt', 'data_01.txt'):
        (folder / '章' / name).write_text('こんにちは\n', encoding='utf-8')
    model = Model()
    service = _service(tmp_path, model)
    result = service.translate_folder(folder, model='m:1', target='한국어', translate_name=True,
                                      source_language='日本語', shared_context=False)
    out = result.output
    names = sorted(path.name for path in (out / '章').iterdir())
    assert (out / '章').is_dir()                                         # 하위 폴더 이름은 그대로
    assert names == ['data_01.txt', '역 앞 광장 (2).txt', '역 앞 광장.txt']
    # 다시 실행하면 같은 이름으로 찾아 모두 건너뛴다
    again = service.translate_folder(folder, model='m:1', target='한국어', translate_name=True,
                                     source_language='日本語', shared_context=False)
    assert not again.translated and len(again.skipped) == 3
