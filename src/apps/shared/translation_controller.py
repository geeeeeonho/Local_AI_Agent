"""Tk 화면에서 번역 도구를 사용하기 위한 콜백. 실제 작업은 worker thread."""
from pathlib import Path
from threading import Event
from tkinter import filedialog
from .translation_view import KINDS, STYLES
from .widgets import set_text

class TranslationController:
    def choose_translation_file(self):
        value=filedialog.askopenfilename(parent=self.root,title='번역할 파일',
              filetypes=[('텍스트/JSON/자막','*.txt *.json *.md *.markdown *.srt *.vtt'),
                         ('모든 파일','*.*')])
        if value:
            self.translation_path.set(value)
            self.translation_output.set('')
            self.analyze_translation_file()

    def choose_translation_output(self):
        original=Path(self.translation_path.get())
        value=filedialog.asksaveasfilename(parent=self.root,title='별도 결과 파일',
            initialdir=str(original.parent) if original.parent.is_dir() else '',
            initialfile=original.stem+'.translated'+original.suffix)
        if value: self.translation_output.set(value)

    def analyze_translation_file(self):
        path=self.translation_path.get().strip()
        if not path:
            self.translation_status.set('파일을 먼저 선택하세요');return
        self.translation_status.set('파일 유형 분석 중...')
        def done(doc):
            self.translation_status.set('감지된 유형: %s · 번역 대상: %d구간' %
                                        (doc.detected,len(doc.segments)))
            set_text(self.translation_source_text,doc.source[:12000])
            self.translation_tabs.select(0)
        self.run_task('tools.inspect',lambda:self.services.translator.inspect(path),done,
            mutate=False,announce=False,
            error=lambda e:self.translation_status.set('파일 분석 실패: '+str(e)))

    def refresh_translation_models(self):
        self.translation_status.set('로컬 모델 확인 중...')
        def fetch():
            from integrations.ollama.inventory import read
            result=read()
            if not result.known: raise RuntimeError('모델 저장소를 확인할 수 없습니다')
            return sorted(result.local_tags)
        def done(names):
            self.translation_model_box.configure(values=names)
            if self.translation_model.get() not in names:
                self.translation_model.set(names[0] if names else '')
            self.translation_status.set('%d개 모델 사용 가능'%len(names) if names else
                                        '로컬 모델이 없습니다. Models에서 설치하세요.')
        self.run_task('tools.models',fetch,done,mutate=False,announce=False,
                      error=lambda e:self.translation_status.set('모델 조회 실패: '+str(e)))

    def cancel_translation(self):
        if not self.runner.busy('tools.translate'):
            self.translation_status.set('진행 중인 번역이 없습니다.');return
        self._translation_cancel.set()
        self.services.translator.abort()
        self.translation_status.set('중단 중 · 완료한 구간은 저장되어 다음에 이어집니다.')

    def start_translation(self):
        if self.runner.busy('tools.translate'): return
        path=self.translation_path.get().strip()
        model=self.translation_model.get().strip()
        if not path or not model:
            self.translation_status.set('파일 및 모델을 선택하세요');return
        options={'path':path,'model':model,'target':self.translation_language.get(),
                 'kind':KINDS[self.translation_kind.get()],
                 'style':STYLES[self.translation_style.get()],
                 'stage':self.translation_stage.get(),
                 'resume':self.translation_resume.get(),
                 'keep_failed':self.translation_keep_failed.get(),
                 'output_path':self.translation_output.get().strip() or None}
        self._translation_cancel=Event()
        self.translation_start_button.configure(state='disabled')
        self.translation_cancel_button.configure(state='normal')
        self.translation_status.set('Ollama 준비 및 번역 시작...')
        def progress(n,total):
            self.services.events.emit('runtime.progress',{'service':'translator',
                'message':'번역 중: %d/%d 구간'%(n,total)})
        def work():
            return self.services.translator.translate_file(
                **options,progress=progress,
                cancelled=lambda:self._translation_cancel.is_set() or self.runner.cancel.is_set())
        def unlock():
            self.translation_start_button.configure(state='normal')
            self.translation_cancel_button.configure(state='disabled')
        def done(result):
            unlock()
            kept=result.kept_lines
            kept_note=(' · 원문 유지 %d줄(%s%s)'%(len(kept),', '.join(map(str,kept[:8])),
                       ' …' if len(kept)>8 else '')) if kept else ''
            self.translation_status.set('번역 완료: %d구간 · 재개 %d구간%s · %s' %
                                        (result.count,result.resumed_units,kept_note,result.output))
            # 다음 번역(다른 언어 등)이 이전 결과 경로를 재사용하지 않도록 비운다.
            self.translation_output.set('')
            set_text(self.translation_result_text,result.text[:12000])
            glossary='\n'.join(f'{source} → {target}' for source,target in result.glossary.items())
            set_text(self.translation_memory_text,
                     '문서 요약\n'+result.memory_summary+'\n\n문체\n'+result.memory_style+
                     '\n\n고정 용어집\n'+(glossary or '(추출된 항목 없음)')+
                     ('\n\n원문 유지(검증 실패) 줄\n'+', '.join(map(str,kept)) if kept else '')+
                     '\n\n문서 메모리는 해당 번역 작업에만 사용됩니다. 작업 완료 후 재개 기록은 삭제됩니다.')
            self.translation_tabs.select(1)
        def failed(exc):
            unlock()
            if isinstance(exc,InterruptedError):
                self.translation_status.set('번역 중단됨 · 같은 설정으로 다시 시작하면 이어서 진행합니다.')
            else:
                self.translation_status.set('번역 실패: '+str(exc))
        if not self.run_task('tools.translate',work,done,mutate=False,long=True,
                             announce=False,error=failed):
            unlock()
