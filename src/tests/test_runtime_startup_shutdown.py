"""What has to start when the user presses a button, and stop when they close.

Chat and Agent are only usable if Ollama and Docker come up with them, and the
window is only closable if everything this process started can be verified
stopped. Each test here stands for a way that stopped being true in practice:

  * a healthy Ollama reported as "an unknown Ollama" because the port's owner
    could not be identified, which blocked Chat and Agent outright;
  * a Docker Desktop this program started and then left running forever;
  * an Ollama this program started and then left running forever;
  * one Docker hiccup during Chat start latching shutdown into permanent
    failure, so the window could not be closed at all;
  * a ninety-second silent, uncancellable wait while Docker Desktop boots;
  * an Agent wizard whose network default disagreed with the mode the window
    had already prepared, so [시작] was refused before anything ran.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import threading

import pytest


SRC = Path(__file__).resolve().parents[1]


def service(tmp_path, monkeypatch=None):
    from launcher.services.ollama import OllamaService
    if monkeypatch is not None:
        # Registration is process-wide on purpose; each test gets a clean slate.
        monkeypatch.setattr(OllamaService, '_cleanup_registered', False)
    env = tmp_path / 'environment'
    exe = tmp_path / 'LocalAI' / 'ollama' / 'ollama.exe'
    exe.parent.mkdir(parents=True)
    exe.write_text('managed', encoding='utf-8')
    svc = OllamaService(env, model_dir=tmp_path / 'LocalAI' / 'models')
    svc.portable_exe = exe
    svc.exe = exe
    return svc


def unidentified(monkeypatch, svc):
    """A serving Ollama whose owning process cannot be read.

    PowerShell timing out, no rights to another account's process path, or
    simply not running on Windows all land here.
    """
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    monkeypatch.setattr(svc, '_listener_pid', lambda: None)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: None)


# ── Ollama: an unreadable port owner is not a hostile one ────────────────

def test_a_serving_ollama_is_used_when_the_port_owner_cannot_be_read(tmp_path, monkeypatch):
    svc = service(tmp_path)
    unidentified(monkeypatch, svc)
    monkeypatch.setattr(svc, 'store_agrees', lambda timeout=5: True)
    monkeypatch.setattr(svc, '_launch', lambda: pytest.fail('must not start a second server'))
    assert svc.ensure_running(boot_timeout=1) is True


def test_an_unreadable_port_owner_does_not_report_ollama_as_stopped(tmp_path, monkeypatch):
    """The status line said "stopped" about a server that was answering."""
    svc = service(tmp_path)
    unidentified(monkeypatch, svc)
    monkeypatch.setattr(svc, 'store_agrees', lambda timeout=5: True)
    assert svc.is_managed_running() is True


def test_an_unverifiable_store_still_does_not_block_the_user(tmp_path, monkeypatch):
    svc = service(tmp_path)
    unidentified(monkeypatch, svc)
    monkeypatch.setattr(svc, 'store_agrees', lambda timeout=5: None)
    assert svc.ensure_running(boot_timeout=1) is True


def test_an_unidentified_server_on_a_different_store_is_rejected(tmp_path, monkeypatch):
    svc = service(tmp_path)
    unidentified(monkeypatch, svc)
    monkeypatch.setattr(svc, 'inspect_store', lambda timeout=5: (
        svc.OTHER_STORE, {'found': str(tmp_path / 'real-store')}))
    said = []
    for level in ('_ok', '_info', '_warn', '_err'):
        monkeypatch.setattr(svc, level, lambda message, _l=level: said.append(message))
    assert svc.ensure_running(boot_timeout=1) is False
    assert any('real-store' in message for message in said), said


def test_a_known_executable_on_another_store_is_unaffected_by_the_fallback(tmp_path, monkeypatch):
    svc = service(tmp_path)
    stranger = tmp_path / 'elsewhere' / 'ollama.exe'
    stranger.parent.mkdir(parents=True)
    stranger.write_text('?', encoding='utf-8')
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    monkeypatch.setattr(svc, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: stranger)
    assert svc.ensure_running(boot_timeout=1) is False


# ── Ollama: machine-shared lifetime ──────────────────────────────────────

def test_starting_shared_ollama_registers_no_window_teardown(tmp_path, monkeypatch):
    from launcher.core import lifelog
    svc = service(tmp_path, monkeypatch)
    running = iter([False, True])
    monkeypatch.setattr(svc, 'is_running', lambda: next(running))
    monkeypatch.setattr(svc, '_launch', lambda: 4242)
    monkeypatch.setattr(svc, '_listener_pid', lambda: 4242)
    monkeypatch.setattr(svc, '_process_executable', lambda _pid: svc.exe)
    monkeypatch.setattr(svc, '_write_runtime_state', lambda _pid: None)
    monkeypatch.setattr(svc, 'persist_store_setting', lambda: 'user')
    registered = []
    monkeypatch.setattr(lifelog, 'register_cleanup',
                        lambda fn, **kw: registered.append((fn, kw)))
    assert svc.ensure_running(boot_timeout=2) is True
    assert registered == [], 'closing one account window must not stop a machine-shared broker'


def test_reusing_shared_ollama_registers_no_teardown(tmp_path, monkeypatch):
    from launcher.core import lifelog
    svc = service(tmp_path, monkeypatch)
    unidentified(monkeypatch, svc)
    monkeypatch.setattr(svc, 'store_agrees', lambda timeout=5: True)
    registered = []
    monkeypatch.setattr(lifelog, 'register_cleanup',
                        lambda fn, **kw: registered.append(fn))
    assert svc.ensure_running(boot_timeout=1) is True
    assert registered == []


def test_stop_managed_ends_the_server_this_window_recorded(tmp_path, monkeypatch):
    svc = service(tmp_path)
    svc._write_runtime_state(4242)
    running = iter([True, False])
    monkeypatch.setattr(svc, 'is_running', lambda: next(running))
    monkeypatch.setattr(svc, '_listener_pid', lambda: 4242)
    killed = []
    monkeypatch.setattr(svc, '_kill', lambda pid: killed.append(pid) or True)
    assert svc.stop_managed(stop_timeout=1) is True
    assert killed == [4242]


def test_stop_managed_never_touches_a_server_we_did_not_start(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    monkeypatch.setattr(svc, '_kill', lambda pid: pytest.fail('not ours to stop'))
    assert svc.stop_managed(stop_timeout=1) is True


def test_stop_managed_leaves_a_port_whose_owner_changed(tmp_path, monkeypatch):
    """Our server is already gone; something else answers on the port now."""
    svc = service(tmp_path)
    svc._write_runtime_state(4242)
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    monkeypatch.setattr(svc, '_listener_pid', lambda: 9999)
    monkeypatch.setattr(svc, '_kill', lambda pid: pytest.fail('that pid is not ours'))
    assert svc.stop_managed(stop_timeout=1) is True
    assert not svc.runtime_state_file.exists()


# ── Docker Desktop: started here, stopped here ───────────────────────────

@pytest.fixture
def docker(monkeypatch):
    from launcher.services.docker import DockerService
    monkeypatch.setattr(DockerService, '_started_by_us', False)
    monkeypatch.setattr(DockerService, '_shutdown_registered', False)
    monkeypatch.delenv('LOCAL_AI_KEEP_DOCKER', raising=False)
    return DockerService


def test_auto_starting_docker_desktop_registers_a_last_stage_teardown(docker, monkeypatch):
    from launcher.core import lifelog
    monkeypatch.setattr(docker, 'daemon_alive', staticmethod(lambda: False))
    monkeypatch.setattr(docker, 'find_desktop_executable', staticmethod(lambda: 'Docker Desktop.exe'))
    monkeypatch.setattr(docker, 'start_desktop', staticmethod(lambda: True))
    monkeypatch.setattr(docker, 'wait_until_alive',
                        staticmethod(lambda timeout=60, poll_interval=1.5, cancel_check=None: True))
    registered = []
    monkeypatch.setattr(lifelog, 'register_cleanup',
                        lambda fn, **kw: registered.append(kw))
    assert docker.ensure_daemon(timeout=1) is True
    assert docker._started_by_us is True
    # Containers are stopped by earlier callbacks; pulling the daemon out from
    # under them would make every one of those fail.
    assert registered == [{'last': True}]


def test_a_docker_we_did_not_start_is_left_alone(docker, monkeypatch):
    monkeypatch.setattr(docker, 'daemon_alive', staticmethod(lambda: True))
    monkeypatch.setattr(docker, 'shutdown_desktop',
                        staticmethod(lambda logger=None: pytest.fail('not ours to stop')))
    assert docker.ensure_daemon(timeout=1) is True
    assert docker._started_by_us is False
    assert docker.stop_desktop_if_started() is True


def test_docker_stays_up_while_other_peoples_containers_run(docker, monkeypatch):
    monkeypatch.setattr(docker, '_started_by_us', True)
    monkeypatch.setattr(docker, 'daemon_alive', staticmethod(lambda: True))
    monkeypatch.setattr(docker, 'foreign_containers', staticmethod(lambda: ['their_postgres']))
    monkeypatch.setattr(docker, 'shutdown_desktop',
                        staticmethod(lambda logger=None: pytest.fail('would kill their work')))
    assert docker.stop_desktop_if_started() is False


def test_docker_stays_up_when_its_container_state_cannot_be_read(docker, monkeypatch):
    monkeypatch.setattr(docker, '_started_by_us', True)
    monkeypatch.setattr(docker, 'daemon_alive', staticmethod(lambda: True))
    monkeypatch.setattr(docker, 'foreign_containers', staticmethod(lambda: None))
    monkeypatch.setattr(docker, 'shutdown_desktop',
                        staticmethod(lambda logger=None: pytest.fail('unknown is not empty')))
    assert docker.stop_desktop_if_started() is False


def test_only_our_own_containers_count_as_ours(docker):
    assert docker.is_own_container('llm_anythingllm')
    assert docker.is_own_container('llm_agent_chat_ab12')
    assert docker.is_own_container('llm_searxng')
    assert not docker.is_own_container('their_postgres')


def test_docker_shutdown_happens_when_only_our_containers_remain(docker, monkeypatch):
    monkeypatch.setattr(docker, '_started_by_us', True)
    monkeypatch.setattr(docker, 'daemon_alive', staticmethod(lambda: True))
    monkeypatch.setattr(docker, 'foreign_containers', staticmethod(lambda: []))
    stopped = []
    monkeypatch.setattr(docker, 'shutdown_desktop',
                        staticmethod(lambda logger=None: stopped.append(True) or True))
    assert docker.stop_desktop_if_started() is True
    assert stopped == [True]


def test_keeping_docker_running_is_one_environment_variable(docker, monkeypatch):
    monkeypatch.setattr(docker, '_started_by_us', True)
    monkeypatch.setenv('LOCAL_AI_KEEP_DOCKER', '1')
    monkeypatch.setattr(docker, 'shutdown_desktop',
                        staticmethod(lambda logger=None: pytest.fail('the user opted out')))
    assert docker.stop_desktop_if_started() is True


# ── shutdown ordering ────────────────────────────────────────────────────

def test_the_daemon_is_only_stopped_after_everything_that_needs_it(monkeypatch):
    from launcher.core import lifelog
    monkeypatch.setattr(lifelog, '_cleanup_callbacks', [])
    monkeypatch.setattr(lifelog, '_final_cleanup_callbacks', [])
    monkeypatch.setattr(lifelog, '_cleanups_ran', False)
    order = []
    lifelog.register_cleanup(lambda: order.append('docker-desktop'), last=True)
    lifelog.register_cleanup(lambda: order.append('container'))
    lifelog.register_cleanup(lambda: order.append('ollama'))
    lifelog.shutdown_then_exit()
    assert order == ['container', 'ollama', 'docker-desktop']


# ── Chat: the window must stay closable ──────────────────────────────────

def chat_backend(tmp_path, ids):
    from test_desktop_integration import fixture
    backend, modules, calls = fixture(tmp_path)
    modules['launcher.anythingllm_runtime'] = NS(CONTAINER='chat', URL='http://localhost:3001')
    sequence = iter(ids)

    def run(*_args, **_kwargs):
        value = next(sequence)
        if isinstance(value, Exception):
            raise value
        return NS(returncode=0, stdout=value)

    modules['launcher.services.docker'].DockerService.run = staticmethod(run)
    modules['launcher.services.docker'].DockerService.stop_container = \
        staticmethod(lambda identifier, timeout: calls.append(('stopped', identifier)) or True)
    return backend, modules, calls


def test_a_failed_identity_probe_does_not_wedge_shutdown_forever(tmp_path):
    """The flag latched. Every later close said "could not be verified"."""
    backend, modules, calls = chat_backend(tmp_path, [OSError('docker went away'), 'id\n', 'id\n', ''])
    backend._chat_probe_failed = True
    assert backend.chat_stop() is False, 'a failing probe is still not a verified stop'
    assert backend.chat_stop() is True, 'once Docker answers again, the window can close'


def test_a_container_created_while_the_probe_failed_is_still_cleaned_up(tmp_path):
    backend, modules, calls = chat_backend(tmp_path, ['new\n', 'new\n', ''])
    backend._chat_probe_failed = True
    backend._chat_before_id = None
    assert backend.chat_stop() is True
    assert ('stopped', 'new') in calls


# ── Chat/Agent preparation: visible, cancellable ─────────────────────────

class RecordingDocker:
    calls = []

    @staticmethod
    def ensure_daemon(logger=None, timeout=60, cancel_check=None):
        RecordingDocker.calls.append({'logger': logger, 'cancel_check': cancel_check})
        return True

    @staticmethod
    def daemon_alive():
        return True


def test_network_preparation_shows_docker_progress_and_can_be_cancelled(tmp_path, monkeypatch):
    from test_desktop_integration import fixture
    backend, modules, calls = fixture(tmp_path)
    RecordingDocker.calls = []
    modules['launcher.services.docker'] = NS(DockerService=RecordingDocker)
    said = []
    flag = threading.Event()
    assert backend.prepare_network('tor', said.append, cancel=flag.is_set)
    passed, = RecordingDocker.calls
    assert passed['cancel_check'] is not None, 'closing the window must not wait 90 seconds'
    for level in ('info', 'ok', 'warn', 'error'):
        getattr(passed['logger'], level)('x')
    assert len(said) == 4, 'Docker auto-start used to happen in complete silence'


def test_chat_start_reports_ollama_progress_and_stops_at_a_cancel(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    seen = []
    services.events.subscribe('runtime.progress', lambda event: seen.append(event.payload['message']))
    backend.inference.ensure_running = lambda log=None: (log and log('Ollama 가동 확인')) or 'http://x'
    assert services.chat.start('direct', search=False)
    assert 'Ollama 가동 확인' in seen, 'a 30 second boot must not look like a hang'
    services.close()


def test_a_cancel_between_network_and_ollama_stops_the_chat_start(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    cancelled = threading.Event()
    backend.prepare_network = lambda mode, log, cancel=None: cancelled.set() or True
    backend.inference.ensure_running = lambda log=None: pytest.fail('cancelled before this')
    with pytest.raises(RuntimeError, match='cancel'):
        services.chat.start('direct', cancel=cancelled.is_set)
    services.close()


# ── Agent: the wizard agrees with the window ─────────────────────────────

def test_the_agent_wizard_defaults_to_the_mode_the_window_prepared(monkeypatch):
    """It was pinned to "warp". Anyone who had chosen another mode on the
    Network page was refused at [시작] without changing a single setting."""
    from launcher import network_policy
    from launcher.agent import entry_dialog
    original = network_policy.current_mode().value
    try:
        for mode in ('direct', 'tor', 'block', 'warp'):
            network_policy.set_mode(mode)
            assert entry_dialog._active_network_mode() == mode
    finally:
        network_policy.set_mode(original)
    source = (SRC / 'launcher' / 'agent' / 'entry_dialog.py').read_text(encoding='utf-8')
    assert 'tk.StringVar(value="warp")' not in source, \
        'the wizard must not pin a mode the window may not have prepared'


def test_a_cancelled_agent_start_takes_the_wizard_progress_screen_down():
    """The wizard swaps the page for its own "준비 중..." screen on [시작].
    A refusal after that left it there with nothing to finish it."""
    pytest.importorskip('tkinter')
    from apps.shared.widgets import PanelHost
    assert hasattr(PanelHost, 'clear')
    tree = ast.parse((SRC / 'apps' / 'shared' / 'window.py').read_text(encoding='utf-8'))
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert 'clear_agent_panel' in names


# ── the legacy Chat action ───────────────────────────────────────────────

def test_the_chat_action_gives_searxng_the_environment_it_requires():
    """``start(env, ...)`` needs ``env``. Calling it bare raised TypeError into
    a warning handler, so search was silently off for the whole session."""
    import inspect
    from launcher import searxng_runtime
    required = [name for name, value in inspect.signature(searxng_runtime.start).parameters.items()
                if value.default is inspect.Parameter.empty]
    tree = ast.parse((SRC / 'launcher' / 'actions' / 'chat.py').read_text(encoding='utf-8'))
    starts = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and node.func.attr == 'start'
              and isinstance(node.func.value, ast.Name)
              and node.func.value.id == 'searxng_runtime']
    assert starts, 'the Chat action still has to start search'
    for call in starts:
        supplied = len(call.args) + len({keyword.arg for keyword in call.keywords})
        assert supplied >= len(required), 'searxng_runtime.start needs ' + ', '.join(required)


# ── a container cannot outlive its daemon ────────────────────────────────
# Stopping Docker Desktop while the window is open used to make shutdown
# impossible: chat_stop raised out of close() and the search runtime reported
# "not stopped" forever, both about containers that had already died with it.

def dead_docker(tmp_path):
    from test_desktop_integration import fixture
    backend, modules, calls = fixture(tmp_path)
    modules['launcher.anythingllm_runtime'] = NS(CONTAINER='chat', URL='http://localhost:3001')
    docker = modules['launcher.services.docker'].DockerService
    docker.run = staticmethod(lambda *a, **k: None)
    docker.daemon_alive = staticmethod(lambda: False)
    return backend, modules, calls


def test_chat_stops_cleanly_when_docker_itself_has_gone(tmp_path):
    backend, modules, calls = dead_docker(tmp_path)
    backend._chat_owned_id = 'abc123'
    assert backend.chat_stop() is True
    assert backend._chat_owned_id is None


def test_chat_stop_reports_failure_instead_of_raising_out_of_shutdown(tmp_path):
    """Docker is up but its answers are unusable: unverified, not an exception."""
    from test_desktop_integration import fixture
    backend, modules, calls = fixture(tmp_path)
    modules['launcher.anythingllm_runtime'] = NS(CONTAINER='chat', URL='http://localhost:3001')
    docker = modules['launcher.services.docker'].DockerService
    docker.run = staticmethod(lambda *a, **k: None)
    docker.daemon_alive = staticmethod(lambda: True)
    backend._chat_owned_id = 'abc123'
    assert backend.chat_stop() is False


def test_search_stops_cleanly_when_docker_itself_has_gone(tmp_path):
    from integrations.searxng.runtime import SearchRuntime
    backend, modules, calls = dead_docker(tmp_path)
    runtime = SearchRuntime(tmp_path / 's.yml', tmp_path / 'cache',
                            modules['launcher.services.docker'].DockerService,
                            image='i', container='llm_searxng', network='n',
                            host_port=8888, container_port=8080)
    runtime.owned = True
    assert runtime.stop() is True
    assert runtime.owned is False


def test_a_service_that_raises_on_stop_is_unverified_not_a_crash(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    services.chat.start('direct', search=False)
    backend.chat_stop = lambda: (_ for _ in ()).throw(RuntimeError('docker exploded'))
    seen = []
    services.events.subscribe('runtime.error', lambda event: seen.append(event.payload))
    assert services.close() is False, 'ownership is kept when a stop cannot be verified'
    assert any(item.get('service') == 'chat' for item in seen), 'and the reason is reported'
    backend.chat_stop = lambda: True
    assert services.close() is True


def test_every_service_is_asked_to_stop_even_after_one_refuses(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    services.chat.start('warp')
    backend.chat_stop = lambda: False
    services.close()
    assert ('search_stop',) in backend.calls, \
        'a Chat that will not stop is no reason to leave search running'


# ── the default network mode prepares out loud ───────────────────────────

def test_cleanup_can_be_suppressed_after_session_release_and_rearmed(monkeypatch):
    from launcher.core import lifelog

    monkeypatch.setattr(lifelog, "_cleanup_callbacks", [])
    monkeypatch.setattr(lifelog, "_sweep_cleanup_callbacks", [])
    monkeypatch.setattr(lifelog, "_final_cleanup_callbacks", [])
    monkeypatch.setattr(lifelog, "_cleanups_ran", False)

    seen = []
    lifelog.register_cleanup(lambda: seen.append("ran"))
    lifelog.suppress_exit_cleanups()
    lifelog.shutdown_then_exit()
    assert seen == []

    lifelog.rearm_exit_cleanups()
    lifelog.shutdown_then_exit()
    assert seen == ["ran"]


def test_agent_searxng_recreates_container_when_network_mode_changed(monkeypatch, tmp_path):
    from launcher import searxng_runtime

    monkeypatch.setenv("NET_MODE", "warp")
    monkeypatch.setattr(searxng_runtime, "_CLEANUP_REGISTERED", False)
    monkeypatch.setattr(searxng_runtime, "is_running", lambda: True)
    monkeypatch.setattr(searxng_runtime, "running_mode", lambda: "tor")
    removed = []
    monkeypatch.setattr(searxng_runtime, "remove", lambda: removed.append("old"))
    monkeypatch.setattr(searxng_runtime, "_ensure_net", lambda: None)
    monkeypatch.setattr(searxng_runtime, "image_exists", lambda: False)

    assert searxng_runtime.start(tmp_path) is False
    assert removed == ["old"]


def test_warp_preparation_reports_progress_and_takes_a_cancel(tmp_path):
    """WARP is the default mode and its start can run past two minutes. Every
    word of it went to a log file and to print(), which reaches nobody under
    pythonw.exe - which is how the desktop app actually runs."""
    import inspect
    from launcher import warp_runtime
    parameters = inspect.signature(warp_runtime.start).parameters
    assert 'log' in parameters and 'cancel_check' in parameters
    said = []
    warp_runtime._log(None, 'INFO', 'WARP 등록 대기 중... 5/45초', said.append)
    assert said == ['WARP 등록 대기 중... 5/45초']


def test_searxng_reports_why_it_did_not_start(tmp_path, monkeypatch):
    """_log returned immediately unless a log_path was given, and every caller
    passed None - so the reason search failed was computed and then dropped."""
    from launcher import searxng_runtime
    said = []
    monkeypatch.setattr(searxng_runtime, 'is_running', lambda: False)
    monkeypatch.setattr(searxng_runtime, '_ensure_net', lambda: None)
    monkeypatch.setattr(searxng_runtime, 'image_exists', lambda: False)
    monkeypatch.setenv('NET_MODE', 'block')
    assert searxng_runtime.start(tmp_path, log=said.append) is False
    assert any('이미지 없음' in message for message in said), said


def test_searxng_registers_the_teardown_every_other_runtime_had(monkeypatch, tmp_path):
    """The Agent path starts this module directly, and nothing stopped it."""
    from launcher import searxng_runtime
    from launcher.core import lifelog
    monkeypatch.setattr(searxng_runtime, '_CLEANUP_REGISTERED', False)
    monkeypatch.setattr(searxng_runtime, 'is_running', lambda: True)
    monkeypatch.setattr(searxng_runtime, 'running_mode', lambda: 'block')
    registered = []
    monkeypatch.setattr(lifelog, 'register_cleanup', lambda fn, **kw: registered.append(fn))
    assert searxng_runtime.start(tmp_path) is True
    assert len(registered) == 1


# ── preparation the user can interrupt ───────────────────────────────────

def test_agent_preparation_stops_at_a_cancel_instead_of_finishing_every_wait(tmp_path):
    from launcher.agent import runtime_coordinator
    from launcher import network_policy
    presenter = NS(info=lambda m: None, warn=lambda m: None, error=lambda m: None,
                   ok=lambda m: None)
    reached = []
    original = runtime_coordinator._ensure_ollama
    try:
        runtime_coordinator._ensure_ollama = lambda env, p: reached.append('ollama') or True
        assert runtime_coordinator.prepare_runtime(
            tmp_path, presenter, 'sandbox', network_policy.NetworkMode.DIRECT,
            cancel=lambda: True) is False
    finally:
        runtime_coordinator._ensure_ollama = original
    assert reached == [], 'a cancelled Agent start must not begin a ninety-second wait'


def test_optional_arguments_reach_only_the_callees_that_take_them():
    from core.calls import invoke, accepts
    seen = {}
    def old_style(mode, log):
        seen['old'] = (mode, log); return 'old'
    def new_style(mode, log, cancel=None):
        seen['new'] = (mode, log, cancel); return 'new'
    assert invoke(old_style, 'warp', print, cancel=lambda: True) == 'old'
    assert invoke(new_style, 'warp', print, cancel='c') == 'new'
    assert seen['new'][2] == 'c'
    assert accepts(new_style, 'cancel') and not accepts(old_style, 'cancel')


# ── every container this program starts is somebody's to stop ────────────

def test_every_module_that_starts_a_container_registers_its_teardown():
    """launcher.searxng_runtime started llm_searxng and registered nothing, so
    opening an Agent once left it running after the window closed. This is a
    structural rule, not a fact about one module."""
    def detached_run(node):
        """A ``docker run -d`` argument list, built anywhere in this module.

        Only detached containers can outlive the process that made them; a
        ``--rm -i`` foreground container dies with its own command, and a list
        that is only compared against or validated is not a start at all.
        """
        if not isinstance(node, ast.List):
            return False
        words = [item.value for item in node.elts
                 if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        if len(words) < 3 or '-d' not in words:
            return False
        return words[:1] == ['run'] or words[:2] == ['docker', 'run']

    offenders = []
    for path in sorted(SRC.rglob('*.py')):
        relative = path.relative_to(SRC)
        if relative.parts[0] == 'tests':
            continue
        source = path.read_text(encoding='utf-8')
        if not any(detached_run(node) for node in ast.walk(ast.parse(source))):
            continue
        if 'register_cleanup' not in source:
            offenders.append(str(relative))
    # integrations/searxng/runtime.py is the exception the rule allows: that
    # instance is owned by DesktopServices.close(), which stops it directly.
    offenders = [name for name in offenders if name != 'integrations/searxng/runtime.py']
    assert offenders == [], \
        '종료 정리를 등록하지 않고 컨테이너를 띄우는 모듈: ' + ', '.join(offenders)


def test_the_owned_search_runtime_is_stopped_by_the_services_that_own_it(tmp_path):
    from test_desktop_services import make
    services, backend = make(tmp_path)
    services.chat.start('warp')
    assert services.close() is True
    assert ('search_stop',) in backend.calls
