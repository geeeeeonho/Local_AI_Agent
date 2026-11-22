from types import SimpleNamespace

import pytest

from installer import __main__ as setup_main


def _args(**overrides):
    values = {
        "install": False,
        "skip_model": False,
        "skip_sandbox": False,
        "skip_build": False,
        "skip_search": False,
        "lang": None,
        "embedded": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_installer_main_has_one_job_install_or_repair(monkeypatch):
    args = _args()
    calls = []
    monkeypatch.setattr(setup_main, "_parse_args", lambda argv=None: args)
    monkeypatch.setattr(
        setup_main, "_run_install",
        lambda received: calls.append(received) or 17,
    )

    assert setup_main.main([]) == 17
    assert calls == [args]


def test_installer_accepts_documented_install_and_skip_flags():
    args = setup_main._parse_args([
        "--install", "--skip-model", "--skip-sandbox", "--skip-build", "--skip-search",
        "--lang", "ko",
    ])
    assert args.install is True
    assert args.skip_model and args.skip_sandbox and args.skip_build and args.skip_search
    assert args.lang == "ko"
    assert args.embedded is False


def test_installer_no_longer_owns_the_manage_ui():
    with pytest.raises(SystemExit):
        setup_main._parse_args(["--manage"])


def test_no_argument_installer_still_means_install_repair():
    args = setup_main._parse_args([])
    assert args.install is False
    assert not args.skip_model



def test_standard_user_setup_never_invokes_shared_installers(monkeypatch, tmp_path):
    # The ordinary user may prepare their private account folder but must
    # never download or replace a shared executable.
    monkeypatch.setattr(setup_main, "ROOT", tmp_path / "LocalAI")
    monkeypatch.setattr(setup_main, "ENV", tmp_path / "LocalAI" / "environment")
    monkeypatch.setattr(setup_main, "APP_DIR", tmp_path / "LocalAI" / "app")
    monkeypatch.setattr(setup_main, "MODEL_STORAGE_DIR", tmp_path / "LocalAI" / "models")
    monkeypatch.setattr(setup_main.lang_setup, "initialize_language", lambda *a, **k: None)
    for name in ("preflight_windows", "preflight_python", "preflight_disk"):
        monkeypatch.setattr(setup_main.utils, name, lambda *a, **k: None)
    monkeypatch.setattr(setup_main.resources, "detect", lambda env: object())
    monkeypatch.setattr(
        setup_main.resources, "compute_safety_profile",
        lambda spec: SimpleNamespace(warnings=(), can_run_full=True))
    calls = []
    account = tmp_path / "LocalAI" / "users" / "second"
    paths = {"user_data": account / "user_data", "workspace": account / "workspace",
             "sandbox": tmp_path / "LocalAI" / "environment" / "agent" / "sandbox"}
    paths["workspace"].mkdir(parents=True)
    monkeypatch.setattr(setup_main.machine_step, "ensure",
                        lambda *a: calls.append("role") or "user")
    monkeypatch.setattr(setup_main.utils, "create_environment",
                        lambda *a, **k: calls.append(("account", k["manage_shared"])) or paths)
    monkeypatch.setattr(setup_main.sandbox, "install",
                        lambda p, **k: calls.append(("sandbox", p["sandbox"])))
    for name in ("prepare_install", "install", "start_service"):
        monkeypatch.setattr(
            setup_main.ollama, name,
            lambda *a, **k: pytest.fail("standard-user setup touched shared Ollama"))
    for module, name in ((setup_main.llmfit_step, "install"), (setup_main.searxng, "install"),
                         (setup_main.tor, "install"), (setup_main.warp, "install"),
                         (setup_main.python_tools, "install_anythingllm"),
                         (setup_main.python_tools, "install_open_interpreter")):
        monkeypatch.setattr(module, name,
                            lambda *a, **k: pytest.fail("standard-user setup ran a shared installer"))
    assert setup_main._run_install(_args(embedded=True)) == 0
    context = paths["user_data"] / "sandbox-build"
    assert calls == ["role", ("account", False), ("sandbox", context)], \
        "the account's own sandbox image is built from a private context"
    assert not paths["sandbox"].exists()


def test_standard_user_setup_honours_skip_sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_main, "ROOT", tmp_path / "LocalAI")
    monkeypatch.setattr(setup_main.lang_setup, "initialize_language", lambda *a, **k: None)
    for name in ("preflight_windows", "preflight_python", "preflight_disk"):
        monkeypatch.setattr(setup_main.utils, name, lambda *a, **k: None)
    monkeypatch.setattr(setup_main.resources, "detect", lambda env: object())
    monkeypatch.setattr(
        setup_main.resources, "compute_safety_profile",
        lambda spec: SimpleNamespace(warnings=(), can_run_full=True))
    monkeypatch.setattr(setup_main.machine_step, "ensure", lambda *a: "user")
    monkeypatch.setattr(setup_main.utils, "create_environment",
                        lambda *a, **k: {"user_data": tmp_path / "u"})
    monkeypatch.setattr(setup_main.sandbox, "install",
                        lambda *a, **k: pytest.fail("--skip-sandbox was ignored"))
    assert setup_main._run_install(_args(embedded=True, skip_sandbox=True)) == 0
