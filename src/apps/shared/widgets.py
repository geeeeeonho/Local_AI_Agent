"""Small persistent Tk building blocks; no runtime calls."""
import tkinter as tk
from tkinter import ttk

from .themes import ThemeController, themed


def theme(root, name='dark'):
    controller = getattr(root, '_localai_theme', None)
    if controller is None:
        return ThemeController(root, name)
    controller.apply(name)
    return controller


def heading(parent, title, description, kind=None):
    title_style = kind + '.Title.TLabel' if kind else 'Title.TLabel'
    ttk.Label(parent,text=title,style=title_style).pack(anchor='w',pady=(0,6))
    ttk.Label(parent,text=description,style='Muted.TLabel',wraplength=760).pack(anchor='w',pady=(0,22))


def note(parent, text):
    ttk.Label(parent,text=text,style='Muted.TLabel',wraplength=780,justify='left').pack(anchor='w',pady=(5,12))


def text_box(parent, *, height=8):
    box=themed(tk.Text(parent,height=height,
                relief='flat',font=('Consolas',10),padx=12,pady=10,wrap='word'),
               background='surface', foreground='fg', insertbackground='fg',
               highlightbackground='border', highlightcolor='chat',
               selectbackground='selected', selectforeground='fg')
    box.pack(fill='both',expand=True,pady=(8,0))
    box.configure(state='disabled')
    return box


def set_text(box, text):
    box.configure(state='normal');box.delete('1.0','end');box.insert('end',str(text));box.configure(state='disabled')


class PanelHost:
    """Compatibility host for existing Presenter panels, inside one persistent view."""
    def __init__(self,parent):
        self.frame=themed(tk.Frame(parent), background='bg')
        self._current=None

    def replace(self, builder):
        # Claim layout space only once there is a panel to show; an empty host
        # used to take half the page before a session or action existed.
        if not self.frame.winfo_ismapped():
            self.frame.pack(fill='both',expand=True,pady=(12,0))
        if self._current is not None:
            hook=getattr(self._current,'on_destroy',None)
            if callable(hook): hook()
            self._current.destroy()
            self._current=None
        panel=builder(self.frame)
        panel.pack(fill='both',expand=True)
        self._current=panel
        controller = getattr(self.frame.winfo_toplevel(), '_localai_theme', None)
        if controller is not None:
            controller.refresh(self.frame)
        return panel


class ScrollArea:
    """Keep static forms/actions reachable on small screens and high-DPI text.

    Mouse-wheel handlers are local to this view (never bind_all), while entry
    focus automatically brings the focused control into the visible viewport.
    """
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        self.canvas = themed(tk.Canvas(self.frame, highlightthickness=0, width=1, height=1),
                             background='bg')
        self.bar = ttk.Scrollbar(self.frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, padding=(0, 0, 10, 0))
        self._item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._content_size, add='+')
        self.canvas.bind('<Configure>', self._canvas_size, add='+')

    def _content_size(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _canvas_size(self, event):
        self.canvas.itemconfigure(self._item, width=event.width)

    def _wheel(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return
        delta = getattr(event, 'delta', 0)
        if getattr(event, 'num', None) == 4:
            units = -3
        elif getattr(event, 'num', None) == 5:
            units = 3
        else:
            units = -max(1, abs(int(delta)) // 120) * (1 if delta > 0 else -1)
        self.canvas.yview_scroll(units, 'units')
        return 'break'

    def _focus(self, event):
        control = event.widget
        top = control.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + control.winfo_height()
        height = self.canvas.winfo_height()
        offset = top if top < 0 else bottom - height if bottom > height else 0
        if offset:
            total = max(1, self.body.winfo_height())
            self.canvas.yview_moveto((self.canvas.canvasy(0) + offset) / total)

    def bind_content(self):
        def visit(widget):
            for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                if not isinstance(widget, (ttk.Combobox, tk.Text, tk.Listbox)):
                    widget.bind(sequence, self._wheel, add='+')
            widget.bind('<FocusIn>', self._focus, add='+')
            for child in widget.winfo_children():
                visit(child)
        visit(self.canvas)
