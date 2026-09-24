from types import SimpleNamespace

from installer import __main__ as setup_main


def _args(**overrides):
    values = {
        "manage": False,
        "install": False,
        "skip_model": False,
        "skip_sandbox": False,
        "skip_build": False,
        "skip_search": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_auto_mode_installs_when_environment_is_missing(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    monkeypatch.setattr(setup_main, "ENV", env)
    assert setup_main._should_manage(_args()) is False


def test_auto_mode_manages_when_environment_exists(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    env.mkdir()
    monkeypatch.setattr(setup_main, "ENV", env)
    monkeypatch.setattr(setup_main, "MODEL_STORAGE_DIR", tmp_path / "LLM_Models")
    assert setup_main._should_manage(_args()) is True


def test_auto_mode_runs_install_flow_for_legacy_model_migration(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    legacy = env / "llm_models" / "blobs"
    legacy.mkdir(parents=True)
    (legacy / "sha256-old").write_text("model", encoding="utf-8")
    shared = tmp_path / "LLM_Models"

    monkeypatch.setattr(setup_main, "ENV", env)
    monkeypatch.setattr(setup_main, "MODEL_STORAGE_DIR", shared)

    assert setup_main._should_manage(_args()) is False


def test_auto_mode_runs_install_flow_for_interrupted_model_migration(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    env.mkdir()
    shared = tmp_path / "LLM_Models"
    staging = shared.with_name(shared.name + ".migrating")
    staging.mkdir()

    monkeypatch.setattr(setup_main, "ENV", env)
    monkeypatch.setattr(setup_main, "MODEL_STORAGE_DIR", shared)

    assert setup_main._should_manage(_args()) is False


def test_auto_mode_runs_install_flow_for_old_forced_store(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    env.mkdir()
    forced = tmp_path / "LLM_Models"
    (forced / "blobs").mkdir(parents=True)
    (forced / "blobs" / "sha256-old").write_text("model", encoding="utf-8")
    shared = tmp_path / "Ollama" / "models"

    monkeypatch.setattr(setup_main, "ENV", env)
    monkeypatch.setattr(setup_main, "LEGACY_FORCED_MODEL_DIR", forced)
    monkeypatch.setattr(setup_main, "MODEL_STORAGE_DIR", shared)

    assert setup_main._should_manage(_args()) is False


def test_explicit_install_wins_even_when_environment_exists(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    env.mkdir()
    monkeypatch.setattr(setup_main, "ENV", env)
    assert setup_main._should_manage(_args(install=True)) is False


def test_explicit_manage_forces_management(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    monkeypatch.setattr(setup_main, "ENV", env)
    assert setup_main._should_manage(_args(manage=True)) is True


def test_legacy_skip_flags_stay_in_install_flow(tmp_path, monkeypatch):
    env = tmp_path / "llm_environment"
    env.mkdir()
    monkeypatch.setattr(setup_main, "ENV", env)
    assert setup_main._should_manage(_args(skip_model=True)) is False
