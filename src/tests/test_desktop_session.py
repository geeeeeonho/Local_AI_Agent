from types import SimpleNamespace as NS
import threading
import pytest


def binding():
    from core.agent import AgentBinding
    state = NS(running=False, stopped=0, starts=0)
    def start(): state.running=True; state.starts+=1; return True
    def stop(timeout): state.running=False; state.stopped+=1
    engine=NS(is_running=lambda:state.running,stop=stop)
    coordinator=NS(service=engine, model_tag='test',start_current=start,
        restart_model=lambda tag:True,reload_policy=lambda:True,restart_service=start,
        new_session=start,stop_service=lambda:'cancelled')
    def controller(service, **kw):
        return NS(handle_input=lambda text:kw['dispatch']('input',lambda:None),
                  poll_once=lambda max_n:0,stop=lambda:kw['stop_service'](),
                  restart=lambda:kw['restart_service']())
    return AgentBinding(coordinator,controller,lambda event:True,{'workspace':'/tmp','model':'test'}),state


def test_session_owns_start_and_verified_shutdown():
    from services.agent.session import AgentSession
    from core.events import EventBus
    b,s=binding(); a=AgentSession(b,EventBus())
    assert a.start() and s.running
    assert a.close() and not s.running
    assert not a.start() and s.starts==1


def test_close_during_start_prevents_late_running_agent():
    from services.agent.session import AgentSession
    from core.events import EventBus
    b,s=binding(); entered=threading.Event(); finish=threading.Event()
    original=b.coordinator.start_current
    def boot(): entered.set(); finish.wait(2); return original()
    b.coordinator.start_current=boot
    a=AgentSession(b,EventBus()); result=[]
    t=threading.Thread(target=lambda:result.append(a.start()));t.start();assert entered.wait(1)
    c=threading.Thread(target=a.close);c.start()
    assert a.closing.wait(1)
    finish.set();t.join(2);c.join(2)
    assert not s.running and result==[False]


def test_unverified_stop_does_not_report_success():
    from services.agent.session import AgentSession
    from core.events import EventBus
    b,s=binding();a=AgentSession(b,EventBus());a.start()
    b.coordinator.service.stop=lambda timeout:None
    assert not a.close()


def test_approval_is_declined_after_shutdown_started():
    from services.agent.session import AgentSession
    from core.events import EventBus
    b,s=binding();a=AgentSession(b,EventBus());a.closing.set()
    assert a.approve(object()) is False


def test_existing_network_intent_used_when_new_settings_absent(tmp_path):
    from test_desktop_services import make
    svc,backend=make(tmp_path);backend.mode='tor'
    assert svc.resolve_mode('chat').value=='tor'
    svc.settings.set_network_mode('block')
    assert svc.resolve_mode('chat').value=='block'


def test_integrations_do_not_import_services_or_apps():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for file in (root/'integrations').rglob('*.py'):
        for node in ast.walk(ast.parse(file.read_text())):
            names=[node.module or ''] if isinstance(node,ast.ImportFrom) else [v.name for v in node.names] if isinstance(node,ast.Import) else []
            assert not any(n.split('.')[0] in ('apps','services') for n in names), str(file)


def test_cancelled_agent_wizard_does_not_start_late(tmp_path):
    from test_desktop_services import make
    svc,backend=make(tmp_path);cancel=threading.Event()
    b,state=binding()
    def configure(*args):cancel.set();return b
    backend.agent_open=configure
    assert svc.agent.open(object(),'direct',cancel=cancel.is_set) is None
    assert state.starts==0
    svc.close()


def test_service_level_repair_refuses_active_chat(tmp_path):
    from test_desktop_services import make
    svc,backend=make(tmp_path);svc.chat.start('direct')
    backend.run_setup=lambda:pytest.fail('installer started during active chat')
    with pytest.raises(RuntimeError,match='session'):svc.setup.repair()
    svc.close()


def test_failed_chat_start_can_be_cleaned_up(tmp_path):
    from test_desktop_services import make
    svc,backend=make(tmp_path)
    def start(*args):raise RuntimeError('late startup failure')
    backend.chat_start=start
    with pytest.raises(RuntimeError):svc.chat.start('direct')
    assert svc.close()
    assert ('chat_stop',) in backend.calls
