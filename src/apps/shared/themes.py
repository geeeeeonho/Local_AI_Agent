"""Per-window palettes and live Tk restyling, with no widget reconstruction.

Classic Tk compatibility panels retain text, callbacks, selection and session
identity. Only recognized legacy colors are adapted; danger/warning log tags
remain semantic. External AnythingLLM/browser and native OS dialogs own their
own appearance. Nothing in this module imports a runtime or changes its policy.
"""
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from weakref import WeakKeyDictionary


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    sidebar: str
    input: str
    fg: str
    muted: str
    border: str
    hover: str
    selected: str
    chat: str
    chat_soft: str
    agent: str
    agent_soft: str
    manage: str
    manage_soft: str
    danger: str
    info: str
    warning: str
    success: str
    solid_ink: str


# One restrained blue-gray accent for routine work. Management uses neutral
# surfaces/outlines, not a competing hue. Warm/green tones are reserved for
# actual warnings/success and never used to label an application feature.
PALETTES = {
    'dark': Palette(
        name='dark', bg='#161c25', surface='#1e2733', sidebar='#181f29',
        input='#232e3b', fg='#e6ebf2', muted='#a8b4c4', border='#3a485c',
        hover='#2d3a4b', selected='#34475e',
        chat='#a4b7ce', chat_soft='#222d3b',
        agent='#a4b7ce', agent_soft='#222d3b',
        manage='#b9c1cd', manage_soft='#202832',
        danger='#efa19b', info='#a4b7ce', warning='#d4b98a', success='#9cc6b0',
        solid_ink='#161c25'),
    'light': Palette(
        name='light', bg='#f5f7fa', surface='#ffffff', sidebar='#eef1f5',
        input='#ffffff', fg='#263344', muted='#5a687a', border='#c8d1dd',
        hover='#e5ebf2', selected='#dce5ef',
        chat='#49617d', chat_soft='#edf1f6',
        agent='#49617d', agent_soft='#edf1f6',
        manage='#596776', manage_soft='#f0f2f5',
        danger='#a94448', info='#49617d', warning='#895f26', success='#356e55',
        solid_ink='#ffffff'),
}

# Colors from retained launcher/presenter/gui/theme.py and its log tags. This
# is a compatibility palette, not another execution-policy dependency.
_LEGACY = {
    '#1e1e1e': 'bg', '#252526': 'surface', '#3c3c3c': 'input',
    '#2a2d2e': 'hover', '#37373d': 'selected', '#cccccc': 'fg',
    '#858585': 'muted', '#ffffff': 'fg', '#0e639c': 'agent',
    '#1177bb': 'agent', '#73c991': 'success', '#3794ff': 'info',
    '#f48771': 'danger', '#6e6e6e': 'muted', '#0098ff': 'agent',
    '#e1bda5': 'warning', '#d7ba7d': 'warning',
}
_PALETTE_COLORS = frozenset(value for palette in PALETTES.values()
                            for value in vars(palette).values())
_COLOR_OPTIONS = ('background', 'foreground', 'activebackground',
                  'activeforeground', 'insertbackground', 'selectbackground',
                  'selectforeground', 'disabledforeground',
                  'highlightbackground', 'highlightcolor', 'troughcolor')


class ThemeController:
    def __init__(self, root, name='dark'):
        if name not in PALETTES:
            raise ValueError('unknown desktop theme')
        self.root = root
        self.palette = PALETTES[name]
        self._explicit = WeakKeyDictionary()
        self._legacy = WeakKeyDictionary()
        self._tags = WeakKeyDictionary()
        root._localai_theme = self
        ttk.Style(root).theme_use('clam')
        self.register(root, background='bg')
        # The toplevel bindtag runs after existing per-widget handlers. Panels
        # created later (including the retained Agent) therefore inherit theme.
        root.bind('<Map>', self._mapped, add='+')
        # Legacy hover handlers rewrite their own colors on the widget under the
        # pointer. Restyle exactly that widget; walking its subtree on every
        # mouse crossing made large panels and tables crawl.
        root.bind('<Enter>', self._hovered, add='+')
        root.bind('<Leave>', self._hovered, add='+')
        self.apply(name)

    @property
    def name(self):
        return self.palette.name

    def register(self, widget, **roles):
        for role in roles.values():
            if not hasattr(self.palette, role):
                raise ValueError('unknown theme role: ' + role)
        self._explicit[widget] = roles
        self._style_widget(widget)
        return widget

    def _mapped(self, event):
        if isinstance(event.widget, tk.Misc):
            self.refresh(event.widget)

    def _hovered(self, event):
        if isinstance(event.widget, tk.Misc):
            try:
                self._style_widget(event.widget)
            except tk.TclError:
                return

    def _style_widget(self, widget):
        if not widget.winfo_exists() or isinstance(widget, ttk.Widget):
            return
        explicit = self._explicit.get(widget)
        if explicit is not None:
            widget.configure(**{option: getattr(self.palette, role)
                                for option, role in explicit.items()})
            return
        roles = self._legacy.setdefault(widget, {})
        keys = widget.keys()
        # Registered shell widgets have explicit roles. Unregistered old panels
        # are inferred once; subsequent palette switches use those saved roles.
        for option in _COLOR_OPTIONS:
            if option not in keys:
                continue
            color = str(widget.cget(option)).lower()
            if option not in roles and color in _LEGACY:
                roles[option] = _LEGACY[color]
            elif color in _LEGACY and color not in _PALETTE_COLORS:
                # Legacy hover handlers can write their original colors again.
                roles[option] = _LEGACY[color]
        if isinstance(widget, tk.Button) and roles.get('background') in ('chat', 'agent', 'danger', 'success', 'warning'):
            roles['foreground'] = 'solid_ink'
            roles['activeforeground'] = 'solid_ink'
        if 'selectbackground' in roles:
            roles['selectbackground'] = 'selected'
            if 'selectforeground' in keys:
                roles['selectforeground'] = 'fg'
        widget.configure(**{option: getattr(self.palette, role) for option, role in roles.items()})
        if isinstance(widget, tk.Text):
            tags = self._tags.setdefault(widget, {})
            for tag in widget.tag_names():
                if tag == 'sel':
                    continue
                color = str(widget.tag_cget(tag, 'foreground')).lower()
                if tag not in tags and color in _LEGACY:
                    tags[tag] = _LEGACY[color]
                if tag in tags:
                    widget.tag_configure(tag, foreground=getattr(self.palette, tags[tag]))

    def refresh(self, widget=None):
        """Restyle existing/new panels on Tk's thread without touching contents."""
        widget = self.root if widget is None else widget
        try:
            self._style_widget(widget)
            for child in widget.winfo_children():
                self.refresh(child)
        except tk.TclError:
            # A panel may have been destroyed by its existing UI callback.
            return

    def apply(self, name):
        if name not in PALETTES:
            raise ValueError('unknown desktop theme')
        self.palette = p = PALETTES[name]
        style = ttk.Style(self.root)
        style.configure('.', font=('Segoe UI', 10), background=p.bg, foreground=p.fg)
        style.configure('TFrame', background=p.bg)
        style.configure('TLabel', background=p.bg, foreground=p.fg)
        style.configure('Sidebar.TFrame', background=p.sidebar)
        style.configure('Sidebar.TLabel', background=p.sidebar, foreground=p.muted)
        style.configure('Brand.TLabel', background=p.sidebar, foreground=p.fg, font=('Segoe UI', 18, 'bold'))
        style.configure('Muted.TLabel', foreground=p.muted)
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Section.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Card.TFrame', background=p.surface)
        style.configure('Card.TLabel', background=p.surface)
        style.configure('TSeparator', background=p.border, bordercolor=p.border,
                        lightcolor=p.border, darkcolor=p.border)
        style.map('TSeparator', background=[('disabled', p.border), ('active', p.border)])
        style.configure('TButton', background=p.surface, foreground=p.fg, padding=(14, 9),
                        borderwidth=0, focuscolor=p.chat)
        style.map('TButton', background=[('disabled', p.surface), ('active', p.hover), ('focus', p.hover)],
                  foreground=[('disabled', p.muted)])
        style.configure('Manage.Accordion.TButton', anchor='w',
                        background=p.manage_soft, foreground=p.fg,
                        font=('Segoe UI', 10, 'bold'),
                        padding=(12, 9), borderwidth=0, focuscolor=p.manage)
        style.map('Manage.Accordion.TButton',
                  background=[('active', p.hover), ('focus', p.hover)])
        style.configure('Manage.AccordionSmall.TButton', anchor='w',
                        background=p.surface, foreground=p.fg,
                        padding=(10, 6), borderwidth=0, focuscolor=p.manage)
        style.map('Manage.AccordionSmall.TButton',
                  background=[('active', p.hover), ('focus', p.hover)])
        style.configure('Nav.TButton', anchor='w', background=p.sidebar, padding=(16, 10),
                        focuscolor=p.chat)
        style.map('Nav.TButton', background=[('focus', p.hover), ('active', p.hover)])
        style.configure('Selected.Nav.TButton', background=p.selected)
        for kind in ('Chat', 'Agent', 'Manage'):
            role = kind.lower()
            color, soft = getattr(p, role), getattr(p, role + '_soft')
            primary = kind != 'Manage'
            style.configure(kind + '.TButton',
                            background=color if primary else soft,
                            foreground=p.solid_ink if primary else color,
                            font=('Segoe UI', 11 if primary else 10, 'bold'),
                            padding=(18, 11), bordercolor=p.border,
                            lightcolor=p.border, darkcolor=p.border,
                            borderwidth=0 if primary else 1, relief='flat' if primary else 'solid')
            style.map(kind + '.TButton',
                      background=[('disabled', p.surface), ('active', soft if primary else p.hover)],
                      foreground=[('disabled', p.muted), ('active', color)])
            style.configure(kind + '.Nav.TButton', background=soft, foreground=color,
                            font=('Segoe UI', 13 if primary else 10, 'bold'),
                            padding=(18, 17 if primary else 11))
            style.map(kind + '.Nav.TButton', background=[('disabled', soft), ('active', p.hover)],
                      foreground=[('disabled', p.muted)])
            # Selection stays a quiet surface change, not a large bright block.
            style.configure('Selected.' + kind + '.Nav.TButton', background=p.selected, foreground=color)
            style.map('Selected.' + kind + '.Nav.TButton',
                      background=[('disabled', p.selected), ('active', p.selected)],
                      foreground=[('disabled', p.muted), ('active', color)])
            style.configure(kind + '.Card.TFrame', background=soft, bordercolor=p.border,
                            lightcolor=p.border, darkcolor=p.border, borderwidth=1, relief='solid')
            style.configure(kind + '.CardBody.TFrame', background=soft, borderwidth=0, relief='flat')
            style.configure(kind + '.Card.TLabel', background=soft, foreground=p.fg)
            style.configure(kind + '.CardMuted.TLabel', background=soft, foreground=p.muted)
            style.configure(kind + '.Title.TLabel', foreground=p.fg, font=('Segoe UI', 24, 'bold'))
        # Kept for common save/refresh actions, distinct from destructive actions.
        style.configure('Accent.TButton', background=p.chat, foreground=p.solid_ink)
        style.map('Accent.TButton', background=[('disabled', p.surface), ('active', p.chat_soft)],
                  foreground=[('disabled', p.muted), ('active', p.chat)])
        style.configure('Danger.TButton', foreground=p.danger)
        style.configure('TEntry', fieldbackground=p.input, foreground=p.fg,
                        insertcolor=p.fg, padding=7)
        style.configure('TCombobox', fieldbackground=p.input, background=p.surface, foreground=p.fg, padding=7)
        style.map('TCombobox', fieldbackground=[('readonly', p.input)], foreground=[('readonly', p.fg)])
        style.configure('TRadiobutton', background=p.bg, foreground=p.fg, padding=8)
        style.map('TRadiobutton', background=[('active', p.hover)], foreground=[('disabled', p.muted)])
        # Selection lists use checkbuttons; without these they kept clam's pale
        # beige indicator and an unreadable label on the dark surface.
        for name, ground in (('TCheckbutton', p.bg), ('Card.TCheckbutton', p.manage_soft)):
            style.configure(name, background=ground, foreground=p.fg,
                            indicatorcolor=p.input, indicatorbackground=p.input,
                            focuscolor=p.chat, padding=4)
            style.map(name,
                      background=[('active', ground)],
                      foreground=[('disabled', p.muted)],
                      indicatorcolor=[('selected', p.chat), ('pressed', p.hover)],
                      indicatorbackground=[('selected', p.chat), ('active', p.hover)])
        # Failures need to be legible as failures, not one more muted line.
        style.configure('Alert.TLabel', foreground=p.danger)
        # A readiness line has three states and they have to be told apart at a
        # glance; "the button is no longer greyed out" is not a signal anyone
        # notices while looking at a log.
        style.configure('Waiting.Status.TLabel', foreground=p.muted,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('Working.Status.TLabel', foreground=p.info,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('Ready.Status.TLabel', foreground=p.success,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('Failed.Status.TLabel', foreground=p.danger,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TNotebook', background=p.bg, borderwidth=0)
        style.configure('TNotebook.Tab', background=p.surface, foreground=p.muted, padding=(17, 10))
        style.map('TNotebook.Tab', background=[('selected', p.chat_soft), ('active', p.hover)],
                  foreground=[('selected', p.chat), ('active', p.fg)])
        style.configure('Treeview', fieldbackground=p.surface, background=p.surface,
                        foreground=p.fg, rowheight=32, borderwidth=0)
        style.configure('Treeview.Heading', background=p.sidebar, foreground=p.fg, padding=8)
        style.map('Treeview', background=[('selected', p.selected)], foreground=[('selected', p.fg)])
        for orientation in ('Vertical', 'Horizontal'):
            style.configure(orientation + '.TScrollbar', background=p.border, troughcolor=p.bg,
                            arrowcolor=p.muted, bordercolor=p.border, lightcolor=p.border,
                            darkcolor=p.border, borderwidth=0)
            # Clam's global disabled/active backgrounds are pale beige. Override
            # them as well as the normal state, especially for full-height thumbs.
            style.map(orientation + '.TScrollbar',
                      background=[('disabled', p.surface), ('active', p.hover)],
                      arrowcolor=[('disabled', p.muted), ('active', p.fg)])
        # Set defaults for future combobox popdowns. Existing popdowns are Tcl
        # widgets, not Python children, so refresh their colors explicitly too.
        self.root.option_add('*TCombobox*Listbox.background', p.surface)
        self.root.option_add('*TCombobox*Listbox.foreground', p.fg)
        self.root.option_add('*TCombobox*Listbox.selectBackground', p.selected)
        self.root.option_add('*TCombobox*Listbox.selectForeground', p.fg)
        self._comboboxes(self.root)
        self.refresh()

    def _comboboxes(self, widget):
        if isinstance(widget, ttk.Combobox):
            popdown = str(widget) + '.popdown.f.l'
            if self.root.tk.call('winfo', 'exists', popdown):
                p = self.palette
                self.root.tk.call(popdown, 'configure', '-background', p.surface, '-foreground', p.fg,
                                  '-selectbackground', p.selected, '-selectforeground', p.fg)
        for child in widget.winfo_children():
            self._comboboxes(child)


def themed(widget, **roles):
    controller = getattr(widget.winfo_toplevel(), '_localai_theme', None)
    if controller is not None:
        controller.register(widget, **roles)
    return widget
