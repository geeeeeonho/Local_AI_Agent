"""테스트 보고서(일본어 TXT·RPG Maker JSON·UI JSON·중국어 장문) 회귀 테스트.

가짜 모델이 보고서에서 확인된 실수를 그대로 저지른다(첫 답에서만, 다시 물으면 바르게 답함):
'id: 0, text:' 섞기, 제어 코드 '\\' → '/', 보호 토큰 빠뜨리기, 화자 이름표 덧붙이기, 다른 언어 단어 섞기.
또 프롬프트의 용어집에 없는 이름은 다르게 옮긴다(佐伯 → 사케). 중간에 한 번 멈췄다가 이어서 번역한다.
기준: 메타데이터·'/' 삽입 0, 제어 코드·식별자 손상 0, JSON 구조·비번역 필드 변경 0, 재개 후 용어 일관성 유지.
"""
import json
import re
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from services.tools.translation import TranslationService

FIXTURES = Path(__file__).parent / 'fixtures' / 'translation'
RIGHT = {'佐伯': '사에키', 'ミア': '미아', '李明': '리밍'}
WRONG = {'佐伯': '사케', 'ミア': '미야', '李明': '이명'}
STUBBORN = ('準備', 'ゴールド')     # 모델이 몇 번을 물어도 'id:'를 섞는 문장
VISIBLE_TAGS = {'[SYSTEM]': '[시스템]', 'SCENE': '장면', 'REPORT': '보고', 'PENDING_REVIEW': '검토_대기',
                'archive_session': '보관_세션', 'status': '상태'}
CODES = re.compile(r'\\[A-Za-z]+(?:\[\d+\])?|\\[.|!]|\[[A-Z][A-Z0-9 _-]*\]|[A-Z]+(?:_[A-Z]+)+|[A-Z]+-\d+'
                   r'|\w+=[A-Z0-9_-]+|\{\w+\}|%s|<[^>]+>')


class Inference:
    def ensure_ready(self): return 'http://127.0.0.1:11434'
    def local_models(self): return ['m:1']


class Stop(RuntimeError):
    pass


class CarelessModel:
    def __init__(self, *, learn=True, stop_after=None):
        self.learn, self.stop_after, self.calls, self.seen = learn, stop_after, 0, set()

    def korean(self, text, terms):
        # 처음 실행: 스스로 정한 번역(RIGHT)을 쓰고 new_terms로 알린다.
        # 재개 실행: 프롬프트 용어집에 없는 이름은 다르게 옮긴다(WRONG) → 학습 용어가 저장되지 않았다면 드러난다.
        for name in RIGHT:
            text = text.replace(name, terms.get(name) or (RIGHT[name] if self.learn else WRONG[name]))
        for tag, korean in VISIBLE_TAGS.items():        # 보이는 시스템 태그·식별자는 번역해 버리는 모델
            text = text.replace(tag, korean)
        return re.sub(r'[\u3040-\u30ff\u4e00-\u9fff]+', '번역', text)

    def stubborn(self, source, number, text):
        """몇 번을 다시 물어도 반복하는 실수: 특정 문장에는 항상 'id:'를 섞고, \\는 항상 /로 쓴다."""
        if any(word in source for word in STUBBORN):
            text = 'id: %d, text: %s' % (number, text)
        return text.replace('\\', '/')

    def chat(self, name, messages, temperature=.2, **options):
        system, prompt = messages[0]['content'], messages[-1]['content']
        if system.startswith('You prepare'):
            return json.dumps({'summary': '', 'terms': {}, 'speakers': {}})
        if system.startswith('Summarize'):
            return json.dumps({'summary': 'story'})
        if system.startswith('Translate these speaker names'):
            return json.dumps({'names': {n: RIGHT.get(n, '이름') for n in json.loads(prompt)['names']}},
                              ensure_ascii=False)
        if prompt.startswith('TRANSLATE_SINGLE:\n'):
            text = prompt.split('\n', 1)[1]
            return json.dumps({'translation': self.stubborn(text, 0, self.korean(text, {}))}, ensure_ascii=False)
        self.calls += 1
        if self.stop_after and self.calls > self.stop_after:
            raise Stop('Ollama stopped')
        data = json.loads(prompt)
        terms = json.loads(data['document_memory'])['terminology']
        key = tuple(item['text'] for item in data['items'])
        careless = key not in self.seen
        subtle = careless and len(self.seen) % 2 == 1    # 큰 실수 대신 이름만 조용히 다르게 옮기는 요청
        self.seen.add(key)
        rows = []
        for number, item in enumerate(data['items']):
            text = self.stubborn(item['text'], item['id'], self.korean(item['text'], terms))
            if item['speaker']:            # 화자 이름표를 항상 덧붙이는 모델
                text = self.korean(item['speaker'], terms) + ': ' + text
            if subtle:
                for name in RIGHT:
                    text = text.replace(terms.get(name) or RIGHT[name], WRONG[name])
            elif careless:
                text = [lambda t: 'id: %d, text: %s' % (item['id'], t),
                        lambda t: re.sub(r'__LOCALAI_KEEP_\w+?__', '/V[23]', t, count=1),
                        lambda t: re.sub(r'__LOCALAI_KEEP_\w+?__', '', t, count=1),
                        lambda t: (item['speaker'] or '앨리스') + ': ' + t,
                        lambda t: t + ' nearby'][number % 5](text)
            rows.append({'id': item['id'], 'text': text})
        reply = {'translations': rows}
        if self.learn:
            reply['new_terms'] = {n: RIGHT[n] for n in RIGHT if any(n in i['text'] for i in data['items'])}
        return json.dumps(reply, ensure_ascii=False)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class ReportRegressionTests(unittest.TestCase):
    def translate(self, name, *, interrupt=True):
        """중간에 멈췄다가 이어서 번역한다. 재개 때 모델은 새 용어를 알려 주지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            shutil.copy(FIXTURES / name, path)
            def service(model):
                return TranslationService(Inference(), lambda _: model, checkpoint_dir=Path(tmp) / 'cp',
                                          protector=None)
            if interrupt:                 # 전체의 1/3쯤 끝났을 때 사용자가 취소
                done = {'n': 0, 'total': 1}
                def progress(n, total):
                    done.update(n=n, total=total)
                with self.assertRaises(InterruptedError):
                    service(CarelessModel()).translate_file(
                        path, model='m:1', keep_failed=True, progress=progress,
                        cancelled=lambda: done['n'] * 3 >= done['total'] > 1)
            result = service(CarelessModel(learn=not interrupt)).translate_file(path, model='m:1',
                                                                                 keep_failed=True)
            if interrupt:
                self.assertGreater(result.resumed_units, 0)
            source = path.read_text(encoding='utf-8')
            # 원문으로 남는 줄은 모델이 끝까지 오염시킨 문장뿐이어야 한다(과도한 보호·거부로 번역이 빠지면 실패).
            stubborn = {number for number, line in enumerate(source.splitlines(), 1)
                        if any(word in line for word in STUBBORN)}
            self.assertLessEqual(set(result.kept_lines), stubborn)
            return source, result.text

    def check_common(self, source, output, texts_in, texts_out):
        joined_in, joined_out = '\n'.join(texts_in), '\n'.join(texts_out)
        self.assertNotRegex(joined_out, r'id:\s*\d|"text"\s*:')                       # 메타데이터 0
        self.assertEqual(joined_out.count('/'), joined_in.count('/'))                    # '/' 삽입 0
        self.assertEqual(Counter(CODES.findall(joined_out)), Counter(CODES.findall(joined_in)))  # 코드·식별자 손상 0
        self.assertNotIn('nearby', joined_out)
        for wrong in WRONG.values():                                                     # 재개 후에도 용어 일관
            self.assertNotIn(wrong, joined_out)

    def test_japanese_dialogue_txt(self):
        source, output = self.translate('dialog_ja.txt')
        self.check_common(source, output, [source], [output])
        self.assertEqual(len(output.splitlines()), len(source.splitlines()))
        self.assertIn('사에키：', output)                       # 화자 이름표도 번역(원문 이름 남지 않음)
        self.assertNotIn('佐伯：', output)
        self.assertNotRegex(output, r'사에키：\s*(사에키|앨리스)\s*:')    # 화자명 중복 0

    def test_rpg_maker_map_json(self):
        source, output = self.translate('Map001.json')
        old, new = json.loads(source), json.loads(output)
        self.check_common(source, output, list(strings(old)), list(strings(new)))
        old_list, new_list = old['events'][0]['pages'][0]['list'], new['events'][0]['pages'][0]['list']
        self.assertEqual([e['code'] for e in new_list], [e['code'] for e in old_list])
        for before, after in zip(old_list, new_list):                    # 비번역 명령·필드는 그대로
            if before['code'] not in (401, 102, 101):
                self.assertEqual(after, before)
        self.assertEqual(new_list[0]['parameters'][:4], old_list[0]['parameters'][:4])
        self.assertEqual(new_list[0]['parameters'][4], '사에키')
        self.assertEqual(new['events'][0]['note'], old['events'][0]['note'])

    def test_ui_json(self):
        source, output = self.translate('ui_ja.json', interrupt=False)   # 한 번의 요청으로 끝나는 작은 파일
        old, new = json.loads(source), json.loads(output)
        self.check_common(source, output, list(strings(old)), list(strings(new)))
        self.assertEqual((new['status'], new['archive_session']), ('PENDING_REVIEW', 'MK-04'))
        self.assertEqual(new['messages'].keys(), old['messages'].keys())

    def test_chinese_long_text(self):
        source, output = self.translate('report_zh.txt')
        self.check_common(source, output, [source], [output])
        self.assertEqual(output.count('리밍'), source.count('李明'))


if __name__ == '__main__':
    unittest.main()
