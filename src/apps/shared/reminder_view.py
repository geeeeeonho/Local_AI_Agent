"""알림 실행 및 계정별 로그인 시작 설정. 일정 데이터는 CalendarService가 소유합니다."""
import os
import tkinter as tk
from tkinter import ttk, messagebox

from .widgets import ScrollArea, wrap_to_parent


def build(parent, w, toolbar=None):
    manager = w.services.reminders
    service = w.services.calendar
    status = tk.StringVar(master=w.root, value='알림 서비스를 확인하세요.')
    registered = tk.StringVar(master=w.root, value='로그인 자동 실행: 확인 중')
    actions = toolbar if toolbar is not None else ttk.Frame(parent)
    if toolbar is None:
        actions.pack(fill='x')
    ttk.Button(actions, text='지금 알림 실행', command=lambda: start()).pack(side='left')
    ttk.Button(actions, text='상태 확인', command=lambda: refresh()).pack(side='left', padx=(6, 0))

    scroller = ScrollArea(parent)
    w.page_scrolls['tools.reminders'] = scroller
    body = scroller.body
    info = ttk.LabelFrame(body, text='알림 실행기 (LLM 불필요)', padding=12)
    info.pack(fill='x', pady=(0, 10))
    ttk.Label(info, textvariable=registered, style='Section.TLabel').pack(anchor='w', pady=(0, 8))
    desc = ttk.Label(info, text='일정을 저장하는 것만으로 알람이 울리지는 않습니다. '\
                     '지금 실행하거나, 이 Windows 계정 로그인 시 실행하도록 등록하세요. '\
                     'Studio 창을 닫아도 별도 알림 프로세스가 유지됩니다. PC가 꺼져 있거나 '\
                     '잠겨 있는 동안에는 즉시 표시되지 않을 수 있습니다.',
                     style='Muted.TLabel', justify='left', wraplength=650)
    desc.pack(fill='x', anchor='w', pady=(0, 12))
    wrap_to_parent(desc)
    line = ttk.Frame(info)
    line.pack(fill='x')
    ttk.Button(line, text='로그인 시 자동 실행 등록', command=lambda: enable(),
               state='normal' if os.name == 'nt' else 'disabled').pack(side='left')
    ttk.Button(line, text='자동 실행 해제', command=lambda: disable(),
               state='normal' if os.name == 'nt' else 'disabled').pack(side='left', padx=(6, 0))
    detail = ttk.Label(body, textvariable=status, style='Muted.TLabel', wraplength=650)
    detail.pack(fill='x', anchor='w', pady=(0, 8))
    wrap_to_parent(detail)
    table_frame = ttk.LabelFrame(body, text='알림을 설정한 항목', padding=8)
    table_frame.pack(fill='both', expand=True)
    table = ttk.Treeview(table_frame, columns=('when', 'title', 'lead', 'repeat'),
                         show='headings', height=10)
    for name, heading, width in [('when', '기준 시각', 145), ('title', '이름', 260),
                                 ('lead', '알림', 80), ('repeat', '반복', 78)]:
        table.heading(name, text=heading)
        table.column(name, width=width, stretch=name == 'title')
    table.pack(fill='both', expand=True)

    def refresh():
        def loaded(pair):
            enabled, items = pair
            registered.set('로그인 자동 실행: ' + ('등록됨' if enabled else '등록되지 않음'))
            for iid in table.get_children():
                table.delete(iid)
            for item in sorted(items, key=lambda x: x['start_at']):
                lead = item.get('remind_minutes')
                if lead is None or item.get('done'):
                    continue
                desc = '정시' if lead == 0 else f'{lead}분 전'
                table.insert('', 'end', iid=item['id'], values=(
                    item['start_at'].replace('T', ' '), item['title'], desc, item.get('repeat', 'none')))
        w.run_task('tools.reminders.list', lambda: (manager.is_registered(), service.list_items()),
                   loaded, mutate=False, announce=False, error=lambda exc: status.set(str(exc)))

    def start():
        w.run_task('tools.reminders.start', manager.start_now,
                   lambda pid: status.set(f'알림 실행을 요청했습니다 (프로세스 {pid}).'),
                   announce=False, error=lambda exc: status.set(str(exc)))

    def enable():
        if not messagebox.askyesno('알림 자동 실행', '현재 Windows 계정의 로그인 자동 실행에 등록할까요?',
                                   parent=w.root):
            return
        w.run_task('tools.reminders.enable', manager.register,
                   lambda _: (status.set('로그인 자동 실행을 등록했습니다.'), refresh()),
                   announce=False, error=lambda exc: status.set(str(exc)))

    def disable():
        w.run_task('tools.reminders.disable', manager.unregister,
                   lambda _: (status.set('다음 로그인부터 자동 실행하지 않습니다. 이미 실행 중인 프로세스는 유지됩니다.'), refresh()),
                   announce=False, error=lambda exc: status.set(str(exc)))

    w.refresh_reminders_tool = refresh
    scroller.bind_content()