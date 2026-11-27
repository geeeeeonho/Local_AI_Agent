"""번역 테스트 데이터셋(일본어 TXT 5 · 일본어 JSON 7 · 중국어 장문 2, 창작 합성 자료) 폴더 회귀 테스트.

폴더 전체를 '한 작품으로' 번역하다가 중간에 Ollama가 멈추고, 다시 실행해 이어서 끝낸다.
가짜 모델은 이전 보고서의 실수를 첫 답에서 저지르고(메타데이터 섞기, \\ → /, 토큰 누락, 화자 이름표,
다른 언어 단어), 보이는 %1은 항상 %s로 바꾸며, 용어집에 없는 이름은 30% 확률로 다르게 옮긴다(리코 → 리스코).
기준: 제어 코드·변수·식별자·라틴 토큰 손상 0, JSON 구조·비번역 필드 변경 0, 줄 수·LF·BOM 유지,
오염 0, 같은 이름은 폴더 전체에서 한 가지 표기.
"""
import json
import random
import re
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from core.tools.translation import CJK_LATIN
from services.tools.translation import TranslationService

DATASET = Path(__file__).parent / 'fixtures' / 'translation_dataset'
KANA = dict(zip('アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワンガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ',
                '아이우에오카키쿠케코사시스세소타치츠테토나니누네노하히후헤호마미무메모야유요라리루레로와응가기구게고자지즈제조다지즈데도바비부베보파피푸페포'))
NAME = re.compile(r'[\u30a1-\u30fa\u30fc]{2,}')
CODES = re.compile(r'\\+[A-Za-z]+(?:\[[^\]]*\])?|\\[.|!<>^{}$]|%\d+|%[-+ #0]*\d*\.\d+[a-z]|\$\{\w+\}|\{\w+\}'
                   r'|%%\w+%%|\[[^\[\]\s]*(?:_\d+|\.[a-z]\w*)[^\[\]\s]*\]|\[[A-Z][A-Z0-9_ -]*\]')
TEXT_COMMANDS = {401, 405, 102, 402, 101}


def korean_name(name):
    return ''.join(KANA.get(char, '') for char in name) or '이름'


class Inference:
    def ensure_ready(self): return 'http://127.0.0.1:11434'
    def local_models(self): return ['m:1']


class CarelessModel:
    def __init__(self, stop_at=None):
        self.random, self.seen, self.calls, self.stop_at = random.Random(11), set(), 0, stop_at

    def korean(self, text, terms, learned):
        for key, value in sorted(terms.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(key, value)
        def name(match):
            value = korean_name(match.group())
            if self.random.random() < .3:
                value = value[0] + '스' + value[1:]
            learned.setdefault(match.group(), value)
            return value
        text = NAME.sub(name, text)
        text = re.sub(r'%\d', '%s', text)             # 보이는 RPG Maker 인자 %1을 printf %s로 바꿔 버리는 모델
        return re.sub(r'[\u3040-\u30ff\u4e00-\u9fff]+', '번역', text)

    def chat(self, model, messages, temperature=.2, **options):
        system, prompt = messages[0]['content'], messages[-1]['content']
        if system.startswith('You prepare'):
            return json.dumps({'summary': '', 'terms': {}, 'speakers': {}})
        if system.startswith('Summarize'):
            return json.dumps({'summary': 'story'})
        if system.startswith('Translate these speaker names'):
            return json.dumps({'names': {n: korean_name(n) if NAME.search(n) else '화자'
                                         for n in json.loads(prompt)['names']}}, ensure_ascii=False)
        if prompt.startswith('TRANSLATE_SINGLE:\n'):
            return json.dumps({'translation': self.korean(prompt.split('\n', 1)[1], {}, {})}, ensure_ascii=False)
        self.calls += 1
        if self.calls == self.stop_at:
            raise RuntimeError('Ollama stopped')
        data = json.loads(prompt)
        terms = json.loads(data['document_memory'])['terminology']
        key = tuple(item['text'] for item in data['items'])
        careless = key not in self.seen
        self.seen.add(key)
        learned, rows = {}, []
        for number, item in enumerate(data['items']):
            text = self.korean(item['text'], terms, learned)
            if careless and number % 3 == 0:
                text = [lambda t: 'id: %d, text: %s' % (item['id'], t),
                        lambda t: re.sub(r'__LOCALAI_KEEP_\w+?__', '/V[23]', t, count=1),
                        lambda t: re.sub(r'__LOCALAI_KEEP_\w+?__', '', t, count=1),
                        lambda t: '화자: ' + t,
                        lambda t: t + ' nearby'][(number // 3) % 5](text)
            rows.append({'id': item['id'], 'text': text})
        return json.dumps({'translations': rows, 'new_terms': learned}, ensure_ascii=False)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def skeleton(value):
    if isinstance(value, dict):
        return {key: skeleton(item) for key, item in value.items()}
    if isinstance(value, list):
        return [skeleton(item) for item in value]
    return '<text>' if isinstance(value, str) else value


def non_text(value, found):
    """번역하면 안 되는 값: 텍스트 명령이 아닌 이벤트 명령, 101의 앞 네 값, note·meta·식별자 키."""
    if isinstance(value, dict):
        if 'code' in value and 'parameters' in value:
            found.append(value['parameters'] if value['code'] not in TEXT_COMMANDS else
                         value['parameters'][:4] if value['code'] == 101 else None)
        for key, item in value.items():
            if key in ('note', 'meta', 'questId', 'format', 'locale', 'id'):
                found.append(item)
            non_text(item, found)
    elif isinstance(value, list):
        for item in value:
            non_text(item, found)
    return found


class DatasetFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name) / 'dataset'
        shutil.copytree(DATASET, folder)
        model = CarelessModel(stop_at=40)
        service = TranslationService(Inference(), lambda _: model, checkpoint_dir=Path(cls.tmp.name) / 'cp',
                                     protector=None)
        with _expect(RuntimeError):            # 40번째 요청에서 Ollama가 멈춘다
            service.translate_folder(folder, model='m:1', keep_failed=True)
        model.stop_at = None
        cls.result = service.translate_folder(folder, model='m:1', keep_failed=True)
        cls.pairs = [(path, cls.result.output / path.relative_to(folder)) for path in sorted(folder.glob('0*/*'))]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_file_is_translated_after_resume(self):
        self.assertEqual(self.result.failed, ())
        self.assertEqual(len(self.pairs), 14)
        self.assertTrue(all(target.exists() for _, target in self.pairs))

    def test_codes_identifiers_and_latin_tokens_are_untouched(self):
        for source, target in self.pairs:
            before, after = source.read_text(encoding='utf-8'), target.read_text(encoding='utf-8')
            if source.suffix == '.json':
                before = '\n'.join(strings(json.loads(before)))
                after = '\n'.join(strings(json.loads(after)))
            self.assertEqual(Counter(CODES.findall(after)), Counter(CODES.findall(before)), source.name)
            self.assertEqual(Counter(CJK_LATIN.findall(after)), Counter(CJK_LATIN.findall(before)), source.name)
            self.assertEqual(after.count('/'), before.count('/'), source.name)
            self.assertNotRegex(after, r'id:\s*\d|"text"\s*:|nearby|화자: ', source.name)

    def test_json_structure_and_non_text_fields_are_unchanged(self):
        for source, target in self.pairs:
            if source.suffix != '.json':
                continue
            old, new = json.loads(source.read_text(encoding='utf-8')), json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(skeleton(new), skeleton(old), source.name)
            self.assertEqual(non_text(new, []), non_text(old, []), source.name)

    def test_text_files_keep_lines_lf_and_no_bom(self):
        for source, target in self.pairs:
            if source.suffix == '.txt':
                raw = target.read_bytes()
                self.assertEqual(raw.count(b'\n'), source.read_bytes().count(b'\n'), source.name)
                self.assertFalse(raw.startswith(b'\xef\xbb\xbf') or b'\r' in raw, source.name)

    def test_names_use_one_form_across_the_folder(self):
        text = '\n'.join(target.read_text(encoding='utf-8') for _, target in self.pairs)
        names = {name for source, _ in self.pairs for name in NAME.findall(source.read_text(encoding='utf-8'))}
        variants = {name: korean_name(name)[0] + '스' + korean_name(name)[1:] for name in names}
        # 다른 표기 안에 들어 있는 글자는 기본 표기로 세지 않는다('스이치'는 '스스이치'·'다스이치'의 일부).
        without_variants = re.sub('|'.join(map(re.escape, sorted(set(variants.values()), key=len, reverse=True))),
                                  '\0', text)
        forms = {}
        for name in names:
            base = korean_name(name)
            if len(base) < 3:            # 한두 음절은 다른 이름의 일부와 겹쳐 셀 수 없다
                continue
            forms[name] = (without_variants.count(base), text.count(variants[name]))
        mixed = {name: count for name, count in forms.items() if all(count)}
        self.assertEqual(mixed, {})


class _expect:
    def __init__(self, error): self.error = error
    def __enter__(self): return self
    def __exit__(self, kind, value, trace):
        if kind is None or not issubclass(kind, self.error):
            raise AssertionError('the first run should stop midway')
        return True


if __name__ == '__main__':
    unittest.main()
