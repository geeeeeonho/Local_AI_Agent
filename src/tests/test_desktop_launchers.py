"""New batch entrypoints and compatibility locks do not mutate runtime paths."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_run_is_the_only_batch_entrypoint_and_uses_the_shared_parser():
    run=(ROOT/'RUN.bat').read_text()
    assert sorted(path.name for path in ROOT.glob('*.bat')) == ['RUN.bat']
    assert '-m apps.studio %*' in run
    assert '-m launcher %*' not in run
    assert '-m installer %*' not in run
    assert 'llm_environment\\venv\\Scripts' not in run


def test_readme_names_every_entrypoint_a_user_can_double_click():
    """루트의 .bat 을 늘리고 README 를 안 고치면 아무도 그 진입점을 모른다."""
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    present=sorted(path.name for path in ROOT.glob('*.bat'))
    assert present
    missing=[name for name in present if name not in readme]
    assert not missing, 'README 에 없는 진입점: '+', '.join(missing)


def test_paths_follow_ollama_and_still_remember_the_old_store(monkeypatch):
    monkeypatch.delenv('LLM_MODEL_DIR',raising=False)
    monkeypatch.delenv('LLM_OLLAMA_DIR',raising=False)
    from core import ollama_paths
    from test_reform_core import _isolated_paths
    paths=_isolated_paths()
    assert paths.MODEL_STORAGE_DIR==ollama_paths.models_dir()
    assert str(paths.LEGACY_FORCED_MODEL_DIR)==r'C:\LLM_Models'


# Redirect the canonical module's attributes instead of replacing the module:
# every deferred `from project_paths import ...` in the tree reads these, and a
# partial stand-in would hide names that other importers legitimately need.
def test_default_inference_does_not_activate_official_migration(monkeypatch,tmp_path):
    from services.inference.service import InferenceService
    from integrations.legacy import desktop
    import project_paths
    monkeypatch.setattr(project_paths,'ENV_DIR',tmp_path/'env')
    monkeypatch.setattr(project_paths,'MODEL_STORAGE_DIR',tmp_path/'models')
    got=[]
    monkeypatch.setattr(desktop,'ManagedInference',lambda env,models,importer:got.append((env,models)) or NS(client=object(),model_dir=models))
    InferenceService()
    assert got==[(tmp_path/'env',tmp_path/'models')]


def test_module_entry_owns_runtime_until_cleanup_finishes(monkeypatch,tmp_path):
    from services.system import bootstrap
    from services.network.ownership import RuntimeOwner
    import project_paths
    monkeypatch.setattr(project_paths,'USER_DATA_DIR',tmp_path)
    competing=RuntimeOwner(tmp_path/'cache'/'desktop-runtime.lock')
    observed=[]
    def check_locked(*a,**k):
        with pytest.raises(RuntimeError):competing.acquire()
        observed.append('locked')
    monkeypatch.setattr(bootstrap.runpy,'run_module',check_locked)
    monkeypatch.setitem(sys.modules,'launcher.core.lifelog',NS(shutdown_then_exit=check_locked))
    assert bootstrap.run_module_entry('launcher',['--tui'])==0
    assert observed==['locked','locked']
    competing.acquire();competing.release()


def test_module_entry_restores_argv_on_exception(monkeypatch,tmp_path):
    from services.system import bootstrap
    import project_paths
    monkeypatch.setattr(project_paths,'USER_DATA_DIR',tmp_path)
    original=sys.argv
    monkeypatch.setattr(bootstrap.runpy,'run_module',lambda *a,**k:(_ for _ in ()).throw(ValueError('bad')))
    with pytest.raises(ValueError):bootstrap.run_module_entry('installer',[])
    assert sys.argv is original


def chat_backend(tmp_path,ids,monkeypatch=None,installed=('chosen:latest',)):
    from test_desktop_integration import fixture
    b,m,c=fixture(tmp_path)
    started=[]
    m['launcher.anythingllm_runtime']=NS(CONTAINER='chat',URL='http://localhost:3001',
        started=started,start=lambda **k:started.append(k) or True,
        stop=lambda:c.append('stopped'),is_running=lambda:False)
    sequence=iter(ids)
    m['launcher.services.docker'].DockerService.stop_container=lambda identifier,timeout:c.append('stopped') or True
    m['launcher.services.docker'].DockerService.run=lambda *a,**k: NS(returncode=0,stdout=next(sequence))
    # Chat resolves its model against the live inventory now, so the stubbed
    # backend needs a stubbed router too — otherwise these reach 127.0.0.1.
    if monkeypatch is not None:
        import model_router_stub as router
        router.serve(monkeypatch,list(installed))
    return b,m,c


def test_chat_recreated_container_is_stopped_on_close(tmp_path,monkeypatch):
    b,m,c=chat_backend(tmp_path,['old\n','new\n','new\n',''],monkeypatch)
    assert b.chat_start('',print,None)=='http://localhost:3001'
    assert b.chat_stop()
    assert c==['stopped']


def test_chat_start_passes_the_canonical_token_limit_and_model(tmp_path,monkeypatch):
    """컨텍스트 한도는 config 한 곳에서만 온다. 예전 코드는 존재하지 않는
    이름 두 개를 거쳐 AttributeError 로 Chat 시작 자체를 막았다."""
    from launcher import config
    b,m,c=chat_backend(tmp_path,['','id\n'],monkeypatch,installed=('picked:tag',))
    b.chat_start('picked:tag',print,None)
    started,=m['launcher.anythingllm_runtime'].started
    assert started['token_limit']==config.CHAT_CONTEXT_WINDOW
    assert started['model_tag']=='picked:tag'


def test_chat_start_picks_an_installed_model_not_a_static_default(tmp_path,monkeypatch):
    """config.MODEL_TAG is a catalogue entry, not proof of an install. Falling
    back to it made Chat ask AnythingLLM for a model Ollama does not have."""
    b,m,c=chat_backend(tmp_path,['','id\n'],monkeypatch,installed=('lighter:3b',))
    b.chat_start('',print,None)
    started,=m['launcher.anythingllm_runtime'].started
    assert started['model_tag']=='lighter:3b'
    assert started['model_tag']!=m['launcher.config'].MODEL_TAG


def test_chat_refuses_to_start_with_no_local_model_installed(tmp_path,monkeypatch):
    b,m,c=chat_backend(tmp_path,[''],monkeypatch,installed=())
    with pytest.raises(RuntimeError):
        b.chat_start('',print,None)
    assert not m['launcher.anythingllm_runtime'].started


def test_chat_reused_container_is_not_stopped(tmp_path,monkeypatch):
    b,m,c=chat_backend(tmp_path,['old\n','old\n'],monkeypatch)
    b.chat_start('',print,None)
    assert b.chat_stop()
    assert not c


def test_chat_replaced_by_another_process_is_not_stopped(tmp_path,monkeypatch):
    b,m,c=chat_backend(tmp_path,['','mine\n','someone-else\n'],monkeypatch)
    b.chat_start('',print,None)
    assert not b.chat_stop()
    assert not c


def parse(app, argv):
    from apps.shared.entry import parse_args
    return parse_args(app, argv)


def test_setup_flags_select_setup_from_any_launcher():
    # The shared parser owns routing. Install/skip flags use the installer,
    # while --manage opens the current Setup desktop app.
    for argv in (['--install'], ['--manage'], ['--skip-model'], ['--skip-search']):
        assert parse('studio', argv).app == 'setup', argv
    assert parse('studio', ['--install']).install
    assert parse('chat', []).app == 'chat'
    assert parse('studio', ['--app', 'chat']).app == 'chat'


def test_naming_a_different_application_with_installation_flags_is_refused():
    for app in ('studio', 'chat', 'interpreter'):
        with pytest.raises(SystemExit):
            parse('studio', ['--app', app, '--install'])


def test_run_bat_only_forces_console_for_console_flows():
    run = (ROOT / 'RUN.bat').read_text()
    force_line = next(line for line in run.splitlines() if 'findstr' in line.lower())
    for flag in ('--install', '--skip-', '--help', '--tui'):
        assert flag in force_line, flag
    assert '--manage' not in force_line
