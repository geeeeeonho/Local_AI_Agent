"""End-to-end long-document translation tests with a deterministic local model stub."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.tools.translation import MAX_UNIT_CHARS, prepare, protect, read_source, render, restore, split_masked
from services.tools.translation import TranslationService


class FakeInference:
    def ensure_ready(self):
        return 'http://127.0.0.1:11434'

    def local_models(self):
        return ['mock-local:latest']


class FakeChat:
    def __init__(self, *, break_terms=False, crash_after=None, corrupt_batch=False):
        self.break_terms = break_terms
        self.crash_after = crash_after
        self.corrupt_batch = corrupt_batch
        self.requests = []
        self.translation_calls = 0
        self.planning_calls = 0
        self.rollup_calls = 0

    def chat(self, name, messages, temperature=.2):
        assert name == 'mock-local:latest'
        system = messages[0]['content']
        prompt = messages[-1]['content']
        self.requests.append((system, prompt))
        if system.startswith('You prepare a compact'):
            self.planning_calls += 1
            return json.dumps({'summary':'A technical novel about the LUMENPROJECT crew.',
                               'style':'Consistent polite dialogue.',
                               'terms':{'LUMENPROJECT':'Lumen Translation'},
                               'speakers':{'Alice':'polite'}},ensure_ascii=False)
        if system.startswith('Summarize important facts'):
            self.rollup_calls += 1
            return json.dumps({'summary':'Crew members are still preparing the mission.'})
        self.translation_calls += 1
        if self.crash_after is not None and self.translation_calls >= self.crash_after:
            raise RuntimeError('Simulated local Ollama shutdown')
        if prompt.startswith('TRANSLATE_SINGLE:\n'):
            return self._translate(prompt.split('TRANSLATE_SINGLE:\n',1)[1])
        items = json.loads(prompt)['items']
        if self.corrupt_batch:
            return 'not a valid JSON response'
        return json.dumps({'translations':[self._translate(row['text']) for row in items]},ensure_ascii=False)

    def _translate(self,text):
        value=text.replace('Hello', 'Hi').replace('LUMENPROJECT',
              'Wrong Project' if self.break_terms else 'Lumen Translation')
        return value


class LongTranslationTests(unittest.TestCase):
    def service(self,root,model):
        # 이 파일의 가짜 모델은 실제로 번역하지 않으므로(영어→영어) 언어 검사는 끈다.
        return TranslationService(FakeInference(),lambda _:model,
                                  checkpoint_dir=root/'checkpoint',check_language=False)

    def test_150_line_document_batched_and_remembers_terms(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); path=root/'book.txt'
            content=''.join(f'Alice: Hello the LUMENPROJECT team, chapter {i}.\n' for i in range(150))
            path.write_text(content,encoding='utf-8')
            mock=FakeChat()
            result=self.service(root,mock).translate_file(path,model='mock-local:latest')
            self.assertEqual(result.selected,'script')
            self.assertLess(mock.translation_calls,30)
            self.assertEqual(result.count,150)
            self.assertIn('Lumen Translation',result.text)
            self.assertNotIn('LUMENPROJECT',result.text)
            self.assertIn('LUMENPROJECT',path.read_text(encoding='utf-8'))
            self.assertEqual(result.glossary['LUMENPROJECT'],'Lumen Translation')
            self.assertEqual(result.resumed_units,0)
            self.assertEqual(len(list((root/'checkpoint').glob('*.sqlite3'))),0)
            for system,prompt in mock.requests:
                self.assertLess(len(system)+len(prompt),15000)

    def test_single_very_long_line_split_and_reassembled(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'long.txt'
            content='Hello ' + ('One long sentence. ' * 5300) + 'End.'
            path.write_text(content,encoding='utf-8')
            model=FakeChat()
            result=self.service(root,model).translate_file(path,model='mock-local:latest')
            self.assertGreater(result.count,50)
            self.assertEqual(result.text,content.replace('Hello','Hi'))
            for system,prompt in model.requests:
                if 'items' in prompt:
                    for unit in json.loads(prompt)['items']:
                        self.assertLessEqual(len(unit['text']),MAX_UNIT_CHARS)
            self.assertGreater(model.rollup_calls,0)

    def test_json_large_text_and_nested_structure(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'large.json'
            data={'title':'Hello LUMENPROJECT',
                  'metadata':{'version':5,'source':'console.log("Hello")',
                              'link':'https://example.org'},
                  'text':'Hello '+('First sentence. '*2000),
                  'list':[{'description':'Hello user', 'id':'123'},2,None,True]}
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            client=FakeChat()
            result=self.service(root,client).translate_file(path,model='mock-local:latest')
            output=json.loads(result.text)
            self.assertEqual(output['title'],'Hi Lumen Translation')
            self.assertEqual(output['metadata'],data['metadata'])
            self.assertEqual(output['list'][0]['id'],'123')
            self.assertEqual(output['text'],data['text'].replace('Hello','Hi'))
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),data)

    def test_resume_after_failure_without_retranslating(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'novel.txt'
            path.write_text(''.join(f'Hello story line {i}.\n' for i in range(100)),encoding='utf-8')
            broken=FakeChat(crash_after=3)
            with self.assertRaises(RuntimeError):
                self.service(root,broken).translate_file(path,model='mock-local:latest')
            self.assertFalse((root/'novel.ko.txt').exists())
            self.assertEqual(len(list((root/'checkpoint').glob('*.sqlite3'))),1)
            fixed=FakeChat()
            result=self.service(root,fixed).translate_file(path,model='mock-local:latest')
            self.assertGreater(result.resumed_units,0)
            self.assertEqual(result.count,100)
            self.assertEqual(len(list((root/'checkpoint').glob('*.sqlite3'))),0)
            self.assertIn('Hi story line 99.',result.text)

    def test_glossary_conflict_rejected_then_resumes(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'terms.txt'
            path.write_text('Hello LUMENPROJECT.\nHello LUMENPROJECT again.\n',encoding='utf-8')
            bad=FakeChat(break_terms=True)
            with self.assertRaisesRegex(ValueError,'terminology'):
                self.service(root,bad).translate_file(path,model='mock-local:latest')
            self.assertFalse((root/'terms.ko.txt').exists())
            good=FakeChat()
            result=self.service(root,good).translate_file(path,model='mock-local:latest')
            self.assertIn('Lumen Translation',result.text)

    def test_vtt_blocks_cues_and_markdown_table_are_preserved(self):
        doc=prepare('WEBVTT\n\nSTYLE\n::cue { color: lime; }\n\nNOTE\nDeveloper note.\n\n'
                    'REGION\nid:fred\n\nfirst-cue\n00:00:01.000 --> 00:00:03.000\nHello!\n', '.vtt')
        self.assertEqual([x.text for x in doc.segments],['Hello!'])
        doc=prepare('| Name | Level |\n| --- | --- |\n| Hello | Open |\n','.md')
        self.assertEqual([s.text for s in doc.segments],['Name','Level','Hello','Open'])
        out=render(doc,['title','level','Hi','Start'])
        self.assertIn('| Hi | Start |',out)
        text='Open [the guide](./docs/guide.md) at C:\\MyDocs\\chapter.txt with &nbsp;.'
        masked,restore_map=protect(text)
        self.assertNotIn('./docs/guide.md',masked)
        self.assertNotIn('C:\\MyDocs',masked)
        self.assertNotIn('&nbsp;',masked)
        self.assertEqual(restore(masked,restore_map),text)

    def test_utf16_bom_source_and_cancelled_checkpoint(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'utf16.srt'
            text='1\n00:00:01,000 --> 00:00:02,000\nHello!\n'
            path.write_bytes(text.encode('utf-16'))
            self.assertEqual(read_source(path),(text,'utf-16'))
            model=FakeChat()
            result=self.service(root,model).translate_file(path,model='mock-local:latest')
            self.assertEqual(result.output.read_bytes()[:2],b'\xff\xfe')
            self.assertIn('Hi!',result.text)

    def test_cancelled_progress_does_not_create_output_and_resumes(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'resume.txt'
            path.write_text(''.join(f'Hello line {i}.\n' for i in range(80)),encoding='utf-8')
            progress=[]
            def on_progress(done,total):
                progress.append(done)
            with self.assertRaises(InterruptedError):
                self.service(root,FakeChat()).translate_file(path,model='mock-local:latest',
                    progress=on_progress,cancelled=lambda:bool(progress and progress[-1]>=10))
            self.assertFalse((root/'resume.ko.txt').exists())
            done=self.service(root,FakeChat()).translate_file(path,model='mock-local:latest')
            self.assertGreater(done.resumed_units,0)

    def test_glossary_fallback_when_planning_invalid(self):
        class InvalidPlan(FakeChat):
            def chat(self, name, messages, temperature=.2):
                if messages[0]['content'].startswith('You prepare a compact'):
                    return 'no memory plan available'
                return super().chat(name,messages,temperature)
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'test.txt';path.write_text('Hello world.',encoding='utf-8')
            out=self.service(root,InvalidPlan()).translate_file(path,model='mock-local:latest')
            self.assertIn('Hi world.',out.text)
            self.assertTrue(out.memory_summary)

    def test_oversize_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'huge.txt'
            with path.open('wb') as stream:
                stream.truncate(33*1024*1024)
            with self.assertRaisesRegex(ValueError,'large'):
                read_source(path)
            with self.assertRaises(ValueError):
                prepare('{oops}', '.json')


if __name__ == '__main__':
    unittest.main()

class MoreBoundaryTests(unittest.TestCase):
    def test_large_doc_auto_detection_only_reads_prefix_for_classification(self):
        text = ('Alice: Hello there.\nBob: Hello again.\n' * 20) + ('One ordinary line.\n' * 5000)
        doc = prepare(text,'.txt')
        self.assertEqual(doc.detected,'script')
        self.assertEqual(len(doc.segments),5040)
        with self.assertRaisesRegex(ValueError,'too many'):
            prepare('Hello world.\n'*81000,'.txt')

    def test_file_modified_during_translation_rejected(self):
        class ModifyingClient(FakeChat):
            def __init__(self,path):
                super().__init__()
                self.path = path
            def chat(self,name,messages,temperature=.2):
                result=super().chat(name,messages,temperature)
                if self.translation_calls == 1:
                    self.path.write_text('Modified source',encoding='utf-8')
                return result
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'change.txt'
            path.write_text('Hello original.\n',encoding='utf-8')
            translator=TranslationService(FakeInference(),lambda _:ModifyingClient(path),
                                          checkpoint_dir=root/'checkpoints')
            with self.assertRaisesRegex(RuntimeError,'changed while'):
                translator.translate_file(path,model='mock-local:latest')
            self.assertFalse((root/'change.ko.txt').exists())

    def test_resume_disabled_retranslates_all(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'resumeoff.txt'
            path.write_text(''.join('Hello old line.\n' for _ in range(20)),encoding='utf-8')
            def service(client):
                return TranslationService(FakeInference(),lambda _:client,
                                          checkpoint_dir=root/'state')
            with self.assertRaises(RuntimeError):
                service(FakeChat(crash_after=2)).translate_file(path,model='mock-local:latest')
            model=FakeChat()
            finished=service(model).translate_file(path,model='mock-local:latest',resume=False)
            self.assertEqual(finished.resumed_units,0)
            self.assertEqual(finished.text.count('Hi old line.'),20)

    def test_oversized_glossary_is_bounded(self):
        from services.tools.translation_memory import initial_memory,MAX_GLOSSARY,MAX_SUMMARY
        class TooMany(FakeChat):
            def chat(self,name,messages,temperature=.2):
                if messages[0]['content'].startswith('You prepare a compact'):
                    return json.dumps({'summary':'X'*100000,
                        'terms':{f'ITEM_{i}':'Y'*100 for i in range(150)}})
                return super().chat(name,messages,temperature)
        doc=prepare(' '.join(f'ITEM_{i}' for i in range(150)),'.txt')
        memory=initial_memory(TooMany(),'mock-local:latest',doc,'한국어','natural')
        self.assertLessEqual(len(memory.summary),MAX_SUMMARY)
        self.assertLessEqual(len(memory.terms),MAX_GLOSSARY)
        self.assertTrue(all(len(v)<=65 for v in memory.terms.values()))

    def test_cannot_overwrite_any_existing_destination(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'a.txt';out=root/'a.ko.txt'
            path.write_text('Hello',encoding='utf-8')
            out.write_text('keep',encoding='utf-8')
            translator=TranslationService(FakeInference(),lambda _:FakeChat(),
                                          checkpoint_dir=root/'state')
            result=translator.translate_file(path,model='mock-local:latest')
            self.assertEqual(result.output.name,'a.ko (2).txt')          # 기본 위치가 차 있으면 번호를 붙임
            with self.assertRaises(FileExistsError):
                translator.translate_file(path,model='mock-local:latest',output_path=out)
            self.assertEqual(out.read_text(encoding='utf-8'),'keep')

class AdditionalIntegrityTests(unittest.TestCase):
    def test_embedded_json_newlines_preserved_without_model_changes(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'multiline.json'
            text='Hello world.\n\nSecond paragraph.\nThird line.'
            path.write_text(json.dumps({'text':text,'source':'let x = 1;'}),encoding='utf-8')
            model=FakeChat()
            result=TranslationService(FakeInference(),lambda _:model,
                checkpoint_dir=root/'state').translate_file(path,model='mock-local:latest')
            output=json.loads(result.text)
            self.assertEqual(output['text'],text.replace('Hello','Hi'))
            self.assertEqual(output['source'],'let x = 1;')
            self.assertGreaterEqual(result.count,3)

    def test_model_returning_truncated_text_cannot_publish(self):
        class TruncatedModel(FakeChat):
            def _translate(self,text):
                return 'OK'
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'length.txt'
            path.write_text('Hello with a lot of meaningful content. '*50,encoding='utf-8')
            translator=TranslationService(FakeInference(),lambda _:TruncatedModel(),
                                          checkpoint_dir=root/'state')
            with self.assertRaisesRegex(ValueError,'failed validation'):
                translator.translate_file(path,model='mock-local:latest')
            self.assertFalse((root/'length.ko.txt').exists())