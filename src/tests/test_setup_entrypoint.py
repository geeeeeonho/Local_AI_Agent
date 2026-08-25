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
    assert setup_main._should_manage(_args()) is True


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
