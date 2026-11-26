"""Tk 화면에서 번역 도구를 사용하기 위한 콜백. 실제 작업은 worker thread."""
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from tkinter import filedialog
from .translation_view import KINDS, STYLES, LANGUAGES as TARGETS
from services.tools.languages import SOURCE_LABELS as SOURCES
from .widgets import set_text, set_status
from core.tools.speech import MEDIA
from services.tools.subtitles import Translate, scan as scan_media
from .subtitle_controller import options_from, overall, report_text, friendly as subtitle_error, STAGES
from .subtitle_view import MEDIA_PATTERN

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
        # 영상·음성 파일 때문에 자동으로 바꾼 유형·목적은 일반 번역의 기본값으로 남기지 않는다.
        saved=getattr(self,'_translation_media_saved',None)
        if saved and is_media(self.translation_path.get()):
            values['kind'],values['style']=saved
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
            elif is_media(path):
                text=('→ 결과: 원본 옆 "%s.srt"(원어 자막, 원본과 같은 이름)와 "%s.%s.srt"(번역 자막). '
                      '음성 인식 설정은 [자막 만들기] 도구의 값을 씁니다.'%(path.stem,path.stem,code))
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
                         ('영상·음성 (자막을 만든 뒤 번역)',MEDIA_PATTERN),
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
        if is_media(path):
            return self.analyze_translation_media(path)
        saved=getattr(self,'_translation_media_saved',None)
        if saved:
            self._translation_media_saved=None
            self._translation_loading=True
            try:
                self.translation_kind.set(saved[0]);self.translation_style.set(saved[1])
            finally:
                self._translation_loading=False
        if Path(path).is_dir():
            self.translation_say('Working','폴더 안의 파일 분석 중...')
            def folder_done(found):
                (rows,others),media=found
                others-=media
                units=sum(count for _,_,count in rows)
                errors=[rel for rel,kind,_ in rows if kind.startswith('error')]
                self.translation_say('Ready' if rows or media else 'Failed',
                    ('준비됨 · 번역할 파일 %d개(%d구간)%s · 그대로 복사 %d개%s · [번역 시작]을 누르세요'
                     % (len(rows),units,(' · 영상·음성 %d개(자막을 만든 뒤 번역, 영상은 복사 안 함)'%media)
                        if media else '',others,(' · 읽을 수 없는 파일 %d개'%len(errors)) if errors else ''))
                    if rows or media else '이 폴더에는 번역할 TXT·JSON·MD·SRT·VTT·영상·음성 파일이 없습니다.')
                set_text(self.translation_source_text,'\n'.join(
                    '%-48s %-12s %6d구간'%(rel,kind[:40],count) for rel,kind,count in rows)
                    or '(번역할 파일 없음)')
                self.translation_tabs.select(0)
            def inspect():
                return self.services.translator.inspect_folder(path),len(scan_media(path))
            self.run_task('tools.inspect',inspect,folder_done,
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
        if is_media(path):
            return self.start_media_translation(options)
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
                    shared_context=shared_context,media=self._folder_media(options['source_language']),
                    **folder_options)
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
            self._translation_revisable=('file',result)
            self.translation_terms_editor.load(result.glossary)
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
            self._translation_revisable=('folder',result)
            terms={}
            for _rel,item in result.translated:
                terms.update(item.glossary)
            if result.memory is not None:
                terms.update(result.memory.terms)
            self.translation_terms_editor.load(terms)
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

    # ── 영상·음성: 자막을 만든 뒤 그 자막을 번역한다(자막 도구와 같은 서비스) ──
    def analyze_translation_media(self,path):
        # 자막용으로 자동 설정한다. 일반 번역의 기본값으로는 저장하지 않는다.
        # 번역 목적은 사용자가 고른 값을 그대로 쓴다(줄 길이는 자막 규칙이 다시 나눈다).
        if not getattr(self,'_translation_media_saved',None):
            self._translation_media_saved=(self.translation_kind.get(),self.translation_style.get())
        self._translation_loading=True
        try:
            self.translation_kind.set(KIND_NAMES['subtitle'])
        finally:
            self._translation_loading=False
        self.translation_say('Working','영상·음성 파일 확인 중...')
        def fetch():
            return self.services.subtitles.status(),self.services.subtitles.media_info(path)
        def done(found):
            status,(duration,audio)=found
            self._translation_media_status=status
            if not status.builds:
                return self.translation_say('Failed','음성 인식 엔진이 없습니다. Tools → 자막 만들기에서 엔진을 설치하세요(관리자).')
            if not status.models:
                return self.translation_say('Failed','음성 인식 모델이 없습니다. Tools → 자막 만들기에서 모델을 받으세요(관리자).')
            if audio is False:
                return self.translation_say('Failed','이 파일에는 오디오 트랙이 없습니다.')
            seconds=int((duration or 0)//1000)
            self.translation_say('Ready','준비됨 · 영상·음성 → 자막 → 번역%s · 콘텐츠 유형을 [자막]으로 맞췄습니다 · [번역 시작]을 누르세요'%(
                ' · 길이 %d:%02d:%02d'%(seconds//3600,seconds//60%60,seconds%60) if duration else ''))
            set_text(self.translation_source_text,'영상·음성 파일: '+str(path)+
                     '\n\n1. 말소리를 받아 적어 원어 자막(SRT)을 만듭니다.'
                     '\n2. 그 자막을 선택한 모델로 번역하고, 번역 언어의 자막 규칙(줄 길이·2줄)으로 다시 나눕니다.'
                     '\n\n받아 적은 원어 자막은 번역을 마친 뒤 이 탭에 표시됩니다.')
            self.translation_tabs.select(0)
        self.run_task('tools.inspect',fetch,done,mutate=False,announce=False,
            error=lambda e:self.translation_say('Failed','파일 확인 실패: '+subtitle_error(e)))

    def start_media_translation(self,options):
        path=options['path']
        self._translation_cancel=Event()
        self.translation_start_button.configure(state='disabled')
        self.translation_cancel_button.configure(state='normal')
        self.translation_open_button.configure(state='disabled')
        self.translation_say('Working','자막을 만든 뒤 번역합니다...',log=True)
        self.set_translation_progress(0,100,'준비 중')
        events=self.services.events
        def progress(stage,fraction,note):
            value=overall(stage,fraction,True)
            events.emit('runtime.progress',{'service':'translator','done':int(value*1000),'total':1000,
                        'message':'%s%s'%(STAGES.get(stage,stage),' '+note if note else '')})
        stop=lambda:self._translation_cancel.is_set() or self.runner.cancel.is_set()
        def work():
            prefs=self.services.settings.subtitle_preferences()
            status=self.services.subtitles.status()
            model=self.services.subtitles.recommend_model(status.models,prefs.get('model',''))
            if not model:
                raise RuntimeError('Speech model is not installed')
            source=options['source_language']
            recognition=options_from(prefs,language=source if source in SOURCES else '자동 감지',model=model)
            return self.services.subtitles.make(path,recognition,translate=Translate(
                target=options['target'],model=options['model'],style=options['style'],
                glossary=options['glossary'],precise=options['precise'],keep_failed=options['keep_failed']),
                progress=progress,cancelled=stop)
        def unlock():
            self.translation_cancel_button.configure(state='disabled')
            self.root.after_idle(self.update_translation_destination)
        def done(result):
            unlock()
            self.set_translation_progress(100,100,'')
            outputs=result.translated_outputs or result.outputs
            self._translation_last_output=outputs[0]
            self.translation_open_button.configure(state='normal')
            note=('번역 생략: 음성 언어(%s)와 번역 언어가 같아 원어 자막만 만들었습니다'%result.language_label
                  if result.translation_skipped else '번역 자막 %d개 구간'%len(result.cues))
            self.translation_say('Ready','완료: %s · %s'%(note,outputs[0]),log=True)
            self._translation_revisable=('media',result)
            self.translation_terms_editor.load(getattr(result.translated,'glossary',None) or {})
            set_text(self.translation_source_text,result.text[:12000])
            set_text(self.translation_result_text,(result.translated_text or result.text)[:12000])
            set_text(self.translation_memory_text,report_text(result))
            self.translation_tabs.select(1)
            self.root.bell()
        def failed(exc):
            unlock()
            if isinstance(exc,InterruptedError):
                self.translation_say('Waiting','중단됨 · 다시 시작하면 인식 결과와 번역한 구간을 이어서 씁니다.',log=True)
            else:
                self.translation_say('Failed','실패: '+subtitle_error(friendly_error(exc)),log=True,level='error')
                self.root.bell()
        if not self.run_task('tools.translate',work,done,mutate=False,long=True,announce=False,error=failed):
            unlock()

    def _folder_media(self,source_language):
        """폴더 안 영상·음성을 자막으로 만들 처리기. 엔진·모델이 없으면 None(예전처럼 복사)."""
        status=self.services.subtitles.status()
        prefs=self.services.settings.subtitle_preferences()
        model=self.services.subtitles.recommend_model(status.models,prefs.get('model',''))
        if not status.builds or not model:
            return None
        language=source_language if source_language in SOURCES else '자동 감지'
        return self.services.subtitles.folder_media(options_from(prefs,language=language,model=model))

    def apply_translation_terms(self,changes,remember):
        """용어 사전에서 고친 용어를 마지막 번역 결과에 적용한다(그 용어가 든 줄만 다시 번역)."""
        found=getattr(self,'_translation_revisable',None)
        if found is None or self.runner.busy('tools.translate'):
            return
        kind,result=found
        if remember:
            self._remember_terms(changes)
        editor=self.translation_terms_editor
        editor.busy(True)
        self._translation_cancel=Event()
        self.translation_cancel_button.configure(state='normal')
        self.translation_say('Working','바꾼 용어 %d개 적용 중 · 그 용어가 든 줄만 다시 번역합니다...'%len(changes),log=True)
        stop=lambda:self._translation_cancel.is_set() or self.runner.cancel.is_set()
        translator=self.services.translator
        def work():
            if kind=='file':
                return kind,translator.revise_terms(result,changes,cancelled=stop)
            if kind=='media':
                return kind,self.services.subtitles.revise_terms(result,changes,cancelled=stop)
            items=[]
            for rel,item in result.translated:
                if item.revision is not None and translator.affected_by(item,changes):
                    item=translator.revise_terms(item,changes,cancelled=stop)
                items.append((rel,item))
            return kind,replace(result,translated=tuple(items))
        def done(found):
            kind,new=found
            self.translation_cancel_button.configure(state='disabled')
            self._translation_revisable=(kind,new)
            if kind=='file':
                count,terms,text=new.revised,new.glossary,new.text
            elif kind=='media':
                count,terms,text=new.translated.revised,new.translated.glossary,new.translated_text
            else:
                count=sum(item.revised for _rel,item in new.translated)
                terms={key:value for _rel,item in new.translated for key,value in item.glossary.items()}
                terms.update(changes)
                text=new.translated[0][1].text if new.translated else ''
            set_text(self.translation_result_text,text[:12000])
            editor.load(terms,note='적용 완료: %d줄을 다시 번역했습니다. 결과 파일을 고쳐 썼습니다.'%count)
            self.translation_say('Ready','용어 적용 완료: %d줄 다시 번역'%count,log=True)
            self.translation_tabs.select(1)
        def failed(exc):
            self.translation_cancel_button.configure(state='disabled')
            editor.busy(False)
            if isinstance(exc,InterruptedError):
                self.translation_say('Waiting','용어 적용을 중단했습니다. 결과 파일은 바뀌지 않았습니다.',log=True)
            else:
                self.translation_say('Failed','용어 적용 실패: '+friendly_error(exc),log=True,level='error')
        self.run_task('tools.translate',work,done,mutate=False,long=True,announce=False,error=failed)

    def _remember_terms(self,changes):
        """고친 용어를 고정 용어집(번역·자막 도구 공용)에 반영한다. 같은 원문 줄은 새 번역으로 바꾼다."""
        lines=[line for line in self.translation_glossary_text.get('1.0','end').splitlines() if line.strip()]
        kept=[line for line in lines if line.split('=',1)[0].strip() not in changes]
        kept+=['%s = %s'%(source,target) for source,target in changes.items()]
        self.translation_glossary_text.delete('1.0','end')
        self.translation_glossary_text.insert('1.0','\n'.join(kept))
        self.schedule_translation_save()

    def set_translation_progress(self,done,total,note=''):
        if not self.translation_progress_row.winfo_manager():
            self.translation_progress_row.pack(fill='x')
        percent=100.0*done/total if total else 0.0
        self.translation_progress.set(percent)
        text='%d%% · %d/%d'%(percent,done,total) if total else ''
        if note:
            text=(text+' · ' if text else '')+note
        self.translation_progress_label.configure(text=text)


def is_media(path):
    """영상·음성 파일이면 번역 전에 자막을 먼저 만든다."""
    path=Path(str(path).strip())
    return path.suffix.lower() in MEDIA and not path.is_dir()


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
