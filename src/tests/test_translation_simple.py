"""번역기 회귀 테스트 — 가급적 아주 간단하게 유지한다.

규칙: 테스트 하나에 동작 하나, 몇 줄짜리 입력, 가짜 모델만 사용(네트워크·실제 Ollama 없음).
복잡한 시나리오가 필요하면 테스트를 늘리기보다 쪼갠다.
"""
import io
import json
import re
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


class StructureTests(unittest.TestCase):
    """줄바꿈·코드·변수 보존 — 한 줄짜리 예로 간단하게."""

    def masked(self, text):
        from core.tools.translation import protect, PROTECTED_TOKEN
        return PROTECTED_TOKEN.sub('▢', protect(text)[0])

    def test_i18n_variables_are_hidden_from_the_model(self):
        for text in ('Hi {name}', 'Hi {{name}}', 'Saved %s in %1$s', 'Hi %(user)s', 'Hi ${user.name}',
                     'Hi %{count}', 'The :attribute field', 'Click <0>here</0>', '@:common.save now',
                     'Use [[username]]', 'File {0} of {1}', 'Press <b>Save</b>', 'Tom &amp; Jerry'):
            self.assertNotRegex(self.masked(text), r'[{}%$:@\[<&]', text)

    def test_icu_keywords_are_hidden_but_messages_are_not(self):
        masked = self.masked('{n, plural, one {# file} other {# files}}')
        self.assertNotIn('plural', masked)
        self.assertNotIn('other', masked)
        self.assertIn('files', masked)

    def test_markdown_reference_label_and_footnote_are_hidden(self):
        self.assertEqual(texts('[docs]: https://example.com\nText[^1] here.\n', '.md'),
                         ['[docs]: https://example.com', 'Text[^1] here.'])
        self.assertNotIn('docs', self.masked('[docs]: https://example.com'))
        self.assertNotIn('^1', self.masked('Text[^1] here.'))

    def test_shell_and_json_lines_in_txt_are_not_translated(self):
        self.assertEqual(texts('Run it.\ncd ~/app && ./run.sh --port 80\n"name": "demo",\n', '.txt'),
                         ['Run it.'])

    def test_lost_bold_marks_are_caught(self):
        model = Model(lambda items: json.dumps({'translations': ['설정을 여세요.' for _ in items]}))
        with self.assertRaises(ValueError):
            translate('Open **Settings** now.\n', model)

    def test_line_breaks_and_blank_lines_are_kept(self):
        model = Model(lambda items: json.dumps({'translations': ['번역 %d' % i for i, _ in enumerate(items)]}))
        out = translate('First line.\r\n\r\n\tSecond line.   \r\n', model).text
        self.assertEqual(out, '번역 0\r\n\r\n\t번역 1   \r\n')


class FolderTests(unittest.TestCase):
    def test_folder_is_translated_into_a_sibling_folder_with_same_names(self):
        model = Model(lambda items: json.dumps({'translations': ['번역 문장' for _ in items]}))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'docs'
            (src / 'sub').mkdir(parents=True)
            (src / 'a.txt').write_text('Hello world.\n', encoding='utf-8')
            (src / 'sub' / 'b.md').write_text('# Hello title\n', encoding='utf-8')
            (src / 'logo.png').write_bytes(b'png')
            (src / 'bad.json').write_text('{oops', encoding='utf-8')
            service = TranslationService(Inference(), lambda _: model,
                                         checkpoint_dir=Path(tmp) / 'cp', protector=None)
            result = service.translate_folder(src, model='m:1')
            self.assertEqual(result.output.name, 'docs.ko')
            self.assertEqual({p.relative_to(result.output).as_posix() for p in result.output.rglob('*') if p.is_file()},
                             {'a.txt', 'sub/b.md', 'logo.png'})
            self.assertEqual([rel for rel, _ in result.failed], ['bad.json'])   # 하나 실패해도 계속
            again = service.translate_folder(src, model='m:1')                   # 다시 실행하면 건너뜀
            self.assertEqual(len(again.translated), 0)


class FolderContextTests(unittest.TestCase):
    """폴더 전체를 한 작품으로: 메모리 1번 생성, 1→2→10 순서, 앞 파일 줄거리 전달."""

    def run_folder(self, shared):
        calls = []
        class Spy:
            def chat(self, name, messages, temperature=.2):
                system, prompt = messages[0]['content'], messages[-1]['content']
                if system.startswith('You prepare'):
                    calls.append('plan')
                    return json.dumps({'summary': 's', 'terms': {'佐伯': '사에키'}}, ensure_ascii=False)
                if system.startswith('Summarize'):
                    return json.dumps({'summary': 'after ' + json.loads(prompt)['recent_translation'][-1]['source']})
                data = json.loads(prompt)
                calls.append((data.get('current_file'), json.loads(data['document_memory'])['story_so_far']))
                return json.dumps({'translations': ['사에키 문장' for _ in data['items']]}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'novel'
            folder.mkdir()
            for name, word in (('ch10', 'じゅう'), ('ch2', 'に'), ('ch1', 'いち')):
                (folder / (name + '.txt')).write_text('佐伯が来た' + word + '。\n', encoding='utf-8')
            TranslationService(Inference(), lambda _: Spy(), checkpoint_dir=Path(tmp) / 'cp',
                               protector=None).translate_folder(folder, model='m:1', shared_context=shared)
        return calls

    def test_shared_context_plans_once_and_passes_the_story_on(self):
        calls = self.run_folder(True)
        self.assertEqual(calls.count('plan'), 1)
        batches = [c for c in calls if c != 'plan']
        self.assertEqual([f for f, _ in batches], ['ch1.txt', 'ch2.txt', 'ch10.txt'])
        self.assertIn('いち', batches[1][1])     # 2장은 1장 끝까지의 줄거리를 받는다

    def test_individual_mode_plans_each_file(self):
        self.assertEqual(self.run_folder(False).count('plan'), 3)


class FolderFlowTests(unittest.TestCase):
    def test_analyze_then_translate_uses_the_cache(self):
        # 화면 흐름 그대로: 폴더 분석 → 번역 시작(분석 결과 재사용)
        model = Model(lambda items: json.dumps({'translations': ['번역 문장' for _ in items]}))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'docs'
            src.mkdir()
            (src / 'a.txt').write_text('Hello world.\n', encoding='utf-8')
            service = TranslationService(Inference(), lambda _: model, checkpoint_dir=Path(tmp) / 'cp', protector=None)
            rows, _ = service.inspect_folder(src)
            result = service.translate_folder(src, model='m:1')
            self.assertEqual((rows[0][2], len(result.translated), result.failed), (1, 1, ()))

    def test_default_output_gets_a_number_when_taken(self):
        from services.tools.translation import default_output
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.txt'
            path.write_text('x')
            (Path(tmp) / 'a.ko.txt').write_text('old')
            self.assertEqual(default_output(path, '한국어').name, 'a.ko (2).txt')

    def test_model_recommendation(self):
        from services.tools.translation import recommend_model
        names = ['qwen2.5-coder:7b', 'gemma4:12b', 'nomic-embed-text']
        self.assertEqual(recommend_model(names), 'gemma4:12b')
        self.assertEqual(recommend_model(names, last='qwen2.5-coder:7b'), 'qwen2.5-coder:7b')


class OutputSafetyTests(unittest.TestCase):
    """보고서 사례: 메타데이터 섞임·제어 코드·시스템 태그·화자명 중복·게임 스크립트 — 간단하게."""

    def test_game_control_codes_and_system_tags_are_protected(self):
        from core.tools.translation import protect, PROTECTED_TOKEN
        masked = PROTECTED_TOKEN.sub('▢', protect('\\N[2]は\\V[23]個！\\.\\| [SYSTEM] PENDING_REVIEW')[0])
        self.assertEqual(masked, '▢は▢個！▢▢ ▢ ▢')

    def test_metadata_echo_is_rejected_even_at_the_last_retry(self):
        model = Model(lambda items: json.dumps({'translations': ['id: 0, text: 번역' for _ in items]}))
        result = translate('佐伯が来た。\n', model, keep_failed=True)
        self.assertNotIn('id:', result.text)            # 끝까지 실패하면 원문 유지, 오염은 저장하지 않음
        self.assertEqual(result.kept_lines, (1,))

    def test_slash_damage_is_rejected(self):
        from core.tools.translation import protect
        from services.tools.translation import _validate
        from services.tools.translation_memory import TranslationMemory
        masked, tokens = protect('ゴールドを手に入れた')
        with self.assertRaises(ValueError):
            _validate(masked, '/V[23]골드를 얻었다', TranslationMemory(), tokens)

    def test_added_speaker_label_is_removed(self):
        model = Model(lambda items: json.dumps({'translations': ['앨리스: 기다려!' for _ in items]}))
        self.assertEqual(translate('Alice: Wait!\nBob: No.\n', model).text.splitlines()[0], 'Alice: 기다려!')

    def test_rpg_maker_scripts_and_plugin_commands_are_not_translated(self):
        src = json.dumps({'list': [{'code': 401, 'parameters': ['こんにちは']},
                                   {'code': 355, 'parameters': ["$gameVariables.setValue(1,'テスト')"]},
                                   {'code': 356, 'parameters': ['ShowQuest 試練']},
                                   {'code': 101, 'parameters': ['Actor1', 0, 0, 2, 'ハロルド']}],
                          'note': '<shop:ポーション>'}, ensure_ascii=False)
        self.assertEqual(texts(src, '.json'), ['こんにちは', 'ハロルド'])

    def test_items_are_matched_by_id_even_when_reordered(self):
        def reply(items):
            data = [{'id': 0, 'text': items[0]}] if len(items) == 1 else []
            return json.dumps({'translations': data or [{'id': i, 'text': t} for i, t in enumerate(items)]})
        class Reordered(Model):
            def chat(self, name, messages, temperature=.2):
                data = json.loads(messages[-1]['content'])
                if 'items' not in data:
                    return '{}'
                rows = [{'id': r['id'], 'text': r['text'].replace('Hello', '안녕')} for r in data['items']]
                return json.dumps({'translations': list(reversed(rows))}, ensure_ascii=False)
        out = translate(''.join('Hello %d.\n' % i for i in range(30)), Reordered()).text
        self.assertEqual(out.splitlines()[25], '안녕 25.')

    def test_learned_terms_are_reused_in_later_batches(self):
        seen = []
        class Learner(Model):
            def chat(self, name, messages, temperature=.2):
                data = json.loads(messages[-1]['content'])
                if 'items' not in data:
                    return '{}'
                seen.append(json.loads(data['document_memory'])['terminology'])
                rows = [{'id': r['id'], 'text': r['text'].replace('佐伯', '사에키').replace('が来た', '가 왔다')}
                        for r in data['items']]
                return json.dumps({'translations': rows, 'new_terms': {'佐伯': '사에키'}}, ensure_ascii=False)
        # 같은 문장은 한 번만 번역하므로 서로 다른 45줄로 여러 번의 요청이 일어나게 한다.
        translate(''.join('佐伯が来た%d。\n' % i for i in range(45)), Learner())
        self.assertEqual(seen[-1], {'佐伯': '사에키'})


class IdentifierTests(unittest.TestCase):
    """식별자 보호와 용어집 번역의 경계 — 간단하게."""

    def test_user_glossary_translates_an_identifier_shaped_name(self):
        seen = []
        class Spy(Model):
            def chat(self, name, messages, temperature=.2):
                data = json.loads(messages[-1]['content'])
                if 'items' in data:
                    seen.extend(item['text'] for item in data['items'])
                    return json.dumps({'translations': ['루멘 프로젝트 팀.' for _ in data['items']]},
                                      ensure_ascii=False)
                return '{}'
        out = translate('Hello LUMEN_PROJECT team.\n', Spy(), glossary='LUMEN_PROJECT = 루멘 프로젝트')
        self.assertIn('LUMEN_PROJECT', seen[0])          # 보호하지 않고 모델에 보여 준다
        self.assertEqual(out.text, '루멘 프로젝트 팀.\n')

    def test_identifier_in_system_position_stays_protected_even_if_in_planner_terms(self):
        from core.tools.translation import system_context
        self.assertTrue(system_context('状態: PENDING_REVIEW\n', 'PENDING_REVIEW'))
        self.assertTrue(system_context('status=PENDING_REVIEW\n', 'PENDING_REVIEW'))
        self.assertFalse(system_context('Hello the LUMEN_PROJECT team.\n', 'LUMEN_PROJECT'))

    def test_scene_tag_line_and_key_values_are_not_translated(self):
        self.assertEqual(texts('[SCENE 01]\nアリス：行くよ。\n', '.txt'), ['行くよ。'])
        from core.tools.translation import protect, PROTECTED_TOKEN
        masked = PROTECTED_TOKEN.sub('▢', protect('status=PENDING_REVIEW，编号 MK-04。')[0])
        self.assertEqual(masked, '▢，编号 ▢。')       # 전각 쉼표 뒤 중국어는 번역 대상으로 남는다


class FinalReviewTests(unittest.TestCase):
    """같은 문장 재사용 · 마지막 원문 대조 검수(반려→수정→보고) · 구조 문맥 — 간단하게."""

    def test_same_sentence_is_translated_once(self):
        sent = []
        class Counter_(Model):
            def chat(self, name, messages, temperature=.2):
                if messages[-1]['content'].startswith('{'):
                    sent.extend(item['text'] for item in json.loads(messages[-1]['content']).get('items', []))
                return super().chat(name, messages, temperature)
        result = translate('Hello Kim.\nHello Kim.\nHello Lee.\n', Counter_())
        self.assertEqual(sorted(sent), ['Hello Kim.', 'Hello Lee.'])
        self.assertEqual((result.text, result.reused), ('안녕 Kim.\n안녕 Kim.\n안녕 Lee.\n', 1))

    def lines(self, n):
        return ''.join('こんにちは、今日は駅で友達と%d時に会う約束をしています。\n' % i for i in range(n))

    def test_truncated_line_is_rejected_and_retranslated_with_the_reason(self):
        notes = []
        class Truncates(Model):
            def chat(self, name, messages, temperature=.2):
                data = json.loads(messages[-1]['content'])
                if 'items' not in data:
                    return '{}'
                rows = []
                for item in data['items']:
                    full = '안녕하세요 오늘은 역에서 친구와 %s시에 만나기로 했어요.' % re.sub(r'\D', '', item['text'])
                    if 'previous_problem' in item:
                        notes.append(item['previous_problem'])
                    elif item['text'].startswith('こんにちは、今日は駅で友達と3時'):
                        full = '안녕 3'                    # 줄 단위 검증은 통과하지만 원문 대비 너무 짧다
                    rows.append({'id': item['id'], 'text': full})
                return json.dumps({'translations': rows}, ensure_ascii=False)
        result = translate(self.lines(12), Truncates())
        self.assertEqual(result.audit_fixed, 1)
        self.assertIn('too short', notes[0])
        self.assertNotIn('안녕 3\n', result.text)

    def test_problem_that_cannot_be_fixed_is_reported(self):
        class Stubborn(Model):
            def chat(self, name, messages, temperature=.2):
                data = json.loads(messages[-1]['content'])
                if 'items' not in data:
                    return '{}'
                return json.dumps({'translations': [
                    {'id': i['id'], 'text': '안녕 3' if i['text'].startswith('こんにちは、今日は駅で友達と3時') else
                     '안녕하세요 오늘은 역에서 친구와 %s시에 만나기로 했어요.' % re.sub(r'\D', '', i['text'])}
                    for i in data['items']]}, ensure_ascii=False)
        result = translate(self.lines(12), Stubborn())
        self.assertEqual([line for line, _ in result.audit], [4])

    def test_rpg_dialogue_gets_speaker_and_item_text_gets_its_name(self):
        from services.tools.translation import _units, _speaker, _section
        doc = prepare(json.dumps({'list': [{'code': 101, 'parameters': ['', 0, 0, 2, 'アオイ']},
                                           {'code': 401, 'parameters': ['ようこそ。']}],
                                  'items': [{'name': '潮霧草', 'description': '海岸の薬草。'}]},
                                 ensure_ascii=False), '.json')
        units = {u.text: u for u in _units(doc)[0]}
        self.assertEqual(_speaker(doc, units['ようこそ。']), 'アオイ')
        self.assertEqual(_section(doc, units['海岸の薬草。']), '潮霧草')

    def test_block_header_is_the_section_for_extracted_text(self):
        from services.tools.translation import _units, _section
        doc = prepare('# 説明\n===== [BTL_001] 廃機関区 =====\n戦闘開始！\n', '.txt')
        unit = [u for u in _units(doc)[0] if u.text == '戦闘開始！'][0]
        self.assertIn('廃機関区', _section(doc, unit))

    def test_greek_symbols_in_the_source_are_not_leftovers(self):
        from services.tools.languages import check_output
        check_output('采用α分支，σ为0.004。', 'α 분기를 쓰고 σ는 0.004이다.', 'Simplified Chinese', 'Korean')
