"""Studio Tools: 부가 기능 목록에서 하나를 골라 연다.

도구를 추가할 때는 TOOLS에 (키, 이름, 설명, 화면 builder, 열 때 할 일) 한 줄을 더한다.
builder(frame, w, toolbar)는 화면 본문을 frame에, 실행 버튼을 맨 위 줄의 toolbar에 만든다.
(버튼을 '← 도구 목록'과 같은 줄에 두어 작은 창에서 본문이 쓸 높이를 늘린다.)
각 도구 화면은 처음 열 때 한 번만 만든다.
"""
from dataclasses import dataclass
from typing import Callable
from tkinter import ttk
from . import translation_view
from .widgets import wrap_to_parent


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    description: str
    build: Callable
    on_open: str = ''           # 창(DesktopWindow) 메서드 이름


TOOLS = (
    Tool('translate', '파일 번역',
         '로컬 모델로 TXT·JSON·Markdown·자막을 구조를 지키며 번역합니다. '
         '고정 용어집, 이어하기, 진행률 표시를 지원합니다.',
         translation_view.build, 'translation_opened'),
)


def build(parent, w):
    w.tool_frames, w.tool_toolbars, w.current_tool = {}, {}, None
    hub = ttk.Frame(parent); hub.pack(fill='both', expand=True)
    w.tool_hub, w.tool_area = hub, ttk.Frame(parent)
    ttk.Label(hub, text='사용할 도구를 선택하세요.', style='Section.TLabel').pack(anchor='w', pady=(0, 10))
    for tool in TOOLS:
        card = ttk.Frame(hub, style='Manage.Card.TFrame', padding=16); card.pack(fill='x', pady=(0, 10))
        ttk.Label(card, text=tool.title, style='Manage.Card.TLabel',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        text = ttk.Label(card, text=tool.description, style='Manage.CardMuted.TLabel',
                         justify='left', wraplength=600)
        text.pack(anchor='w', fill='x', pady=(4, 10)); wrap_to_parent(text, inset=50)
        ttk.Button(card, text='열기', style='Accent.TButton',
                   command=lambda key=tool.key: w.open_tool(key)).pack(anchor='w')

    top = ttk.Frame(w.tool_area); top.pack(fill='x', pady=(0, 6))
    ttk.Button(top, text='← 도구 목록', command=w.show_tool_hub).pack(side='left')
    w.tool_title = ttk.Label(top, text='', style='Section.TLabel')
    w.tool_title.pack(side='left', padx=(12, 12))
    w.tool_top = top
    w.tool_body = ttk.Frame(w.tool_area); w.tool_body.pack(fill='both', expand=True)


class ToolsController:
    def open_tool(self, key):
        tool = next(item for item in TOOLS if item.key == key)
        if key not in self.tool_frames:
            frame = ttk.Frame(self.tool_body)
            toolbar = ttk.Frame(self.tool_top)
            tool.build(frame, self, toolbar)
            self.tool_frames[key], self.tool_toolbars[key] = frame, toolbar
        for name, frame in self.tool_frames.items():
            if name != key:
                frame.pack_forget()
                self.tool_toolbars[name].pack_forget()
        self.tool_toolbars[key].pack(side='right')
        self.tool_frames[key].pack(fill='both', expand=True)
        self.tool_title.configure(text=tool.title)
        self.tool_hub.pack_forget()
        self.tool_area.pack(fill='both', expand=True)
        self.current_tool = key
        if tool.on_open:
            getattr(self, tool.on_open)()

    def show_tool_hub(self):
        self.tool_area.pack_forget()
        self.tool_hub.pack(fill='both', expand=True)
        self.current_tool = None
