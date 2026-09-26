import json
from pathlib import Path

import pytest

from installer.core.filesystem import (
    create_environment,
    ensure_shared_model_access,
    write_install_manifest,
)
from launcher.services.ollama import OllamaService


def test_default_windows_layout_keeps_models_under_localai(monkeypatch):
    from core import ollama_paths, runtime_root
    import project_paths

    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.delenv("LLM_PROJECT_ROOT", raising=False)

    assert ollama_paths.SHARED_MODELS_DIR == runtime_root.WINDOWS_ROOT / "models"
    assert ollama_paths.PROJECT_INSTALL_DIR == runtime_root.WINDOWS_ROOT / "ollama"


def test_explicit_root_takes_shared_assets_with_it(monkeypatch, tmp_path):
    import project_paths
    root = tmp_path / "LocalAI"
    monkeypatch.setenv("LOCAL_AI_ROOT", str(root))
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)

    assert project_paths.runtime_dir() == root
    assert project_paths.model_dir() == root / "models"


def test_user_model_override_is_still_respected():
    from core import ollama_paths
    moved = {"OLLAMA_MODELS": r"D:\ai-models"}
    assert str(ollama_paths.models_dir(moved)) == r"D:\ai-models"


def test_service_explicitly_points_ollama_at_shared_store(tmp_path, monkeypatch):
    import project_paths
    broker = tmp_path / "LocalAI" / "ollama"
    broker.mkdir(parents=True)
    exe = broker / "ollama.exe"
    exe.write_text("ollama", encoding="utf-8")
    monkeypatch.setattr(project_paths, "OLLAMA_INSTALL_DIR", broker)

    store = tmp_path / "LocalAI" / "models"
    svc = OllamaService(tmp_path / "environment", model_dir=store)
    svc.exe = exe
    svc.portable_exe = exe

    assert svc.env_vars({})["OLLAMA_MODELS"] == str(store)


def test_create_environment_builds_shared_and_private_sides(tmp_path, monkeypatch):
    from installer.core import filesystem

    root = tmp_path / "LocalAI"
    env = root / "environment"
    models = root / "models"
    account = root / "users" / "Tester"
    broker = root / "ollama"

    monkeypatch.setattr(filesystem, "MODEL_STORAGE_DIR", models)
    monkeypatch.setattr(filesystem, "OLLAMA_INSTALL_DIR", broker)
    monkeypatch.setattr(filesystem, "ensure_shared_model_access", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "publish_shared_model_dir", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)

    paths = create_environment(env, account_root=account)

    assert paths["env"] == env
    assert paths["ollama"] == broker
    assert paths["models"] == models
    assert paths["account"] == account
    assert paths["user_data"] == account / "user_data"
    assert paths["logs"] == account / "logs"
    assert paths["workspace"] == account / "workspace"
    assert paths["open_interpreter_home"] == account / "user_data" / "interpreter"


def test_create_environment_does_not_scan_or_move_old_model_folders(tmp_path, monkeypatch):
    from installer.core import filesystem

    root = tmp_path / "LocalAI"
    env = root / "environment"
    models = root / "models"
    account = root / "users" / "Tester"
    old = tmp_path / "LLM_Models"
    (old / "blobs").mkdir(parents=True)
    (old / "blobs" / "sha256-old").write_text("old", encoding="utf-8")

    monkeypatch.setattr(filesystem, "MODEL_STORAGE_DIR", models)
    monkeypatch.setattr(filesystem, "OLLAMA_INSTALL_DIR", root / "ollama")
    monkeypatch.setattr(filesystem, "ensure_shared_model_access", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "publish_shared_model_dir", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)

    create_environment(env, account_root=account)

    assert old.exists()
    assert (old / "blobs" / "sha256-old").exists()
    assert models.is_dir()
    assert not (models / "blobs" / "sha256-old").exists()


def test_shared_model_access_grants_builtin_users_read_execute(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("integrations.windows.acl.subprocess.run", fake_run)
    assert ensure_shared_model_access(model_dir, windows=True) is True
    assert calls[0][0] == [
        "icacls", str(model_dir), "/grant",
        "*S-1-5-32-545:(OI)(CI)(RX)", "/T", "/Q",
    ]


def test_explicit_model_dir_is_not_published_or_reacled(tmp_path, monkeypatch):
    from installer.core import filesystem
    touched = []
    monkeypatch.setattr(filesystem, "ensure_shared_model_access",
                        lambda *a, **k: touched.append("acl"))
    monkeypatch.setattr(filesystem, "publish_shared_model_dir",
                        lambda *a, **k: touched.append("setx"))
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "OLLAMA_INSTALL_DIR", tmp_path / "ollama")

    filesystem.create_environment(
        tmp_path / "environment",
        model_dir=tmp_path / "chosen",
        account_root=tmp_path / "users" / "Tester",
    )
    assert touched == []


def test_install_manifest_records_shared_root_and_private_account(tmp_path, monkeypatch):
    from installer.core import filesystem

    root = tmp_path / "LocalAI"
    env = root / "environment"
    models = root / "models"
    account = root / "users" / "Tester"
    broker = root / "ollama"

    monkeypatch.setattr(filesystem, "MODEL_STORAGE_DIR", models)
    monkeypatch.setattr(filesystem, "OLLAMA_INSTALL_DIR", broker)
    monkeypatch.setattr(filesystem, "ensure_shared_model_access", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "publish_shared_model_dir", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)

    paths = create_environment(env, account_root=account)
    manifest = write_install_manifest(
        paths,
        project_root=tmp_path / "checkout",
        status="installed",
        components=["ollama"],
    )

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert Path(data["runtime_root"]) == root
    assert Path(data["environment_path"]) == env
    assert Path(data["ollama_path"]) == broker
    assert Path(data["model_storage"]) == models
    assert Path(data["account_path"]) == account


@pytest.mark.parametrize("raw,expected", [
    (r"C:\LocalAI\models", r"C:\LocalAI\models"),
    (r'"C:\LocalAI\models"', r"C:\LocalAI\models"),
    ("  C:\\LocalAI\\models  ", r"C:\LocalAI\models"),
    (r"D:\내 모델\ollama", r"D:\내 모델\ollama"),
])
def test_ollama_models_is_parsed_the_way_ollama_parses_it(raw, expected):
    from core import ollama_paths
    assert str(ollama_paths.configured_models_dir({"OLLAMA_MODELS": raw})) == expected


@pytest.mark.parametrize("raw", ["", "   ", '""', "''", None])
def test_empty_ollama_models_uses_shared_default(raw):
    from core import ollama_paths
    environ = {} if raw is None else {"OLLAMA_MODELS": raw}
    assert ollama_paths.configured_models_dir(environ) is None
    assert ollama_paths.models_dir(environ) == ollama_paths.SHARED_MODELS_DIR
