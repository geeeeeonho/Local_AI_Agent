"""번역기 회귀 테스트 — 가급적 아주 간단하게 유지한다.

규칙: 테스트 하나에 동작 하나, 몇 줄짜리 입력, 가짜 모델만 사용(네트워크·실제 Ollama 없음).
복잡한 시나리오가 필요하면 테스트를 늘리기보다 쪼갠다.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from core.tools.translation import prepare, read_source
from integrations.ollama.client import OllamaClient
from services.tools.translation import TranslationService, parse_glossary, source_profile
from services.tools.translation_memory import Checkpoint, repeated_entities


def texts(source, suffix):
    return [s.text for s in prepare(source, suffix).segments]


class Inference:
    def ensure_ready(self): return 'http://127.0.0.1:11434'
    def local_models(self): return ['m:1']


class Model:
    """원문 'Hello'를 '안녕'으로 바꿔 돌려주는 가짜 모델. reply로 응답 모양을 바꾼다."""
    def __init__(self, reply=None):
        self.reply = reply or (lambda items: json.dumps({'translations': items}, ensure_ascii=False))

    def chat(self, name, messages, temperature=.2):
        prompt = messages[-1]['content']
        if prompt.startswith('TRANSLATE_SINGLE:\n'):
            return self.reply([prompt.split('\n', 1)[1].replace('Hello', '안녕')])
        data = json.loads(prompt)
        if 'items' not in data:
            return '{}'
        return self.reply([row['text'].replace('Hello', '안녕') for row in data['items']])


def translate(text, model, **options):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'a.txt'
        path.write_text(text, encoding='utf-8')
        service = TranslationService(Inference(), lambda _: model,
                                     checkpoint_dir=Path(tmp) / 'cp', protector=None)
        return service.translate_file(path, model='m:1', **options)


class ParsingTests(unittest.TestCase):
    def test_subtitle_lines_are_not_mistaken_for_code(self):
        srt = '1\n00:00:01,000 --> 00:00:02,000\nif you want it\nHello (laughs)\n'
        self.assertEqual(texts(srt, '.srt'), ['if you want it', 'Hello (laughs)'])

    def test_prose_is_not_mistaken_for_code(self):
        self.assertEqual(texts('return to sender, she wrote.\n', '.txt'),
                         ['return to sender, she wrote.'])

    def test_code_line_is_still_skipped(self):
        self.assertEqual(texts('Install it.\npip install requests\n', '.txt'), ['Install it.'])

    def test_markdown_heading_and_nested_list(self):
        md = '# Title\n```\nx = 1\n```\n- item\n    - nested item\n'
        self.assertEqual(texts(md, '.md'), ['Title', 'item', 'nested item'])

    def test_json_identifier_values_are_kept(self):
        src = json.dumps({'title': 'Hello', 'status': 'active', 'userId': 'Hello', 'label': 'dark-mode'})
        self.assertEqual(texts(src, '.json'), ['Hello'])

    def test_note_label_is_not_a_speaker(self):
        self.assertEqual(prepare('Note: one.\nWarning: two.\n', '.txt').detected, 'general')

    def test_full_width_colon_speaker(self):
        self.assertEqual(prepare('アリス：こんにちは\nボブ：やあ\n', '.txt').detected, 'script')

    def test_non_korean_legacy_encoding_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jp.txt'
            path.write_bytes('こんにちは世界'.encode('shift_jis'))
            with self.assertRaises(ValueError):
                read_source(path)


class ModelReplyTests(unittest.TestCase):
    def test_think_block_is_ignored(self):
        model = Model(lambda items: '<think>\n...\n</think>\n' + json.dumps({'translations': items}))
        self.assertEqual(translate('Hello world.\n', model).text, '안녕 world.\n')

    def test_label_in_single_reply_is_removed(self):
        model = Model(lambda items: 'not json' if len(items) > 1 or 'world' not in items[0]
                      else 'Translation: ' + items[0])
        self.assertEqual(translate('Hello world.\n', model).text, '안녕 world.\n')

    def test_failed_unit_keeps_original_when_asked(self):
        model = Model(lambda items: json.dumps({'translations': ['' for _ in items]}))
        result = translate('Hello world.\n', model, keep_failed=True)
        self.assertEqual((result.text, result.kept_lines), ('Hello world.\n', (1,)))

    def test_timeout_is_retried(self):
        calls = []
        class Slow(Model):
            def chat(self, name, messages, temperature=.2):
                calls.append(1)
                if len(calls) == 2:          # 첫 번역 요청만 시간 초과
                    raise TimeoutError('slow')
                return super().chat(name, messages, temperature)
        self.assertEqual(translate('Hello world.\n', Slow()).text, '안녕 world.\n')


class JapaneseTests(unittest.TestCase):
    def test_japanese_names_become_glossary_candidates(self):
        doc = prepare('佐伯が来た。\n佐伯は笑った。\n田中さんも。\n', '.txt')
        self.assertTrue({'佐伯', '田中'} <= set(repeated_entities(doc)))

    def test_source_language_and_classical_text(self):
        self.assertEqual(source_profile(prepare('今日は雨が降っている。\n', '.txt')), ('Japanese', False))
        self.assertEqual(source_profile(prepare('いとをかし。\n昔、男ありけり。\n', '.txt'))[1], True)

    def test_prompt_carries_japanese_guide(self):
        seen = []
        class Spy(Model):
            def chat(self, name, messages, temperature=.2):
                seen.append(messages[0]['content'])
                return super().chat(name, messages, temperature)
        translate('佐伯が戻ってきた。\n', Spy(lambda items: json.dumps({'translations': ['사에키가 돌아왔다.']})))
        self.assertTrue(any('Japanese→Korean' in system for system in seen))

    def test_glossary_text_format(self):
        self.assertEqual(parse_glossary('# 주석\n佐伯 = 사에키\n記述 → 서술\n'),
                         {'佐伯': '사에키', '記述': '서술'})

    def test_user_glossary_is_enforced(self):
        wrong = Model(lambda items: json.dumps({'translations': ['사케가 돌아왔다.' for _ in items]}))
        with self.assertRaisesRegex(ValueError, 'glossary'):
            translate('佐伯が戻ってきた。\n', wrong, glossary='佐伯 = 사에키')
        right = Model(lambda items: json.dumps({'translations': ['사에키가 돌아왔다.' for _ in items]}))
        self.assertIn('사에키', translate('佐伯が戻ってきた。\n', right, glossary='佐伯 = 사에키').text)


class ProgressTests(unittest.TestCase):
    def test_progress_reaches_total(self):
        seen = []
        translate(''.join('Hello %d.\n' % i for i in range(25)), Model(),
                  progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (25, 25))


class ClientTests(unittest.TestCase):
    def client(self, lines):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): self.close()
        class Opener:
            def open(self, request, timeout):
                self.payload = json.loads(request.data)
                return Response(b''.join(json.dumps(x).encode() + b'\n' for x in lines))
        opener = Opener()
        return OllamaClient(opener=opener, timeout=5), opener

    def test_stream_joins_content_and_disables_thinking(self):
        client, opener = self.client([{'message': {'content': 'Hel', 'thinking': 'x'}},
                                      {'message': {'content': 'lo'}, 'done': True}])
        self.assertEqual(client.chat('m:1', []), 'Hello')
        self.assertEqual((opener.payload['stream'], opener.payload['think']), (True, False))

    def test_length_limit_is_an_error(self):
        client, _ = self.client([{'message': {'content': 'Hel'}, 'done': True, 'done_reason': 'length'}])
        with self.assertRaises(ValueError):
            client.chat('m:1', [])


class CheckpointTests(unittest.TestCase):
    def test_saved_text_is_sealed(self):
        class Flip:
            def protect(self, data): return data[::-1]
            def unprotect(self, data): return data[::-1]
        with tempfile.TemporaryDirectory() as tmp:
            point = Checkpoint(Path(tmp), 'k', protector=Flip())
            point.save_units([(0, '비밀 문장')])
            self.assertEqual(point.completed(), {0: '비밀 문장'})
            raw = point.connection.execute('SELECT text FROM units').fetchone()[0]
            point.close()
            self.assertNotIn('비밀', raw)


if __name__ == '__main__':
    unittest.main()


class OtherLanguageTests(unittest.TestCase):
    """언어쌍이 바뀌어도 같은 종류의 실수를 잡는지 — 한 줄짜리 예로 간단하게."""

    def caught(self, source, answer, src, tgt):
        from services.tools.languages import check_output, ReviewError
        try:
            check_output(source, answer, src, tgt)
            return False
        except ReviewError:
            return True

    def test_source_language_detection(self):
        from services.tools.languages import detect_language
        samples = {'Russian': 'Я не знаю, где мой телефон.', 'Thai': 'ฉันไม่รู้ว่าโทรศัพท์อยู่ที่ไหน',
                   'French': 'Je ne sais pas où est mon téléphone.', 'German': 'Ich weiß nicht, wo mein Telefon ist.',
                   'Vietnamese': 'Tôi không biết điện thoại của tôi ở đâu.', 'Korean': '전화기가 어디 있는지 몰라.'}
        for name, text in samples.items():
            self.assertEqual(detect_language(text), name)

    def test_untranslated_line_between_latin_languages(self):
        text = 'Please close the door before you leave.'
        self.assertTrue(self.caught(text, text, 'English', 'Spanish'))

    def test_partial_clause_left_in_source_language(self):
        self.assertTrue(self.caught('Der Zug fährt um 19:30 ab.', 'Le train part à 19h30 der Zug.', 'German', 'French'))

    def test_cyrillic_left_in_korean(self):
        self.assertTrue(self.caught('Где мой телефон?', '내 телефон 어디 있어?', 'Russian', 'Korean'))

    def test_simplified_character_in_traditional_output(self):
        self.assertTrue(self.caught('这很好。', '这很好。', 'Simplified Chinese', 'Traditional Chinese'))

    def test_changed_number(self):
        self.assertTrue(self.caught('The train leaves at 19:30.', 'Der Zug fährt um 18:30 ab.', 'English', 'German'))

    def test_correct_translations_pass(self):
        self.assertFalse(self.caught('The hotel has a small bar.', 'Das Hotel hat eine kleine Bar.', 'English', 'German'))
        self.assertFalse(self.caught('Set max_tokens in config.yaml.', 'config.yaml에서 max_tokens를 설정하세요.',
                                     'English', 'Korean'))

    def test_same_source_and_target_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'same'):
            translate('こんにちは。\n', Model(), target='日本語')

    def test_prompt_names_the_language_pair(self):
        seen = []
        class Spy(Model):
            def chat(self, name, messages, temperature=.2):
                seen.append(messages[0]['content'])
                return super().chat(name, messages, temperature)
        translate('Bonjour tout le monde, je suis là.\n', Spy(lambda items: json.dumps({'translations': ['Hallo zusammen, ich bin da.']})),
                  target='Deutsch', source_language='Français')
        self.assertTrue(any('Translate from French into German' in system for system in seen))
