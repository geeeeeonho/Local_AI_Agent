"""Real Tk integration tests; external runtimes are deliberately injected."""
import gc
import time
from pathlib import Path
import pytest
from test_desktop_services import make


def pump(window, predicate=lambda:True, timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        window.root.update()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('UI condition did not settle')


@pytest.fixture
def ui(tmp_path):
    # Finalize prior Tk cycles on the GUI thread, never a new executor worker.
    gc.collect()
    tk = pytest.importorskip('tkinter')
    from apps.shared.window import DesktopWindow
    svc,backend=make(tmp_path)
    try: root=tk.Tk()
    except tk.TclError: pytest.skip('Real Tk requires DISPLAY; run with Xvfb on Linux')
    window=DesktopWindow('studio',svc,root=root,start_polling=False)
    yield window,svc,backend
    window.runner.shutdown()
    window._unsubscribe()
    svc.close()
    try: root.after_cancel(window._timer)
    except tk.TclError: pass
    try: root.destroy()
    except tk.TclError: pass


def test_all_studio_pages_are_persistent(ui):
    w,_,_=ui
    expected={'home','chat','agent','models','network','system','settings','setup'}
    assert set(w.pages)==expected
    for key in expected:
        page=w.pages[key];w.navigate(key);pump(w)
        assert w.pages[key] is page and page.winfo_exists()


def test_chat_start_invokes_shared_service_without_installer(ui):
    w,svc,backend=ui
    w.session_mode.set('block');w.start_chat()
    pump(w,lambda:svc.chat.started)
    assert ('chat','') in backend.calls
    assert not any(c[0]=='search' for c in backend.calls)
    assert svc.chat.url=='http://127.0.0.1:3001'


def test_model_table_uses_real_index(ui):
    import json
    w,svc,_=ui
    blobs=svc.model_dir/'blobs';blobs.mkdir()
    (blobs/('sha256-'+'a'*64)).write_bytes(b'weights')
    m=svc.model_dir/'manifests'/'registry.ollama.ai'/'library'/'demo';m.mkdir(parents=True)
    (m/'latest').write_text(json.dumps({'layers':[{'digest':'sha256:'+'a'*64,'size':7,'mediaType':'application/vnd.ollama.image.model'}]}))
    w.refresh_models();pump(w,lambda:bool(w.model_tree.get_children()))
    values=w.model_tree.item(w.model_tree.get_children()[0])['values']
    assert values[0]=='demo:latest'
    assert (svc.model_dir/'MODEL_INDEX.json').exists()


def test_project_save_round_trips_without_copying_workspace(ui,tmp_path):
    w,svc,_=ui
    w.project_fields['id'].set('demo')
    w.project_fields['name'].set('Demo')
    w.project_fields['workspace_path'].set(str(tmp_path))
    w.save_project();pump(w,lambda:svc.projects.get('demo') is not None)
    assert svc.projects.get('demo').workspace_path==str(tmp_path)
    assert not (tmp_path/'anythingllm').exists()


def test_settings_change_is_shared_not_live_reconfiguration(ui):
    w,svc,backend=ui
    w.settings_scope.set('chat');w.settings_mode.set('tor');w.save_settings()
    pump(w,lambda:svc.settings.network_mode(app='chat').value=='tor')
    assert backend.calls==[]


def test_busy_duplicate_operation_is_not_scheduled(ui):
    import threading
    w,_,_=ui;done=threading.Event()
    assert w.run_task('example',lambda:done.wait(1))
    assert not w.run_task('example',lambda:None)
    done.set();pump(w,lambda:not w.runner.busy('example'))


def test_health_refresh_is_quiet_and_activity_log_is_taller(ui):
    w,_,_=ui
    assert int(w.activity.cget('height')) >= 8
    w.refresh_health()
    pump(w,lambda:not w.runner.busy('health'))
    contents=w.activity.get('1.0','end')
    assert 'health ...' not in contents
    assert 'health completed' not in contents


def test_manual_health_refresh_reports_a_useful_summary(ui):
    w,_,_=ui
    w.refresh_health(fresh=True)
    pump(w,lambda:not w.runner.busy('health'))
    contents=w.activity.get('1.0','end')
    assert '상태 확인 중' in contents
    assert '상태 확인 완료' in contents
    assert 'Ollama=' in contents and 'Docker=' in contents


def test_shutdown_does_not_destroy_ui_before_workers_finish(ui):
    import threading
    w,_,_=ui;done=threading.Event()
    w.run_task('example',lambda:done.wait(2))
    w.request_close()
    pump(w)
    assert w.root.winfo_exists()
    done.set()
    # The window owns final destruction; fixture tolerates an already closed root.
    deadline=time.monotonic()+3
    while not w.closed and time.monotonic()<deadline:
        w.root.update();time.sleep(.01)
    assert w.closed


@pytest.mark.parametrize('app,primary', [('chat','chat'),('interpreter','agent'),('setup','setup'),('studio','home')])
def test_app_specs_have_independent_primary_views(app,primary):
    from apps.shared.specs import SPECS
    assert SPECS[app].primary==primary
    assert primary in SPECS[app].pages


def test_cli_help_does_not_load_runtime():
    import subprocess,sys
    for app in ('studio','chat','interpreter','setup'):
        p=subprocess.run([sys.executable,'-m','apps.'+app,'--help'],capture_output=True,text=True)
        assert p.returncode==0 and 'LocalAI' in p.stdout


def test_apps_do_not_import_backend_or_process_commands():
    import ast
    root=Path(__file__).resolve().parents[1]/'apps'
    assert root.exists()
    for path in root.rglob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names=[node.module or ''] if isinstance(node,ast.ImportFrom) else [v.name for v in node.names] if isinstance(node,ast.Import) else []
            assert not any(n.split('.')[0] in {'integrations','launcher','installer','subprocess'} for n in names),str(path)


def test_settings_view_loads_the_saved_scope(ui):
    w,svc,_=ui
    svc.settings.set_network_mode('tor')
    w.navigate('settings')
    assert w.settings_mode.get()=='tor'


def test_selected_project_is_reloaded_before_start(ui,tmp_path):
    from core.projects.model import Project
    w,svc,_=ui
    svc.projects.save(Project(id='demo',name='Demo',workspace_path=str(tmp_path),network_mode='warp'))
    w.load_projects();w.project_id.set('demo')
    svc.projects.save(Project(id='demo',name='Demo',workspace_path=str(tmp_path),network_mode='tor'))
    assert w.selected_mode('chat')=='tor'


# ── what the Chat page says while it is starting ─────────────────────────
# Ollama and Docker come up as part of Chat start, and both can take a long
# time. The readiness box only ever showed messages tagged service='chat', so
# a ninety-second Docker Desktop boot and every Ollama message went to the
# activity log instead, and the page sat on one unchanging line.

def test_chat_readiness_shows_the_whole_preparation_trail(ui):
    w,svc,backend=ui
    def prepare(mode,log,cancel=None):
        log('Docker 데몬이 응답하지 않습니다 — 자동 시작 시도')
        backend.mode=mode
        return True
    backend.prepare_network=prepare
    backend.inference.ensure_running=lambda log=None:(log and log('Ollama 가동 확인 (3초)')) or 'http://x'
    w.session_mode.set('block');w.start_chat()
    # Wait for the trail itself, not for the worker: the service finishing and
    # the Tk timer draining what it emitted are two different moments.
    pump(w,lambda:svc.chat.started and len(w._chat_progress)>3)
    # The box carries the success summary once Chat is up; the trail it showed
    # on the way there is what these two messages had to reach.
    trail='\n'.join(w._chat_progress)
    assert 'Docker 데몬이 응답하지 않습니다' in trail, trail
    assert 'Ollama 가동 확인' in trail, trail


def test_a_failed_chat_start_leaves_the_reason_on_the_page(ui):
    w,svc,backend=ui
    backend.images=False
    w.session_mode.set('block');w.start_chat()
    pump(w,lambda:'실패' in w.chat_text.get('1.0','end-1c'))
    shown=w.chat_text.get('1.0','end-1c')
    assert '[3/5]' in shown or 'Setup' in shown, shown
    # The page must not keep claiming a start is in progress afterwards.
    assert w._chat_starting is False


def test_closing_interrupts_an_agent_turn_instead_of_waiting_it_out(ui):
    """A model turn can run for minutes, and shutdown queued behind it with no
    way for the user to get the window to close."""
    import threading
    from test_desktop_session import binding
    w,svc,backend=ui
    b,state=binding()
    interrupted=threading.Event()
    b.coordinator.stop_service=lambda:interrupted.set() or 'cancelled'
    backend.agent_open=lambda presenter,network,project,**kw:b
    w.session_mode.set('direct');w.start_agent()
    pump(w,lambda:svc.agent.opened)
    w.request_close()
    pump(w,interrupted.is_set)
    assert interrupted.is_set()


# ── the layout must not starve the controls ──────────────────────────────
# pack hands out what is left over, and when nothing is left it takes it from
# whatever it placed last. That put the primary action of the model screen -
# "선택대로 적용" - at one pixel tall: still present, still answering a click,
# but nowhere near where it was drawn. This walks every page at the window's
# own documented minimum size and insists the controls are still controls.

CONTROLS = ('TButton', 'TCheckbutton', 'TRadiobutton', 'TCombobox', 'TEntry')


def every_widget(node, out):
    out.append(node)
    for child in node.winfo_children():
        every_widget(child, out)


def on_a_hidden_tab(widget, notebooks):
    node, child = widget, None
    while node is not None:
        if str(node) in notebooks and child is not None:
            if str(child) != notebooks[str(node)].select():
                return True
        child, node = node, getattr(node, 'master', None)
    return False


def test_no_control_is_squeezed_to_nothing_at_the_minimum_window_size(ui):
    w,svc,backend=ui
    w.root.update();w.root.wm_geometry('880x560')
    pump(w,lambda:w.root.winfo_height()<=560)
    starved=[]
    for key in w.spec.pages:
        w.navigate(key);pump(w)
        book={'chat':getattr(w,'chat_tabs',None),'models':getattr(w,'model_tabs',None)}.get(key)
        for tab in (list(book.tabs()) if book is not None else [None]):
            if tab is not None:book.select(tab);pump(w)
            nodes=[];every_widget(w.pages[key],nodes)
            notebooks={str(n):n for n in nodes if n.winfo_class()=='TNotebook'}
            for node in nodes:
                if node.winfo_class() not in CONTROLS:continue
                if on_a_hidden_tab(node,notebooks) or not node.winfo_ismapped():continue
                if node.winfo_height()<18:
                    label=node.cget('text') if node.winfo_class()!='TEntry' else ''
                    starved.append('%s %s(%s) %dpx' % (key,node.winfo_class(),label,node.winfo_height()))
    assert starved==[],'쓸 수 없을 만큼 눌린 컨트롤:\n  '+'\n  '.join(starved)


def test_the_wheel_handler_is_not_stacked_again_on_every_refresh(ui):
    """The catalogue rebinds after each redraw; add='+' used to keep the old
    handler too, so one notch eventually scrolled several pages at once."""
    w,svc,backend=ui
    w.navigate('models');pump(w)
    area=w.page_scrolls['models.choose']
    for _ in range(4):area.bind_content()
    handlers=[line for line in area.canvas.bind('<MouseWheel>').split('\n') if line.strip()]
    assert len(handlers)<=1,handlers


def test_a_tree_keeps_its_own_wheel_instead_of_scrolling_the_page(ui):
    w,svc,backend=ui
    w.navigate('models');pump(w)
    w.model_tabs.select(w.model_pages['disk']);pump(w)
    bound=[line for line in w.model_tree.bind('<MouseWheel>').split('\n') if line.strip()]
    assert bound==[],'the page must not take the wheel from a widget that scrolls itself'


def test_the_activity_log_folds_away_and_comes_back(ui):
    """Eight lines of log is a quarter of the window at its minimum size."""
    w,svc,backend=ui
    w.root.update();w.root.wm_geometry('880x560')
    pump(w,lambda:w.root.winfo_height()<=560)
    w.navigate('models');pump(w)
    opened=w.page_area.winfo_height()
    w.toggle_activity();pump(w)
    folded=w.page_area.winfo_height()
    assert folded>opened,'folding the log has to give its space to the page'
    w.toggle_activity();pump(w)
    assert w.page_area.winfo_height()==opened,'and unfolding has to give it back'


def test_the_folded_choice_is_remembered(ui):
    w,svc,backend=ui
    w.toggle_activity()
    pump(w,lambda:not w.runner.busy())
    assert svc.settings.activity_visible() is False


def test_explanations_rewrap_to_the_width_they_actually_have(ui):
    """Every wraplength was a pixel count picked for a wide window; narrower
    than that and the sentence explaining a button was simply cut off."""
    w,svc,backend=ui
    w.navigate('models')
    # A notebook pane that has never been shown is one pixel wide, so ask the
    # tab the user is actually looking at.
    w.model_tabs.select(w.model_pages['choose']);pump(w)
    w.root.wm_geometry('1280x860')
    pump(w,lambda:w.model_pages['choose'].winfo_width()>900)
    wide=int(w.choice_storage_label.cget('wraplength'))
    w.root.wm_geometry('880x560')
    pump(w,lambda:w.model_pages['choose'].winfo_width()<800)
    narrow=int(w.choice_storage_label.cget('wraplength'))
    assert narrow<wide,'the label kept a width the window no longer has: %s/%s'%(narrow,wide)
