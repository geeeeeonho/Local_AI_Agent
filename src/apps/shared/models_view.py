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

from .widgets import PanelHost, ScrollArea, Disclosure, note, set_text, text_box, wrap_to_parent


def model_display_name(tag, limit=35):
    """Short readable model name for four-column cards.

    Keep both the model family and the quantization/version suffix in view.
    The exact Ollama tag remains available in the model's expanded details.
    """
    name=str(tag).rsplit('/',1)[-1]
    if len(name) <= limit:
        return name
    suffix=12
    return name[:limit-suffix-1] + '…' + name[-suffix:]


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
        self.body = ttk.Frame(self.frame, padding=(2, 2, 2, 4) if compact else (5, 4, 5, 7))
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



class CatalogColumns:
    """Responsive role-card grid: four peers across when space permits.

    A model tag may be very long, so cards use wrapped labels instead of
    forcing the grid columns wider than the viewport. On narrower windows the
    same widgets move to two or one column. No widgets or checkbox variables
    are recreated during a resize.
    """

    MAX_COLUMNS = 4
    MIN_COLUMN_WIDTH = 240

    @classmethod
    def columns_for_width(cls, width):
        # Never squeeze three cards into a width that fits only two legibly.
        width = int(width)
        if width >= 4 * cls.MIN_COLUMN_WIDTH:
            return 4
        return 2 if width >= 2 * cls.MIN_COLUMN_WIDTH else 1

    def __init__(self, parent):
        self.parent = parent
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='x')
        self.slots = []
        self.columns = 0
        self._placed = 0
        # Bind to our own frame, not the persistent ScrollArea.body. The
        # catalogue destroys/recreates this grid on refresh; a parent-bound
        # callback would keep referring to the destroyed grid on every resize.
        self.frame.bind('<Configure>', self._resize, add='+')

    def add(self):
        slot = ttk.Frame(self.frame, padding=(3, 3))
        self.slots.append(slot)
        self.reflow()
        return slot

    def _resize(self, event):
        self.reflow(event.width)

    def reflow(self, width=None):
        if width is None:
            width = self.frame.winfo_width()
        columns = self.columns_for_width(width)
        if columns == self.columns and self._placed == len(self.slots):
            return
        self.columns, self._placed = columns, len(self.slots)
        for slot in self.slots:
            slot.grid_forget()
        for column in range(self.MAX_COLUMNS):
            self.frame.columnconfigure(column, weight=int(column < columns),
                                       minsize=0)
        for index, slot in enumerate(self.slots):
            slot.grid(row=index // columns, column=index % columns,
                      sticky='nsew', padx=2, pady=2)


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

    def fixed(self, build, *, pad=(0, 5)):
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

    def grows(self, build, *, pad=(0, 4)):
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
    summary=ttk.Label(frame,textvariable=w.choice_summary,
                      style='Section.TLabel')
    summary.pack(side='left',anchor='w')
    w.choice_summary_label=summary
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


def _gpu_panel(side, w):
    """VRAM in three comparable 100% bars, always independent of install choices."""
    frame=ttk.Frame(side)
    frame.pack(fill='x',pady=(0,7))
    top=ttk.Frame(frame)
    top.pack(fill='x')
    ttk.Label(top,text='GPU 메모리',style='Section.TLabel').pack(side='left')
    ttk.Button(top,text='↻',width=2,command=w.refresh_gpu_advisor).pack(side='right')
    w.gpu_hardware_line=tk.StringVar(master=w.root,value='GPU 확인 전')
    ttk.Label(frame,textvariable=w.gpu_hardware_line,style='Muted.TLabel',
              wraplength=207,justify='left').pack(anchor='w',pady=(2,4))
    w.gpu_selected_model=tk.StringVar(master=w.root,value='모델을 선택하세요')
    ttk.Label(frame,textvariable=w.gpu_selected_model,style='Manage.Card.TLabel',
              wraplength=207,justify='left').pack(anchor='w',pady=(0,6))

    w.gpu_bars={}
    for key,title in (
        ('used','현재 사용'),('model','선택 모델'),('projected','추가 적재 시'),
    ):
        info=ttk.Frame(frame);info.pack(fill='x')
        ttk.Label(info,text=title,style='Muted.TLabel').pack(side='left')
        number=tk.StringVar(master=w.root,value='확인 전')
        ttk.Label(info,textvariable=number,style='Muted.TLabel').pack(side='right')
        bar=ttk.Progressbar(frame,mode='determinate',maximum=100)
        bar.pack(fill='x',pady=(2,6))
        w.gpu_bars[key]=(bar,number)

    w.gpu_fit_note=tk.StringVar(master=w.root,
        value='모델의 GPU 적재량은 선택해서 확인합니다.')
    note_widget=ttk.Label(frame,textvariable=w.gpu_fit_note,style='Muted.TLabel',
              wraplength=182,justify='left')
    note_widget.pack(anchor='w')
    # Keep wrapped labels within the actual sidebar width, not its desktop size.
    def resize_labels(event):
        width=max(155,frame.winfo_width()-14)
        note_widget.configure(wraplength=width)
    frame.bind('<Configure>',resize_labels,add='+')
    ttk.Separator(side).pack(fill='x',pady=(5,7))


def _selection_toolbar(parent, w):
    """Simple default choice with optional batch selection tools."""
    frame=ttk.Frame(parent)
    main=ttk.Frame(frame)
    main.pack(fill='x')
    _button(main, '권장 세트', lambda: w.set_selection('recommended'), 'Manage')
    _button(main, '새로고침', w.load_catalog)
    details=ttk.Frame(frame)
    expanded=[False]
    def toggle():
        expanded[0]=not expanded[0]
        if expanded[0]:
            details.pack(fill='x',pady=(3,0))
        else:
            details.pack_forget()
        more.configure(text='전체 선택 · 해제 ▾' if expanded[0] else '전체 선택 · 해제 ▸')
    more=ttk.Button(main,text='전체 선택 · 해제 ▸',
                    style='Manage.Details.TButton',command=toggle)
    more.pack(side='right')
    _button(details,'전체 선택',lambda:w.set_selection('all'))
    _button(details,'전체 해제',lambda:w.set_selection('none'))
    return frame


def _disk_toolbar(parent, w):
    """Advanced disk repair actions should never overflow the header."""
    frame=ttk.Frame(parent)
    _bar(frame, (
        ('인덱스 갱신',w.refresh_models,'Manage',False),
        ('모델 고르기',lambda:w.model_tabs.select(w.model_pages['choose']),None,False))).pack(fill='x')
    disclosure=Disclosure(frame,'저장소 · 공용 설정')
    _bar(disclosure.body, (
        ('모든 계정 공용으로 고치기',w.repair_sharing,'Manage',False),
        ('일반 Ollama 경로 연결',w.connect_external_ollama,'Manage',False))).pack(fill='x')
    return frame


def _scroll_frame(parent, w):
    """Catalog on the left, always-visible compact uncatalogued models at right."""
    outer = ttk.Frame(parent)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)
    scroller = ScrollArea(outer, place=False)
    outer.scroller = scroller
    scroller.frame.grid(row=0, column=0, sticky='nsew')
    w.page_scrolls['models.choose'] = scroller
    w.choice_body = scroller.body

    side = ttk.Frame(outer, padding=(4, 2), width=240)
    side.grid(row=0, column=1, sticky='nsew')
    side.grid_propagate(False)
    # The GPU inspector is independently scrollable on very short/high-DPI
    # windows. Its third bar and the extra-model button are never cut off.
    gpu_scroll=ScrollArea(side)
    w.page_scrolls['models.gpu']=gpu_scroll
    side_body=gpu_scroll.body
    _gpu_panel(side_body, w)

    w.uncatalogued_expanded=False
    w.uncatalogued_panel = ScrollArea(side_body)
    w.uncatalogued_body = w.uncatalogued_panel.body
    w.uncatalogued_managed_body = ttk.Frame(w.uncatalogued_body)
    w.uncatalogued_managed_body.pack(fill='x')
    w.uncatalogued_external_body = ttk.Frame(w.uncatalogued_body)
    w.uncatalogued_external_body.pack(fill='x')
    w.uncatalogued_panel.frame.configure(height=160)
    w.uncatalogued_panel.frame.pack_forget()
    def toggle_more():
        w.uncatalogued_expanded=not w.uncatalogued_expanded
        if w.uncatalogued_expanded:
            w.uncatalogued_panel.frame.pack(fill='both',expand=True)
            w.uncatalogued_panel.bind_content()
        else:
            w.uncatalogued_panel.frame.pack_forget()
        more.configure(text='기타 설치 모델 ▾' if w.uncatalogued_expanded
                       else '기타 설치 모델 ▸')
    more=ttk.Button(side_body,text='기타 설치 모델 ▸',
                    style='Manage.Details.TButton',command=toggle_more)
    more.pack(fill='x',anchor='w')
    gpu_scroll.bind_content()
    # On a narrow window return some width to the actual model catalogue.
    def size_side(event):
        wanted=205 if event.width<700 else 240
        if int(side.cget('width'))!=wanted:
            side.configure(width=wanted)
    outer.bind('<Configure>',size_side,add='+')
    return outer


def build(parent, w):
    w.model_tabs = ttk.Notebook(parent)
    w.model_tabs.pack(fill='both', expand=True)
    pages = (('stack', '현재 스택', _stack),
             ('choose', '설치 · 모델 관리', _choose),
             ('disk', '디스크 사용량', _disk))
    w.model_pages = {}
    for key, title, builder in pages:
        page = ttk.Frame(w.model_tabs, padding=(5, 7))
        w.model_tabs.add(page, text=title)
        w.model_pages[key] = page
        builder(page, w)
    # Most users open Models to browse or manage installations. The runtime
    # stack remains one click away, and the Ollama repair action selects it.
    w.model_tabs.select(w.model_pages['choose'])


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
    layout.fixed(lambda box: _selection_toolbar(box,w),pad=(0,3))
    layout.fixed(lambda box: _note(box,
        '체크 = 설치 또는 유지 · GPU에서 보기는 모델 실행 예상량만 확인합니다.'),
        pad=(0,3))
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



def _disk(parent, w):
    layout = Stack(parent)
    layout.fixed(lambda box:_disk_toolbar(box,w),pad=(0,4))
    w.model_summary = tk.StringVar(master=w.root, value=str(w.services.model_dir))
    layout.fixed(lambda box: _label(box, w.model_summary), pad=(0, 4))
    # Whether every Windows account can really use this store is a fact about
    # the machine, not about the path, so it gets its own line and can say it
    # does not know.
    w.sharing_summary = tk.StringVar(master=w.root, value='공용 상태 확인 중...')
    layout.fixed(lambda box: _label(box, w.sharing_summary), pad=(0, 8))
    w.external_store_summary = tk.StringVar(master=w.root, value='일반 Ollama 경로 상태 미확인')
    layout.fixed(lambda box: _label(box, w.external_store_summary), pad=(0, 7))
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
