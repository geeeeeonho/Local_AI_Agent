"""Tk 화면에서 번역 도구를 사용하기 위한 콜백. 실제 작업은 worker thread."""
import time
from pathlib import Path
from threading import Event
from tkinter import filedialog
from .translation_view import KINDS, STYLES, LANGUAGES as TARGETS
from services.tools.languages import SOURCE_LABELS as SOURCES
from .widgets import set_text, set_status

KIND_NAMES={value:label for label,value in KINDS.items()}


class TranslationController:
    def translation_say(self,state,text,*,log=False,level='info'):
        """상태 줄을 색(대기/진행/완료/실패)과 함께 바꾼다. log=True면 하단 알림 줄에도 남겨
        다른 화면에 있거나 창이 작아도 결과를 놓치지 않게 한다."""
        set_status(self.translation_status_label,state,text)
        if log:
            self.log('[번역] '+text,level=level)

    # 화면 값 ↔ 저장된 기본값
    def _translation_fields(self):
        return {'target':self.translation_language,'model':self.translation_model,
                'source':self.translation_source_language,'kind':self.translation_kind,
                'style':self.translation_style,'shared':self.translation_shared,
                'resume':self.translation_resume,'keep_failed':self.translation_keep_failed,
                'precise':self.translation_precise,'stage':self.translation_stage}

    def translation_opened(self):
        """처음 열 때 지난번 선택(언어·모델·고급 설정)을 불러오고 모델 목록을 채운다."""
        if getattr(self,'_translation_prefs_loaded',False):
            return
        self._translation_prefs_loaded=True
        self._translation_last_model=''
        def apply(prefs):
            self._translation_loading=True
            fields=self._translation_fields()
            allowed={'target':TARGETS,'source':SOURCES,'kind':tuple(KINDS),'style':tuple(STYLES)}
            for key,value in prefs.items():
                if key in fields and (key not in allowed or value in allowed[key]):
                    fields[key].set(value)
            self._translation_last_model=prefs.get('model','')
            self._translation_last_dir=prefs.get('last_dir','')
            if prefs.get('glossary'):
                self.translation_glossary_text.delete('1.0','end')
                self.translation_glossary_text.insert('1.0',prefs['glossary'])
            self.toggle_translation_advanced(prefs.get('advanced',False),save=False)
            self._translation_loading=False
            # 이후 바꾸는 값은 바로(0.8초 모아서) 저장한다: 모델·언어·고급 설정·용어집
            for variable in self._translation_fields().values():
                variable.trace_add('write',lambda *_:self.schedule_translation_save())
            self.translation_glossary_text.bind('<KeyRelease>',lambda _e:self.schedule_translation_save(),add='+')
            self.refresh_translation_models()
        self.run_task('tools.prefs',self.services.settings.translation_preferences,apply,
                      mutate=False,announce=False,error=lambda _e:self.refresh_translation_models())

    def schedule_translation_save(self):
        if getattr(self,'_translation_loading',False) or self.closing:
            return
        pending=getattr(self,'_translation_save_job',None)
        if pending is not None:
            self.root.after_cancel(pending)
        self._translation_save_job=self.root.after(800,self.save_translation_preferences)

    def save_translation_preferences(self):
        self._translation_save_job=None
        values={key:variable.get() for key,variable in self._translation_fields().items()}
        values['advanced']=bool(getattr(self,'_translation_advanced_open',False))
        values['last_dir']=getattr(self,'_translation_last_dir','') or ''
        values['glossary']=self.translation_glossary_text.get('1.0','end').strip()[:20000]
        if not values['model']:
            values['model']=getattr(self,'_translation_last_model','')
        self.runner.submit('tools.prefs.save',
            lambda:self.services.settings.set_translation_preferences(values),
            lambda _:None,lambda exc:self.log('번역 기본값 저장 실패: '+str(exc),level='error'),mutate=False)

    def toggle_translation_advanced(self,show=None,*,save=True):
        visible=bool(getattr(self,'_translation_advanced_open',False))
        show=not visible if show is None else bool(show)
        self._translation_advanced_open=show
        if show and not visible:
            self.translation_advanced.pack(fill='x',before=self.translation_tabs_widget)
        elif not show and visible:
            self.translation_advanced.pack_forget()
        self.translation_advanced_button.configure(text='고급 설정 ▾' if show else '고급 설정 ▸')
        scroller=self.page_scrolls.get('tools.translate')
        if scroller is not None:
            scroller.bind_content()
        if save:
            self.schedule_translation_save()

    def update_translation_destination(self):
        """결과가 어디에 생기는지 미리 보여 주고, 시작 가능 여부에 맞춰 버튼을 켜고 끈다."""
        raw=self.translation_path.get().strip()
        custom=self.translation_output.get().strip()
        code=self.translation_code()
        if not raw:
            text='결과는 원본 옆에 자동으로 만듭니다. (파일 → 이름.%s.txt, 폴더 → 폴더이름.%s)'%(code,code)
        else:
            path=Path(raw)
            if custom:
                text='→ 결과: '+custom+'  (고급 설정에서 지정)'
            elif path.is_dir():
                text='→ 결과: 원본 옆 "%s.%s" 폴더 (같은 구조·같은 파일 이름, 다른 파일은 복사)'%(path.name,code)
            elif path.suffix:
                text='→ 결과: 원본 옆 "%s.%s%s" (이미 있으면 번호를 붙여 새로 만듭니다)'%(path.stem,code,path.suffix)
            else:
                text='파일이나 폴더 경로를 확인하세요.'
        self.translation_destination.configure(text=text)
        if not self.runner.busy('tools.translate'):
            ready=bool(raw and self.translation_model.get().strip())
            self.translation_start_button.configure(state='normal' if ready else 'disabled')

    def open_translation_folder(self):
        target=getattr(self,'_translation_last_output',None)
        if not target:return
        try:
            self.services.translator.reveal(target)
        except OSError as exc:
            self.translation_say('Failed','폴더를 열 수 없습니다: '+str(exc))

    def choose_translation_file(self):
        value=filedialog.askopenfilename(parent=self.root,title='번역할 파일',
              initialdir=self._translation_start_dir(),
              filetypes=[('텍스트/JSON/자막','*.txt *.json *.md *.markdown *.srt *.vtt'),
                         ('모든 파일','*.*')])
        if value:
            self._remember_translation_dir(Path(value).parent)
            self.translation_path.set(value)
            self.translation_output.set('')
            self.analyze_translation_file()

    def _translation_start_dir(self):
        folder=getattr(self,'_translation_last_dir','')
        return folder if folder and Path(folder).is_dir() else ''

    def _remember_translation_dir(self,folder):
        self._translation_last_dir=str(folder)
        self.schedule_translation_save()

    def choose_translation_folder(self):
        value=filedialog.askdirectory(parent=self.root,title='번역할 폴더',mustexist=True,
                                      initialdir=self._translation_start_dir())
        if value:
            self._remember_translation_dir(Path(value).parent)
            self.translation_path.set(value)
            self.translation_output.set('')
            self.analyze_translation_file()

    def choose_translation_output(self):
        original=Path(self.translation_path.get())
        if original.is_dir():
            value=filedialog.askdirectory(parent=self.root,title='결과 폴더 (비워 두면 "폴더이름.언어코드")',
                                          initialdir=str(original.parent))
            if value: self.translation_output.set(value)
            return
        value=filedialog.asksaveasfilename(parent=self.root,title='별도 결과 파일',
            initialdir=str(original.parent) if original.parent.is_dir() else '',
            initialfile=original.stem+'.translated'+original.suffix)
        if value: self.translation_output.set(value)

    def analyze_translation_file(self):
        path=self.translation_path.get().strip()
        if not path:
            self.translation_say('Waiting','파일을 먼저 선택하세요.');return
        if Path(path).is_dir():
            self.translation_say('Working','폴더 안의 파일 분석 중...')
            def folder_done(found):
                rows,others=found
                units=sum(count for _,_,count in rows)
                errors=[rel for rel,kind,_ in rows if kind.startswith('error')]
                self.translation_say('Ready' if rows else 'Failed',
                    ('준비됨 · 번역할 파일 %d개(%d구간) · 그대로 복사 %d개%s · [번역 시작]을 누르세요'
                     % (len(rows),units,others,(' · 읽을 수 없는 파일 %d개'%len(errors)) if errors else ''))
                    if rows else '이 폴더에는 번역할 TXT·JSON·MD·SRT·VTT 파일이 없습니다.')
                set_text(self.translation_source_text,'\n'.join(
                    '%-48s %-12s %6d구간'%(rel,kind[:40],count) for rel,kind,count in rows)
                    or '(번역할 파일 없음)')
                self.translation_tabs.select(0)
            self.run_task('tools.inspect',lambda:self.services.translator.inspect_folder(path),folder_done,
                mutate=False,announce=False,
                error=lambda e:self.translation_say('Failed','폴더 분석 실패: '+friendly_error(e)))
            return
        self.translation_say('Working','파일 유형 분석 중...')
        def done(doc):
            self.translation_say('Ready','준비됨 · %s · %d구간 · [번역 시작]을 누르세요' %
                                 (KIND_NAMES.get(doc.detected,doc.detected),len(doc.segments)))
            set_text(self.translation_source_text,doc.source[:12000])
            self.translation_tabs.select(0)
        self.run_task('tools.inspect',lambda:self.services.translator.inspect(path),done,
            mutate=False,announce=False,
            error=lambda e:self.translation_say('Failed','파일 분석 실패: '+friendly_error(e)))

    def translation_code(self):
        from .translation_view import CODES
        return CODES.get(self.translation_language.get(),'')

    def refresh_translation_models(self):
        self.translation_say('Working','로컬 모델 확인 중...')
        fetch=self.services.translator.local_models
        def done(names):
            self.translation_model_box.configure(values=names)
            if self.translation_model.get() not in names:
                # 지난번 모델 → 번역에 무난한 모델 순으로 자동 선택(직접 고를 필요 없게)
                self.translation_model.set(self.services.translator.recommend_model(
                    names,getattr(self,'_translation_last_model','')))
            if not names:
                self.translation_say('Failed','로컬 모델이 없습니다. Models 화면에서 설치하세요.')
            elif not self.translation_path.get().strip():
                self.translation_say('Waiting','번역할 파일이나 폴더를 선택하세요.')
        self.run_task('tools.models',fetch,done,mutate=False,announce=False,
                      error=lambda e:self.translation_say('Failed','모델 조회 실패: '+str(e)))

    def cancel_translation(self):
        if not self.runner.busy('tools.translate'):
            self.translation_say('Waiting','진행 중인 번역이 없습니다.');return
        self._translation_cancel.set()
        self.services.translator.abort()
        self.translation_say('Working','중단 중 · 완료한 구간은 저장되어 다음에 이어집니다.')

    def start_translation(self):
        if self.runner.busy('tools.translate'): return
        path=self.translation_path.get().strip()
        model=self.translation_model.get().strip()
        if not path or not model:
            self.translation_say('Failed','파일과 모델을 먼저 선택하세요.');return
        options={'path':path,'model':model,'target':self.translation_language.get(),
                 'kind':KINDS[self.translation_kind.get()],
                 'style':STYLES[self.translation_style.get()],
                 'stage':self.translation_stage.get(),
                 'resume':self.translation_resume.get(),
                 'keep_failed':self.translation_keep_failed.get(),
                 'precise':self.translation_precise.get(),
                 'source_language':self.translation_source_language.get(),
                 'glossary':self.translation_glossary_text.get('1.0','end'),
                 'output_path':self.translation_output.get().strip() or None}
        self.save_translation_preferences()
        self._translation_cancel=Event()
        self.translation_start_button.configure(state='disabled')
        self.translation_cancel_button.configure(state='normal')
        self.translation_say('Working','Ollama 준비 및 번역 시작...',log=True)
        self.translation_open_button.configure(state='disabled')
        self.set_translation_progress(0,0,'준비 중')
        clock={}
        folder_mode=Path(path).is_dir()
        shared_context=self.translation_shared.get()
        current={'file':''}
        def progress(n,total):
            # 작업 스레드에서 호출된다. 화면 갱신은 이벤트로 Tk 스레드에 넘긴다.
            now=time.monotonic()
            if 'start' not in clock:
                clock['start'],clock['first']=now,n     # 이어하기로 이미 끝난 구간은 속도 계산에서 뺀다
            eta=''
            done_here=n-clock['first']
            if done_here>0 and n<total:
                eta='약 %s 남음'%_duration((now-clock['start'])/done_here*(total-n))
            self.services.events.emit('runtime.progress',{'service':'translator',
                'done':n,'total':total,'eta':eta,
                'message':'%s번역 중: %d/%d 구간%s'%(current['file'] if folder_mode else '',n,total,
                                                     ' · '+eta if eta else '')})
        def on_file(index,count,name):
            current['file']='파일 %d/%d · %s · '%(index,count,name)
        def work():
            stop=lambda:self._translation_cancel.is_set() or self.runner.cancel.is_set()
            if folder_mode:
                folder_options=dict(options)
                folder_options.pop('path');output_dir=folder_options.pop('output_path')
                return self.services.translator.translate_folder(
                    path,output_dir=output_dir,progress=progress,on_file=on_file,cancelled=stop,
                    shared_context=shared_context,**folder_options)
            return self.services.translator.translate_file(**options,progress=progress,cancelled=stop)
        def unlock():
            if not self.translation_progress.get()>=100:
                self.translation_progress_label.configure(text='중지됨')
            self.translation_cancel_button.configure(state='disabled')
            self.root.after_idle(self.update_translation_destination)   # 시작 버튼 상태 복원
        def done(result):
            if folder_mode:
                return folder_finished(result)
            self.set_translation_progress(result.count,result.count,'')
            unlock()
            kept=result.kept_lines
            kept_note=(' · 원문 유지 %d줄(%s%s)'%(len(kept),', '.join(map(str,kept[:8])),
                       ' …' if len(kept)>8 else '')) if kept else ''
            review=result.review_lines
            review_note=(' · 검토 필요 %d줄'%len(review)) if review else ''
            self.translation_say('Ready','번역 완료: %d구간 · 재개 %d구간%s%s%s · %s' %
                                 (result.count,result.resumed_units,kept_note,review_note,
                                  audit_note(result),result.output),log=True)
            self._translation_last_output=result.output
            self.translation_open_button.configure(state='normal')
            self.root.bell()
            # 다음 번역(다른 언어 등)이 이전 결과 경로를 재사용하지 않도록 비운다.
            self.translation_output.set('')
            set_text(self.translation_result_text,result.text[:12000])
            glossary='\n'.join(f'{source} → {target}' for source,target in result.glossary.items())
            set_text(self.translation_memory_text,
                     '문서 요약\n'+result.memory_summary+'\n\n문체\n'+result.memory_style+
                     '\n\n고정 용어집\n'+(glossary or '(추출된 항목 없음)')+
                     ('\n\n원문 유지(검증 실패) 줄\n'+', '.join(map(str,kept)) if kept else '')+
                     ('\n\n검토 필요(원문 단어 일부 남음) 줄\n'+', '.join(map(str,review)) if review else '')+
                     audit_text(result)+
                     '\n\n문서 메모리는 해당 번역 작업에만 사용됩니다. 작업 완료 후 재개 기록은 삭제됩니다.')
            self.translation_tabs.select(1)
        def folder_finished(result):
            files=len(result.translated)+len(result.skipped)+len(result.failed)
            self.set_translation_progress(files,max(files,1),'파일 %d개'%files)
            unlock()
            review=sum(len(r.review_lines) for _,r in result.translated)
            kept=sum(len(r.kept_lines) for _,r in result.translated)
            state='Failed' if result.failed and not result.translated else 'Ready'
            fixed=sum(r.audit_fixed for _,r in result.translated)
            left=sum(len(r.audit) for _,r in result.translated)
            self.translation_say(state,'폴더 번역 완료: 번역 %d개 · 건너뜀 %d개 · 실패 %d개 · 복사 %d개%s%s%s · %s' % (
                len(result.translated),len(result.skipped),len(result.failed),result.copied,
                (' · 검토 필요 %d줄'%review) if review else '',(' · 원문 유지 %d줄'%kept) if kept else '',
                (' · 검수 자동 수정 %d · 확인 필요 %d줄'%(fixed,left)) if fixed or left else ' · 원문 대조 검수 통과',
                result.output),log=True,level='error' if state=='Failed' else 'info')
            self._translation_last_output=result.output
            self.translation_open_button.configure(state='normal')
            self.root.bell()
            self.translation_output.set('')
            reasons={'already translated':'이미 번역됨','already in the target language':'이미 번역 언어',
                     'no translatable text':'번역할 문장 없음(복사)'}
            lines=['번역한 파일']
            lines+=['  %s  (%d구간%s%s%s)'%(rel,r.count,(' · 검수 확인 필요 '+', '.join('%d줄'%n for n,_ in r.audit[:6]))
                     if r.audit else '',(' · 검토 %s줄'%','.join(map(str,r.review_lines[:6])))
                     if r.review_lines else '',(' · 원문 유지 %s줄'%','.join(map(str,r.kept_lines[:6])))
                     if r.kept_lines else '') for rel,r in result.translated] or ['  (없음)']
            if result.skipped:
                lines+=['','건너뛴 파일']+['  %s  (%s)'%(rel,reasons.get(why,why)) for rel,why in result.skipped]
            if result.failed:
                lines+=['','실패한 파일 (나머지는 계속 번역함)']+['  %s  — %s'%(rel,friendly_error(err))
                                                       for rel,err in result.failed]
            memory=result.memory
            if memory is not None:
                glossary='\n'.join('  %s → %s'%pair for pair in memory.terms.items()) or '  (추출된 항목 없음)'
                lines=['폴더 전체 메모리 (모든 파일이 함께 사용)','  요약: '+memory.summary,
                       '  문체: '+memory.style,'  공유 용어집:',glossary,'']+lines
            else:
                lines=['파일마다 따로 번역했습니다(폴더 맥락 공유 꺼짐).','']+lines
            set_text(self.translation_memory_text,'\n'.join(lines))
            first=result.translated[0][1].text if result.translated else ''
            set_text(self.translation_result_text,first[:12000] or '번역한 파일이 없습니다.')
            self.translation_tabs.select(2)
        def failed(exc):
            unlock()
            if isinstance(exc,InterruptedError):
                self.translation_say('Waiting','번역 중단됨 · 같은 설정으로 다시 시작하면 이어서 진행합니다.',log=True)
            else:
                self.translation_say('Failed','번역 실패: '+friendly_error(exc),log=True,level='error')
                self.root.bell()
        if not self.run_task('tools.translate',work,done,mutate=False,long=True,
                             announce=False,error=failed):
            unlock()

    def set_translation_progress(self,done,total,note=''):
        if not self.translation_progress_row.winfo_manager():
            self.translation_progress_row.pack(fill='x')
        percent=100.0*done/total if total else 0.0
        self.translation_progress.set(percent)
        text='%d%% · %d/%d'%(percent,done,total) if total else ''
        if note:
            text=(text+' · ' if text else '')+note
        self.translation_progress_label.configure(text=text)


def _duration(seconds):
    seconds=int(seconds)
    if seconds<60:return '%d초'%seconds
    if seconds<3600:return '%d분'%(seconds//60)
    return '%d시간 %d분'%(seconds//3600,seconds%3600//60)


# 서비스의 영어 오류를 사용자가 할 일 중심의 한국어로 바꾼다(원문은 괄호에 남겨 신고 시 참고).
_FRIENDLY=(
    ('source and target language are the same','원문과 번역 언어가 같습니다. [원문 언어]나 [번역 언어]를 바꾸세요.'),
    ('unsupported language','지원하지 않는 언어입니다.'),
    ('not available locally','선택한 모델이 이 PC에 없습니다. [새로고침] 후 다시 고르세요.'),
    ('already exists','같은 이름의 결과 파일이 이미 있습니다. 출력 파일 위치나 이름을 바꾸세요.'),
    ('another process has created','같은 이름의 결과 파일이 방금 생겼습니다. 출력 파일 이름을 바꾸세요.'),
    ('changed while translating','번역 중에 원본 파일이 바뀌어 결과를 저장하지 않았습니다. 다시 시작하세요.'),
    ('cannot overwrite the original','원본 파일에는 덮어쓸 수 없습니다. 다른 출력 파일을 고르세요.'),
    ('output directory does not exist','출력 폴더가 없습니다.'),
    ('too large','파일이 너무 큽니다(최대 32MiB). 나누어 번역하세요.'),
    ('too many translation','번역 구간이 너무 많습니다. 파일을 나누어 번역하세요.'),
    ('encoding','파일 인코딩을 알 수 없습니다. 메모장 등에서 UTF-8로 저장한 뒤 다시 시도하세요.'),
    ('decode','파일 인코딩을 알 수 없습니다. UTF-8로 저장한 뒤 다시 시도하세요.'),
    ('unsupported file extension','지원하지 않는 형식입니다. TXT·JSON·MD·SRT·VTT만 됩니다.'),
    ('unclosed markdown','닫히지 않은 코드 블록(```)이 있어 번역 범위를 정할 수 없습니다.'),
    ('no translatable files','이 폴더에는 번역할 TXT·JSON·MD·SRT·VTT 파일이 없습니다.'),
    ('too many files','폴더의 파일이 너무 많습니다(최대 2000개). 나누어 번역하세요.'),
    ('output folder cannot be','결과 폴더는 원본 폴더나 그 상위 폴더일 수 없습니다.'),
    ('no translatable content','번역할 문장을 찾지 못했습니다. 콘텐츠 유형을 바꿔 보세요.'),
    ('glossary','고정 용어집의 번역을 모델이 끝까지 따르지 않았습니다. 용어를 확인하거나 [실패한 구간은 원문 유지]를 켜세요.'),
    ('failed validation','모델 응답이 검증을 통과하지 못했습니다. [실패한 구간은 원문 유지]를 켜거나 더 큰 모델을 쓰세요.'),
    ('connection refused','Ollama에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요.'),
    ('timed out','모델 응답이 너무 오래 걸립니다. 더 작은 모델을 쓰거나 다른 작업을 닫으세요.'),
    ('memory','모델을 실행할 메모리가 부족합니다. 더 작은 모델을 고르세요.'),
)


def friendly_error(exc):
    text=str(exc)
    lower=text.lower()
    for key,message in _FRIENDLY:
        if key in lower:
            return message+' ('+text[:160]+')'
    return text


# 최종 원문 대조 검수 결과를 한국어로 보여 준다.
_AUDIT_REASONS=(('untranslated','번역 안 됨(원문과 같음)'),('too short','원문보다 지나치게 짧음(잘림 의심)'),
                ('too long','원문보다 지나치게 긺(덧붙임 의심)'),('inconsistent','인명·용어 표기 불일치'),
                ('left in','원문 문자 남음'),('another language','다른 언어 단어 섞임'),
                ('left untranslated','원문 단어 남음'),('Number','숫자 바뀜'),('similar','번역 안 됨(원문과 거의 같음)'))


def audit_reason(text):
    return next((label for key,label in _AUDIT_REASONS if key.lower() in text.lower()),text)


def audit_note(result):
    if not result.audit_fixed and not result.audit:
        return ' · 원문 대조 검수 통과'
    return ' · 검수 자동 수정 %d · 확인 필요 %d줄'%(result.audit_fixed,len(result.audit))


def audit_text(result):
    head='\n\n원문 대조 검수: 같은 문장 재사용 %d · 반려 후 다시 번역해 고침 %d · 확인 필요 %d줄'%(
        result.reused,result.audit_fixed,len(result.audit))
    return head+''.join('\n  %d줄: %s'%(line,audit_reason(reason)) for line,reason in result.audit[:40])
