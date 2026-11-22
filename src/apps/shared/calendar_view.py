"""LocalAI Studio Tools: 일정과 할 일. 외부 캘린더/MCP 없이 동작합니다."""
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

from .widgets import ScrollArea, wrap_to_parent

KIND = {'일정': 'event', '할 일': 'task'}
KIND_LABEL = {value: key for key, value in KIND.items()}
REPEAT = {'없음': 'none', '매일': 'daily', '매주': 'weekly', '매월': 'monthly'}
REPEAT_LABEL = {value: key for key, value in REPEAT.items()}
REMIND = {'알림 없음': None, '정시': 0, '5분 전': 5, '10분 전': 10,
          '30분 전': 30, '1시간 전': 60, '하루 전': 1440}
REMIND_LABEL = {value: key for key, value in REMIND.items()}


def build(parent, w, toolbar=None):
    service = w.services.calendar
    state = {'selected': None, 'items': {}}
    start = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)
    title = tk.StringVar(master=w.root)
    kind = tk.StringVar(master=w.root, value='일정')
    date = tk.StringVar(master=w.root, value=start.strftime('%Y-%m-%d'))
    time = tk.StringVar(master=w.root, value=start.strftime('%H:%M'))
    repeat = tk.StringVar(master=w.root, value='없음')
    remind = tk.StringVar(master=w.root, value='10분 전')
    status = tk.StringVar(master=w.root, value='내 PC에만 저장됩니다. LLM 연결은 필요하지 않습니다.')

    controls = toolbar if toolbar is not None else ttk.Frame(parent)
    if toolbar is None:
        controls.pack(fill='x')
    ttk.Button(controls, text='새 일정', command=lambda: clear_form()).pack(side='left')
    ttk.Button(controls, text='새로고침', command=lambda: refresh()).pack(side='left', padx=(6, 0))

    scroller = ScrollArea(parent)
    w.page_scrolls['tools.calendar'] = scroller
    body = scroller.body
    form = ttk.LabelFrame(body, text='일정·할 일 등록 / 수정', padding=12)
    form.pack(fill='x', pady=(0, 8))

    def field(label, variable, *, values=None, width=16):
        row = ttk.Frame(form)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label, width=10).pack(side='left')
        if values:
            entry = ttk.Combobox(row, textvariable=variable, values=values,
                                 state='readonly', width=width)
        else:
            entry = ttk.Entry(row, textvariable=variable, width=width)
        entry.pack(side='left', fill='x', expand=True)
        return entry

    field('제목', title)
    field('유형', kind, values=tuple(KIND))
    field('날짜', date)
    field('시간', time)
    field('반복', repeat, values=tuple(REPEAT))
    field('알림', remind, values=tuple(REMIND))
    ttk.Label(form, text='날짜: YYYY-MM-DD   시간: HH:MM   |   반복은 일정에서만 사용합니다.',
              style='Muted.TLabel').pack(anchor='w', pady=(3, 8))
    note = tk.Text(form, height=3, wrap='word', font=('Segoe UI', 10))
    ttk.Label(form, text='메모 (선택)').pack(anchor='w')
    note.pack(fill='x', pady=(3, 8))
    actions = ttk.Frame(form)
    actions.pack(fill='x')
    ttk.Button(actions, text='저장', style='Accent.TButton', command=lambda: save()).pack(side='left')
    ttk.Button(actions, text='완료/미완료', command=lambda: toggle_done()).pack(side='left', padx=(6, 0))
    ttk.Button(actions, text='삭제', command=lambda: delete()).pack(side='left', padx=(6, 0))
    label = ttk.Label(body, textvariable=status, style='Muted.TLabel', wraplength=660,
                      justify='left')
    label.pack(anchor='w', fill='x', pady=(0, 8))
    wrap_to_parent(label)

    table_container = ttk.LabelFrame(body, text='저장된 일정과 할 일', padding=8)
    table_container.pack(fill='both', expand=True)
    table = ttk.Treeview(table_container, columns=('date', 'type', 'repeat', 'remind', 'state'),
                         show='headings', height=9, selectmode='browse')
    for col, label, width in (
            ('date', '예정 시각', 134), ('type', '분류 / 제목', 260), ('repeat', '반복', 65),
            ('remind', '알림', 86), ('state', '완료', 56)):
        table.heading(col, text=label)
        table.column(col, width=width, minwidth=48, stretch=col == 'type')
    vertical = ttk.Scrollbar(table_container, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=vertical.set)
    table.pack(side='left', fill='both', expand=True)
    vertical.pack(side='right', fill='y')

    def clear_form():
        state['selected'] = None
        table.selection_remove(table.selection())
        title.set('')
        kind.set('일정')
        repeat.set('없음')
        remind.set('10분 전')
        date.set((datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d'))
        time.set((datetime.now() + timedelta(hours=1)).strftime('%H:%M'))
        note.delete('1.0', 'end')
        status.set('새 일정을 입력하세요.')

    def selected(_event=None):
        ids = table.selection()
        if not ids:
            return
        item = state['items'].get(ids[0])
        if not item:
            return
        state['selected'] = ids[0]
        title.set(item['title'])
        kind.set(KIND_LABEL.get(item['kind'], '일정'))
        moment = item['start_at'].replace('T', ' ').split(' ')
        date.set(moment[0])
        time.set(moment[1][:5])
        repeat.set(REPEAT_LABEL.get(item['repeat'], '없음'))
        remind.set(REMIND_LABEL.get(item.get('remind_minutes'), '알림 없음'))
        note.delete('1.0', 'end')
        note.insert('1.0', item.get('note', ''))
        status.set('선택한 항목을 수정하거나 삭제할 수 있습니다.')

    table.bind('<<TreeviewSelect>>', selected)

    def refresh():
        def done(items):
            state['items'] = {item['id']: item for item in items}
            for iid in table.get_children():
                table.delete(iid)
            for item in sorted(items, key=lambda x: (x.get('done', False), x['start_at'])):
                label = ('[할 일] ' if item['kind'] == 'task' else '') + item['title']
                table.insert('', 'end', iid=item['id'], values=(
                    item['start_at'].replace('T', ' '), label,
                    REPEAT_LABEL.get(item.get('repeat'), '없음'),
                    REMIND_LABEL.get(item.get('remind_minutes'), '없음'),
                    '완료' if item.get('done') else ''))
            current = state['selected']
            if current and current in state['items']:
                table.selection_set(current)
            elif current:
                state['selected'] = None
        w.run_task('tools.calendar.list', service.list_items, done,
                   mutate=False, announce=False, error=lambda exc: status.set(str(exc)))

    def _values():
        return dict(title=title.get(), start_at=date.get() + ' ' + time.get(),
                    kind=KIND[kind.get()], repeat=REPEAT[repeat.get()],
                    remind_minutes=REMIND[remind.get()], note=note.get('1.0', 'end').strip())

    def save():
        values = _values()
        identifier = state['selected']
        operation = (lambda: service.update(identifier, **values)) if identifier else (lambda: service.add(**values))
        def finished(_):
            status.set('저장했습니다.')
            refresh()
            if hasattr(w, 'refresh_reminders_tool'):
                w.refresh_reminders_tool()
        w.run_task('tools.calendar.save', operation, finished,
                   error=lambda exc: status.set(str(exc)), announce=False)

    def delete():
        identifier = state['selected']
        if not identifier:
            status.set('먼저 목록에서 일정을 선택하세요.')
            return
        if not messagebox.askyesno('일정 삭제', '선택한 일정을 삭제하시겠습니까?', parent=w.root):
            return
        def finished(_):
            clear_form()
            refresh()
        w.run_task('tools.calendar.delete', lambda: service.delete(identifier), finished,
                   error=lambda exc: status.set(str(exc)), announce=False)

    def toggle_done():
        identifier = state['selected']
        item = state['items'].get(identifier)
        if not item or item['kind'] != 'task':
            status.set('할 일 항목을 선택하면 완료 상태를 바꿀 수 있습니다.')
            return
        w.run_task('tools.calendar.done', lambda: service.set_done(identifier, not item.get('done', False)),
                   lambda _: refresh(), error=lambda exc: status.set(str(exc)), announce=False)

    w.refresh_calendar_tool = refresh
    scroller.bind_content()