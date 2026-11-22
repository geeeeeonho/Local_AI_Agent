"""Studio Tools의 파일 번역 화면.

작은 창에서도 상태·진행률·시작/취소 버튼이 가려지지 않도록, 이 셋은 스크롤되지 않는
상단 고정 영역에 두고 설정과 결과는 그 아래 스크롤 영역에 둔다.
"""
import tkinter as tk
from tkinter import ttk
from services.tools.languages import SOURCE_LABELS, TARGET_LABELS, LANGUAGES as _ALL

CODES={item.label:item.code for item in _ALL if item.target}
from .widgets import note, text_box, set_text, status_line, ScrollArea, wrap_to_parent

KINDS={'자동 감지':'auto','일반 문서':'general','소설':'novel','대본 / 대사':'script',
       '자막':'subtitle','코드 포함 문서':'code','구조화 데이터':'structured'}
STYLES={'원문 충실':'faithful','자연스러운 번역':'natural','자막용 간결 번역':'concise'}
LANGUAGES=TARGET_LABELS


def _variables(w):
    w.translation_path=tk.StringVar(master=w.root)
    w.translation_output=tk.StringVar(master=w.root)
    w.translation_model=tk.StringVar(master=w.root)
    w.translation_kind=tk.StringVar(master=w.root,value='자동 감지')
    w.translation_style=tk.StringVar(master=w.root,value='자연스러운 번역')
    w.translation_language=tk.StringVar(master=w.root,value='한국어')
    w.translation_source_language=tk.StringVar(master=w.root,value='자동 감지')
    w.translation_stage=tk.BooleanVar(master=w.root,value=False)
    w.translation_resume=tk.BooleanVar(master=w.root,value=True)
    w.translation_keep_failed=tk.BooleanVar(master=w.root,value=True)
    w.translation_precise=tk.BooleanVar(master=w.root,value=False)
    w.translation_progress=tk.DoubleVar(master=w.root,value=0)
    w.translation_status=tk.StringVar(master=w.root,value='1단계: 번역할 파일을 선택하세요.')


def _check(parent,text,variable,detail=None):
    """긴 설명은 체크박스 글자에 넣지 않고 줄바꿈되는 보조 설명으로 둔다(좁은 창에서 잘리지 않게)."""
    ttk.Checkbutton(parent,text=text,variable=variable).pack(anchor='w',pady=(4,0))
    if detail:
        label=ttk.Label(parent,text=detail,style='Muted.TLabel',justify='left',wraplength=600)
        label.pack(anchor='w',padx=(26,0))
        wrap_to_parent(label,inset=60)


def build(parent,w,toolbar=None):
    _variables(w)

    # ── 상단 고정: 실행 버튼(도구 목록 줄) · 상태 · 진행률 ──
    header=ttk.Frame(parent);header.pack(fill='x',pady=(0,8))
    actions=toolbar if toolbar is not None else ttk.Frame(header)
    if toolbar is None:
        actions.pack(fill='x',pady=(0,8))
    w.translation_status_label=status_line(header,w.translation_status)
    bar=ttk.Frame(header);bar.pack(fill='x')
    w.translation_progress_bar=ttk.Progressbar(bar,variable=w.translation_progress,maximum=100,
                                               mode='determinate')
    w.translation_progress_bar.pack(side='left',fill='x',expand=True)
    w.translation_progress_label=ttk.Label(bar,text='',style='Muted.TLabel')
    w.translation_progress_label.pack(side='left',padx=(8,0))
    w.translation_start_button=ttk.Button(actions,text='번역 시작',style='Accent.TButton',
                                           command=w.start_translation)
    w.translation_start_button.pack(side='left')
    w.translation_cancel_button=ttk.Button(actions,text='취소',state='disabled',
                                            command=w.cancel_translation)
    w.translation_cancel_button.pack(side='left',padx=(6,0))
    w.translation_open_button=ttk.Button(actions,text='결과 폴더',state='disabled',
                                          command=w.open_translation_folder)
    w.translation_open_button.pack(side='left',padx=(6,0))

    # ── 스크롤 영역: 설정과 결과 ──
    scroller=ScrollArea(parent);w.page_scrolls['tools.translate']=scroller
    body=scroller.body

    panel=ttk.LabelFrame(body,text='파일',padding=12);panel.pack(fill='x',pady=(0,10))
    def line(owner,label):
        frame=ttk.Frame(owner);frame.pack(fill='x',pady=3)
        ttk.Label(frame,text=label,width=11).pack(side='left')
        return frame
    row=line(panel,'원본')
    ttk.Entry(row,textvariable=w.translation_path).pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='파일',command=w.choose_translation_file).pack(side='left',padx=(5,0))
    ttk.Button(row,text='폴더',command=w.choose_translation_folder).pack(side='left',padx=(5,0))
    ttk.Button(row,text='분석',command=w.analyze_translation_file).pack(side='left',padx=(5,0))
    row=line(panel,'결과')
    ttk.Entry(row,textvariable=w.translation_output).pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='위치',command=w.choose_translation_output).pack(side='left',padx=(5,0))
    note(panel,'파일: TXT·JSON·MD·SRT·VTT, 최대 32MiB. 결과를 비워 두면 원본 옆에 "이름.ko.txt"를 만듭니다.\n'
         '폴더: 하위 폴더까지 모두 번역해 "폴더이름.ko" 폴더에 같은 구조·같은 파일 이름으로 만듭니다. '
         '그림 등 다른 파일은 그대로 복사하고, 다시 실행하면 남은 파일만 번역합니다. 기존 파일은 덮어쓰지 않습니다.')

    options=ttk.LabelFrame(body,text='번역 설정',padding=12);options.pack(fill='x',pady=(0,10))
    row=line(options,'로컬 모델')
    w.translation_model_box=ttk.Combobox(row,textvariable=w.translation_model,values=(),state='readonly')
    w.translation_model_box.pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='새로고침',command=w.refresh_translation_models).pack(side='left',padx=(5,0))
    for label,variable,values in (('원문 언어',w.translation_source_language,SOURCE_LABELS),
                                  ('번역 언어',w.translation_language,LANGUAGES),
                                  ('콘텐츠 유형',w.translation_kind,tuple(KINDS)),
                                  ('번역 목적',w.translation_style,tuple(STYLES))):
        row=line(options,label)
        ttk.Combobox(row,textvariable=variable,values=values,state='readonly').pack(
            side='left',fill='x',expand=True)
    _check(options,'중단한 번역 이어하기',w.translation_resume,
           '같은 파일·설정이면 완료한 구간과 문서 메모리를 다시 씁니다.')
    _check(options,'실패한 구간은 원문 유지',w.translation_keep_failed,
           '끝까지 검증을 통과하지 못한 줄만 원문으로 두고 계속합니다. 완료 후 줄 번호를 알려 줍니다.')
    _check(options,'정밀 모드 (느림)',w.translation_precise,
           '지원 모델에서 추론(thinking)을 켜 관용구·뉘앙스를 더 검토합니다. 여러 배 느립니다.')
    _check(options,'[지문]도 번역',w.translation_stage,'대본의 [괄호 지문] 줄도 번역합니다.')

    glossary=ttk.LabelFrame(body,text='고정 용어집 (선택)',padding=12);glossary.pack(fill='x',pady=(0,10))
    note(glossary,'한 줄에 "원문 = 번역". 인명·핵심 용어는 반드시 이 번역을 씁니다. 예: 佐藤 = 사토')
    w.translation_glossary_text=text_box(glossary,height=3,expand=False)
    w.translation_glossary_text.configure(state='normal')   # 사용자가 입력하는 칸

    notebook=ttk.Notebook(body);notebook.pack(fill='x',pady=(0,6))
    original=ttk.Frame(notebook);translated=ttk.Frame(notebook);memory=ttk.Frame(notebook)
    notebook.add(original,text='원본');notebook.add(translated,text='번역본')
    notebook.add(memory,text='문서 메모리 · 검토')
    w.translation_source_text=text_box(original,height=12)
    w.translation_result_text=text_box(translated,height=12)
    w.translation_memory_text=text_box(memory,height=12)
    w.translation_tabs=notebook
    set_text(w.translation_source_text,'분석된 파일의 앞부분이 표시됩니다.')
    set_text(w.translation_result_text,'번역 결과가 표시됩니다.')
    set_text(w.translation_memory_text,'번역을 완료하면 요약·문체·용어집과 검토가 필요한 줄을 보여 줍니다.')
    scroller.bind_content()
