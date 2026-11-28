"""Studio Tools의 자막 만들기 화면.

번역 화면과 같은 배치: 실행 버튼은 '← 도구 목록' 줄, 상태·진행률은 고정 영역, 나머지는 스크롤.
기본은 파일을 고르고 [자막 만들기]만 누르면 된다. 번역 자막, 품질, 줄 길이는 필요할 때 바꾼다.
"""
import tkinter as tk
from tkinter import ttk

from core.tools import speech
from services.tools.languages import SOURCE_LABELS, TARGET_LABELS
from .translation_view import STYLES
from .widgets import FoldGroup, ScrollArea, SideBySide, note, set_text, status_line, text_box, wrap_to_parent
from .glossary_editor import GlossaryEditor

FORMATS = {'SRT (가장 널리 쓰임)': ('srt',), 'WebVTT (웹·유튜브)': ('vtt',), 'SRT + WebVTT': ('srt', 'vtt')}
QUALITIES = {'최고 정확도 (정밀 단어 시각 · 느림)': 'best', '균형': 'balanced', '빠름': 'fast'}
LINES = {'2줄 (표준)': 2, '1줄': 1}
MODEL_LABELS = {item.label: item.key for item in speech.MODELS}
MEDIA_PATTERN = ' '.join('*' + suffix for suffix in sorted(speech.MEDIA))


def _variables(w):
    root = w.root
    w.subtitle_path = tk.StringVar(master=root)
    w.subtitle_script = tk.StringVar(master=root)        # 대본 파일(선택, 파일 하나일 때만)
    w.subtitle_language = tk.StringVar(master=root, value='자동 감지')
    w.subtitle_format = tk.StringVar(master=root, value=tuple(FORMATS)[0])
    w.subtitle_model = tk.StringVar(master=root)
    w.subtitle_translate = tk.BooleanVar(master=root, value=False)
    w.subtitle_main_name = tk.BooleanVar(master=root, value=True)
    w.subtitle_translate_name = tk.BooleanVar(master=root, value=False)
    w.subtitle_target = tk.StringVar(master=root, value='한국어')
    w.subtitle_llm = tk.StringVar(master=root)
    w.subtitle_style = tk.StringVar(master=root, value='자연스러운 번역')
    w.subtitle_quality = tk.StringVar(master=root, value=tuple(QUALITIES)[0])
    w.subtitle_vad = tk.BooleanVar(master=root, value=True)
    w.subtitle_keep_sounds = tk.BooleanVar(master=root, value=False)
    w.subtitle_gpu = tk.BooleanVar(master=root, value=True)
    w.subtitle_sensitive = tk.BooleanVar(master=root, value=False)
    w.subtitle_lines = tk.StringVar(master=root, value=tuple(LINES)[0])
    w.subtitle_chars = tk.StringVar(master=root, value='자동')
    w.subtitle_progress = tk.DoubleVar(master=root, value=0)
    w.subtitle_status = tk.StringVar(master=root, value='자막을 만들 영상이나 음성 파일을 선택하세요.')
    w.subtitle_engine_text = tk.StringVar(master=root, value='음성 인식 엔진 확인 중…')


def _check(parent, text, variable, detail=None):
    ttk.Checkbutton(parent, text=text, variable=variable).pack(anchor='w', pady=(4, 0))
    if detail:
        label = ttk.Label(parent, text=detail, style='Muted.TLabel', justify='left', wraplength=600)
        label.pack(anchor='w', padx=(26, 0))
        wrap_to_parent(label, inset=60)


def build(parent, w, toolbar=None):
    _variables(w)
    w._subtitle_files = []

    # ── 상단 고정: 실행 버튼 · 상태 · 진행률 ──
    header = ttk.Frame(parent); header.pack(fill='x', pady=(0, 8))
    actions = toolbar if toolbar is not None else ttk.Frame(header)
    if toolbar is None:
        actions.pack(fill='x', pady=(0, 8))
    w.subtitle_status_label = status_line(header, w.subtitle_status)
    bar = ttk.Frame(header)
    w.subtitle_progress_row = bar
    ttk.Progressbar(bar, variable=w.subtitle_progress, maximum=100, mode='determinate').pack(
        side='left', fill='x', expand=True)
    w.subtitle_progress_label = ttk.Label(bar, text='', style='Muted.TLabel')
    w.subtitle_progress_label.pack(side='left', padx=(8, 0))
    w.subtitle_start_button = ttk.Button(actions, text='자막 만들기', style='Accent.TButton',
                                         command=w.start_subtitles, state='disabled')
    w.subtitle_start_button.pack(side='left')
    w.subtitle_cancel_button = ttk.Button(actions, text='취소', state='disabled', command=w.cancel_subtitles)
    w.subtitle_cancel_button.pack(side='left', padx=(6, 0))
    w.subtitle_open_button = ttk.Button(actions, text='결과 열기', state='disabled',
                                        command=w.open_subtitle_folder)
    w.subtitle_open_button.pack(side='left', padx=(6, 0))

    scroller = ScrollArea(parent); w.page_scrolls['tools.subtitles'] = scroller
    body = scroller.body

    def line(owner, label, width=11):
        frame = ttk.Frame(owner); frame.pack(fill='x', pady=3)
        ttk.Label(frame, text=label, width=width).pack(side='left')
        return frame

    # 구획마다 접을 수 있고, 접은 상태는 다음에도 기억한다(실행 단추·진행률은 위에 늘 보인다).
    folds = w.subtitle_folds = FoldGroup(on_change=w.subtitle_folds_changed)
    # 영상·음성 파일(왼쪽)과 대본으로 시간 맞추기(오른쪽)를 나란히. 좁은 창에서는 위아래로 쌓는다.
    side = SideBySide(body)
    source_section = folds.add(side.frame, 'source', '영상 · 음성 파일', place=False)
    side.add(source_section.frame)
    basic = source_section.body
    pick = ttk.Frame(basic); pick.pack(fill='x')
    ttk.Button(pick, text='파일 선택…', style='Accent.TButton',
               command=w.choose_subtitle_files).pack(side='left')
    ttk.Button(pick, text='폴더 선택…', command=w.choose_subtitle_folder).pack(side='left', padx=(6, 8))
    entry = ttk.Entry(pick, textvariable=w.subtitle_path)
    entry.pack(side='left', fill='x', expand=True)
    entry.bind('<Return>', lambda _e: w.analyze_subtitle_input())
    w.subtitle_destination = ttk.Label(basic, text='', style='Muted.TLabel', justify='left', wraplength=600)
    w.subtitle_destination.pack(anchor='w', fill='x', pady=(8, 6)); wrap_to_parent(w.subtitle_destination, inset=40)
    row = ttk.Frame(basic); row.pack(fill='x', pady=(2, 0))
    ttk.Label(row, text='음성 언어').pack(side='left')
    ttk.Combobox(row, textvariable=w.subtitle_language, values=SOURCE_LABELS, state='readonly',
                 width=10).pack(side='left', padx=(6, 12))
    ttk.Label(row, text='형식').pack(side='left')
    ttk.Combobox(row, textvariable=w.subtitle_format, values=tuple(FORMATS), state='readonly',
                 width=12).pack(side='left', fill='x', expand=True, padx=(6, 0))
    row = ttk.Frame(basic); row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='인식 모델').pack(side='left')
    ttk.Button(row, text='↻', width=3, command=w.refresh_subtitle_status).pack(side='right', padx=(4, 0))
    if 'models' in w.spec.pages:      # 모델 설치·삭제는 Models 화면이 맡는다
        ttk.Button(row, text='모델 관리 →', command=w.open_speech_models).pack(side='right', padx=(4, 0))
    w.subtitle_model_box = ttk.Combobox(row, textvariable=w.subtitle_model, values=(), state='readonly')
    w.subtitle_model_box.pack(side='left', fill='x', expand=True, padx=(6, 0))
    engine_label = ttk.Label(basic, textvariable=w.subtitle_engine_text, style='Muted.TLabel',
                             justify='left', wraplength=600)
    engine_label.pack(anchor='w', fill='x', pady=(6, 0)); wrap_to_parent(engine_label, inset=40)

    # 대본이 이미 있으면: 글은 대본 그대로, 시각만 음성 인식으로 맞춘다.
    script_section = folds.add(side.frame, 'script', '대본으로 시간 맞추기 (선택)', place=False)
    side.add(script_section.frame)
    script = script_section.body
    # 진행 방식 두 가지를 서로 다른 단추로: 번호·이름·한 줄 설명이 다르고, 고른 방식은 채운 단추로 바뀐다.
    w.subtitle_mode_buttons = {}
    for key, name, hint, command in (
            ('home', '① 한 폴더 — 대본과 영상이 함께', '대본 폴더 안의 영상·음성과 짝지어 바로 준비합니다.',
             w.choose_subtitle_script_home),
            ('split', '② 따로 — 대본 폴더만 고르기', '영상·음성 폴더는 왼쪽 [폴더 선택…]에서 따로 고릅니다.',
             w.choose_subtitle_script_folder)):
        way = ttk.Frame(script); way.pack(fill='x', pady=(0, 6))
        button = ttk.Button(way, text=name + ' …', style='Mode.TButton', command=command)
        button.pack(fill='x')
        hint_label = ttk.Label(way, text=hint, style='Muted.TLabel', justify='left', wraplength=400)
        hint_label.pack(anchor='w', padx=(4, 0), pady=(2, 0)); wrap_to_parent(hint_label, inset=10, minimum=200)
        w.subtitle_mode_buttons[key] = button
    row = ttk.Frame(script); row.pack(fill='x', pady=(2, 0))
    ttk.Entry(row, textvariable=w.subtitle_script).pack(side='left', fill='x', expand=True)
    w.subtitle_mode_buttons['file'] = ttk.Button(row, text='대본 파일 하나…', command=w.choose_subtitle_script)
    w.subtitle_mode_buttons['file'].pack(side='left', padx=(6, 0))
    ttk.Button(row, text='지우기', command=lambda: w.subtitle_script.set('')).pack(side='left', padx=(6, 0))
    w.subtitle_mode_label = ttk.Label(script, text='', style='Mode.TLabel')
    w.subtitle_mode_label.pack(anchor='w', pady=(6, 0))
    w.subtitle_script_summary = ttk.Label(script, text='', justify='left', wraplength=400)
    w.subtitle_script_summary.pack(anchor='w', fill='x', pady=(6, 0))
    wrap_to_parent(w.subtitle_script_summary, inset=10, minimum=200)
    label = ttk.Label(script, text='자막 글은 대본 그대로, 시각만 음성에서 맞춥니다. 같은 이름끼리 짝짓고(1화.mp4 ↔ '
                                   '1화.txt) 대본 한 줄은 새 자막에서 시작하며 [괄호] 지문 줄은 뺍니다. 같은 이름의 자막은 '
                                   '"영상.<언어>.srt"(모르면 .og)로 보관하고, 음성에서 찾지 못한 줄은 검토 목록에 알립니다.',
                      style='Muted.TLabel', justify='left', wraplength=400)
    label.pack(anchor='w', fill='x', pady=(6, 0)); wrap_to_parent(label, inset=10, minimum=200)

    # 번역 자막: 기존 번역 도구(로컬 LLM)를 그대로 쓴다.
    link = folds.add(body, 'translate', '번역 자막').body
    _check(link, '번역 자막도 함께 만들기', w.subtitle_translate,
           '원어 자막을 만든 뒤 [파일 번역] 도구로 번역하고, 번역 언어의 줄 길이 규칙으로 다시 나눕니다. '
           '원어 자막과 번역 자막을 모두 원본 옆에 저장합니다.')
    w.subtitle_translate_options = ttk.Frame(link)
    row = ttk.Frame(w.subtitle_translate_options); row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='번역 언어').pack(side='left')
    ttk.Combobox(row, textvariable=w.subtitle_target, values=TARGET_LABELS, state='readonly',
                 width=14).pack(side='left', padx=(6, 14))
    ttk.Label(row, text='번역 목적').pack(side='left')
    ttk.Combobox(row, textvariable=w.subtitle_style, values=tuple(STYLES), state='readonly',
                 width=16).pack(side='left', padx=(6, 0))
    row = ttk.Frame(w.subtitle_translate_options); row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='번역 모델').pack(side='left')
    ttk.Button(row, text='↻', width=3, command=w.refresh_subtitle_llms).pack(side='right', padx=(4, 0))
    w.subtitle_llm_box = ttk.Combobox(row, textvariable=w.subtitle_llm, values=(), state='readonly')
    w.subtitle_llm_box.pack(side='left', fill='x', expand=True, padx=(6, 0))
    _check(w.subtitle_translate_options, '번역 자막을 원본 이름으로 저장', w.subtitle_main_name,
           '번역 자막이 "영상.srt"가 되어 재생기가 바로 불러오고, 원어 자막은 "영상.<원어>.srt"(예: 영상.ja.srt)로 '
           '저장합니다. 끄면 원어 자막이 "영상.srt", 번역 자막이 "영상.<번역 언어>.srt"입니다.')
    _check(w.subtitle_translate_options, '영상·음성 파일 이름도 번역', w.subtitle_translate_name,
           '영상·음성 파일 이름을 번역 언어로 바꾸고 자막도 그 이름을 씁니다(재생기가 자막을 그대로 불러옴). '
           '이름 속 번호·코드는 그대로 두고, 이미 번역 언어인 이름은 바꾸지 않습니다. 바꾼 이름은 검토 내역에 적습니다.')
    w.subtitle_translate.trace_add('write', lambda *_: w.toggle_subtitle_translation())

    w.subtitle_advanced_button = ttk.Button(body, text='고급 설정 ▸', command=w.toggle_subtitle_advanced)
    w.subtitle_advanced_button.pack(anchor='w', pady=(0, 6))
    advanced = ttk.Frame(body); w.subtitle_advanced = advanced
    options = folds.add(advanced, 'rules', '인식 · 자막 규칙').body
    for label, variable, values in (('인식 품질', w.subtitle_quality, tuple(QUALITIES)),
                                    ('최대 줄 수', w.subtitle_lines, tuple(LINES))):
        row = line(options, label)
        ttk.Combobox(row, textvariable=variable, values=values, state='readonly').pack(
            side='left', fill='x', expand=True)
    row = line(options, '줄 글자 수')
    ttk.Combobox(row, textvariable=w.subtitle_chars, values=('자동',) + tuple(str(n) for n in range(10, 61, 2)),
                 width=8).pack(side='left')
    ttk.Label(row, text='자동: 한국어·중국어 16, 일본어 13, 영어 등 42자', style='Muted.TLabel').pack(
        side='left', padx=(8, 0))
    _check(options, '음성 구간 감지(VAD)', w.subtitle_vad,
           '말소리가 없는 구간을 먼저 걸러 내 무음·음악에서 문장을 지어내는 현상을 크게 줄입니다.')
    _check(options, '작은 목소리 우선 (누락 줄이기)', w.subtitle_sensitive,
           '말소리 감지를 더 민감하게 합니다. 작게 말하거나 다른 언어가 섞인 영상에서 빠지는 대사가 줄지만, '
           '깨끗한 녹음은 오히려 인식이 조금 나빠질 수 있어 기본은 꺼 둡니다.')
    _check(options, '효과음·음악 표기 유지', w.subtitle_keep_sounds,
           '[음악] (박수) ♪ 같은 소리 묘사를 자막에 남깁니다(청각 장애인용 자막). 끄면 대사만 남깁니다.')
    _check(options, 'GPU 사용', w.subtitle_gpu,
           'NVIDIA GPU 빌드가 있으면 사용하고, 실패하면 자동으로 CPU로 다시 실행합니다.')
    hint = folds.add(advanced, 'hint', '용어 힌트').body
    note(hint, '등장인물·고유명사·전문 용어를 적으면 그 철자로 받아 적을 확률이 높아집니다. '
               '예: 사토 유키, LocalAI, 쿠버네티스')
    w.subtitle_prompt_text = text_box(hint, height=2, expand=False)
    w.subtitle_prompt_text.configure(state='normal')

    preview_section = folds.add(body, 'preview', '미리보기 · 검토', padding=6, pady=(0, 6))
    notebook = ttk.Notebook(preview_section.body); notebook.pack(fill='x')
    preview, translated, report = ttk.Frame(notebook), ttk.Frame(notebook), ttk.Frame(notebook)
    notebook.add(preview, text='자막'); notebook.add(translated, text='번역 자막')
    notebook.add(report, text='검토 · 정리 내역')
    terms = ttk.Frame(notebook, padding=8); notebook.add(terms, text='용어 사전 수정')
    w.subtitle_terms_editor = GlossaryEditor(
        terms, w.root, on_apply=w.apply_subtitle_terms,
        remember_label='고정 용어집에도 추가([파일 번역]과 함께 쓰며 다음 번역에도 적용)')
    w.subtitle_preview_text = text_box(preview, height=12)
    w.subtitle_translated_text = text_box(translated, height=12)
    w.subtitle_report_text = text_box(report, height=12)
    w.subtitle_tabs = notebook
    set_text(w.subtitle_preview_text, '만든 자막이 여기에 표시됩니다. 인식 중에는 받아 적는 문장이 차례로 나타납니다.')
    set_text(w.subtitle_translated_text, '[번역 자막도 함께 만들기]를 켜면 번역 자막이 표시됩니다.')
    set_text(w.subtitle_report_text, '확인이 필요한 자막(인식 확신도 낮음, 읽기 속도 빠름)과 '
                                     '자동으로 지운 반복·환각 문장을 보여 줍니다.')
    for variable in (w.subtitle_path, w.subtitle_script, w.subtitle_translate_name, w.subtitle_model, w.subtitle_translate, w.subtitle_llm, w.subtitle_main_name,
                     w.subtitle_target, w.subtitle_format, w.subtitle_language):
        variable.trace_add('write', lambda *_: w.update_subtitle_destination())
    w.toggle_subtitle_translation()
    w.update_subtitle_destination()
    scroller.bind_content()
