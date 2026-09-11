"""New batch entrypoints and compatibility locks do not mutate runtime paths."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_run_and_setup_forward_to_one_application_parser():
    run=(ROOT/'RUN.bat').read_text()
    setup=(ROOT/'SETUP.bat').read_text()
    assert '-m apps.studio %*' in run
    assert '-m apps.setup %*' in setup
    assert '-m launcher %*' not in run
    assert '-m installer %*' not in setup
    for flag in ('--tui','--install','--manage','--skip-','--help'):
        assert flag in run


def test_core_keeps_active_legacy_model_default(monkeypatch):
    monkeypatch.delenv('LLM_MODEL_DIR',raising=False)
    monkeypatch.delenv('LLM_OLLAMA_DIR',raising=False)
    from test_reform_core import _isolated_paths
    assert str(_isolated_paths().MODEL_STORAGE_DIR)==r'C:\LLM_Models'


def test_default_inference_does_not_activate_official_migration(monkeypatch,tmp_path):
    from services.inference.service import InferenceService
    from integrations.legacy import desktop
    monkeypatch.setitem(sys.modules,'project_paths',NS(ENV_DIR=tmp_path/'env',MODEL_STORAGE_DIR=tmp_path/'models'))
    got=[]
    monkeypatch.setattr(desktop,'ManagedInference',lambda env,models,importer:got.append((env,models)) or NS(client=object(),model_dir=models))
    service=InferenceService()
    assert got==[(tmp_path/'env',tmp_path/'models')]


def test_legacy_entry_owns_runtime_until_cleanup_finishes(monkeypatch,tmp_path):
    from services.system import bootstrap
    from services.network.ownership import RuntimeOwner
    monkeypatch.setitem(sys.modules,'project_paths',NS(USER_DATA_DIR=tmp_path))
    competing=RuntimeOwner(tmp_path/'cache'/'desktop-runtime.lock')
    observed=[]
    def check_locked(*a,**k):
        with pytest.raises(RuntimeError):competing.acquire()
        observed.append('locked')
    monkeypatch.setattr(bootstrap.runpy,'run_module',check_locked)
    monkeypatch.setitem(sys.modules,'launcher.core.lifelog',NS(shutdown_then_exit=check_locked))
    assert bootstrap.legacy_entry('launcher',['--tui'])==0
    assert observed==['locked','locked']
    competing.acquire();competing.release()


def test_legacy_entry_restores_argv_on_exception(monkeypatch,tmp_path):
    from services.system import bootstrap
    monkeypatch.setitem(sys.modules,'project_paths',NS(USER_DATA_DIR=tmp_path))
    original=sys.argv
    monkeypatch.setattr(bootstrap.runpy,'run_module',lambda *a,**k:(_ for _ in ()).throw(ValueError('bad')))
    with pytest.raises(ValueError):bootstrap.legacy_entry('installer',[])
    assert sys.argv is original


def chat_backend(tmp_path,ids):
    from test_desktop_integration import fixture
    b,m,c=fixture(tmp_path)
    m['launcher.anythingllm_runtime']=NS(CONTAINER='chat',URL='http://localhost:3001',
        start=lambda **k:True,stop=lambda:c.append('stopped'),is_running=lambda:False)
    sequence=iter(ids)
    m['launcher.services.docker'].DockerService.stop_container=lambda identifier,timeout:c.append('stopped') or True
    m['launcher.services.docker'].DockerService.run=lambda *a,**k: NS(returncode=0,stdout=next(sequence))
    return b,m,c


def test_chat_recreated_container_is_stopped_on_close(tmp_path):
    b,m,c=chat_backend(tmp_path,['old\n','new\n','new\n',''])
    assert b.chat_start('',print,None)=='http://localhost:3001'
    assert b.chat_stop()
    assert c==['stopped']


def test_chat_reused_container_is_not_stopped(tmp_path):
    b,m,c=chat_backend(tmp_path,['old\n','old\n'])
    b.chat_start('',print,None)
    assert b.chat_stop()
    assert not c


def test_chat_replaced_by_another_process_is_not_stopped(tmp_path):
    b,m,c=chat_backend(tmp_path,['','mine\n','someone-else\n'])
    b.chat_start('',print,None)
    assert not b.chat_stop()
    assert not c
