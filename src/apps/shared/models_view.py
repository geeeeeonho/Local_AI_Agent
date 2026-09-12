"""One model screen: what loads now, what to get, and what is on disk.

This replaces the split between the retained launcher's "installed model info"
and "model management" menu items. Both answered half a question, so choosing a
model meant reading one screen and typing a tag into another.

Checked means "should exist", the same contract the installer's selection
dialog uses: check to install, uncheck an installed model to remove it. Nothing
here deletes blob files directly; Ollama still owns the store.
"""
import tkinter as tk
from tkinter import ttk

from .widgets import PanelHost, ScrollArea, note, set_text, text_box


def _row(parent):
    frame = ttk.Frame(parent)
    frame.pack(fill='x', pady=(0, 10))
    return frame


def _button(parent, text, command, kind=None, accent=False):
    style = kind + '.TButton' if kind else ('Accent.TButton' if accent else 'TButton')
    widget = ttk.Button(parent, text=text, command=command, style=style)
    widget.pack(side='left', padx=(0, 8))
    return widget


def _tree(parent, columns, headings, widths, height):
    wrapper = ttk.Frame(parent)
    wrapper.pack(fill='both', expand=True)
    tree = ttk.Treeview(wrapper, columns=columns, show='headings', height=height)
    for key, title, width in zip(columns, headings, widths):
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=60)
    scroll = ttk.Scrollbar(wrapper, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    tree.pack(fill='both', expand=True)
    return tree


def build(parent, w):
    w.model_tabs = ttk.Notebook(parent)
    w.model_tabs.pack(fill='both', expand=True)
    pages = (('stack', '현재 스택', _stack),
             ('choose', '모델 고르기', _choose),
             ('disk', '디스크 사용량', _disk))
    w.model_pages = {}
    for key, title, builder in pages:
        page = ttk.Frame(w.model_tabs, padding=(6, 14))
        w.model_tabs.add(page, text=title)
        w.model_pages[key] = page
        builder(page, w)


def _stack(parent, w):
    w.stack_summary = tk.StringVar(master=w.root, value='메모리와 설치 상태를 아직 확인하지 않았습니다.')
    ttk.Label(parent, textvariable=w.stack_summary, style='Muted.TLabel',
              wraplength=780, justify='left').pack(anchor='w', pady=(0, 12))
    w.stack_tree = _tree(parent, ('role', 'model', 'need', 'disk'),
                         ('역할', '지금 선택될 모델', '필요 메모리', '디스크'),
                         (170, 430, 110, 90), 6)
    w.stack_tree.bind('<<TreeviewSelect>>', lambda event: w.show_stack_detail())
    w.stack_detail = text_box(parent, height=6)
    set_text(w.stack_detail, '역할을 선택하면 그 역할의 전체 사다리와 각 단계의 설치 여부를 보여 줍니다.')
    bar = _row(parent)
    _button(bar, '상태 새로고침', w.refresh_stack, kind='Manage')
    _button(bar, 'Ollama 시작 / 확인', w.ensure_ollama)
    _button(bar, '받으러 가기', lambda: w.model_tabs.select(w.model_pages['choose']))
    w.hosts['models'] = PanelHost(parent)
    note(parent, '선택 모델은 지금 여유 메모리를 기준으로 기존 실행 사다리가 정합니다. 이 화면은 그 결과를 '
                 '보여줄 뿐, 별도의 선택 규칙을 두지 않습니다.\n'
                 '디스크에 없는 모델이 선택되어 있으면 실행 시 더 가벼운 단계로 내려갑니다. '
                 '"모델 고르기"에서 받아 두면 그 단계가 실제로 쓰입니다.')


def _choose(parent, w):
    w.choice_summary = tk.StringVar(master=w.root, value='카탈로그를 아직 읽지 않았습니다.')
    ttk.Label(parent, textvariable=w.choice_summary, style='Section.TLabel',
              wraplength=780, justify='left').pack(anchor='w', pady=(0, 6))
    w.choice_plan = tk.StringVar(master=w.root, value='')
    ttk.Label(parent, textvariable=w.choice_plan, style='Muted.TLabel',
              wraplength=780, justify='left').pack(anchor='w', pady=(0, 12))
    bar = _row(parent)
    _button(bar, '권장 세트', lambda: w.set_selection('recommended'), kind='Manage')
    _button(bar, '전체 선택', lambda: w.set_selection('all'))
    _button(bar, '전체 해제', lambda: w.set_selection('none'))
    _button(bar, '목록 새로고침', w.load_catalog)
    scroller = ScrollArea(parent)
    w.page_scrolls['models.choose'] = scroller
    w.choice_body = scroller.body
    w.choice_scroller = scroller
    w.choice_vars = {}
    ttk.Label(w.choice_body, text='카탈로그를 읽는 중...', style='Muted.TLabel').pack(anchor='w')
    apply_bar = _row(parent)
    w.apply_button = _button(apply_bar, '선택대로 적용', w.apply_selection, accent=True)
    note(parent, '체크 = 있어야 함. 체크하면 설치하고, 설치된 모델의 체크를 풀면 삭제합니다.\n'
                 '다운로드는 로컬 Ollama 서버의 호스트 네트워크를 씁니다. WARP/Tor 우회는 보장되지 않고, '
                 'Block에서는 거부합니다.')


def _disk(parent, w):
    bar = _row(parent)
    _button(bar, '인덱스 갱신', w.refresh_models, kind='Manage')
    _button(bar, '모델 고르기', lambda: w.model_tabs.select(w.model_pages['choose']))
    w.model_summary = tk.StringVar(master=w.root, value=str(w.services.model_dir))
    ttk.Label(parent, textvariable=w.model_summary, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
    w.model_tree = _tree(parent, ('name', 'size', 'shared', 'exclusive', 'status'),
                         ('Model', 'Size (GiB)', 'Shared', 'Exclusive', 'Files'),
                         (330, 100, 100, 100, 140), 7)
    w.model_tree.bind('<<TreeviewSelect>>', lambda event: w.show_model_details())
    w.model_details = text_box(parent, height=7)
    set_text(w.model_details, '모델을 선택하면 manifest와 blob 구성을 보여 줍니다.\n'
                              '참조 없는 파일은 관찰 결과일 뿐, 삭제 허가가 아닙니다.')
