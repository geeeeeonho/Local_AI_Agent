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


def test_launch_is_blocked_until_legacy_models_are_migrated(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    legacy = svc.env / "llm_models" / "blobs"
    legacy.mkdir(parents=True)
    (legacy / "sha256-old").write_text("model", encoding="utf-8")

    monkeypatch.setattr(svc, "is_running", lambda: False)
    monkeypatch.setattr(
        svc,
        "_launch",
        lambda: (_ for _ in ()).throw(AssertionError("must not launch before migration")),
    )

    assert svc.ensure_running(boot_timeout=1) is False


def test_launch_is_blocked_until_interrupted_migration_is_recovered(monkeypatch, tmp_path):
    svc = _service(tmp_path)
    staging = svc.model_dir.with_name(svc.model_dir.name + ".migrating")
    staging.mkdir(parents=True)

    monkeypatch.setattr(svc, "is_running", lambda: False)
    monkeypatch.setattr(
        svc,
        "_launch",
        lambda: (_ for _ in ()).throw(AssertionError("must not launch before migration recovery")),
    )

    assert svc.ensure_running(boot_timeout=1) is False


# ── Ollama as the intermediary ───────────────────────────────────────────
# The project used to refuse every Ollama it had not unzipped itself, because
# it could not know which OLLAMA_MODELS such a server had been started with.
# Now that Ollama owns the install and the store, an officially installed
# server is the normal case - but "not ours" still has to mean "prove it is
# looking at the same store" rather than "trust it".

def official(tmp_path, name="ollama.exe"):
    folder = tmp_path / "Programs" / "Ollama"
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_text("official", encoding="utf-8")
    return exe


def running_as(monkeypatch, svc, executable, pid=4242):
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: pid)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: executable)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: False)


def test_an_installed_official_ollama_is_preferred_over_the_portable_copy(tmp_path, monkeypatch):
    from core import ollama_paths
    exe = official(tmp_path)
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: (exe.parent,))
    svc = _service(tmp_path)
    assert svc.exe == exe
    assert svc.portable_exe != exe


def test_an_official_server_sharing_our_store_is_used_not_killed(tmp_path, monkeypatch):
    from core import ollama_paths
    exe = official(tmp_path)
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: (exe.parent,))
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, exe)
    monkeypatch.setattr(svc, "store_agrees", lambda timeout=5: True)
    killed = []
    monkeypatch.setattr(svc, "_terminate_listener", lambda pid: killed.append(pid) or True)
    assert svc.ensure_running(boot_timeout=1) is True
    assert killed == [], "someone else's service must not be terminated"


def test_an_official_server_on_a_different_store_is_used_and_explained(tmp_path, monkeypatch):
    """This used to refuse, and refusing was the bug.

    Install Ollama the official way and never set OLLAMA_MODELS, and it serves
    from its own default store while this project resolves the shared one. That
    is the ordinary case, not a misconfiguration, and treating it as fatal left
    Chat and Agent unable to start against a perfectly good server. Ollama is
    the router: what it lists is what a prompt reaches, wherever the files sit.
    Where they sit decides where downloads go, so it is reported, not enforced.
    """
    from core import ollama_paths
    exe = official(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "models"
    elsewhere.mkdir(parents=True)
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: (exe.parent,))
    monkeypatch.setattr(ollama_paths, "store_candidates", lambda environ=None: (elsewhere,))
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, exe)
    monkeypatch.setattr(svc, "store_agrees", lambda timeout=5: False)
    monkeypatch.setattr(svc, "locate_store", lambda timeout=5: elsewhere)
    said = []
    for level in ("_ok", "_info", "_warn", "_err"):
        monkeypatch.setattr(svc, level, lambda m, _l=level: said.append(m))
    assert svc.ensure_running(boot_timeout=1) is True
    assert any(str(exe) in message for message in said), said
    assert any(str(elsewhere) in message for message in said), said


def test_an_unverifiable_store_is_used_rather_than_blocking_the_user(tmp_path, monkeypatch):
    from core import ollama_paths
    exe = official(tmp_path)
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: (exe.parent,))
    svc = _service(tmp_path)
    running_as(monkeypatch, svc, exe)
    monkeypatch.setattr(svc, "store_agrees", lambda timeout=5: None)
    assert svc.ensure_running(boot_timeout=1) is True


def test_an_ollama_from_nowhere_known_is_still_refused(tmp_path, monkeypatch):
    from core import ollama_paths
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: ())
    svc = _service(tmp_path)
    stranger = tmp_path / "somewhere" / "ollama.exe"
    stranger.parent.mkdir(parents=True)
    stranger.write_text("?", encoding="utf-8")
    running_as(monkeypatch, svc, stranger)
    assert svc.ensure_running(boot_timeout=1) is False


def test_health_sees_an_official_server_we_did_not_launch(tmp_path, monkeypatch):
    from core import ollama_paths
    exe = official(tmp_path)
    monkeypatch.setattr(ollama_paths, "install_candidates", lambda environ=None: (exe.parent,))
    svc = _service(tmp_path)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 4242)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: False)
    monkeypatch.setattr(svc, "store_agrees", lambda timeout=5: True)
    assert svc.is_managed_running() is True
    # A store mismatch is not the word "stopped". Folding the two together made
    # the status page report a serving Ollama as absent.
    monkeypatch.setattr(svc, "store_agrees", lambda timeout=5: False)
    assert svc.is_managed_running() is True


def test_store_agreement_compares_served_models_against_the_disk(tmp_path, monkeypatch):
    import model_router_stub as router
    svc = _service(tmp_path)

    router.serve(monkeypatch, [])
    assert svc.store_agrees() is True, "nothing served, nothing to disagree about"

    router.serve(monkeypatch, ["ghost:7b"])
    router.store(monkeypatch, [])
    assert svc.store_agrees() is False, "serves a model we cannot see on disk"

    router.store(monkeypatch, ["Ghost:7B"])
    assert svc.store_agrees() is True, "case differences are not disagreement"


def test_agreement_reads_manifests_only_not_every_blob(tmp_path, monkeypatch):
    """This runs on the health poll; it must not grow with the store."""
    import model_router_stub as router
    svc = _service(tmp_path)
    router.serve(monkeypatch, ["a:1"])
    router.store(monkeypatch, ["a:1"])
    walked = router.forbid_blob_walk(monkeypatch)
    assert svc.store_agrees() is True
    assert walked == [], "build_index stats every blob for no reason here"


def test_an_unreachable_server_reports_unknown_not_disagreement(tmp_path, monkeypatch):
    from launcher.services import ollama as module
    svc = _service(tmp_path)
    def refuse(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(module.urllib.request, "urlopen", refuse)
    assert svc.store_agrees() is None
