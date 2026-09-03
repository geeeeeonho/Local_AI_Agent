from pathlib import Path

from launcher.services.ollama import OllamaService


def _service(tmp_path):
    env = tmp_path / "llm_environment"
    exe = env / "ollama_runtime" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("portable", encoding="utf-8")
    return OllamaService(env, model_dir=tmp_path / "LLM_Models")


def test_managed_status_requires_owned_listener_and_matching_runtime_state(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: svc.exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: True)

    assert svc.is_managed_running() is True


def test_managed_status_rejects_untracked_managed_listener(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: svc.exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: False)

    assert svc.is_managed_running() is False


def test_running_foreign_ollama_is_rejected(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 4242)
    monkeypatch.setattr(
        svc,
        "_process_executable",
        lambda _pid: Path(r"C:\Users\someone\AppData\Local\Programs\Ollama\ollama.exe"),
    )

    assert svc.ensure_running() is False


def test_prepare_install_stops_managed_listener_before_storage_migration(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running = iter([True, False])
    monkeypatch.setattr(svc, "is_running", lambda: next(running))
    monkeypatch.setattr(svc, "_listener_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: svc.exe)

    terminated = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: terminated.append(pid) or True)

    assert svc.prepare_install(stop_timeout=1) is True
    assert terminated == [31337]


def test_prepare_install_rejects_foreign_listener(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 4242)
    monkeypatch.setattr(
        svc,
        "_process_executable",
        lambda _pid: Path(r"C:\Program Files\Ollama\ollama.exe"),
    )

    assert svc.prepare_install(stop_timeout=1) is False


def test_untracked_managed_ollama_is_restarted_with_shared_model_path(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    running = iter([True, False, True])
    monkeypatch.setattr(svc, "is_running", lambda: next(running))
    monkeypatch.setattr(svc, "_listener_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: svc.exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: False)

    terminated = []
    launched = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: terminated.append(pid) or True)
    monkeypatch.setattr(svc, "_launch", lambda: launched.append(svc.env_vars({})["OLLAMA_MODELS"]) or 31338)
    monkeypatch.setattr(svc, "_write_runtime_state", lambda _pid: None)

    assert svc.ensure_running(boot_timeout=1) is True
    assert terminated == [31337]
    assert launched == [str(svc.model_dir)]


def test_tracked_managed_ollama_is_reused_without_restart(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 31337)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: svc.exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: True)

    monkeypatch.setattr(
        svc,
        "_terminate_listener",
        lambda _pid: (_ for _ in ()).throw(AssertionError("must not restart tracked server")),
    )

    assert svc.ensure_running() is True
