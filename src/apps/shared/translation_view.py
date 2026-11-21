"""Studio Tools의 파일 번역 화면."""
import tkinter as tk
from tkinter import ttk
from .widgets import note, text_box, set_text

KINDS={'자동 감지':'auto','일반 문서':'general','소설':'novel','대본 / 대사':'script',
       '자막':'subtitle','코드 포함 문서':'code','구조화 데이터':'structured'}
STYLES={'원문 충실':'faithful','자연스러운 번역':'natural','자막용 간결 번역':'concise'}
LANGUAGES=('한국어','English','日本語','简体中文','Español')

def build(parent,w):
    w.translation_path=tk.StringVar(master=w.root)
    w.translation_output=tk.StringVar(master=w.root)
    w.translation_model=tk.StringVar(master=w.root)
    w.translation_kind=tk.StringVar(master=w.root,value='자동 감지')
    w.translation_style=tk.StringVar(master=w.root,value='자연스러운 번역')
    w.translation_language=tk.StringVar(master=w.root,value='한국어')
    w.translation_stage=tk.BooleanVar(master=w.root,value=False)
    w.translation_status=tk.StringVar(master=w.root,value='파일을 선택한 뒤 분석하세요.')
    panel=ttk.LabelFrame(parent,text='파일 번역 설정',padding=12)
    panel.pack(fill='x',pady=(0,10))
    def line(label):
        frame=ttk.Frame(panel);frame.pack(fill='x',pady=3)
        ttk.Label(frame,text=label,width=13).pack(side='left')
        return frame
    row=line('원본 파일')
    ttk.Entry(row,textvariable=w.translation_path).pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='파일 선택',command=w.choose_translation_file).pack(side='left',padx=5)
    ttk.Button(row,text='분석',command=w.analyze_translation_file).pack(side='left')

    row=line('콘텐츠 유형')
    ttk.Combobox(row,textvariable=w.translation_kind,values=tuple(KINDS),
                 state='readonly',width=22).pack(side='left')
    ttk.Label(row,text='번역 목적').pack(side='left',padx=(18,6))
    ttk.Combobox(row,textvariable=w.translation_style,values=tuple(STYLES),
                 state='readonly',width=22).pack(side='left')

    row=line('로컬 모델')
    w.translation_model_box=ttk.Combobox(row,textvariable=w.translation_model,
                                          values=(),state='readonly')
    w.translation_model_box.pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='새로고침',command=w.refresh_translation_models).pack(side='left',padx=(6,0))

    row=line('번역 언어')
    ttk.Combobox(row,textvariable=w.translation_language,values=LANGUAGES,
                 state='readonly',width=19).pack(side='left')
    ttk.Checkbutton(row,text='[지문]도 번역',variable=w.translation_stage).pack(side='left',padx=(20,0))

    row=line('출력 파일')
    ttk.Entry(row,textvariable=w.translation_output).pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='저장 위치',command=w.choose_translation_output).pack(side='left',padx=(6,0))
    note(panel,'TXT/JSON/MD/SRT/VTT 지원. 코드·변수·JSON 키·타임코드 보존. '
         '출력 경로를 비우면 별도 새 파일을 생성하며 원본은 수정하지 않습니다.')

    actions=ttk.Frame(parent);actions.pack(fill='x',pady=4)
    w.translation_start_button=ttk.Button(actions,text='번역 시작',style='Accent.TButton',
                                           command=w.start_translation)
    w.translation_start_button.pack(side='left')
    w.translation_cancel_button=ttk.Button(actions,text='취소',state='disabled',
                                            command=w.cancel_translation)
    w.translation_cancel_button.pack(side='left',padx=(8,0))
    ttk.Label(actions,textvariable=w.translation_status,style='Muted.TLabel',
              wraplength=520).pack(side='left',padx=(15,0),fill='x',expand=True)

    notebook=ttk.Notebook(parent);notebook.pack(fill='both',expand=True)
    original=ttk.Frame(notebook);translated=ttk.Frame(notebook)
    notebook.add(original,text='원본');notebook.add(translated,text='번역본')
    w.translation_source_text=text_box(original,height=10)
    w.translation_result_text=text_box(translated,height=10)
    w.translation_tabs=notebook
    set_text(w.translation_source_text,'분석된 파일의 앞부분이 표시됩니다.')
    set_text(w.translation_result_text,'번역 결과가 표시됩니다.')
