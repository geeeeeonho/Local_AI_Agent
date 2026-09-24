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


def wrap_to_parent(label, *, inset=40, minimum=280):
    """Re-wrap a label to the width it actually has.

    Every wraplength in this UI was a fixed pixel count (660, 740, 760, 780,
    900) chosen for a wide window. Narrower than that and the text is simply
    cut off mid-sentence, which is how explanations of what a button will do
    went missing exactly on the screens where there was least room.
    """
    def resize(event):
        width = max(minimum, event.width - inset)
        if abs(int(label.cget('wraplength') or 0) - width) > 8:
            label.configure(wraplength=width)
    label.master.bind('<Configure>', resize, add='+')
    return label


def heading(parent, title, description, kind=None):
    title_style = kind + '.Title.TLabel' if kind else 'Title.TLabel'
    ttk.Label(parent,text=title,style=title_style).pack(anchor='w',pady=(0,6))
    text=ttk.Label(parent,text=description,style='Muted.TLabel',wraplength=760,justify='left')
    text.pack(anchor='w',pady=(0,22));wrap_to_parent(text)


def note(parent, text, *, side='top'):
    label=ttk.Label(parent,text=text,style='Muted.TLabel',wraplength=780,justify='left')
    label.pack(anchor='w',pady=(5,12),side=side,fill='x')
    return wrap_to_parent(label)


def text_box(parent, *, height=8, expand=True, side='top', place=True):
    """A read-only box.

    ``expand=False`` keeps its requested height instead of competing with the
    other expanding widget on the page - two boxes both asking left the model
    detail box 26 pixels tall, under two lines, at any window size.
    ``place=False`` returns it unplaced, for a parent laid out with grid.
    """
    box=themed(tk.Text(parent,height=height,
                relief='flat',font=('Consolas',10),padx=12,pady=10,wrap='word'),
               background='surface', foreground='fg', insertbackground='fg',
               highlightbackground='border', highlightcolor='chat',
               selectbackground='selected', selectforeground='fg')
    if place:
        box.pack(fill='both' if expand else 'x',expand=expand,pady=(8,0),side=side)
    box.configure(state='disabled')
    return box


def set_text(box, text):
    box.configure(state='normal');box.delete('1.0','end');box.insert('end',str(text));box.configure(state='disabled')


class PanelHost:
    """Compatibility host for existing Presenter panels, inside one persistent view.

    ``show``/``hide`` are injected because the host lives in pages laid out two
    different ways, and asking pack to place a frame inside a grid-managed
    parent is a Tk error, not a layout quirk.
    """
    def __init__(self,parent,*,show=None,hide=None):
        self.frame=themed(tk.Frame(parent), background='bg')
        self._current=None
        self._show=show if show is not None else (
            lambda frame: frame.pack(fill='both',expand=True,pady=(12,0)))
        self._hide=hide if hide is not None else (lambda frame: frame.pack_forget())

    def replace(self, builder):
        # Claim layout space only once there is a panel to show; an empty host
        # used to take half the page before a session or action existed.
        if not self.frame.winfo_ismapped():
            self._show(self.frame)
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

    def clear(self):
        """Drop the current panel and give the layout space back.

        A cancelled or failed Agent start used to leave the wizard's own
        "준비 중..." progress screen on the page with nothing left to finish it,
        which is indistinguishable from a hang.
        """
        if self._current is not None:
            hook=getattr(self._current,'on_destroy',None)
            if callable(hook):
                try: hook()
                except Exception: pass
            try: self._current.destroy()
            except Exception: pass
            self._current=None
        if self.frame.winfo_ismapped():
            self._hide(self.frame)


class ScrollArea:
    """Keep static forms/actions reachable on small screens and high-DPI text.

    Mouse-wheel handlers are local to this view (never bind_all), while entry
    focus automatically brings the focused control into the visible viewport.
    """
    def __init__(self, parent, *, place=True):
        self.frame = ttk.Frame(parent)
        # ``place=False`` leaves the frame for a grid-managed parent to position;
        # packing into one is a Tk error, not a layout preference.
        if place:
            self.frame.pack(fill='both', expand=True)
        self.canvas = themed(tk.Canvas(self.frame, highlightthickness=0, width=1, height=1),
                             background='bg')
        self.bar = ttk.Scrollbar(self.frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, padding=(0, 0, 10, 0))
        self._item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self._bound = set()
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

    #: Widgets that scroll themselves. The page must not steal their wheel:
    #: a Treeview inside a scrolled page used to scroll the page instead of
    #: its own rows, which is exactly the "the wheel goes somewhere else"
    #: complaint.
    SELF_SCROLLING = (ttk.Combobox, ttk.Treeview, tk.Text, tk.Listbox)

    def bind_content(self):
        """(Re)bind wheel and focus handling for everything now in this area.

        This is called again after content is rebuilt - the model catalogue
        redraws its rows on every refresh - and it used to add another handler
        each time with ``add='+'``, so one notch of the wheel eventually
        scrolled several pages at once.
        """
        bound = self._bound
        def visit(widget):
            key = str(widget)
            if key not in bound:
                bound.add(key)
                if not isinstance(widget, self.SELF_SCROLLING):
                    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                        widget.bind(sequence, self._wheel, add='+')
                widget.bind('<FocusIn>', self._focus, add='+')
            for child in widget.winfo_children():
                visit(child)
        # Widgets destroyed since the last pass must not keep their names alive.
        alive = set()
        def collect(widget):
            alive.add(str(widget))
            for child in widget.winfo_children():
                collect(child)
        collect(self.canvas)
        bound &= alive
        visit(self.canvas)
