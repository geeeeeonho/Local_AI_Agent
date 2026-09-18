"""One persistent desktop shell. Every runtime operation goes through services."""
from __future__ import annotations
import json
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from types import SimpleNamespace
import webbrowser
from core.projects.model import Project
from core.urls import local_url
from .specs import SPECS, LABELS, navigation_groups, nav_style
from .tasks import TaskRunner
from .widgets import set_text, theme
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
        self.root.geometry('1280x860')
        # Fits a 1366x768 laptop with its title bar and taskbar; the static
        # pages scroll, so a smaller window loses no controls.
        self.root.minsize(880,560)
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
        self.message_label=ttk.Label(footer,textvariable=self.message,style='Muted.TLabel',wraplength=900)
        self.message_label.pack(anchor='w')
        self.activity=themed(tk.Text(content,height=3,relief='flat',
                              font=('Consolas',9),padx=14,pady=8,state='disabled'),
                              background='surface',foreground='muted',highlightbackground='border',highlightcolor='chat',
                              selectbackground='selected',selectforeground='fg')
        self.activity.pack(side='bottom',fill='x',padx=24,pady=(4,0))
        self.activity.tag_configure('alert',foreground=self.theme.palette.danger)
        self.page_area=ttk.Frame(content);self.page_area.pack(fill='both',expand=True)
        self.page_area.columnconfigure(0,weight=1);self.page_area.rowconfigure(0,weight=1)
        for key in self.spec.pages:
            page=views.build(self.page_area,key,self);page.grid(row=0,column=0,sticky='nsew');self.pages[key]=page

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
            self.load_catalog();self.refresh_stack()

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
        if text:self.log(event.topic+': '+str(text))

    def run_task(self,key,fn,done=None,*,mutate=True):
        if self.closing:return False
        def finish(value):
            if done and not self.closing:done(value)
            self.log(key+' completed')
        ok=self.runner.submit(key,fn,finish,lambda exc:self.log(key+': '+str(exc),level='error'),mutate=mutate)
        if ok:self.log(key+' ...')
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
        def ready(url):
            self.chat_open_button.configure(state='normal')
            set_text(self.chat_text,'AnythingLLM is ready\n\n'+str(url)+'\nNetwork: '+mode+
                '\nWorkspace linkage: '+(project.anythingllm_workspace if project else '(none)')+
                '\n\nOpen AnythingLLM to use Chat, files, documents and RAG.\nUse Session stop when finished.')
            if open_when_ready:self.open_chat()
        self.run_task('chat.start',lambda:self.services.chat.start(mode,model=model,cancel=self.runner.cancel.is_set),ready)

    def open_chat(self):
        try:
            if self.services.chat.url:webbrowser.open(local_url(self.services.chat.url))
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
        def ready(session):
            if session is None:return
            self.agent_session=session
            callbacks={'input':lambda text:self.run_task('agent.input',lambda:session.handle_input(text)),
                'stop':lambda:self.run_task('agent.stop_turn',session.stop),
                'restart':lambda:self.run_task('agent.restart',session.restart)}
            self.agent_panel=self.hosts['agent'].replace(lambda parent:
                self.services.system.create_agent_panel(parent,session.metadata,callbacks))
            # Old setup log panels were replaced by a session view, not reused.
            p._current_log_panel=None;p._current_log_done=None
            self.agent_panel.enable_send()
        self.run_task('agent.start',lambda:self.services.agent.open(p,mode,project=project,cancel=self.runner.cancel.is_set),ready)

    def stop_sessions(self):
        def stopped(ok):
            if not ok:raise RuntimeError('Shutdown was not verified; ownership is retained.')
            if self.agent_panel is not None:self.agent_panel.disable_send()
            self.agent_session=None
            if hasattr(self,'chat_open_button'):self.chat_open_button.configure(state='disabled')
            self.refresh_health()
        self.run_task('sessions.stop',self.services.close,stopped)

    def refresh_models(self):
        def scan():
            self.services.models.refresh_index()
            return self.services.models.inventory()
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
            free=store['free_bytes']
            self.model_summary.set(
                f"{store['path']}\n"
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
        def display(stack):
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
        self.run_task('models.stack',self.services.models.current_stack,display,mutate=False)

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
    def load_catalog(self):
        def display(catalog):
            self._catalog=catalog
            self.build_catalog_rows(catalog)
            self.update_choice_summary()
        self.run_task('models.catalog',self.services.models.catalog,display,mutate=False)

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
        self.choice_plan.set(f"메모리 예산 {catalog['budget_gb']:.0f}GB 기준 3단계를 미리 체크했습니다 "
                             '(여유 메모리는 오르내리므로 세 단계를 모두 둡니다).\n  '+'\n  '.join(parts))
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

    def storage_line(self,plan):
        store=plan['storage']
        where='받는 곳 '+store['path']
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

    def refresh_health(self):
        def display(status):
            shown=lambda value:'ready' if value is True else 'stopped' if value is False else 'unknown'
            self.health.set('    '.join(key.title()+': '+shown(value) for key,value in status.items()))
            active=self.services.network.mode
            if hasattr(self,'network_text'):set_text(self.network_text,'Pinned mode: '+(active.value if active else '(none)')+
                '\nRuntime ownership in this window: '+str(self.services.owner.owned)+
                '\n\nPreferences apply to the next session. Block reuses canonical relay quiescence and internal-network verification.')
            if hasattr(self,'system_text'):set_text(self.system_text,json.dumps(status,indent=2)+
                '\n\nEnvironment: '+str(self.services.env)+'\nModels: '+str(self.services.model_dir)+'\nUser data: '+str(self.services.data))
        self.run_task('health',self.services.system.health,display,mutate=False)

    def repair(self):
        if self.services.chat.started or self.services.agent.opened:
            self.log('Stop active sessions before Setup / Repair.',level='error');return
        if not messagebox.askyesno('Setup / Repair','Run the existing installer in a separate console?\nReview its prompts before installing or migrating data.',parent=self.root):return
        self.run_task('setup.repair',self.services.setup.repair)

    def maintenance(self,key,host='setup'):
        if self.services.chat.started or self.services.agent.opened:
            self.log('Stop active sessions before maintenance.',level='error');return
        try:p=self.presenter(host)
        except Exception as exc:self.log(str(exc),level='error');return
        self.run_task('setup.'+key,lambda:self.services.setup.maintenance(key,p))

    def request_close(self):
        if self.closing:return
        self.closing=True;self.runner.cancel.set();self._polling=False
        if self.services.agent.session is not None:self.services.agent.session.closing.set()
        for p in self.presenters.values():
            fn=getattr(p,'_on_user_cancel',None)
            if callable(fn):fn()
        for button in self.nav.values():button.configure(state='disabled')
        self.log('Closing: waiting for active operations and verified session shutdown. Finish any open approval/installer prompts.')

    def _tick(self):
        if self.closed:return
        self.runner.drain()
        if self.closed:return
        for _ in range(100):
            try:event=self.events.get_nowait()
            except queue.Empty:break
            self._handle_event(event)
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
            if self._ticks==1 or self._ticks%200==0:self.refresh_health()
            session=self.agent_session
            if session is not None and self._ticks%2==0:
                self.runner.submit('agent.poll',session.poll_once,lambda _:None,lambda exc:self.log(str(exc),level='error'),mutate=False)
        if not self.closed:self._timer=self.root.after(50,self._tick)

    def run(self):
        self.root.mainloop()
