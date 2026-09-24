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


def test_installer_no_longer_owns_the_manage_ui():
    with pytest.raises(SystemExit):
        setup_main._parse_args(["--manage"])


def test_no_argument_installer_still_means_install_repair():
    args = setup_main._parse_args([])
    assert args.install is False
    assert not args.skip_model
