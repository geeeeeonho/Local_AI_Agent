from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_custom_session_helpers_are_not_runtime_owned():
    text = _text("src/launcher/core/user_data.py")
    for name in (
        "new_session_id",
        "session_path",
        "list_sessions",
        "latest_session",
        "session_meta",
    ):
        assert f"def {name}(" not in text
    assert "session_*.json" not in text


def test_dead_sandbox_options_module_is_gone():
    assert not (REPO_ROOT / "src/launcher/actions/_sandbox_options.py").exists()


def test_gui_compatibility_shims_are_gone():
    assert not (REPO_ROOT / "src/launcher/gui.py").exists()
    assert not (REPO_ROOT / "src/launcher/checkbox.py").exists()
    assert (REPO_ROOT / "src/launcher/presenter/gui/__init__.py").is_file()


def test_legacy_agent_event_adapter_is_gone():
    text = _text("src/launcher/agent/events.py")
    assert "_LEGACY_TYPES" not in text
    assert "from_legacy_message" not in text


def test_active_openwebui_runtime_identifiers_are_absent():
    forbidden = (
        "OPEN_WEBUI_PORT",
        "OPEN_WEBUI_URL",
        "LOCAL_AI_CHAT_ENGINE",
    )
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token}: {path.relative_to(REPO_ROOT)}"
