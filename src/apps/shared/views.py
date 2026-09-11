"""Persistent view construction. User actions are delegated to the shared shell."""
import tkinter as tk
from tkinter import ttk, filedialog
from .widgets import heading, note, text_box, PanelHost, set_text
from .specs import LABELS, DESCRIPTIONS


def row(parent):
    frame=ttk.Frame(parent);frame.pack(fill='x',pady=(0,10));return frame


def button(parent,text,fn,accent=False):
    b=ttk.Button(parent,text=text,command=fn,style='Accent.TButton' if accent else 'TButton')
    b.pack(side='left',padx=(0,8));return b


def mode_row(parent,w):
    r=row(parent)
    ttk.Label(r,text='Session network').pack(side='left',padx=(0,10))
    ttk.Combobox(r,textvariable=w.session_mode,state='readonly',width=13,
                 values=('inherit','warp','tor','direct','block')).pack(side='left')
    return r


def home(parent,w):
    note(parent,'\uc790\uc8fc \uc4f0\ub294 \uae30\ub2a5\uc744 \ud558\ub098\uc758 \ucc3d\uc5d0\uc11c \uc2e4\ud589\ud558\uc138\uc694.\n'
         '\ubaa8\ub378\uacfc \ubb38\uc11c\ub294 \uae30\uc874 \uc704\uce58\ub97c \uc720\uc9c0\ud569\ub2c8\ub2e4.')
    for key,caption in [('chat','Chat / Knowledge'),('agent','Agent / Automation'),('projects','Project workspace'),('models','Model inventory')]:
        card=ttk.Frame(parent,style='Card.TFrame',padding=18);card.pack(fill='x',pady=6)
        ttk.Button(card,text=caption,command=lambda k=key:w.navigate(k)).pack(side='left')
        ttk.Label(card,text=DESCRIPTIONS[key],wraplength=500,style='Card.TLabel').pack(side='left',padx=20)
    note(parent,'Studio / Chat / Interpreter / Setup\uc740 \ub3d9\uc77c\ud55c \uc11c\ube44\uc2a4\ub97c \uc0ac\uc6a9\ud569\ub2c8\ub2e4.\n'
         '\uc0c1\ud0dc \ud655\uc778\uc740 \uc124\uce58\ub098 \ubaa8\ub378 \uc2e4\ud589\uc744 \uc790\ub3d9\uc73c\ub85c \uc2dc\uc791\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.')


def chat(parent,w):
    mode_row(parent,w)
    r=row(parent)
    button(r,'\ucc44\ud305 \uc900\ube44',w.start_chat,True)
    w.chat_open_button=button(r,'AnythingLLM \uc5f4\uae30',w.open_chat)
    w.chat_open_button.configure(state='disabled')
    button(r,'\uc138\uc158 \uc885\ub8cc',w.stop_sessions)
    note(parent,'AnythingLLM\uc758 \uc6d0\ub798 \ud654\uba74\uc744 \ube0c\ub77c\uc6b0\uc800\uc5d0\uc11c \uc5fd\ub2c8\ub2e4. \ubb38\uc11c / RAG / \ub300\ud654 \uae30\ub85d\uc744 \ubcf5\uc81c\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.\n'
         '\ub2e4\ub978 \ud0ed\uc73c\ub85c \uc774\ub3d9\ud574\ub3c4 \uc138\uc158\uc740 \uc720\uc9c0\ub429\ub2c8\ub2e4. \ub204\ub77d\ub41c \uc124\uce58\ub294 Setup / Repair\uc5d0\uc11c \uc9c4\ud589\ud569\ub2c8\ub2e4.')
    w.chat_text=text_box(parent)
    set_text(w.chat_text,'Ready to connect\n\nSelect a project and network intent, then prepare Chat.\nBlock: local Chat/RAG only; public search stays disabled.')


def agent(parent,w):
    r=mode_row(parent,w)
    button(r,'Agent \uc2dc\uc791',w.start_agent,True)
    button(r,'\uc138\uc158 \uc885\ub8cc',w.stop_sessions)
    note(parent,'\uae30\uc874 \ud504\ub85c\ud544 / \ubaa8\ub378 / Host\u00b7Sandbox / \ud3f4\ub354 \uc120\ud0dd\uacfc \uc2b9\uc778 \uc808\ucc28\ub97c \uc0ac\uc6a9\ud569\ub2c8\ub2e4.\n'
         'Project \uc791\uc5c5 \ud3f4\ub354\ub294 \uc120\ud0dd \ucc3d\uc758 \uae30\ubcf8\uac12\uc77c \ubfd0, \uc790\ub3d9 \uc811\uadfc \ud5c8\uc6a9\uc774 \uc544\ub2d9\ub2c8\ub2e4.')
    w.hosts['agent']=PanelHost(parent)


def projects(parent,w):
    w.project_fields={key:tk.StringVar(master=w.root,value='inherit' if key=='network_mode' else '')
                      for key in ('id','name','workspace_path','anythingllm_workspace','chat_model','agent_model','network_mode')}
    labels={'id':'Project ID','name':'\uc774\ub984','workspace_path':'Workspace \ud3f4\ub354',
            'anythingllm_workspace':'AnythingLLM Workspace slug','chat_model':'Chat \ubaa8\ub378 (\uc120\ud0dd)',
            'agent_model':'Agent \ubaa8\ub378 \ucc38\uace0\uac12','network_mode':'Network override'}
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
    button(r,'\ud3f4\ub354 \uc120\ud0dd',choose)
    button(r,'\uc800\uc7a5',w.save_project,True)
    button(r,'\uc5f0\uacb0 \uc0ad\uc81c',w.delete_project)
    note(parent,'\uc5f0\uacb0 \uc815\ubcf4\ub9cc \uc800\uc7a5\ud569\ub2c8\ub2e4. Workspace \ub0b4\uc6a9\uc774\ub098 AnythingLLM \ub370\uc774\ud130\ub294 \uc774\ub3d9\u00b7\uc0ad\uc81c\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.\n'
         'Agent \ubaa8\ub378\uc740 \uc2dc\uc791 \uc124\uc815\uc5d0\uc11c \ub2e4\uc2dc \ud655\uc778\ud558\uc138\uc694.')


def models(parent,w):
    r=row(parent);button(r,'\uc778\ub371\uc2a4 \uac31\uc2e0',w.refresh_models,True)
    button(r,'Setup / Repair',lambda:w.navigate('setup'))
    w.model_summary=tk.StringVar(master=w.root,value=str(w.services.model_dir))
    ttk.Label(parent,textvariable=w.model_summary,style='Muted.TLabel').pack(anchor='w',pady=8)
    columns=('name','size','shared','exclusive','status')
    wrapper=ttk.Frame(parent);wrapper.pack(fill='both',expand=True)
    w.model_tree=ttk.Treeview(wrapper,columns=columns,show='headings',height=7)
    for key,title,width in zip(columns,('Model','Size (GiB)','Shared','Exclusive','Files'),(350,90,90,90,150)):
        w.model_tree.heading(key,text=title);w.model_tree.column(key,width=width,minwidth=70)
    scroll=ttk.Scrollbar(wrapper,orient='vertical',command=w.model_tree.yview)
    w.model_tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');w.model_tree.pack(fill='both',expand=True)
    w.model_tree.bind('<<TreeviewSelect>>',lambda event:w.show_model_details())
    w.model_details=text_box(parent,height=7)
    set_text(w.model_details,'Select a model to inspect its manifest and blobs.\nUnreferenced files are observations, never permission to delete.')


def network(parent,w):
    note(parent,'Direct = \uc778\ud130\ub137 \uc9c1\uc811 \uc5f0\uacb0\nWARP / Tor = \uad00\ub9ac\ud615 \ud504\ub85d\uc2dc \uc900\ube44 \uc2e4\ud328 \uc2dc \uc2e4\ud589 \uc911\ub2e8\n'
         'Block = \uacf5\uc6a9 \uc6f9 egress \ucc28\ub2e8, \uac80\uc0c9 \ube44\ud65c\uc131, Host Block \uac70\ubd80\n\n'
         '\uc774 \ubc84\uc804\uc740 \ub3d9\uc77c \ud504\ub85c\uc81d\ud2b8\uc758 \ud55c \ucc3d\uc774 \uad00\ub9ac\ud615 \uc2e4\ud589\uc744 \uc18c\uc720\ud569\ub2c8\ub2e4. \ub2e4\ub978 \ucc3d\uc740 \uc870\ud68c\ud560 \uc218 \uc788\uc73c\uba70, '
         '\uc18c\uc720 \ucc3d\uc758 \uc138\uc158\uc744 \uc885\ub8cc\ud55c \ub4a4 \ubcc0\uacbd\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.')
    r=row(parent);button(r,'\uc0c1\ud0dc \ud655\uc778',w.refresh_health)
    button(r,'\uc815\ucc45 \uc124\uc815',lambda:w.navigate('settings'))
    button(r,'\uc138\uc158 \uc885\ub8cc / \uc7a0\uae08 \ud574\uc81c',w.stop_sessions)
    w.network_text=text_box(parent)
    set_text(w.network_text,'No managed session started in this window.')


def system(parent,w):
    r=row(parent);button(r,'\uc0c1\ud0dc \uc0c8\ub85c\uace0\uce68',w.refresh_health,True)
    button(r,'Setup / Repair',lambda:w.navigate('setup'))
    w.system_text=text_box(parent)
    set_text(w.system_text,'Environment: '+str(w.services.env)+'\nModels: '+str(w.services.model_dir)+'\nUser data: '+str(w.services.data))


def settings(parent,w):
    w.settings_scope=tk.StringVar(master=w.root,value='global')
    w.settings_mode=tk.StringVar(master=w.root,value='warp')
    r=row(parent)
    scope_box=ttk.Combobox(r,textvariable=w.settings_scope,values=('global','studio','chat','interpreter','setup'),state='readonly',width=18)
    scope_box.pack(side='left',padx=(0,12))
    scope_box.bind('<<ComboboxSelected>>',lambda event:w.load_settings())
    ttk.Combobox(r,textvariable=w.settings_mode,values=('warp','tor','direct','block'),state='readonly',width=18).pack(side='left',padx=(0,12))
    button(r,'\uc800\uc7a5',w.save_settings,True)
    note(parent,'\ubcc0\uacbd\uc740 \ub2e4\uc74c \uc138\uc158\ubd80\ud130 \uc801\uc6a9\ub429\ub2c8\ub2e4. \uc2e4\ud589 \uc911\uc778 \uc11c\ube44\uc2a4\uc758 \ub124\ud2b8\uc6cc\ud06c\ub97c \uc989\uc2dc \ubc14\uafb8\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.\n'
         '\uc0c8 \uc124\uc815\uc774 \uc5c6\uc73c\uba74 \uae30\uc874 \ub7f0\ucc98\uc758 \ub124\ud2b8\uc6cc\ud06c \uc124\uc815\uc744 \uae30\ubcf8\uac12\uc73c\ub85c \uc0ac\uc6a9\ud569\ub2c8\ub2e4.')


def setup(parent,w):
    r=row(parent);button(r,'\uc124\uce58 / \ubcf5\uad6c \uc2dc\uc791',w.repair,True)
    button(r,'\uc0c1\ud0dc \ud655\uc778',w.refresh_health)
    note(parent,'\uc124\uce58\uae30\ub294 \ubcc4\ub3c4 \ucf58\uc194\uc5d0\uc11c \uc5f4\ub9ac\uba70 \uc644\ub8cc\ub420 \ub54c\uae4c\uc9c0 \uc774 \ucc3d\uc774 \ucd94\uc801\ud569\ub2c8\ub2e4.\n'
         '\uad00\ub9ac\ud615 \uc138\uc158\uc744 \uba3c\uc800 \uc885\ub8cc\ud558\uc138\uc694. \uae30\uc874 \uc124\uce58\u00b7\ubaa8\ub378 \uacbd\ub85c\ub97c \uc720\uc9c0\ud569\ub2c8\ub2e4.')
    ttk.Label(parent,text='Model management',style='Section.TLabel').pack(anchor='w',pady=(12,8))
    r=row(parent);w.install_tag=tk.StringVar(master=w.root)
    ttk.Entry(r,textvariable=w.install_tag,width=35).pack(side='left',padx=(0,10))
    button(r,'\ubaa8\ub378 \uc124\uce58',lambda:w.change_model('install'))
    button(r,'\ubaa8\ub378 \uc0ad\uc81c',lambda:w.change_model('remove'))
    note(parent,'\uc124\uce58 \ub2e4\uc6b4\ub85c\ub4dc\ub294 Ollama \uc11c\ubc84\uc758 \ud638\uc2a4\ud2b8 \ub124\ud2b8\uc6cc\ud06c\ub97c \uc0ac\uc6a9\ud569\ub2c8\ub2e4. WARP/Tor \uc6b0\ud68c\ub97c \ubcf4\uc7a5\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. Block\uc5d0\uc11c\ub294 \ub2e4\uc6b4\ub85c\ub4dc\ub97c \uac70\ubd80\ud569\ub2c8\ub2e4.')
    r=row(parent)
    for key,text in [('docker_image','Docker \ube4c\ub4dc'),('docker_clean','Docker \uc815\ub9ac'),('searxng_action','Search \uad00\ub9ac'),('settings_action','\uae30\uc874 \uc124\uc815')]:
        button(r,text,lambda k=key:w.maintenance(k))
    w.hosts['setup']=PanelHost(parent)


BUILDERS={'home':home,'chat':chat,'projects':projects,'agent':agent,'models':models,
          'network':network,'system':system,'settings':settings,'setup':setup}


def build(parent,key,w):
    page=ttk.Frame(parent,padding=(26,24))
    heading(page,LABELS[key],DESCRIPTIONS[key])
    BUILDERS[key](page,w)
    return page
