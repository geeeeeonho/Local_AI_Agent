"""번역기 구조 보존과 모델 호출을 네트워크 없이 검증한다."""
import json
import tempfile
import unittest
from pathlib import Path
from core.tools.translation import prepare, protect, restore, render, read_source
from services.tools.translation import TranslationService

class FakeInference:
    def ensure_ready(self): return 'http://127.0.0.1:11434'
    def local_models(self): return ['test-local:1']

class FakeModel:
    def chat(self,name,messages,temperature=.2):
        assert name=='test-local:1'
        system=messages[0]['content']
        prompt=messages[-1]['content']
        if system.startswith('You prepare a compact'):
            return json.dumps({'summary':'A simple scripted conversation.',
                               'style':'Natural speech.','terms':{},'speakers':{}})
        if system.startswith('Summarize important facts'):
            return json.dumps({'summary':'The conversation continues.'})
        if prompt.startswith('TRANSLATE_SINGLE:\n'):
            return prompt.split('TRANSLATE_SINGLE:\n')[-1].replace('Hello','안녕하세요').replace('Open','열어')
        data=json.loads(prompt)
        return json.dumps({'translations':[
            row['text'].replace('Hello','안녕하세요').replace('Open','열어')
            for row in data['items']]},ensure_ascii=False)

class TranslationTests(unittest.TestCase):
    def test_txt_detects_script_and_protects_names(self):
        text='[Scene 1]\r\nAlice: Hello!\r\nBob: Open the door!\r\n[Door opens]\r\n'
        doc=prepare(text,'.txt')
        self.assertEqual(doc.detected,'script')
        self.assertEqual([x.text for x in doc.segments],['Hello!','Open the door!'])
        result=render(doc,['안녕!','문을 열어!'])
        self.assertIn('Alice: 안녕!\r\nBob: 문을 열어!',result)
        self.assertIn('[Door opens]',result)
        self.assertIn('Door opens',[x.text for x in prepare(text,'.txt',stage=True).segments])

    def test_json_structure_and_placeholders(self):
        src='{"title":"Hello","command":"pip install x","arr":["Open",3],"message":"Hi {name}!"}'
        doc=prepare(src,'.json')
        self.assertEqual([x.text for x in doc.segments],['Hello','Open','Hi {name}!'])
        output=render(doc,['안녕','열어','안녕 {name}!'])
        parsed=json.loads(output)
        self.assertEqual(parsed['command'],'pip install x')
        self.assertEqual(parsed['arr'],['열어',3])
        masked,keep=protect('Hi `pip install x` {name}')
        self.assertEqual(restore(masked,keep),'Hi `pip install x` {name}')
        with self.assertRaises(ValueError): restore('missing token',keep)

    def test_markdown_and_subtitle(self):
        doc=prepare('# Title\n```python\nprint("Hello")\n```\nText with `code`\n','.md')
        self.assertEqual([x.text for x in doc.segments],['Title','Text with `code`'])
        sub=prepare('1\n00:00:01,100 --> 00:00:02,100\nHello!\n','.srt')
        self.assertEqual([x.text for x in sub.segments],['Hello!'])

    def test_write_separate_file_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'scene.txt'
            path.write_text('Alice: Hello {name}!\nBob: Open the door.\n',encoding='utf-8')
            service=TranslationService(FakeInference(),lambda endpoint:FakeModel(),
                                       checkpoint_dir=Path(tmp)/'checkpoints')
            done=service.translate_file(path,model='test-local:1')
            self.assertTrue(done.output.exists())
            self.assertIn('Alice: 안녕하세요 {name}!',done.text)
            self.assertIn('Alice: Hello',path.read_text(encoding='utf-8'))
            with self.assertRaises(FileExistsError): service.translate_file(path,model='test-local:1')
            with self.assertRaises(ValueError): service.translate_file(path,model='test-local:1',output_path=path)

    def test_cancel_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'text.txt';path.write_text('Hello user',encoding='utf-8')
            service=TranslationService(FakeInference(),lambda endpoint:FakeModel())
            with self.assertRaises(InterruptedError):
                service.translate_file(path,model='test-local:1',cancelled=lambda:True)
            self.assertFalse((Path(tmp)/'text.ko.txt').exists())

if __name__=='__main__': unittest.main()
