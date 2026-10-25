"""One model screen: what loads now, what to get, and what is on disk.

This replaces the split between the retained launcher's "installed model info"
and "model management" menu items. Both answered half a question, so choosing a
model meant reading one screen and typing a tag into another.

Checked means "should exist": check to install, uncheck an installed model to
remove it. This is the only interactive model manager; installation no longer
opens a second selection dialog. Nothing here deletes blob files directly;
Ollama still owns the store.
"""
import tkinter as tk
from tkinter import ttk

from .widgets import PanelHost, ScrollArea, note, set_text, text_box, wrap_to_parent


class ModelAccordion:
    """Independently foldable, keyboard-operable section for the model picker.

    Bodies are hidden with pack_forget, never destroyed, so checkboxes keep
    their Tk variables and selections while their section is collapsed.
    """

    def __init__(self, parent, title, *, expanded=False, compact=False,
                 on_change=None):
        self.title = title
        self._expanded = False
        self._on_change = on_change
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='x', pady=(5, 1))
        style = ('Manage.AccordionSmall.TButton' if compact
                 else 'Manage.Accordion.TButton')
        self.button = ttk.Button(self.frame, style=style, command=self.toggle)
        self.button.pack(fill='x')
        self.body = ttk.Frame(self.frame, padding=(14, 3, 0, 5))
        self.set_expanded(expanded, notify=False)

    @property
    def expanded(self):
        return self._expanded

    def set_expanded(self, expanded, *, notify=True):
        expanded = bool(expanded)
        changed = expanded != self._expanded
        if changed:
            if expanded:
                self.body.pack(fill='x', pady=(2, 4))
            else:
                self.body.pack_forget()
        self._expanded = expanded
        self.button.configure(text=('▼  ' if expanded else '▶  ') + self.title)
        if changed and notify and self._on_change:
            self._on_change(expanded)

    def toggle(self):
        self.set_expanded(not self._expanded)


class Stack:
    """Rows stacked top to bottom, where exactly one of them takes the slack.

    ``pack`` distributes what is left over, and when there is nothing left over
    it takes it from whatever it packed last. That is how a button bar ended up
    one pixel tall while still answering clicks from nowhere near where it was
    drawn. ``grid`` with a weight on one row and a floor under every other row
    gives the fixed parts their height first, and only then hands the remainder
    to the content.
    """

    def __init__(self, parent):
        self.parent = parent
        self.row = 0
        parent.columnconfigure(0, weight=1)

    def fixed(self, build, *, pad=(0, 10)):
        """One row that keeps the height it asks for, whatever else happens.

        "Asks for" is re-read whenever the widget changes, not frozen at build
        time. Several of these rows are labels driven by a ``StringVar``: they
        are measured empty, then filled with a path or a three-line download
        plan, then cleared again. A height reserved once is wrong twice - and
        when it is wrong high, the row it steals from is the list this screen
        exists to show.
        """
        widget = build(self.parent)
        row, extra = self.row, pad[0] + pad[1]
        widget.grid(row=row, column=0, sticky='ew', pady=pad)

        def remeasure(event=None):
            wanted = widget.winfo_reqheight() + extra
            current = self.parent.grid_rowconfigure(row).get('minsize') or 0
            if abs(int(current) - wanted) > 1:
                self.parent.rowconfigure(row, minsize=wanted)

        self.parent.update_idletasks()
        self.parent.rowconfigure(self.row, weight=0)
        remeasure()
        # Only when the widget itself resizes, so this settles instead of
        # bouncing: the write is skipped once the two agree.
        widget.bind('<Configure>', remeasure, add='+')
        self.row += 1
        return widget

    def grows(self, build, *, pad=(0, 8)):
        """The one row that absorbs and gives up space."""
        widget = build(self.parent)
        widget.grid(row=self.row, column=0, sticky='nsew', pady=pad)
        self.parent.rowconfigure(self.row, weight=1, minsize=80)
        self.row += 1
        return widget

    def host(self):
        """A PanelHost row that takes no space until something is put in it."""
        row = self.row
        self.row += 1
        def show(frame):
            frame.grid(row=row, column=0, sticky='nsew', pady=(12, 0))
            self.parent.rowconfigure(row, weight=1, minsize=120)
        def hide(frame):
            frame.grid_remove()
            self.parent.rowconfigure(row, weight=0, minsize=0)
        return PanelHost(self.parent, show=show, hide=hide)


def _bar(parent, buttons):
    """A row of buttons. ``frame.buttons`` is how a caller reaches them.

    Stack places the row, so a builder can only hand back the frame - and a
    caller that stored the return value as "the button" was then calling
    ``state()`` on a frame, which ttk accepts in silence. The apply button
    simply stopped being disabled when there was nothing to apply.
    """
    frame = ttk.Frame(parent)
    frame.buttons = [_button(frame, text, command, kind=kind, accent=accent)
                     for text, command, kind, accent in buttons]
    return frame


def _label(parent, variable, style='Muted.TLabel'):
    label = ttk.Label(parent, textvariable=variable, style=style,
                      wraplength=780, justify='left')
    return wrap_to_parent(label)


def _note(parent, text):
    label = ttk.Label(parent, text=text, style='Muted.TLabel',
                      wraplength=780, justify='left')
    return wrap_to_parent(label)


def _row(parent, *, side='top'):
    """A bar of controls.

    ``side='bottom'`` reserves the bar's height before the expanding content
    gets any: packed after a tree or a text box that asks to expand, the bar is
    the first thing the layout starves, and at the window's own minimum size
    these buttons shrank to four pixels - still there, still "clickable", but
    nowhere near where they looked.
    """
    frame = ttk.Frame(parent)
    frame.pack(fill='x', pady=(0, 10), side=side)
    return frame


def _button(parent, text, command, kind=None, accent=False):
    style = kind + '.TButton' if kind else ('Accent.TButton' if accent else 'TButton')
    widget = ttk.Button(parent, text=text, command=command, style=style)
    widget.pack(side='left', padx=(0, 8))
    return widget


def _apply_row(parent, w):
    """The apply button, and beside it what applying would download."""
    frame = _bar(parent, (('선택대로 적용', w.apply_selection, None, True),))
    plan = ttk.Label(frame, textvariable=w.choice_plan, style='Muted.TLabel',
                     wraplength=560, justify='left')
    plan.pack(side='left', anchor='w', padx=(4, 0))
    w.choice_plan_label = wrap_to_parent(plan, inset=260, minimum=200)
    return frame


def _progress_row(parent, w):
    """Inline model transfer status; no separate download window."""
    frame = ttk.Frame(parent)
    bar = ttk.Progressbar(frame, mode='determinate', maximum=100)
    bar.pack(side='left', fill='x', expand=True)
    text = ttk.Label(frame, textvariable=w.model_progress_text,
                     style='Muted.TLabel', width=38, anchor='w')
    text.pack(side='left', padx=(10, 0))
    w.model_progress = bar
    return frame


def _summary_row(parent, w):
    """What the catalog says, and where the store is, on one line.

    Left is the count and total; right is the path. They are never both long,
    and the screen below them is a list of twenty-five checkboxes that needs
    every pixel it can get.
    """
    frame = ttk.Frame(parent)
    ttk.Label(frame, textvariable=w.choice_summary,
              style='Section.TLabel').pack(side='left', anchor='w')
    storage = ttk.Label(frame, textvariable=w.choice_storage, style='Muted.TLabel',
                        wraplength=520, justify='right')
    storage.pack(side='right', anchor='e', padx=(12, 0))
    # The path re-wraps with the window like every other explanation here, but
    # to what is left beside the summary rather than to the whole row.
    frame.storage = wrap_to_parent(storage, inset=380, minimum=160)
    return frame


def _tree_frame(parent, columns, headings, widths, height):
    """The tree plus its scrollbar, as one row for :class:`Stack` to place."""
    wrapper = ttk.Frame(parent)
    tree = ttk.Treeview(wrapper, columns=columns, show='headings', height=height)
    for key, title, width in zip(columns, headings, widths):
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=60)
    scroll = ttk.Scrollbar(wrapper, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    tree.pack(fill='both', expand=True)
    # Stack places the frame; the caller wants the tree it contains.
    wrapper.tree = tree
    return wrapper


def _scroll_frame(parent, w):
    scroller = ScrollArea(parent, place=False)
    w.page_scrolls['models.choose'] = scroller
    w.choice_body = scroller.body
    scroller.frame.scroller = scroller
    return scroller.frame


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
    layout = Stack(parent)
    layout.fixed(lambda box: _bar(box, (
        ('상태 새로고침', w.refresh_stack, 'Manage', False),
        ('Ollama 시작 / 확인', w.ensure_ollama, None, False),
        ('받으러 가기', lambda: w.model_tabs.select(w.model_pages['choose']), None, False))))
    w.stack_summary = tk.StringVar(master=w.root,
                                   value='메모리와 설치 상태를 아직 확인하지 않았습니다.')
    layout.fixed(lambda box: _label(box, w.stack_summary))
    w.stack_tree = layout.grows(lambda box: _tree_frame(
        box, ('role', 'model', 'need', 'disk'),
        ('역할', '지금 선택될 모델', '필요 메모리', '디스크'), (170, 430, 110, 90), 6)).tree
    w.stack_tree.bind('<<TreeviewSelect>>', lambda event: w.show_stack_detail())
    w.stack_detail = layout.fixed(lambda box: text_box(box, height=5, place=False))
    set_text(w.stack_detail, '역할을 선택하면 그 역할의 전체 사다리와 각 단계의 설치 여부를 보여 줍니다.')
    w.hosts['models'] = layout.host()
    layout.fixed(lambda box: _note(box,
        '선택 모델은 지금 여유 메모리를 기준으로 기존 실행 사다리가 정합니다. '
        '"모델 고르기"에서 받아 두면 그 단계가 실제로 쓰입니다.'))


def _choose(parent, w):
    layout = Stack(parent)
    layout.fixed(lambda box: _bar(box, (
        ('권장 세트', lambda: w.set_selection('recommended'), 'Manage', False),
        ('전체 선택', lambda: w.set_selection('all'), None, False),
        ('전체 해제', lambda: w.set_selection('none'), None, False),
        ('목록 새로고침', w.load_catalog, None, False))))
    layout.fixed(lambda box: _note(box,
        '역할을 펼쳐 상·중·하 권장 모델을 확인하세요. 각 단계와 추가 옵션도 접거나 펼칠 수 있습니다. '
        '같은 모델을 여러 역할에서 선택해도 설치는 한 번만 진행됩니다.'),
        pad=(0, 6))
    # Two lines that each said one short thing, stacked above the list. On a
    # laptop that list had ninety-nine pixels to show twenty-five models in,
    # so the header shares one row and gives the rest back.
    w.choice_summary = tk.StringVar(master=w.root, value='카탈로그를 아직 읽지 않았습니다.')
    w.choice_storage = tk.StringVar(master=w.root, value='')
    header = layout.fixed(lambda box: _summary_row(box, w), pad=(0, 6))
    w.choice_storage_label = header.storage
    w.choice_scroller = layout.grows(lambda box: _scroll_frame(box, w)).scroller
    w.choice_vars = {}
    ttk.Label(w.choice_body, text='카탈로그를 읽는 중...', style='Muted.TLabel').pack(anchor='w')
    # The action this whole screen exists for. It is a fixed row, so it cannot
    # be the thing the layout gives up when the window is small - and the plan
    # it is about to carry out rides beside it rather than on a row of its own,
    # because that row was three lines tall and the list under it was one.
    w.choice_plan = tk.StringVar(master=w.root, value='')
    w.apply_button = layout.fixed(lambda box: _apply_row(box, w)).buttons[0]
    w.model_progress_text = tk.StringVar(master=w.root, value='대기')
    layout.fixed(lambda box: _progress_row(box, w), pad=(0, 6))
    # One line, not three. The rule is the whole explanation; the rest was
    # detail that cost the list two more rows every time the screen opened.
    layout.fixed(lambda box: _note(box,
        '체크 = 있어야 함 · 체크하면 설치하고, 설치된 모델의 체크를 풀면 삭제합니다.'),
        pad=(0, 4))


def _disk(parent, w):
    layout = Stack(parent)
    layout.fixed(lambda box: _bar(box, (
        ('인덱스 갱신', w.refresh_models, 'Manage', False),
        ('모델 고르기', lambda: w.model_tabs.select(w.model_pages['choose']), None, False),
        ('모든 계정 공용으로 고치기', w.repair_sharing, 'Manage', False))))
    w.model_summary = tk.StringVar(master=w.root, value=str(w.services.model_dir))
    layout.fixed(lambda box: _label(box, w.model_summary), pad=(0, 4))
    # Whether every Windows account can really use this store is a fact about
    # the machine, not about the path, so it gets its own line and can say it
    # does not know.
    w.sharing_summary = tk.StringVar(master=w.root, value='공용 상태 확인 중...')
    layout.fixed(lambda box: _label(box, w.sharing_summary), pad=(0, 8))
    w.model_tree = layout.grows(lambda box: _tree_frame(
        box, ('name', 'size', 'shared', 'exclusive', 'status'),
        ('Model', 'Size (GiB)', 'Shared', 'Exclusive', 'Files'),
        (330, 100, 100, 100, 140), 7)).tree
    w.model_tree.bind('<<TreeviewSelect>>', lambda event: w.show_model_details())
    w.model_details = layout.fixed(lambda box: text_box(box, height=6, place=False))
    set_text(w.model_details, '모델을 선택하면 manifest와 blob 구성을 보여 줍니다.\n'
                              '참조 없는 파일은 관찰 결과일 뿐, 삭제 허가가 아닙니다.')
    layout.fixed(lambda box: _note(box,
        '모든 모델은 이 한 곳에 모입니다. 파일을 직접 지우지 마세요 — '
        '여러 모델이 같은 계층을 공유합니다.'))
