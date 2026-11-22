"""Opt-in search, safe network reuse and idle status probe contracts."""
from pathlib import Path
from types import SimpleNamespace

from test_desktop_services import make


def test_chat_defaults_to_no_web_search(tmp_path):
    svc, backend = make(tmp_path)
    assert svc.chat.start("direct")
    assert not any(c[0] == "search" for c in backend.calls)
    assert backend.calls.count(("prepare", "direct")) == 1
    svc.close()


def test_opt_in_chat_search_reuses_prepared_network(tmp_path):
    svc, backend = make(tmp_path)
    assert svc.chat.start("direct", search=True)
    assert backend.calls.count(("prepare", "direct")) == 1
    assert backend.calls.count(("search", "direct")) == 1
    svc.close()


def test_agent_passes_search_intent_into_backend(tmp_path):
    from services.agent.launcher import AgentLauncher
    calls = []
    class Backend:
        def agent_open(self, presenter, network, project, search=False):
            calls.append((network, search))
            return None

    class Network:
        mode = None
        def prepare(self, mode, cancel=None):
            self.mode = mode
            return SimpleNamespace(value=mode)
        def reset(self):
            self.mode = None

    agent = AgentLauncher(Backend(), Network(), SimpleNamespace(emit=lambda *_: None))
    assert agent.open(object(), "direct", search=True) is None
    assert calls == [("direct", True)]


def test_agent_direct_host_skips_search_when_not_requested(monkeypatch, tmp_path):
    from launcher.agent import runtime_coordinator as coordinator
    from launcher import network_policy

    monkeypatch.setattr(coordinator, "_ensure_ollama", lambda *_: True)
    monkeypatch.setattr(coordinator.DockerService, "daemon_alive", lambda: True)
    # A no-search session must not call SearXNG even when Docker is running.
    from launcher import searxng_runtime
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("SearXNG was called for a no-search session")
    monkeypatch.setattr(searxng_runtime, "is_running", must_not_run)
    monkeypatch.setattr(searxng_runtime, "start", must_not_run)
    presenter = SimpleNamespace(error=lambda *_: None, warn=lambda *_: None,
                                info=lambda *_: None)
    assert coordinator.prepare_runtime(
        tmp_path, presenter, "host", network_policy.NetworkMode.DIRECT,
        search=False)


def test_health_skips_container_probes_when_docker_is_offline(tmp_path):
    from integrations.desktop import DesktopBackend

    class Ollama:
        def __init__(self, *args, **kwargs):
            pass
        def is_managed_running(self):
            return False
        def describe_store(self):
            return "not running"

    class Docker:
        @staticmethod
        def daemon_alive():
            return False
        @staticmethod
        def container_running(*_args):
            raise AssertionError("must not check a container without Docker")

    modules = {
        "launcher.services.ollama": SimpleNamespace(OllamaService=Ollama),
        "launcher.services.docker": SimpleNamespace(DockerService=Docker),
    }
    backend = object.__new__(DesktopBackend)
    backend.env = tmp_path
    backend.model_dir = tmp_path / "models"
    backend.load = lambda key: modules[key]
    backend.describe_records_privacy = lambda: True
    status = backend._probe_health()
    assert status["docker"] is False
    assert status["chat"] is False
    assert status["chat_image"] is None
    assert status["search"] is False


def test_gui_idle_tick_uses_250ms_and_agent_tick_uses_100ms(monkeypatch):
    import queue
    from apps.shared.window import DesktopWindow

    class Runner:
        def drain(self):
            pass
        def submit(self, *args, **kwargs):
            return True

    class Root:
        def __init__(self):
            self.intervals = []
        def after(self, interval, fn):
            self.intervals.append(interval)

    w = object.__new__(DesktopWindow)
    w.root = Root()
    w.runner = Runner()
    w.events = queue.Queue()
    w.closed = w.closing = False
    w._polling = True
    w._ticks = 0
    w._next_health_at = float("inf")
    w._next_theme_at = float("inf")
    w.agent_session = None
    w._tick()
    assert w.root.intervals[-1] == 250

    w.agent_session = SimpleNamespace(poll_once=lambda: None)
    w._tick()
    assert w.root.intervals[-1] == 100
