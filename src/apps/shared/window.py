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
from .specs import SPECS, LABELS
from .tasks import TaskRunner
from .widgets import BG, MUTED, ACCENT, SURFACE, set_text, theme
from . import views


class DesktopWindow:
    def __init__(self, app, services, *, root=None, start_polling=True):
        self.app, self.spec, self.services = app, SPECS[app], services
        self.root = root if root is not None else tk.Tk()
        theme(self.root)
        self.root.title(self.spec.title)
        self.root.geometry('1280x860');self.root.minsize(1000,720)
        self.runner = TaskRunner()
        self.events = queue.Queue(maxsize=2048)
        self._unsubscribe = services.events.subscribe('*', self._enqueue)
        self.closing = False;self.closed = False;self._shutdown_started = False
        self._polling = start_polling;self._ticks = 0
        self.pages = {};self.hosts = {};self.presenters = {};self.nav = {}
        self._model_records = {};self._projects = {}
        self.agent_panel = None;self.agent_session = None
        self.session_mode = tk.StringVar(master=self.root,value='inherit')
        self.project_id = tk.StringVar(master=self.root,value='(none)')
        self.message = tk.StringVar(master=self.root,value='Ready')
        self.health = tk.StringVar(master=self.root,value='Ollama ?    Docker ?    Chat ?    Search ?')
        self._build()
        self.load_projects()
        self.navigate(self.spec.primary)
        self.root.protocol('WM_DELETE_WINDOW', self.request_close)
        self._timer = self.root.after(50, self._tick)

    def _build(self):
        outer=ttk.Frame(self.root);outer.pack(fill='both',expand=True)
        sidebar=tk.Frame(outer,bg=BG,width=215);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        tk.Label(sidebar,text='LOCAL AI',bg=BG,fg=ACCENT,font=('Segoe UI',17,'bold')).pack(anchor='w',padx=23,pady=(27,3))
        tk.Label(sidebar,text=self.spec.title.replace('LocalAI ',''),bg=BG,fg=MUTED,font=('Segoe UI',10)).pack(anchor='w',padx=24,pady=(0,30))
        for key in self.spec.pages:
            b=ttk.Button(sidebar,text=LABELS[key],style='Nav.TButton',command=lambda k=key:self.navigate(k))
            b.pack(fill='x',padx=10,pady=2);self.nav[key]=b
        tk.Label(sidebar,text='Shared services\nLocal data stays local',bg=BG,fg=MUTED,
                 justify='left',font=('Segoe UI',9)).pack(side='bottom',anchor='w',padx=24,pady=22)
        tk.Frame(outer,width=1,bg='#2b3545').pack(side='left',fill='y')
        content=ttk.Frame(outer);content.pack(fill='both',expand=True)
        header=ttk.Frame(content,padding=(24,18));header.pack(fill='x')
        ttk.Label(header,text='PROJECT',style='Muted.TLabel').pack(side='left',padx=(0,12))
        self.project_box=ttk.Combobox(header,textvariable=self.project_id,state='readonly',values=('(none)',),width=22)
        self.project_box.pack(side='left')
        self.project_box.bind('<<ComboboxSelected>>',lambda event:self.project_selected())
        ttk.Label(header,textvariable=self.health,style='Muted.TLabel').pack(side='right')
        tk.Frame(content,height=1,bg='#2b3545').pack(fill='x')
        footer=ttk.Frame(content,padding=(18,8));footer.pack(side='bottom',fill='x')
        ttk.Label(footer,textvariable=self.message,style='Muted.TLabel',wraplength=900).pack(anchor='w')
        self.activity=tk.Text(content,height=4,bg=SURFACE,fg=MUTED,relief='flat',
                              font=('Consolas',9),padx=14,pady=8,state='disabled')
        self.activity.pack(side='bottom',fill='x',padx=24,pady=(4,0))
        self.page_area=ttk.Frame(content);self.page_area.pack(fill='both',expand=True)
        self.page_area.columnconfigure(0,weight=1);self.page_area.rowconfigure(0,weight=1)
        for key in self.spec.pages:
            page=views.build(self.page_area,key,self);page.grid(row=0,column=0,sticky='nsew');self.pages[key]=page

    def navigate(self,key):
        if key not in self.pages: return
        self.pages[key].tkraise();self.current_page=key
        for name,button in self.nav.items():
            button.configure(style='Selected.Nav.TButton' if name==key else 'Nav.TButton')
        if key=='projects':self.load_projects();self.project_selected()
        if key=='settings':self.load_settings()

    def _enqueue(self,event):
        try:self.events.put_nowait(event)
        except queue.Full:
            # Progress history is bounded; approval decisions never travel here.
            try:self.events.get_nowait()
            except queue.Empty:pass
            try:self.events.put_nowait(event)
            except queue.Full:pass

    def log(self,text):
        text=str(text)
        self.message.set(text[:220])
        self.activity.configure(state='normal')
        self.activity.insert('end',text+'\n')
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
        ok=self.runner.submit(key,fn,finish,lambda exc:self.log(key+': '+str(exc)),mutate=mutate)
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
            self.project_box.configure(values=('(none)',*self._projects))
            if self.project_id.get() not in self._projects:self.project_id.set('(none)')
        except Exception as exc:self.log('Project registry: '+str(exc))

    def project_selected(self):
        try:project=self.current_project()
        except Exception as exc:self.log('Project registry: '+str(exc));return
        if not hasattr(self,'project_fields'):return
        data=project.to_dict() if project else {}
        for key,var in self.project_fields.items():
            var.set(data.get(key) or ('inherit' if key=='network_mode' else ''))

    def save_project(self):
        data={k:v.get().strip() for k,v in self.project_fields.items()}
        data['network_mode']=None if data['network_mode']=='inherit' else data['network_mode']
        try:project=Project(**data)
        except (TypeError,ValueError) as exc:self.log(str(exc));return
        def saved(_):
            self.load_projects();self.project_id.set(project.id);self.project_selected()
        self.run_task('project.save',lambda:self.services.projects.save(project),saved)

    def delete_project(self):
        identifier=self.project_fields['id'].get().strip()
        if identifier not in self._projects:return
        if not messagebox.askyesno('Project', 'Delete this linkage only? Workspace files remain unchanged.',parent=self.root):return
        self.run_task('project.delete',lambda:self.services.projects.delete(identifier),lambda _:self.load_projects())

    def load_settings(self):
        scope=self.settings_scope.get()
        try:self.settings_mode.set(self.services.resolve_mode(None if scope=='global' else scope).value)
        except Exception as exc:self.log('Settings: '+str(exc))

    def save_settings(self):
        scope,mode=self.settings_scope.get(),self.settings_mode.get()
        self.run_task('settings.save',lambda:self.services.settings.set_network_mode(mode,
            app=None if scope=='global' else scope))

    def start_chat(self):
        if self.services.chat.started:self.open_chat();return
        try:project=self.current_project();mode=self.selected_mode('chat')
        except Exception as exc:self.log(str(exc));return
        model=project.chat_model if project else ''
        def ready(url):
            self.chat_open_button.configure(state='normal')
            set_text(self.chat_text,'AnythingLLM is ready\n\n'+str(url)+'\nNetwork: '+mode+
                '\nWorkspace linkage: '+(project.anythingllm_workspace if project else '(none)')+
                '\n\nOpen AnythingLLM to use Chat, files, documents and RAG.\nUse Session stop when finished.')
        self.run_task('chat.start',lambda:self.services.chat.start(mode,model=model,cancel=self.runner.cancel.is_set),ready)

    def open_chat(self):
        try:
            if self.services.chat.url:webbrowser.open(local_url(self.services.chat.url))
        except Exception as exc:self.log(str(exc))

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
        except Exception as exc:self.log(str(exc));return
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
            self.model_summary.set(f"{totals['models']} models | {totals['size_bytes']/1024**3:.3f} GiB | scan_complete={index['scan_complete']}")
            if index['errors']:set_text(self.model_details,json.dumps(index['errors'],ensure_ascii=False,indent=2))
        self.run_task('models.refresh',scan,display)

    def show_model_details(self):
        chosen=self.model_tree.selection()
        if chosen:set_text(self.model_details,json.dumps(self._model_records[chosen[0]],ensure_ascii=False,indent=2))

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
            self.log('Stop active sessions before Setup / Repair.');return
        if not messagebox.askyesno('Setup / Repair','Run the existing installer in a separate console?\nReview its prompts before installing or migrating data.',parent=self.root):return
        self.run_task('setup.repair',self.services.setup.repair)

    def change_model(self,operation):
        name=self.install_tag.get().strip()
        if not name:return
        text=('Download '+name+' through the local Ollama server?' if operation=='install' else 'Remove model '+name+' using Ollama? Shared blobs are managed by Ollama.')
        if not messagebox.askyesno('Model management',text,parent=self.root):return
        fn=self.services.setup.install_model if operation=='install' else self.services.setup.remove_model
        self.run_task('models.'+operation,lambda:fn(name),lambda _:self.refresh_models() if 'models' in self.pages else None)

    def maintenance(self,key):
        if self.services.chat.started or self.services.agent.opened:
            self.log('Stop active sessions before maintenance.');return
        try:p=self.presenter('setup')
        except Exception as exc:self.log(str(exc));return
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
            if self._ticks==1 or self._ticks%200==0:self.refresh_health()
            session=self.agent_session
            if session is not None and self._ticks%2==0:
                self.runner.submit('agent.poll',session.poll_once,lambda _:None,lambda exc:self.log(str(exc)),mutate=False)
        if not self.closed:self._timer=self.root.after(50,self._tick)

    def run(self):
        self.root.mainloop()
