"""Models 화면의 '음성 인식 (자막)' 탭: 자막 엔진과 음성 인식 모델의 설치·복구·삭제.

LLM 모델과 마찬가지로 모델 관리는 Models 화면이 맡는다. Tools → 자막 만들기는 설치된 모델을 쓰기만 하고,
엔진이나 모델이 없으면 이 탭으로 가는 바로가기를 보여 준다. 설치·삭제는 LocalAI 관리자만 할 수 있다.
"""
import tkinter as tk
from tkinter import ttk

from .widgets import ScrollArea, note, status_line, wrap_to_parent


def build(parent, w):
    w.speech_status = tk.StringVar(master=w.root, value='음성 인식 엔진과 모델을 확인하는 중…')
    w.speech_engine_text = tk.StringVar(master=w.root, value='')
    w.speech_progress = tk.DoubleVar(master=w.root, value=0)

    header = ttk.Frame(parent); header.pack(fill='x', pady=(0, 6))
    w.speech_status_label = status_line(header, w.speech_status)
    bar = ttk.Frame(header)
    w.speech_progress_row = bar
    ttk.Progressbar(bar, variable=w.speech_progress, maximum=100, mode='determinate').pack(
        side='left', fill='x', expand=True)
    w.speech_progress_label = ttk.Label(bar, text='', style='Muted.TLabel')
    w.speech_progress_label.pack(side='left', padx=(8, 0))

    scroller = ScrollArea(parent); w.page_scrolls['models.speech'] = scroller
    body = scroller.body
    engine = ttk.LabelFrame(body, text='음성 인식 엔진 (whisper.cpp · ffmpeg · 음성 구간 감지)', padding=12)
    engine.pack(fill='x', pady=(0, 8))
    label = ttk.Label(engine, textvariable=w.speech_engine_text, style='Muted.TLabel', justify='left',
                      wraplength=600)
    label.pack(anchor='w', fill='x'); wrap_to_parent(label, inset=40)
    row = ttk.Frame(engine); row.pack(fill='x', pady=(8, 0))
    w.speech_engine_button = ttk.Button(row, text='엔진 설치 / 복구', command=w.install_speech_engine)
    w.speech_engine_button.pack(side='left')
    w.speech_cancel_button = ttk.Button(row, text='취소', state='disabled', command=w.cancel_speech_job)
    w.speech_cancel_button.pack(side='left', padx=(6, 0))

    models = ttk.LabelFrame(body, text='음성 인식 모델', padding=12); models.pack(fill='x', pady=(0, 8))
    note(models, '권장은 large-v3-turbo입니다. large-v3도 받아 두면 자막 만들기의 [인식 품질: 최고 정확도]가 '
                 '의심스러운 구간만 large-v3로 다시 인식합니다. 받은 모델은 이 PC의 모든 계정이 함께 씁니다.')
    table = ttk.Treeview(models, columns=('model', 'size', 'gpu', 'state'), show='headings', height=6,
                         selectmode='browse')
    for name, heading, width in (('model', '모델', 260), ('size', '크기', 80), ('gpu', 'GPU 메모리', 90),
                                 ('state', '상태', 90)):
        table.heading(name, text=heading)
        table.column(name, width=width, stretch=name == 'model')
    table.pack(fill='x', pady=(4, 4))
    table.bind('<<TreeviewSelect>>', lambda _e: w.describe_speech_model())
    w.speech_model_table = table
    w.speech_model_note = ttk.Label(models, text='모델을 고르면 설명이 나옵니다.', style='Muted.TLabel',
                                    justify='left', wraplength=600)
    w.speech_model_note.pack(anchor='w', fill='x'); wrap_to_parent(w.speech_model_note, inset=40)
    buttons = ttk.Frame(models); buttons.pack(fill='x', pady=(6, 0))
    w.speech_get_button = ttk.Button(buttons, text='선택 모델 받기 / 복구', style='Accent.TButton',
                                     command=w.download_speech_model)
    w.speech_get_button.pack(side='left')
    w.speech_remove_button = ttk.Button(buttons, text='선택 모델 삭제', command=w.remove_speech_model)
    w.speech_remove_button.pack(side='left', padx=(6, 0))
    ttk.Button(buttons, text='↻ 새로고침', command=w.refresh_speech_status).pack(side='right')
    scroller.bind_content()
