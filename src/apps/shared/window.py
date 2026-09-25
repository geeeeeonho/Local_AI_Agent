"""One persistent desktop shell. Every runtime operation goes through services."""
from __future__ import annotations
import json
import queue
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from types import SimpleNamespace
import webbrowser
from core.projects.model import Project
from core.urls import local_url
from .specs import SPECS, LABELS, navigation_groups, nav_style
from .tasks import TaskRunner
from core.window_size import ACTIVITY_LINES, activity_lines
from .widgets import (opening_geometry, set_text, set_status, theme,
                      wrap_to_parent)
from .themes import themed
from . import views


class DesktopWindow:
    def __init__(self, app, services, *, root=None, start_polling=True):
        self.app, self.spec, self.services = app, SPECS[app], services
        self.root = root if root is not None else tk.Tk()
        appearance_error = None
        try:
            appearance = services.settings.theme()
        except (OSError, ValueError) as exc:
            appearance, appearance_error = 'dark', str(exc)
        self.theme = theme(self.root, appearance)
        self.theme_choice = tk.StringVar(master=self.root, value=appearance)
        self._appearance_generation = 0
        self._appearance_error = None
        self.root.title(self.spec.title)
        # Fits a 1366x768 laptop with its title bar and taskbar; the static
        # pages scroll, so a smaller window loses no controls.
        self.root.minsize(880,560)
        self.root.geometry(opening_geometry(self.root))
        self.runner = TaskRunner()
        self.events = queue.Queue(maxsize=2048)
        self._unsubscribe = services.events.subscribe('*', self._enqueue)
        self.closing = False;self.closed = False;self._shutdown_started = False
        self._polling = start_polling;self._ticks = 0
        self.pages = {};self.page_scrolls = {};self.hosts = {};self.presenters = {};self.nav = {}
        self._model_records = {};self._projects = {};self.project_boxes = []
        self._stack_rows = {};self._catalog = None;self.choice_vars = {}
        self.current_page = None
        self.agent_panel = None;self.agent_session = None
        self._chat_progress = [];self._chat_starting = False
        self.chat_state = tk.StringVar(master=self.root,
            value='준비 안 됨 · [Chat 시작]을 누르면 Network → Ollama → AnythingLLM 순으로 확인합니다.')
        self.agent_state = tk.StringVar(master=self.root,
            value='준비 안 됨 · [Agent 시작]을 누르면 프로필과 모델을 고른 뒤 실행 환경을 준비합니다.')
        self.session_mode = tk.StringVar(master=self.root,value='inherit')
        self.project_id = tk.StringVar(master=self.root,value='(none)')
        self.message = tk.StringVar(master=self.root,value='Ready')
        self.health = tk.StringVar(master=self.root,value='Ollama ?    Docker ?    Chat ?    Search ?')
        self._build()
        self.load_projects()
        self.navigate(self.spec.primary)
        self.theme.refresh()
        if appearance_error:
            self.log('Theme preference could not be loaded: ' + appearance_error)
        self.root.bind('<FocusIn>', self._appearance_focus, add='+')
        self.root.protocol('WM_DELETE_WINDOW', self.request_close)
        self._timer = self.root.after(50, self._tick)

    def _build(self):
        outer=ttk.Frame(self.root);outer.pack(fill='both',expand=True)
        sidebar=ttk.Frame(outer,style='Sidebar.TFrame',width=235)
        sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        ttk.Label(sidebar,text='LOCAL AI',style='Brand.TLabel').pack(anchor='w',padx=22,pady=(25,4))
        ttk.Label(sidebar,text=self.spec.title.replace('LocalAI ',''),style='Sidebar.TLabel').pack(anchor='w',padx=23,pady=(0,22))
        captions={'WORK':'\uc8fc\uc694 \uc791\uc5c5','MANAGE':'\ubaa8\ub378 \u00b7 \uc124\uce58 \uad00\ub9ac','GENERAL':'\ud658\uacbd \u00b7 \uc124\uc815'}
        for group,keys in navigation_groups(self.app):
            ttk.Label(sidebar,text=captions[group],style='Sidebar.TLabel',font=('Segoe UI',9,'bold')).pack(anchor='w',padx=22,pady=(8,8))
            for key in keys:
                b=ttk.Button(sidebar,text=LABELS[key],style=nav_style(key),command=lambda k=key:self.navigate(k))
                b.pack(fill='x',padx=12,pady=3);self.nav[key]=b
            ttk.Separator(sidebar).pack(fill='x',padx=20,pady=(14,6))
        ttk.Label(sidebar,text='Shared services\nLocal data stays local',style='Sidebar.TLabel',
                  justify='left',font=('Segoe UI',9)).pack(side='bottom',anchor='w',padx=22,pady=18)
        ttk.Separator(outer,orient='vertical').pack(side='left',fill='y')
        content=ttk.Frame(outer);content.pack(fill='both',expand=True)
        header=ttk.Frame(content,padding=(24,16));header.pack(fill='x')
        ttk.Label(header,text=self.spec.title,style='Section.TLabel').pack(side='left')
        ttk.Label(header,textvariable=self.health,style='Muted.TLabel').pack(side='right')
        ttk.Separator(content).pack(fill='x')
        footer=ttk.Frame(content,padding=(18,8));footer.pack(side='bottom',fill='x')
        # The toggle sits with the status line, not above the log, so the log's
        # own height is never what you have to click through to get it back.
        self.activity_button=ttk.Button(footer,width=12,command=self.toggle_activity)
        self.activity_button.pack(side='right',padx=(12,0))
        self.message_label=ttk.Label(footer,textvariable=self.message,style='Muted.TLabel',wraplength=900)
        self.message_label.pack(anchor='w',side='left',fill='x',expand=True)
        wrap_to_parent(self.message_label,inset=180)
        # Keep operational progress visible. The previous 3-line Text widget hid
        # useful Chat/Agent startup stages behind periodic health task messages.
        # Eight lines is a quarter of the window at its own minimum size, though,
        # so it can be folded away and the choice is remembered.
        self.activity=themed(scrolledtext.ScrolledText(content,height=ACTIVITY_LINES[1],relief='flat',
                              font=('Consolas',9),padx=14,pady=8,state='disabled',wrap='word'),
                              background='surface',foreground='muted',highlightbackground='border',highlightcolor='chat',
                              selectbackground='selected',selectforeground='fg')
        self.activity.tag_configure('alert',foreground=self.theme.palette.danger)
        try:self._activity_visible=self.services.settings.activity_visible()
        except (OSError,ValueError):self._activity_visible=True
        self._apply_activity_visibility()
        self.page_area=ttk.Frame(content);self.page_area.pack(fill='both',expand=True)
        self._apply_activity_visibility()
        # Eight lines is a fifth of a desktop window and a third of a laptop
        # one. Left fixed, the log took so much of a 1366x768 screen that the
        # model list below it had four pixels to show twenty-five models in.
        self.root.bind('<Configure>',self._fit_activity,add='+')
        self._fit_activity()
        self.page_area.columnconfigure(0,weight=1);self.page_area.rowconfigure(0,weight=1)
        for key in self.spec.pages:
            page=views.build(self.page_area,key,self);page.grid(row=0,column=0,sticky='nsew');self.pages[key]=page

    def _apply_activity_visibility(self):
        if self._activity_visible:
            # `before` matters: pack serves its children in order, and the page
            # area claims the remaining space with expand=True. Re-packed after
            # it, the log came back with nothing left to occupy and stayed
            # invisible - folding it was a one-way door.
            options={'side':'bottom','fill':'x','padx':24,'pady':(4,0)}
            if getattr(self,'page_area',None) is not None:options['before']=self.page_area
            self.activity.pack(**options)
        elif self.activity.winfo_ismapped():
            self.activity.pack_forget()
        self.activity_button.configure(text='기록 접기' if self._activity_visible else '기록 펼치기')

    def _fit_activity(self,event=None):
        """Keep the log to its share of the window, in whole lines."""
        if event is not None and getattr(event,'widget',None) is not self.root:
            return
        height=self.root.winfo_height()
        if height<=1:
            return
        wanted=activity_lines(height)
        if int(self.activity.cget('height'))!=wanted:
            self.activity.configure(height=wanted)

    def toggle_activity(self):
        self._activity_visible=not self._activity_visible
        self._apply_activity_visibility()
        self.runner.submit('activity.save',
            lambda:self.services.settings.set_activity_visible(self._activity_visible),
            lambda _:None,lambda exc:self.log('Activity log: '+str(exc),level='error'),mutate=False)

    def navigate(self,key):
        if key=='projects':
            self.show_project_links()
            return
        if key not in self.pages: return
        self.pages[key].tkraise();self.current_page=key
        for name,button in self.nav.items():
            button.configure(style=nav_style(name,name==key))
        if key in ('chat','agent'):self.load_projects()
        if key=='settings':self.load_settings();self.sync_theme()
        if key=='models' and self._catalog is None:
            self.load_models_screen()

    def _enqueue(self,event):
        try:self.events.put_nowait(event)
        except queue.Full:
            # Progress history is bounded; approval decisions never travel here.
            try:self.events.get_nowait()
            except queue.Empty:pass
            try:self.events.put_nowait(event)
            except queue.Full:pass

    def log(self,text,*,level='info'):
        # A failure used to look exactly like progress on the same muted line.
        text=str(text)
        self.message.set(text[:220])
        self.message_label.configure(style='Alert.TLabel' if level=='error' else 'Muted.TLabel')
        self.activity.configure(state='normal')
        start=self.activity.index('end-1c')
        self.activity.insert('end',text+'\n')
        if level=='error':self.activity.tag_add('alert',start,'end-1c')
        if int(self.activity.index('end-1c').split('.')[0])>400:
            self.activity.delete('1.0','101.0')
        self.activity.see('end');self.activity.configure(state='disabled')

    def _handle_event(self,event):
        data=event.payload
        if event.topic.startswith('agent.') and self.agent_session is not None:
            if data.get('session')!=self.agent_session.id:return
            if self.agent_panel is not None:
                if event.topic=='agent.event':self.agent_panel.append_message(data.get('level','system'),data.get('message',''))
                if event.topic=='agent.ready':
                    (self.agent_panel.enable_send if data.get('ready') else self.agent_panel.disable_send)()
                    self.agent_panel.set_current_model(data.get('model',''))
        text=data.get('message') or data.get('detail') or data.get('status')
        # Network, Ollama and search progress belongs on the Chat page too while
        # Chat is starting. Filtering on service=='chat' meant the readiness box
        # sat on "[1/5] Network preparation" for the entire ninety seconds that
        # Docker Desktop was booting, with the explanation in the activity log.
        service=data.get('service')
        if text and event.topic=='runtime.progress' and (
                service=='chat' or self._chat_starting):
            label=str(text) if service in (None,'chat') else str(service)+': '+str(text)
            if self._chat_starting:self.set_chat_state('Working','준비 중 · '+label[:150])
            self._chat_progress.append(label)
            self._chat_progress = self._chat_progress[-12:]
            if hasattr(self, 'chat_text') and not self.services.chat.started:
                set_text(
                    self.chat_text,
                    'Chat 준비 중...\n\n' + '\n'.join(self._chat_progress),
                )
        if text:self.log(event.topic+': '+str(text),
                         level='error' if event.topic=='runtime.error' else 'info')

    def run_task(self,key,fn,done=None,*,mutate=True,announce=True,error=None):
        if self.closing:return False
        def finish(value):
            if done and not self.closing:done(value)
            if announce:self.log(key+' completed')
        def failed(exc):
            self.log(key+': '+str(exc),level='error')
            if error is not None and not self.closing:error(exc)
        ok=self.runner.submit(key,fn,finish,failed,mutate=mutate)
        if ok and announce:self.log(key+' ...')
        return ok

    def current_project(self):
        identifier = self.project_id.get()
        if identifier == '(none)':return None
        project = self.services.projects.get(identifier)
        if project is None:raise RuntimeError('Selected Project no longer exists. Select a Project again.')
        return project

    def selected_mode(self,app):
        explicit=self.session_mode.get()
        return self.services.resolve_mode(app,project=self.current_project(),
            session=None if explicit=='inherit' else explicit).value

    def load_projects(self):
        try:
            self._projects={p.id:p for p in self.services.projects.list()}
            for box in self.project_boxes:
                box.configure(values=('(none)',*self._projects))
            if self.project_id.get() not in self._projects:self.project_id.set('(none)')
        except Exception as exc:self.log('Project registry: '+str(exc),level='error')

    def project_selected(self):
        try:project=self.current_project()
        except Exception as exc:self.log('Project registry: '+str(exc),level='error');return
        if not hasattr(self,'project_fields'):return
        data=project.to_dict() if project else {}
        for key,var in self.project_fields.items():
            var.set(data.get(key) or ('inherit' if key=='network_mode' else ''))

    def show_project_links(self):
        if 'chat' in self.pages:
            self.navigate('chat')
            self.chat_tabs.select(self.chat_links_page)
        elif 'agent' in self.pages:
            self.navigate('agent')
            self.agent_tabs.select(self.agent_links_page)
        self.load_projects()
        self.project_selected()

    def new_project_link(self):
        self.project_id.set('(none)')
        self.project_selected()

    def manage_chat_projects(self):
        # Workspace creation is owned by AnythingLLM, not the LocalAI registry.
        self.start_chat(open_when_ready=True)

    def save_project(self):
        data={k:v.get().strip() for k,v in self.project_fields.items()}
        data['network_mode']=None if data['network_mode']=='inherit' else data['network_mode']
        try:project=Project(**data)
        except (TypeError,ValueError) as exc:self.log(str(exc),level='error');return
        def saved(_):
            self.load_projects();self.project_id.set(project.id);self.project_selected()
        self.run_task('project.save',lambda:self.services.projects.save(project),saved)

    def delete_project(self):
        identifier=self.project_fields['id'].get().strip()
        if identifier not in self._projects:return
        if not messagebox.askyesno('Project', 'Delete this linkage only? Workspace files remain unchanged.',parent=self.root):return
        self.run_task('project.delete',lambda:self.services.projects.delete(identifier),lambda _:(self.load_projects(),self.project_selected()))

    def _appearance_focus(self, event):
        if event.widget is self.root:
            self.sync_theme()

    def sync_theme(self):
        if self.closing or self.runner.busy('appearance.save') or self.runner.busy('appearance.sync'):
            return
        generation = self._appearance_generation
        def done(value):
            if self.closing or generation != self._appearance_generation:
                return
            if value != self.theme.name:
                self.theme.apply(value)
            self.theme_choice.set(value)
            self._appearance_error = None
        def failed(exc):
            if self.closing or generation != self._appearance_generation:
                return
            if str(exc) != self._appearance_error:
                self.log('Theme preference: ' + str(exc))
                self._appearance_error = str(exc)
        self.runner.submit('appearance.sync',self.services.settings.theme,done,failed,mutate=False)

    def save_theme(self):
        if self.closing or self.runner.busy('appearance.save'):
            self.theme_choice.set(self.theme.name)
            return
        value = self.theme_choice.get()
        self._appearance_generation += 1
        for button in self.theme_buttons:
            button.state(['disabled'])
        def unlock():
            for button in self.theme_buttons:
                button.state(['!disabled'])
        def done(_):
            if not self.closing:
                self.theme.apply(value)
                self.theme_choice.set(value)
                self.log('Theme saved: ' + value)
            unlock()
        def failed(exc):
            self.theme_choice.set(self.theme.name)
            self.log('Theme could not be saved: ' + str(exc))
            unlock()
        # Appearance writes do not wait behind a long-running Agent/installation
        # task; JsonStore still serializes all writes with its OS-backed lock.
        self.runner.submit('appearance.save',lambda:self.services.settings.set_theme(value),done,failed,mutate=False)

    def load_settings(self):
        scope=self.settings_scope.get()
        try:self.settings_mode.set(self.services.resolve_mode(None if scope=='global' else scope).value)
        except Exception as exc:self.log('Settings: '+str(exc),level='error')

    def save_settings(self):
        scope,mode=self.settings_scope.get(),self.settings_mode.get()
        self.run_task('settings.save',lambda:self.services.settings.set_network_mode(mode,
            app=None if scope=='global' else scope))

    def start_chat(self, *, open_when_ready=False):
        if self.services.chat.started:self.open_chat();return
        try:project=self.current_project();mode=self.selected_mode('chat')
        except Exception as exc:self.log(str(exc),level='error');return
        model=project.chat_model if project else ''
        self._chat_progress = ['요청 접수 · Network → Ollama → AnythingLLM → model 연결 순으로 확인합니다.']
        # Events are drained on the Tk timer, so they can arrive after the worker
        # has already finished. A flag the worker does not race decides whether
        # they still belong on the Chat readiness box.
        self._chat_starting = True
        self.set_chat_state('Working','준비 중 · 진행 상황은 아래에 그대로 나옵니다. 창은 계속 쓸 수 있습니다.')
        set_text(self.chat_text,'Chat 준비 시작\n\n'+self._chat_progress[0])
        def work():
            try:
                return self.services.chat.start(mode,model=model,cancel=self.runner.cancel.is_set)
            except Exception as exc:
                self.services.events.emit('runtime.progress',{
                    'service':'chat','message':'준비 실패: '+str(exc)})
                raise
        def ready(url):
            self._chat_starting = False
            active_model=self.services.chat.model or model or '(default)'
            self.set_chat_state('Ready','준비 완료 · [대화 화면 열기]를 누르세요 · 모델 '+active_model)
            set_text(self.chat_text,'Chat 연결 검증 완료\n\n'+str(url)+'\nNetwork: '+mode+
                '\nOllama model: '+active_model+
                '\nContainer → host Ollama → model: verified'+
                '\nWorkspace linkage: '+(project.anythingllm_workspace if project else '(none)')+
                '\n\nAnythingLLM에서 Chat, 파일, 문서, RAG를 사용할 수 있습니다.\n종료 시 세션 종료를 사용하세요.')
            if open_when_ready:self.open_chat()
        def failed(exc):
            # Keep the whole preparation trail on the page: the last line alone
            # never said which of the five steps actually stopped.
            self._chat_starting = False
            self.set_chat_state('Failed','준비 실패 · '+str(exc)[:150])
            if hasattr(self,'chat_text'):
                set_text(self.chat_text,'Chat 준비 실패\n\n'+'\n'.join(self._chat_progress)+
                    '\n\n'+str(exc))
        self.run_task('chat.start',work,ready,error=failed)

    #: Wording that identifies a cause the user can act on from here. Order
    #: matters: "the models are here and the server cannot see them" contains
    #: the word 모델 too, and sending that user to the download screen is the
    #: one instruction that cannot help them.
    STORE_UNREAD=('그 경로를 읽지 않습니다','그 경로를 읽고 있지 않습니다')
    MODELS_NEEDED=('로컬 Ollama 모델이 없습니다','설치된 로컬 모델이 없습니다','모델을 먼저')
    SETUP_NEEDED=('AnythingLLM is not installed','이미지가 없습니다','Setup / Repair',
                  '[설치 / 복구]')

    def state_action(self,text):
        """The button that belongs next to this message, if there is one.

        A message that says where to go is only half an instruction while the
        page offers no way to get there.
        """
        if any(hint in text for hint in self.STORE_UNREAD):
            return ('Ollama 다시 시작 →',self.fix_model_store)
        if any(hint in text for hint in self.MODELS_NEEDED):
            return ('모델 화면 열기 →',lambda:self.navigate('models'))
        if any(hint in text for hint in self.SETUP_NEEDED):
            return ('설치 / 복구 열기 →',lambda:self.navigate('setup'))
        return None

    def fix_model_store(self):
        """Take the user to the action that restarts Ollama on the right store.

        The models are installed; Ollama reads OLLAMA_MODELS only at startup,
        so they stay invisible until it is restarted. The Ollama action asks
        before ending a process the user did not ask us to end.
        """
        self.navigate('models')
        try:self.model_tabs.select(self.model_pages['stack'])
        except Exception:pass
        self.ensure_ollama()

    def set_chat_state(self,state,text):
        """One place decides how ready Chat looks, so the words, the colour and
        the open button can never disagree with each other."""
        label=getattr(self,'chat_status',None)
        if label is not None:set_status(label,state,text,self.state_action(text))
        button=getattr(self,'chat_open_button',None)
        if button is not None:
            ready=state=='Ready'
            button.configure(state='normal' if ready else 'disabled',
                             style='Chat.TButton' if ready else 'TButton',
                             text='대화 화면 열기 →' if ready else '대화 화면 열기')

    def set_agent_state(self,state,text):
        label=getattr(self,'agent_status',None)
        if label is not None:set_status(label,state,text,self.state_action(text))

    def open_chat(self):
        try:
            if self.services.chat.url:
                url=local_url(self.services.chat.url)
                if webbrowser.open(url) is False:
                    self.log('브라우저 자동 열기에 실패했습니다. 직접 여세요: '+url,level='error')
        except Exception as exc:self.log(str(exc),level='error')

    def presenter(self,key):
        if key not in self.presenters:
            proxy=SimpleNamespace(root=self.root,host=self.hosts[key],
                set_message=lambda message,level='info':self.services.events.emit('runtime.progress',{'message':str(message)}))
            self.presenters[key]=self.services.system.create_presenter(proxy)
        p=self.presenters[key]
        flag=getattr(p,'_action_cancel',None)
        if flag is not None:flag.clear()
        return p

    def start_agent(self):
        if self.services.agent.opened:
            self.log('An Agent is already active. Stop the session before opening another.');return
        try:p=self.presenter('agent');mode=self.selected_mode('interpreter');project=self.current_project()
        except Exception as exc:self.log(str(exc),level='error');return
        self.set_agent_state('Working','준비 중 · 시작 설정을 고른 뒤 Ollama·Docker·네트워크를 준비합니다.')
        def ready(session):
            if session is None:
                # The wizard replaces this host with its own progress screen the
                # moment [시작] is pressed. A cancel or a rejected selection has
                # to take that screen back down, or the page keeps saying the
                # Agent is starting when nothing is.
                self.clear_agent_panel()
                self.set_agent_state('Waiting','취소됨 · [Agent 시작]으로 다시 시작할 수 있습니다.')
                return
            self.agent_session=session
            self.set_agent_state('Ready','준비 완료 · 아래 대화 패널에서 지시를 입력하세요 · 모델 '
                                 +str(session.metadata.get('model','')))
            callbacks={'input':lambda text:self.run_task('agent.input',lambda:session.handle_input(text)),
                'stop':lambda:self.run_task('agent.stop_turn',session.stop),
                'restart':lambda:self.run_task('agent.restart',session.restart)}
            self.agent_panel=self.hosts['agent'].replace(lambda parent:
                self.services.system.create_agent_panel(parent,session.metadata,callbacks))
            # Old setup log panels were replaced by a session view, not reused.
            p._current_log_panel=None;p._current_log_done=None
            self.agent_panel.enable_send()
        self.run_task('agent.start',
            lambda:self.services.agent.open(p,mode,project=project,cancel=self.runner.cancel.is_set),
            ready,error=self._agent_failed)

    def _agent_failed(self,exc):
        self.clear_agent_panel()
        self.set_agent_state('Failed','준비 실패 · '+str(exc)[:150])

    def clear_agent_panel(self):
        self.agent_panel=None
        try:self.hosts['agent'].clear()
        except Exception as exc:self.log('Agent panel: '+str(exc),level='error')

    def stop_sessions(self):
        def stopped(ok):
            if not ok:raise RuntimeError('Shutdown was not verified; ownership is retained.')
            if self.agent_panel is not None:self.agent_panel.disable_send()
            self.agent_session=None
            self.set_chat_state('Waiting','세션을 종료했습니다 · [Chat 시작]으로 다시 준비할 수 있습니다.')
            self.set_agent_state('Waiting','세션을 종료했습니다 · [Agent 시작]으로 다시 준비할 수 있습니다.')
            self.refresh_health()
        self.run_task('sessions.stop',self.services.close,stopped)

    def refresh_models(self):
        def scan():
            self.services.models.refresh_index()
            index=self.services.models.inventory()
            # Reading the registry and the ACL belongs on the worker with the
            # rest of the scan, not on the Tk thread painting the result.
            index['sharing']=self.services.models.sharing()
            return index
        def display(index):
            self.model_tree.delete(*self.model_tree.get_children())
            self._model_records={}
            for model in index['models']:
                issue_count=sum(len(model.get(k,())) for k in ('missing_blobs','unavailable_blobs','size_mismatches'))
                values=(model['name'],*(f'{model[k]/1024**3:.3f}' for k in ('size_bytes','shared_bytes','exclusive_bytes')),
                    str(issue_count)+' issue(s)' if issue_count else 'observed')
                iid=self.model_tree.insert('','end',values=values);self._model_records[iid]=model
            totals=index['totals']
            store=self.services.models.storage()
            self.show_sharing(index.get('sharing'))
            free=store['free_bytes']
            kind=(' · 모든 계정 공용' if store.get('shared')
                  else ' · 이 계정 전용' if store.get('per_user') else '')
            self.model_summary.set(
                f"{store['path']}{kind}\n"
                f"모델 {totals['models']}개 · 사용 {totals['size_bytes']/1024**3:.1f} GiB"
                + ('' if free is None else f" · 남은 공간 {free/1024**3:.1f} GiB")
                + f" · 전체 검사 완료={index['scan_complete']}")
            if index['errors']:set_text(self.model_details,json.dumps(index['errors'],ensure_ascii=False,indent=2))
        self.run_task('models.refresh',scan,display)

    def show_model_details(self):
        chosen=self.model_tree.selection()
        if chosen:set_text(self.model_details,json.dumps(self._model_records[chosen[0]],ensure_ascii=False,indent=2))

    # ── model screen: current stack ───────────────────────────────────────
    def refresh_stack(self):
        self.run_task('models.stack',self.services.models.current_stack,self.show_stack,mutate=False)

    def show_stack(self,stack):
        self._stack_rows={}
        self.stack_tree.delete(*self.stack_tree.get_children())
        for role in stack['roles']:
            iid=self.stack_tree.insert('','end',values=(
                role['label'],role['chosen'] or '(사다리 없음)',
                f"{role['need_gb']:.1f} GB",'있음' if role['on_disk'] else '없음'))
            self._stack_rows[iid]=role
        free=stack['free_gb']
        missing=sum(0 if role['on_disk'] else 1 for role in stack['roles'])
        self.stack_summary.set(
            ('여유 메모리 확인 불가' if free is None else f'여유 메모리 {free:.1f} GB')
            + f" · 메모리 예산 {stack['budget_gb']:.0f} GB · "
            + ('모든 역할의 모델이 디스크에 있습니다.' if not missing
               else f'{missing}개 역할의 선택 모델이 디스크에 없습니다.'))

    def show_stack_detail(self):
        chosen=self.stack_tree.selection()
        if not chosen:return
        role=self._stack_rows.get(chosen[0])
        if role is None:return
        lines=[role['label']+'  ('+role['name']+')','',
               '지금 선택될 모델: '+(role['chosen'] or '(없음)'),'','사다리 (무거운 단계부터):']
        for rung in role['ladder']:
            mark='O' if rung['on_disk'] else 'X'
            here=' <- 선택' if rung['tag']==role['chosen'] else ''
            lines.append(f"  [{mark}] {rung['tag']}  (>= {rung['need_gb']:.1f} GB){here}")
        lines+=['','[O] 디스크에 있음 · [X] 없음. 없는 단계는 실행 시 건너뜁니다.']
        set_text(self.stack_detail,'\n'.join(lines))

    def ensure_ollama(self):
        """Explicit managed-Ollama start/verify, with the retained diagnostics."""
        try:presenter=self.presenter('models')
        except Exception as exc:self.log(str(exc),level='error');return
        self.run_task('models.ollama',lambda:self.services.setup.maintenance('ollama_action',presenter))

    # ── model screen: catalog selection ──────────────────────────────────
    def load_models_screen(self):
        """First open: one store scan feeds both the catalogue and the stack."""
        def display(pair):
            catalog,stack=pair
            self.show_catalog(catalog)
            self.show_stack(stack)
        self.run_task('models.overview',self.services.models.overview,display,mutate=False)

    def load_catalog(self):
        self.run_task('models.catalog',self.services.models.catalog,self.show_catalog,mutate=False)

    def show_catalog(self,catalog):
        self._catalog=catalog
        self.build_catalog_rows(catalog)
        self.update_choice_summary()

    def build_catalog_rows(self,catalog):
        for child in self.choice_body.winfo_children():child.destroy()
        self.choice_vars={}
        groups=(('기본 (권장)',[m for m in catalog['models'] if m['group']=='core']),
                ('추가 후보 (역할별)',[m for m in catalog['models'] if m['group']!='core']))
        for title,models in groups:
            if not models:continue
            self.add_catalog_group(title)
            for model in models:
                self.add_catalog_row(model,checked=model['installed'] or model['recommended'])
        if catalog['extra_installed']:
            self.add_catalog_group('설치됨 (카탈로그 외)')
            for tag in catalog['extra_installed']:
                self.add_catalog_row({'tag':tag,'role':'직접 받은 모델','level_label':'','note':'',
                                      'size_gb':0.0,'memory_gb':0.0,'installed':True,
                                      'desc':'카탈로그에 없는 모델입니다. 체크를 풀면 삭제합니다.'},
                                     checked=True)
        plan=catalog['plan']
        parts=[f"[{label}] "+(', '.join(plan.get(key) or ()) or '없음')
               for key,label in catalog['levels']]
        # One line beside the apply button. The three tiers used to be three
        # more lines above the list, which left the list of twenty-five models
        # with less height than the explanation of it; the full breakdown goes
        # to the activity log, where a long answer costs nothing.
        counts=' · '.join(f"{label} {len(plan.get(key) or ())}개"
                          for key,label in catalog['levels'])
        self.choice_plan.set(f"메모리 예산 {catalog['budget_gb']:.0f}GB 기준 "
                             f"3단계를 미리 체크했습니다 · {counts} · 자세한 목록은 기록에")
        self.log('선택 계획 · 여유 메모리는 오르내리므로 세 단계를 모두 둡니다:')
        for part in parts:
            self.log('  '+part)
        self.choice_scroller.bind_content()

    def add_catalog_group(self,title):
        ttk.Label(self.choice_body,text=title,style='Section.TLabel').pack(anchor='w',pady=(16,2))
        ttk.Separator(self.choice_body).pack(fill='x',pady=(0,8))

    def add_catalog_row(self,model,*,checked):
        var=tk.BooleanVar(master=self.root,value=checked)
        self.choice_vars[model['tag']]=var
        card=ttk.Frame(self.choice_body,style='Manage.Card.TFrame',padding=12)
        card.pack(fill='x',pady=4)
        facts=[model['tag'],model['role']]
        if model.get('level_label'):
            facts.append('['+model['level_label']+']'+((' '+model['note']) if model.get('note') else ''))
        if model['size_gb']:facts.append(f"~{model['size_gb']:.1f}GB")
        if model['installed']:facts.append('설치됨')
        ttk.Checkbutton(card,text='   ·   '.join(facts),variable=var,
                        command=self.update_choice_summary,
                        style='Card.TCheckbutton').pack(anchor='w',fill='x')
        if model.get('desc'):
            ttk.Label(card,text=model['desc'],style='Manage.CardMuted.TLabel',
                      wraplength=660,justify='left').pack(anchor='w',padx=(26,0),pady=(4,0))

    def selected_tags(self):
        return {tag for tag,var in self.choice_vars.items() if var.get()}

    def set_selection(self,mode):
        catalog=getattr(self,'_catalog',None)
        if catalog is None:return
        recommended=set(catalog['recommended'])
        installed={m['tag'] for m in catalog['models'] if m['installed']}|set(catalog['extra_installed'])
        for tag,var in self.choice_vars.items():
            if mode=='all':var.set(True)
            elif mode=='none':var.set(False)
            else:var.set(tag in recommended or tag in installed)
        self.update_choice_summary()

    def update_choice_summary(self):
        catalog=getattr(self,'_catalog',None)
        if catalog is None:return
        try:plan=self.services.models.plan_changes(self.selected_tags(),installed=self.catalog_installed())
        except Exception as exc:self.choice_summary.set('선택 계산 실패: '+str(exc));return
        self._plan=plan
        self.choice_summary.set(f"설치 예정 {len(plan['install'])}개 (최대 ~{plan['download_gb']:.1f} GB)"
                                f"   ·   삭제 예정 {len(plan['remove'])}개")
        self.choice_storage.set(self.storage_line(plan))
        # A selection that cannot fit is shown as a problem, not as a number the
        # user is expected to compare themselves mid-download.
        short=plan['fits'] is False and plan['install']
        self.choice_storage_label.configure(style='Alert.TLabel' if short else 'Muted.TLabel')
        self.apply_button.state(['!disabled'] if plan['install'] or plan['remove'] else ['disabled'])

    SHARING_UNKNOWN='다른 계정도 쓸 수 있는지 확인하지 못했습니다.'

    def show_sharing(self,state):
        if not state:
            self.sharing_summary.set(self.SHARING_UNKNOWN);return
        every=state.get('every_account')
        if every is True:
            text='이 PC의 모든 Windows 계정이 같은 모델을 씁니다.'
        elif every is None:
            text=self.SHARING_UNKNOWN
        else:
            text='이 계정에서만 쓸 수 있습니다. '+' '.join(state.get('reasons') or ())
        self.sharing_summary.set(text)
        button=getattr(self,'sharing_button',None)
        if button is not None:
            # Offer the fix only where there is something the program can fix;
            # a user-scope override is that account's own setting.
            button.configure(state='normal' if state.get('repairable') else 'disabled')

    def repair_sharing(self):
        def done(result):
            self.show_sharing(result)
            if result.get('every_account') is True:
                self.log('공용 설정을 고쳤습니다: '+result['path'])
            else:
                self.log('공용 설정을 끝내지 못했습니다. 관리자 권한으로 다시 시도하세요. '
                         +' '.join(result.get('reasons') or ()),level='error')
        self.run_task('models.sharing',self.services.models.repair_sharing,done)

    def storage_line(self,plan):
        store=plan['storage']
        where='받는 곳 '+store['path']
        if store.get('shared'):
            where+=' (이 PC의 모든 Windows 계정이 함께 씁니다)'
        elif store.get('per_user'):
            where+=' (이 계정 전용 — 다른 계정은 다시 받아야 합니다)'
        if not store['exists']:
            where+=' (아직 없음 — 첫 설치 때 만들어집니다)'
        if plan['free_gb'] is None:
            return where+'  ·  남은 공간을 확인할 수 없습니다'
        line=where+f"  ·  남은 공간 {plan['free_gb']:.1f} GB"
        if plan['install'] and plan['fits'] is False:
            line+=f"  ·  {plan['download_gb']-plan['free_gb']:.1f} GB 부족합니다"
        return line

    def catalog_installed(self):
        catalog=getattr(self,'_catalog',None)
        if catalog is None:return set()
        return {m['tag'] for m in catalog['models'] if m['installed']}|set(catalog['extra_installed'])

    def apply_selection(self):
        if self.runner.busy('models.apply'):return
        try:plan=self.services.models.plan_changes(self.selected_tags(),installed=self.catalog_installed())
        except Exception as exc:self.log('선택 계산 실패: '+str(exc),level='error');return
        if not plan['install'] and not plan['remove']:
            self.log('변경할 내용이 없습니다.');return
        lines=[]
        if plan['install']:
            lines.append(f"설치 {len(plan['install'])}개 (~{plan['download_gb']:.1f} GB):")
            lines+=['  + '+tag for tag in plan['install'][:12]]
        if plan['remove']:
            lines.append(f"삭제 {len(plan['remove'])}개:")
            lines+=['  - '+tag for tag in plan['remove'][:12]]
        lines.append('')
        lines.append(self.storage_line(plan))
        if plan['install'] and plan['fits'] is False:
            lines.append('공간이 모자라면 받다가 중간에 실패합니다. 먼저 정리하거나 덜 고르세요.')
        lines.append('')
        lines.append('설치는 로컬 Ollama 서버가 받고, 삭제는 Ollama가 정리합니다. 계속할까요?')
        if not messagebox.askyesno('모델 적용','\n'.join(lines),parent=self.root):return
        def work():
            done={'install':[],'remove':[],'failed':[]}
            # Model operations all depend on the same Ollama/store precondition.
            # Check/bootstrap it once so one machine-level problem is not printed
            # again for every selected model.
            try:
                self.services.setup.ensure_model_runtime(download=bool(plan['install']))
            except Exception as exc:
                done['failed'].append(('prepare','Ollama',str(exc)))
                return done
            for tag in plan['remove']:
                try:self.services.setup.remove_model(tag);done['remove'].append(tag)
                except Exception as exc:done['failed'].append(('remove',tag,str(exc)))
            for tag in plan['install']:
                if self.runner.cancel.is_set():break
                try:self.services.setup.install_model(tag);done['install'].append(tag)
                except Exception as exc:done['failed'].append(('install',tag,str(exc)))
            return done
        def finished(done):
            for kind,tag,error in done['failed']:
                self.log(kind+' 실패 '+tag+': '+error,level='error')
            self.log(f"설치 {len(done['install'])}개 · 삭제 {len(done['remove'])}개 완료"
                     + (f" · 실패 {len(done['failed'])}개" if done['failed'] else ''),
                     level='error' if done['failed'] else 'info')
            self.load_catalog();self.refresh_stack()
            if 'models' in self.pages:self.refresh_models()
        self.run_task('models.apply',work,finished)

    def refresh_health(self,*,fresh=False):
        if fresh:
            self.log('상태 확인 중 · Ollama / Docker / Chat / Search')
        def display(status):
            shown=lambda value:'ready' if value is True else 'stopped' if value is False else 'unknown'
            header_keys=('ollama','docker','chat','search')
            self.health.set('    '.join(
                key.title()+': '+shown(status.get(key)) for key in header_keys
            ))
            if fresh:
                summary=' · '.join(key.title()+'='+shown(status.get(key)) for key in header_keys)
                elapsed=status.get('probe_seconds')
                suffix=(' · %.1f초' % elapsed) if isinstance(elapsed,(int,float)) else ''
                self.log('상태 확인 완료 · '+summary+suffix)
            store=status.get('ollama_store')
            if hasattr(self,'chat_text') and not self.services.chat.attempted:
                set_text(
                    self.chat_text,
                    'Chat 준비 상태\n\n'
                    'AnythingLLM image: '+shown(status.get('chat_image'))+'\n'
                    'AnythingLLM + Ollama/model connection: '+shown(status.get('chat'))+'\n'
                    'Ollama: '+shown(status.get('ollama'))+
                    (('\n  └ '+str(store)) if isinstance(store,str) else '')+'\n'
                    'Docker: '+shown(status.get('docker'))+
                    '\n\nChat 시작을 누르면 Network → Ollama → AnythingLLM → model 순으로 검증합니다.'
                )
            # Before anything is started the readiness line reports the poll,
            # so the page is never blank about why it is not ready.
            if not self.services.chat.attempted and not self._chat_starting:
                stray=status.get('runtime_root') or status.get('records_private')
                if isinstance(stray,str):
                    # An install the previous release left in the checkout is
                    # complete and working; it is simply somewhere the new
                    # paths do not look. Saying "not ready" without saying
                    # that sends the user off to re-download it.
                    self.set_chat_state('Waiting',stray)
                elif status.get('ollama') is False:
                    self.set_chat_state('Waiting','Ollama 가 응답하지 않습니다 · '
                        '[Chat 시작]을 누르면 이 창이 직접 시작합니다.')
                elif isinstance(store,str) and ('로컬 모델이 없습니다' in store
                                                or '읽고 있지 않습니다' in store):
                    self.set_chat_state('Waiting',store)
                elif status.get('chat_image') is False:
                    self.set_chat_state('Waiting','AnythingLLM 이미지가 없습니다 · '
                        '[설치 / 복구]에서 먼저 받으세요.')
                else:
                    self.set_chat_state('Waiting','준비 안 됨 · [Chat 시작]을 누르세요'
                        +((' · '+str(store)) if isinstance(store,str) else ''))
            active=self.services.network.mode
            if hasattr(self,'network_text'):set_text(self.network_text,'Pinned mode: '+(active.value if active else '(none)')+
                '\nRuntime ownership in this window: '+str(self.services.owner.owned)+
                '\n\nPreferences apply to the next session. Block reuses canonical relay quiescence and internal-network verification.')
            if hasattr(self,'system_text'):set_text(self.system_text,json.dumps(status,indent=2)+
                '\n\n공용 (이 PC 의 모든 계정) ─ Environment: '+str(self.services.env)+
                '\n공용 ─ Models: '+str(self.services.model_dir)+
                '\n내 계정 전용 ─ '+self.services.account_label()+': '+str(self.services.data))
        # Health is background telemetry, not user work. Keep failures visible,
        # but do not flood the shared activity log with "health .../completed".
        self.run_task('health',lambda:self.services.system.health(fresh=fresh),display,mutate=False,announce=False)

    def repair(self):
        if self.services.chat.started or self.services.agent.opened:
            self.log('Stop active sessions before Setup / Repair.',level='error');return
        if not messagebox.askyesno('Setup / Repair','Run the existing installer in a separate console?\nReview its prompts before installing or migrating data.',parent=self.root):return
        def done(_result):
            self.log('설치 / 복구가 끝났습니다. 상태를 다시 확인합니다.')
            self.refresh_health(fresh=True)
        self.run_task('setup.repair',self.services.setup.repair,done,
                      error=lambda exc:self.refresh_health(fresh=True))

    def maintenance(self,key,host='setup'):
        if self.services.chat.started or self.services.agent.opened:
            self.log('Stop active sessions before maintenance.',level='error');return
        try:p=self.presenter(host)
        except Exception as exc:self.log(str(exc),level='error');return
        self.run_task('setup.'+key,lambda:self.services.setup.maintenance(key,p))

    def request_close(self):
        if self.closing:return
        self.closing=True;self.runner.cancel.set();self._polling=False
        session=self.services.agent.session
        if session is not None:
            session.closing.set()
            # An Agent turn already running keeps shutdown queued behind it, and
            # a model turn can last minutes. Interrupt it the way the Stop button
            # does, on the read pool so it does not queue behind that same turn.
            self.runner.submit('agent.interrupt',session.stop_turn,lambda _:None,
                lambda exc:self.log('agent.interrupt: '+str(exc),level='error'),mutate=False)
        for p in self.presenters.values():
            fn=getattr(p,'_on_user_cancel',None)
            if callable(fn):fn()
        for button in self.nav.values():button.configure(state='disabled')
        self.log('Closing: waiting for active operations and verified session shutdown. Finish any open approval/installer prompts.')

    def _tick(self):
        if self.closed:return
        # Progress a worker emitted happened before that worker's result, so
        # drain the events first. The other order printed the failure above the
        # steps that led to it, and let a completion callback close the Chat
        # trail before the very messages explaining it had been shown.
        for _ in range(100):
            try:event=self.events.get_nowait()
            except queue.Empty:break
            self._handle_event(event)
        if self.closed:return
        self.runner.drain()
        if self.closed:return
        if self.closing and not self.runner.busy() and not self._shutdown_started:
            self._shutdown_started=True
            def done(ok):
                if not ok:failed(RuntimeError('Runtime shutdown could not be verified.'));return
                self.closed=True;self._unsubscribe();self.runner.shutdown();self.root.destroy()
            def failed(exc):
                self.closing=False;self._shutdown_started=False;self.runner.cancel.clear()
                for button in self.nav.values():button.configure(state='normal')
                self.log(str(exc)+' Window retained; retry Session stop.')
            self.runner.submit('shutdown',self.services.close,done,failed)
        elif not self.closing and self._polling:
            self._ticks+=1
            if self._ticks%200==0:self.sync_theme()
            # Backend health is cached for 30 seconds; probing every 10 seconds
            # only resubmitted the same check and obscured useful progress logs.
            if self._ticks==1 or self._ticks%600==0:self.refresh_health()
            session=self.agent_session
            if session is not None and self._ticks%2==0:
                self.runner.submit('agent.poll',session.poll_once,lambda _:None,lambda exc:self.log(str(exc),level='error'),mutate=False)
        if not self.closed:self._timer=self.root.after(50,self._tick)

    def run(self):
        self.root.mainloop()
