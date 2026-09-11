"""Small persistent Tk building blocks; no runtime calls."""
import tkinter as tk
from tkinter import ttk

BG = '#10151e'
SURFACE = '#192230'
FG = '#edf2fa'
MUTED = '#a4b2c6'
ACCENT = '#63d3bd'


def theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI',10), background=BG, foreground=FG)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=SURFACE)
    style.configure('Card.TLabel', background=SURFACE, foreground=FG)
    style.configure('TLabel', background=BG, foreground=FG)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Segoe UI',24,'bold'))
    style.configure('Section.TLabel', font=('Segoe UI',12,'bold'))
    style.configure('TButton', padding=(14,9), background=SURFACE, borderwidth=0)
    style.map('TButton',background=[('active','#273a50'),('disabled','#1d2530')])
    style.configure('Accent.TButton', foreground=BG, background=ACCENT)
    style.map('Accent.TButton',background=[('active','#8aebd7'),('disabled','#3a5c58')])
    style.configure('Nav.TButton', anchor='w', padding=(17,12), background=BG)
    style.configure('Selected.Nav.TButton', background=SURFACE, foreground=ACCENT)
    style.configure('TEntry', fieldbackground=SURFACE, foreground=FG, padding=7)
    style.configure('TCombobox', fieldbackground=SURFACE, foreground=FG, padding=7)
    style.map('TCombobox',fieldbackground=[('readonly',SURFACE)],foreground=[('readonly',FG)])
    style.configure('Treeview', fieldbackground=SURFACE, background=SURFACE,
                    foreground=FG, rowheight=32, borderwidth=0)
    style.configure('Treeview.Heading',background='#253246', foreground=FG,padding=8)
    style.map('Treeview',background=[('selected','#28596b')])
    root.option_add('*TCombobox*Listbox.background',SURFACE)
    root.option_add('*TCombobox*Listbox.foreground',FG)


def heading(parent, title, description):
    ttk.Label(parent,text=title,style='Title.TLabel').pack(anchor='w',pady=(0,6))
    ttk.Label(parent,text=description,style='Muted.TLabel',wraplength=760).pack(anchor='w',pady=(0,22))


def note(parent, text):
    ttk.Label(parent,text=text,style='Muted.TLabel',wraplength=780,justify='left').pack(anchor='w',pady=(5,12))


def text_box(parent, *, height=8):
    box=tk.Text(parent,height=height,bg=SURFACE,fg=FG,insertbackground=FG,
                relief='flat',font=('Consolas',10),padx=12,pady=10,wrap='word')
    box.pack(fill='both',expand=True,pady=(8,0))
    box.configure(state='disabled')
    return box


def set_text(box, text):
    box.configure(state='normal');box.delete('1.0','end');box.insert('end',str(text));box.configure(state='disabled')


class PanelHost:
    """Compatibility host for existing Presenter panels, inside one persistent view."""
    def __init__(self,parent):
        self.frame=tk.Frame(parent,bg=BG)
        self.frame.pack(fill='both',expand=True,pady=(12,0))
        self._current=None

    def replace(self, builder):
        if self._current is not None:
            hook=getattr(self._current,'on_destroy',None)
            if callable(hook): hook()
            self._current.destroy()
            self._current=None
        panel=builder(self.frame)
        panel.pack(fill='both',expand=True)
        self._current=panel
        return panel
