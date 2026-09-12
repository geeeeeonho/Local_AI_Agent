from pathlib import Path
from types import SimpleNamespace as NS
from enum import Enum
import pytest


class Mode(str, Enum):
    BLOCK='block'; DIRECT='direct'; WARP='warp'; TOR='tor'


def fixture(tmp_path):
    from integrations.legacy.desktop import LegacyBackend
    calls=[]
    # Mirror launcher.config's real names only. Inventing a constant here is how
    # the desktop shipped a chat_start that crashed on launcher.config.MODEL_CONTEXT.
    cfg=NS(OLLAMA_PORT=11434, MODEL_TAG='chosen:latest', CHAT_CONTEXT_WINDOW=4096,
           SEARXNG_CONTAINER='search', SANDBOX_CONTAINER_PREFIX='box_')
    policy=NS(NetworkMode=Mode, current_mode=lambda: Mode.WARP,
              set_mode=lambda mode: calls.append(('mode', mode)) or Mode(mode),
              ensure_block_network=lambda **kw: calls.append(('block', kw)) or True)
    docker=NS(daemon_alive=lambda: True, ensure_daemon=lambda **kw: True,
              container_running=lambda name: False)
    managed=NS(is_managed_running=lambda: True, ensure_running=lambda: True)
    modules={
        'launcher.config':cfg, 'launcher.network_policy':policy,
        'launcher.services.docker':NS(DockerService=docker),
        'launcher.services.ollama':NS(OllamaService=lambda *a,**k: managed),
        'launcher.warp_runtime':NS(image_exists=lambda: True,
             start=lambda **kw: calls.append(('warp',kw)) or False),
        'launcher.tor_runtime':NS(image_exists=lambda: True,
             start=lambda **kw: calls.append(('tor',kw)) or True),
        'launcher.searxng_runtime':NS(image_exists=lambda: True,
             start=lambda *a,**k: calls.append(('search',a,k)) or True),
    }
    backend=LegacyBackend(tmp_path/'env',tmp_path/'models',tmp_path,importer=modules.__getitem__)
    return backend, modules, calls


def test_block_calls_canonical_quiescence_without_injected_run(tmp_path):
    b,m,c=fixture(tmp_path)
    assert b.prepare_network('block', print)
    assert c[0] == ('mode','block')
    assert c[1][0] == 'block' and 'run' not in c[1][1]


def test_warp_failure_is_not_converted_to_direct(tmp_path):
    b,m,c=fixture(tmp_path)
    assert not b.prepare_network('warp', print)
    assert ('mode','direct') not in c


def test_search_passes_explicit_mode_without_starting_legacy_proxies(tmp_path,monkeypatch):
    b,m,c=fixture(tmp_path)
    cfg=m['launcher.config']
    cfg.SEARXNG_IMAGE='search-image';cfg.LLM_NETWORK='net';cfg.SEARXNG_HOST_PORT=8888;cfg.SEARXNG_CONTAINER_PORT=8080
    m['launcher.network_policy'].container_proxy_env=lambda mode:{'ALL_PROXY':'socks5h://llm_tor:9050'}
    from integrations.searxng import runtime
    monkeypatch.setattr(runtime,'SearchRuntime',lambda *a,**k:NS(start=lambda mode,proxy:c.append((mode,proxy)) or True))
    assert b.search_start('tor', print)
    assert c==[('tor','socks5h://llm_tor:9050')]


def test_search_refuses_block_at_integration_boundary(tmp_path):
    b,m,c=fixture(tmp_path)
    with pytest.raises(ValueError): b.search_start('block', print)
    assert not c


def test_runtime_adapter_checks_managed_ownership_before_model_api(tmp_path):
    b,m,c=fixture(tmp_path)
    m['launcher.services.ollama'].OllamaService=lambda *a,**k:NS(ensure_running=lambda:False)
    with pytest.raises(RuntimeError): b.inference.ensure_running()


def test_agent_mismatched_network_cannot_boot_runtime(tmp_path):
    b,m,c=fixture(tmp_path)
    p=NS(error=lambda text:c.append(('error',text)))
    m['launcher.actions.agent_chat']=NS(_ensure_gui=lambda p:True,
        _select_setup=lambda env,p:('profile',tmp_path,'sandbox',{'tag':'test'},Mode.DIRECT))
    assert not b.agent_open(p,'block',None)
    assert ('mode','block') in c
    assert any(x[0]=='error' for x in c)


def test_agent_selected_host_block_is_rejected_even_with_bad_adapter(tmp_path):
    b,m,c=fixture(tmp_path)
    p=NS(error=lambda text:c.append(('error',text)))
    m['launcher.actions.agent_chat']=NS(_ensure_gui=lambda p:True,
        _select_setup=lambda env,p:('profile',tmp_path,'host',{'tag':'test'},Mode.BLOCK))
    with pytest.raises(ValueError): b.agent_open(p,'block',None)


def test_agent_uses_original_runtime_coordinator_and_controller(tmp_path):
    b,m,c=fixture(tmp_path)
    p=NS(error=lambda text:None)
    old=NS(_ensure_gui=lambda p:True,
        _select_setup=lambda env,p:('profile',tmp_path,'sandbox',{'tag':'test'},Mode.TOR),
        _match_installed_model=lambda tag,p:tag,
        _launch_panel=lambda env,p,**kw:c.append(('panel',kw)))
    m['launcher.actions.agent_chat']=old
    m['launcher.agent.runtime_coordinator']=NS(
        prepare_runtime=lambda *args:c.append(('prepare_agent',args)) or True,
        RuntimeCoordinator=lambda **kw: c.append(('coordinator',kw)) or NS(**kw))
    m['launcher.agent.chat_session_controller']=NS(ChatSessionController=object)
    m['launcher.presenter.base']=NS(RISK_HIGH=3)
    m['launcher.agent.runtime_config']=NS(
        resolve_resource_limits=lambda env:('8g','4'),
        build_cmd_for_mode=lambda *a,**k:(['canonical','command'],False))
    binding=b.agent_open(p,'tor',None)
    assert binding.metadata['network']=='tor'
    assert c[0][0]=='prepare_agent'
    panel=c[-1][1]
    assert panel['command']==['canonical','command']
    assert panel['selected_network'] is Mode.TOR
    assert panel['workspace']==tmp_path


def test_bad_local_chat_url_is_not_opened(tmp_path):
    from services.system.urls import local_url
    for url in ['https://example.com', 'http://127.0.0.1.evil:3001',
                'http://user@127.0.0.1:3001','file:///etc/passwd',
                'http://127.0.0.1:3001/\r\nevil']:
        with pytest.raises(ValueError): local_url(url)
    assert local_url('http://127.0.0.1:3001') == 'http://127.0.0.1:3001'
