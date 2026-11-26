"""번역 결과의 용어 사전을 보고 고치는 표(번역 도구·자막 도구가 함께 쓴다).

번역이 끝나면 모델이 정한 용어(원문 → 번역)를 보여 준다. 항목을 골라 번역을 고치거나 새 항목을
더한 뒤 [바꾼 용어 적용]을 누르면, 화면이 넘긴 on_apply(바뀐 것들 {원문: 새 번역})가 그 용어가 든
구간만 다시 번역한다. 고친 항목은 굵게 표시하고 [되돌리기]로 원래 값으로 돌릴 수 있다.
"""
import tkinter as tk
from tkinter import ttk

from .widgets import wrap_to_parent


class GlossaryEditor:
    def __init__(self, parent, root, *, on_apply, remember_label='고정 용어집에도 추가(다음 번역에도 적용)'):
        self.on_apply = on_apply
        self.original = {}
        self.current = {}
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        self.note = ttk.Label(self.frame, text='번역을 마치면 원문 용어와 번역이 여기에 표시됩니다.',
                              style='Muted.TLabel', justify='left', wraplength=600)
        self.note.pack(anchor='w', fill='x', pady=(0, 6)); wrap_to_parent(self.note, inset=40)
        self.table = ttk.Treeview(self.frame, columns=('source', 'target'), show='headings', height=7,
                                  selectmode='browse')
        self.table.heading('source', text='원문'); self.table.heading('target', text='번역')
        self.table.column('source', width=220); self.table.column('target', width=260)
        self.table.tag_configure('changed', font=('Segoe UI', 9, 'bold'))
        self.table.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _e: self._selected())
        edit = ttk.Frame(self.frame); edit.pack(fill='x', pady=(6, 0))
        self.source = tk.StringVar(master=root)
        self.target = tk.StringVar(master=root)
        ttk.Label(edit, text='원문').pack(side='left')
        ttk.Entry(edit, textvariable=self.source, width=18).pack(side='left', padx=(4, 8))
        ttk.Label(edit, text='번역').pack(side='left')
        entry = ttk.Entry(edit, textvariable=self.target)
        entry.pack(side='left', fill='x', expand=True, padx=(4, 6))
        entry.bind('<Return>', lambda _e: self.set_term())
        ttk.Button(edit, text='고치기 / 추가', command=self.set_term).pack(side='left')
        ttk.Button(edit, text='되돌리기', command=self.revert).pack(side='left', padx=(4, 0))
        actions = ttk.Frame(self.frame); actions.pack(fill='x', pady=(6, 0))
        self.remember = tk.BooleanVar(master=root, value=True)
        ttk.Checkbutton(actions, text=remember_label, variable=self.remember).pack(side='left')
        self.apply_button = ttk.Button(actions, text='바꾼 용어 적용', style='Accent.TButton',
                                       command=self._apply, state='disabled')
        self.apply_button.pack(side='right')

    def load(self, terms, *, note=''):
        """새 결과의 용어 사전으로 바꾼다(고치던 내용은 버린다)."""
        self.original = dict(terms)
        self.current = dict(terms)
        self._render()
        self.note.configure(text=note or ('용어 %d개. 항목을 골라 번역을 고치거나 새 항목을 더한 뒤 '
                                          '[바꾼 용어 적용]을 누르면 그 용어가 든 줄만 다시 번역합니다.'
                                          % len(terms)))

    def changes(self):
        return {source: target for source, target in self.current.items()
                if target and self.original.get(source) != target}

    def set_term(self):
        source, target = self.source.get().strip(), self.target.get().strip()
        if source and target:
            self.current[source] = target
            self._render(select=source)

    def revert(self):
        source = self.source.get().strip()
        if source in self.original:
            self.current[source] = self.original[source]
        else:
            self.current.pop(source, None)
        self._render(select=source if source in self.current else None)

    def busy(self, value):
        self.apply_button.configure(state='disabled' if value or not self.changes() else 'normal')

    def _selected(self):
        selected = self.table.selection()
        if selected:
            source = self.table.item(selected[0], 'values')[0]
            self.source.set(source)
            self.target.set(self.current.get(source, ''))

    def _render(self, select=None):
        self.table.delete(*self.table.get_children())
        changed = self.changes()
        for source in sorted(self.current, key=lambda key: (key not in changed, key.lower())):
            iid = self.table.insert('', 'end', values=(source, self.current[source]),
                                    tags=('changed',) if source in changed else ())
            if source == select:
                self.table.selection_set(iid)
        self.busy(False)

    def _apply(self):
        changes = self.changes()
        if changes:
            self.on_apply(changes, self.remember.get())
