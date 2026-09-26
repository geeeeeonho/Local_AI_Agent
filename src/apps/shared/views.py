"""Persistent view construction. User actions are delegated to the shared shell."""
import tkinter as tk
from tkinter import ttk, filedialog
from .widgets import (heading, note, text_box, PanelHost, ScrollArea, set_text,
                      status_line)
from .specs import LABELS, DESCRIPTIONS
from . import models_view


def row(parent):
    frame=ttk.Frame(parent);frame.pack(fill='x',pady=(0,10));return frame


def button(parent,text,fn,accent=False,kind=None):
    style = kind + '.TButton' if kind else ('Accent.TButton' if accent else 'TButton')
    b=ttk.Button(parent,text=text,command=fn,style=style)
    b.pack(side='left',padx=(0,8));return b


def mode_row(parent,w):
    r=row(parent)
    ttk.Label(r,text='Session network').pack(side='left',padx=(0,10))
    ttk.Combobox(r,textvariable=w.session_mode,state='readonly',width=13,
                 values=('inherit','warp','tor','direct','block')).pack(side='left')
    return r


def home(parent,w):
    note(parent,'주요 작업은 Chat과 Agent에서. 준비가 필요할 때만 모델을 관리하세요.')
    tasks=ttk.Frame(parent);tasks.pack(fill='x',pady=(4,20))
    tasks.columnconfigure((0,1),weight=1,uniform='main')
    for column,key in enumerate(('chat','agent')):
        kind=key.title()
        card=ttk.Frame(tasks,style=kind+'.Card.TFrame',padding=24)
        card.grid(row=0,column=column,sticky='nsew',padx=(0,8) if column==0 else (8,0))
        ttk.Label(card,text='01 / CHAT' if key=='chat' else '02 / AGENT',
                  style=kind+'.Card.TLabel',font=('Segoe UI',11,'bold')).pack(anchor='w')
        title='대화와 문서' if key=='chat' else '코딩과 자동화'
        detail=('프로젝트 · Workspace · RAG\nAnythingLLM에서 함께 관리합니다.' if key=='chat' else
                '명령 · 파일 변경 · 승인\nOpen Interpreter로 작업합니다.')
        ttk.Label(card,text=title,style=kind+'.Card.TLabel',font=('Segoe UI',19,'bold')).pack(anchor='w',pady=(12,10))
        ttk.Label(card,text=detail,style=kind+'.CardMuted.TLabel',wraplength=330,justify='left').pack(anchor='w',pady=(0,22))
        ttk.Button(card,text=kind+' 열기',style=kind+'.TButton',command=lambda k=key:w.navigate(k)).pack(anchor='w')
    card=ttk.Frame(parent,style='Manage.Card.TFrame',padding=18);card.pack(fill='x',pady=(0,18))
    ttk.Label(card,text='모델 · 설치 관리',style='Manage.Card.TLabel',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(card,text='모델 용량 확인, 설치와 삭제, 실행 환경 복구',style='Manage.CardMuted.TLabel').pack(anchor='w',pady=(6,14))
    actions=ttk.Frame(card,style='Manage.CardBody.TFrame');actions.pack(anchor='w')
    button(actions,'모델 보기',lambda:w.navigate('models'),kind='Manage')
    button(actions,'설치 / 복구',lambda:w.navigate('setup'),kind='Manage')
    note(parent,'모델과 문서는 기존 위치를 유지합니다. 화면 이동은 실행 중인 세션을 중단하지 않습니다.')


def link_selector(parent,w):
    r=row(parent)
    ttk.Label(r,text='Agent 연결 (선택)',style='Muted.TLabel').pack(side='left',padx=(0,10))
    box=ttk.Combobox(r,textvariable=w.project_id,state='readonly',values=('(none)',),width=24)
    box.pack(side='left')
    box.bind('<<ComboboxSelected>>',lambda event:w.project_selected())
    w.project_boxes.append(box)
    if not hasattr(w,'project_box'):w.project_box=box
    return r


def chat(parent,w):
    w.chat_tabs=ttk.Notebook(parent);w.chat_tabs.pack(fill='both',expand=True)
    main=ttk.Frame(w.chat_tabs,padding=(4,16))
    w.chat_links_page=ttk.Frame(w.chat_tabs,padding=(4,16))
    w.chat_tabs.add(main,text='대화 · Workspace')
    w.chat_tabs.add(w.chat_links_page,text='Agent 연결 (선택)')
    content=ScrollArea(main);w.page_scrolls['chat.main']=content
    main=content.body
    mode_row(main,w)
    r=row(main)
    button(r,'Chat 시작',w.start_chat,kind='Chat')
    w.chat_open_button=button(r,'대화 화면 열기',w.open_chat)
    w.chat_open_button.configure(state='disabled')
    button(r,'세션 종료',w.stop_sessions)
    # Right under the buttons it belongs to, and filled in before anything has
    # been pressed: the only signal used to be the open button losing its
    # greyed-out look, which is not something anyone is watching for.
    w.chat_status=status_line(main,w.chat_state)
    card=ttk.Frame(main,style='Chat.Card.TFrame',padding=18);card.pack(fill='x',pady=(8,8))
    ttk.Label(card,text='프로젝트는 Chat 안에서',style='Chat.Card.TLabel',font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(card,text='Workspace를 만들고, 문서와 대화를 AnythingLLM에서 관리합니다.',
              style='Chat.CardMuted.TLabel',wraplength=740).pack(anchor='w',pady=(6,12))
    ttk.Button(card,text='프로젝트 만들기 / 관리',style='Chat.TButton',command=w.manage_chat_projects).pack(anchor='w')
    note(main,'프로젝트 연결은 필수가 아닙니다. AnythingLLM의 대화와 문서 데이터는 복제하지 않습니다.\n'
         'AnythingLLM은 브라우저로 열리며, 테마는 그 화면의 설정을 따릅니다.')
    w.chat_text=text_box(main,height=10)
    set_text(w.chat_text,'Chat 준비 상태 확인 중...\n\n'
             'Chat 시작 시 Network → Ollama → AnythingLLM → 선택 모델 연결을 순서대로 검증합니다.')
    content.bind_content()
    projects(w.chat_links_page,w)


def agent(parent,w):
    link=link_selector(parent,w)
    main=parent
    if 'chat' in w.spec.pages:
        button(link,'Chat에서 연결 관리',w.show_project_links)
    else:
        # Standalone Interpreter retains optional saved linkage without a
        # separate Projects navigation item or another persistent registry.
        w.agent_tabs=ttk.Notebook(parent);w.agent_tabs.pack(fill='both',expand=True)
        main=ttk.Frame(w.agent_tabs,padding=(4,12))
        w.agent_links_page=ttk.Frame(w.agent_tabs,padding=(4,12))
        w.agent_tabs.add(main,text='Agent 실행')
        w.agent_tabs.add(w.agent_links_page,text='Chat 연결 (선택)')
        projects(w.agent_links_page,w)
    r=mode_row(main,w)
    button(r,'Agent 시작',w.start_agent,kind='Agent')
    button(r,'세션 종료',w.stop_sessions)
    w.agent_status=status_line(main,w.agent_state)
    note(main,'기존 프로필 / 모델 / Host·Sandbox / 폴더 선택과 승인 절차를 유지합니다.\n'
         '연결 폴더는 선택 창의 기본값이며, 자동 접근 허용이 아닙니다.')
    w.hosts['agent']=PanelHost(main)


def projects(parent,w):
    scroller=ScrollArea(parent);w.page_scrolls['links']=scroller
    parent=scroller.body
    note(parent,'이 화면은 Chat Workspace와 Agent 작업 폴더의 연결 정보만 관리합니다.\n'
         '실제 프로젝트와 문서는 AnythingLLM 안에서 만들고 관리하세요.')
    selector=link_selector(parent,w)
    button(selector,'새 연결',w.new_project_link)
    w.project_fields={key:tk.StringVar(master=w.root,value='inherit' if key=='network_mode' else '')
                      for key in ('id','name','workspace_path','anythingllm_workspace','chat_model','agent_model','network_mode')}
    labels={'id':'연결 ID','name':'이름','workspace_path':'Workspace 폴더',
            'anythingllm_workspace':'AnythingLLM Workspace slug','chat_model':'Chat 모델 (선택)',
            'agent_model':'Agent 모델 참고값','network_mode':'Network override'}
    form=ttk.Frame(parent);form.pack(fill='x')
    for index,(key,value) in enumerate(w.project_fields.items()):
        ttk.Label(form,text=labels[key]).grid(row=index,column=0,sticky='w',padx=(0,16),pady=6)
        field=ttk.Combobox(form,textvariable=value,values=('inherit','warp','tor','direct','block'),state='readonly') if key=='network_mode' else ttk.Entry(form,textvariable=value)
        field.grid(row=index,column=1,sticky='ew',pady=6)
    form.columnconfigure(1,weight=1)
    def choose():
        value=filedialog.askdirectory(parent=w.root,mustexist=True)
        if value:w.project_fields['workspace_path'].set(value)
    r=row(parent)
    button(r,'폴더 선택',choose)
    button(r,'저장',w.save_project,True)
    button(r,'연결 삭제',w.delete_project,kind='Danger')
    note(parent,'연결 정보만 저장합니다. Workspace 내용이나 AnythingLLM 데이터는 이동·삭제하지 않습니다.\n'
         'Agent 모델은 시작 설정에서 다시 확인하세요.')

    scroller.bind_content()


def models(parent,w):
    models_view.build(parent,w)


def network(parent,w):
    note(parent,'Direct = 인터넷 직접 연결\nWARP / Tor = 관리형 프록시 준비 실패 시 실행 중단\n'
         'Block = 공용 웹 egress 차단, 검색 비활성, Host Block 거부\n\n'
         '이 버전은 동일 프로젝트의 한 창이 관리형 실행을 소유합니다. 다른 창은 조회할 수 있으며, '
         '소유 창의 세션을 종료한 뒤 변경할 수 있습니다.')
    r=row(parent);button(r,'상태 확인',lambda:w.refresh_health(fresh=True))
    button(r,'정책 설정',lambda:w.navigate('settings'))
    button(r,'세션 종료 / 잠금 해제',w.stop_sessions)
    w.network_text=text_box(parent)
    set_text(w.network_text,'No managed session started in this window.')


def system(parent,w):
    r=row(parent);button(r,'상태 새로고침',lambda:w.refresh_health(fresh=True),True)
    button(r,'모델 설치 / 관리',lambda:w.navigate('setup'),kind='Manage')
    w.system_text=text_box(parent)
    set_text(w.system_text,'Environment: '+str(w.services.env)+'\nModels: '+str(w.services.model_dir)+'\nUser data: '+str(w.services.data))


def settings(parent,w):
    ttk.Label(parent,text='화면 테마',style='Section.TLabel').pack(anchor='w',pady=(0,8))
    r=row(parent)
    w.theme_buttons=[]
    for value,label in (('dark','다크'),('light','라이트')):
        choice=ttk.Radiobutton(r,text=label,variable=w.theme_choice,value=value,command=w.save_theme)
        choice.pack(side='left',padx=(0,20));w.theme_buttons.append(choice)
    note(parent,'선택 즉시 적용하고 네 앱의 공통 설정으로 저장합니다. 대화와 작업은 중단하지 않습니다.\n'
         'AnythingLLM 브라우저 화면과 운영체제 대화상자는 각자의 테마 설정을 따릅니다.')
    ttk.Separator(parent).pack(fill='x',pady=(8,20))
    ttk.Label(parent,text='네트워크 정책',style='Section.TLabel').pack(anchor='w',pady=(0,8))
    w.settings_scope=tk.StringVar(master=w.root,value='global')
    w.settings_mode=tk.StringVar(master=w.root,value='warp')
    r=row(parent)
    scope_box=ttk.Combobox(r,textvariable=w.settings_scope,values=('global','studio','chat','interpreter','setup'),state='readonly',width=18)
    scope_box.pack(side='left',padx=(0,12))
    scope_box.bind('<<ComboboxSelected>>',lambda event:w.load_settings())
    ttk.Combobox(r,textvariable=w.settings_mode,values=('warp','tor','direct','block'),state='readonly',width=18).pack(side='left',padx=(0,12))
    button(r,'저장',w.save_settings,True)
    note(parent,'변경은 다음 세션부터 적용됩니다. 실행 중인 서비스의 네트워크를 즉시 바꾸지 않습니다.\n'
         '새 설정이 없으면 기존 런처의 네트워크 설정을 기본값으로 사용합니다.')


def setup(parent,w):
    w.setup_status = tk.StringVar(
        master=w.root,
        value='대기 · 설치 옵션을 고른 뒤 같은 창에서 실행합니다.',
    )
    w.setup_sandbox = tk.BooleanVar(master=w.root, value=True)
    w.setup_build = tk.BooleanVar(master=w.root, value=True)
    w.setup_search = tk.BooleanVar(master=w.root, value=True)

    status_line(parent, w.setup_status)

    card=ttk.Frame(parent,style='Manage.Card.TFrame',padding=18)
    card.pack(fill='x',pady=(8,14))
    ttk.Label(card,text='설치 / 복구 구성',style='Manage.Card.TLabel',
              font=('Segoe UI',12,'bold')).pack(anchor='w')
    ttk.Label(
        card,
        text='Ollama · AnythingLLM · Open Interpreter · WARP는 기본 공용 런타임으로 준비합니다. '
             '아래 선택은 부가 Docker/Search 구성입니다.',
        style='Manage.CardMuted.TLabel',wraplength=720,justify='left',
    ).pack(anchor='w',pady=(6,12))

    options=ttk.Frame(card,style='Manage.CardBody.TFrame')
    options.pack(fill='x')

    def sync_build_choice():
        enabled=w.setup_sandbox.get()
        if not enabled:
            w.setup_build.set(False)
        w.setup_build_check.configure(state='normal' if enabled else 'disabled')

    ttk.Checkbutton(
        options,text='Sandbox 실행 환경 준비',
        variable=w.setup_sandbox,command=sync_build_choice,
        style='Card.TCheckbutton',
    ).pack(anchor='w',pady=3)
    w.setup_build_check=ttk.Checkbutton(
        options,text='Sandbox Docker 이미지 빌드',
        variable=w.setup_build,style='Card.TCheckbutton',
    )
    w.setup_build_check.pack(anchor='w',padx=(24,0),pady=3)
    ttk.Checkbutton(
        options,text='웹 검색 준비 (SearXNG + Tor)',
        variable=w.setup_search,style='Card.TCheckbutton',
    ).pack(anchor='w',pady=3)

    controls=ttk.Frame(card,style='Manage.CardBody.TFrame')
    controls.pack(fill='x',pady=(14,0))
    w.setup_start_button=button(
        controls,'설치 / 복구 실행',w.repair,accent=True,kind='Manage')
    w.setup_cancel_button=button(
        controls,'실행 중단',w.cancel_setup,kind='Danger')
    w.setup_cancel_button.configure(state='disabled')
    button(controls,'기본 선택',w.reset_setup_options)

    note(parent,'별도 설치 콘솔이나 선택창을 열지 않습니다. 진행 로그는 이 창 아래 Activity에 '
         '실시간으로 표시됩니다. 모델은 Models 화면에서 같은 방식으로 선택/다운로드합니다.')

    if 'models' in w.spec.pages:
        card=ttk.Frame(parent,style='Manage.Card.TFrame',padding=18)
        card.pack(fill='x',pady=(4,14))
        ttk.Label(card,text='모델 설치와 삭제',style='Manage.Card.TLabel',
                  font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(card,text='모델 선택 · 설치 · 삭제 · 다운로드 진행률은 Models 한 화면에서 처리합니다.',
                  style='Manage.CardMuted.TLabel',wraplength=700).pack(anchor='w',pady=(6,12))
        ttk.Button(card,text='Models 열기',style='Manage.TButton',
                   command=lambda:w.navigate('models')).pack(anchor='w')

    ttk.Label(parent,text='유지보수',style='Section.TLabel').pack(anchor='w',pady=(8,8))
    r=row(parent)
    for key,text in [('docker_image','Docker 빌드'),('docker_clean','Docker 정리'),
                     ('searxng_action','Search 관리'),('ollama_action','Ollama 확인')]:
        button(r,text,lambda k=key:w.maintenance(k))
    button(r,'설정 화면',lambda:w.navigate('settings'))
    note(parent,'유지보수 메뉴와 체크 선택도 이 Setup 페이지 안에 표시됩니다. '
         '실행 결과는 동일한 로그 영역에 기록됩니다.')
    w.hosts['setup']=PanelHost(parent)


BUILDERS={'home':home,'chat':chat,'agent':agent,'models':models,
          'network':network,'system':system,'settings':settings,'setup':setup}


def build(parent,key,w):
    page=ttk.Frame(parent,padding=(26,24))
    heading(page,LABELS[key],DESCRIPTIONS[key],kind={'chat':'Chat','agent':'Agent','models':'Manage','setup':'Manage'}.get(key))
    if key in ('home','settings','setup','network','system'):
        scroller=ScrollArea(page);w.page_scrolls[key]=scroller
        BUILDERS[key](scroller.body,w)
        scroller.bind_content()
    else:
        BUILDERS[key](page,w)
    return page
