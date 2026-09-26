from pathlib import Path

from launcher.services.ollama import OllamaService


def _service(tmp_path):
    env = tmp_path / "environment"
    broker = tmp_path / "LocalAI" / "ollama"
    broker.mkdir(parents=True, exist_ok=True)
    exe = broker / "ollama.exe"
    exe.write_text("managed", encoding="utf-8")
    svc = OllamaService(env, model_dir=tmp_path / "LocalAI" / "models")
    svc.portable_exe = exe
    svc.exe = exe
    return svc


def running_as(monkeypatch, svc, executable, pid=4242, state=False):
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: pid)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: executable)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: state)


def test_tracked_shared_broker_is_reused(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, svc.exe, pid=31337, state=True)
    assert svc.ensure_running() is True


def test_shared_broker_started_by_another_account_is_reused_not_restarted(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, svc.exe, pid=31337, state=False)
    monkeypatch.setattr(svc, "_launched_by_us", lambda _pid: False)
    killed = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: killed.append(pid) or True)

    assert svc.ensure_running() is True
    assert killed == []


def test_shared_broker_from_another_account_is_rejected_on_proven_store_mismatch(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, svc.exe, pid=31337, state=False)
    monkeypatch.setattr(svc, "_launched_by_us", lambda _pid: False)
    monkeypatch.setattr(
        svc,
        "inspect_store",
        lambda timeout=5: (svc.OTHER_STORE, {"found": str(tmp_path / "other-models")}),
    )
    killed = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: killed.append(pid) or True)

    assert svc.ensure_running() is False
    assert killed == []


def test_prepare_install_leaves_running_shared_broker_alone(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, svc.exe, pid=31337, state=False)
    killed = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: killed.append(pid) or True)

    assert svc.prepare_install(stop_timeout=1) is True
    assert killed == []


def test_prepare_install_rejects_unrelated_listener(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    foreign = tmp_path / "elsewhere" / "ollama.exe"
    foreign.parent.mkdir()
    foreign.write_text("foreign", encoding="utf-8")
    running_as(monkeypatch, svc, foreign)

    assert svc.prepare_install(stop_timeout=1) is False


def test_unknown_ollama_location_is_rejected(monkeypatch, tmp_path):
    from core import ollama_paths
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: ())
    svc = _service(tmp_path)
    stranger = tmp_path / "somewhere" / "ollama.exe"
    stranger.parent.mkdir(parents=True)
    stranger.write_text("?", encoding="utf-8")
    running_as(monkeypatch, svc, stranger)

    assert svc.ensure_running(boot_timeout=1) is False


def test_process_we_started_can_still_be_cleaned_up(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, svc.exe, pid=31337, state=False)
    monkeypatch.setattr(svc, "_state_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_launched_by_us", lambda _pid: True)
    monkeypatch.setattr(svc, "stop_supervisor", lambda: True)
    killed = []
    monkeypatch.setattr(svc, "_kill", lambda pid: killed.append(pid) or True)
    states = iter([True, False])
    monkeypatch.setattr(svc, "is_running", lambda: next(states))

    assert svc.stop_managed(stop_timeout=1) is True
    assert killed == [31337]


def test_service_injects_shared_model_path(tmp_path):
    svc = _service(tmp_path)
    assert svc.env_vars({})["OLLAMA_MODELS"] == str(svc.model_dir)


def test_store_agreement_compares_served_models_against_disk(tmp_path, monkeypatch):
    import model_router_stub as router
    svc = _service(tmp_path)

    router.serve(monkeypatch, [])
    assert svc.store_agrees() is True

    router.serve(monkeypatch, ["ghost:7b"])
    router.store(monkeypatch, [])
    assert svc.store_agrees() is False

    router.store(monkeypatch, ["Ghost:7B"])
    assert svc.store_agrees() is True


def test_unreachable_server_reports_unknown_not_disagreement(tmp_path, monkeypatch):
    from launcher.services import ollama as module
    svc = _service(tmp_path)

    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", refuse)
    assert svc.store_agrees() is None
