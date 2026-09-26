import json
from pathlib import Path

import pytest

from installer.core.filesystem import (
    create_environment,
    ensure_shared_model_access,
    ensure_shared_runtime_lock_access,
    ensure_accounts_parent_access,
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


def test_model_control_paths_are_shared_not_account_scoped(monkeypatch, tmp_path):
    import project_paths
    root = tmp_path / "LocalAI"
    monkeypatch.setenv("LOCAL_AI_ROOT", str(root))
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)

    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Alice")
    alice_data = project_paths.user_data_dir()
    alice_registry = project_paths.model_registry_path()
    alice_lock = project_paths.model_mutation_lock_path()

    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Bob")
    bob_data = project_paths.user_data_dir()

    assert alice_data != bob_data
    assert alice_registry == project_paths.model_registry_path() == root / "models" / ".localai" / "registry.json"
    assert alice_lock == project_paths.model_mutation_lock_path() == root / "models" / ".localai" / "model-mutation.lock"
    assert project_paths.model_files_path() == root / "models" / "MODEL_FILES.csv"


def test_role_registry_written_by_alice_is_read_by_bob(monkeypatch, tmp_path):
    import project_paths
    from launcher.models import model_roles

    root = tmp_path / "LocalAI"
    monkeypatch.setenv("LOCAL_AI_ROOT", str(root))
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)
    shared = project_paths.model_registry_path()
    shared.parent.mkdir(parents=True)
    shared.write_text(json.dumps({
        "replace": {
            "coding": [{
                "need": 9.0,
                "primary": "model-A",
                "alts": [],
            }]
        }
    }), encoding="utf-8")

    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Alice")
    alice_path = Path(model_roles._registry_path())
    alice_replace, _, _ = model_roles.load_registry()

    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Bob")
    bob_path = Path(model_roles._registry_path())
    bob_replace, _, _ = model_roles.load_registry()

    assert alice_path == bob_path == shared
    assert alice_replace["coding"][0]["primary"] == "model-A"
    assert bob_replace == alice_replace


def test_legacy_personal_registry_is_not_auto_imported(monkeypatch, tmp_path):
    import project_paths
    from launcher.models import model_roles

    root = tmp_path / "LocalAI"
    monkeypatch.setenv("LOCAL_AI_ROOT", str(root))
    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Alice")
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)

    legacy = project_paths.user_data_dir() / "models" / "registry.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({
        "replace": {
            "coding": [{"need": 9.0, "primary": "legacy-A", "alts": []}]
        }
    }), encoding="utf-8")

    assert not project_paths.model_registry_path().exists()
    replace, add, errors = model_roles.load_registry()
    assert replace == {}
    assert add == {}
    assert errors == []
    assert legacy.exists(), "legacy data is preserved, not migrated or deleted"


def test_user_ollama_models_is_diagnostic_not_the_managed_store():
    from core import ollama_paths
    moved = {"OLLAMA_MODELS": r"D:\ai-models"}
    assert str(ollama_paths.configured_models_dir(moved)) == r"D:\ai-models"
    assert ollama_paths.models_dir(moved) == ollama_paths.SHARED_MODELS_DIR
    assert ollama_paths.store_candidates(moved)[0] == ollama_paths.configured_models_dir(moved)


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
    monkeypatch.setattr(filesystem, "ensure_shared_runtime_access", lambda *a, **k: True)
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
    assert paths["open_interpreter_home"] == account / "user_data" / "interpreter" / "host"
    assert paths["runtime_lock"] == env / "desktop-runtime.lock"
    assert paths["runtime_lock"].is_file()
    assert paths["model_control"] == models / ".localai"
    assert paths["model_registry"] == models / ".localai" / "registry.json"
    assert paths["model_mutation_lock"] == models / ".localai" / "model-mutation.lock"
    assert json.loads(paths["model_registry"].read_text(encoding="utf-8")) == {}
    assert paths["model_mutation_lock"].is_file()


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
    monkeypatch.setattr(filesystem, "ensure_shared_runtime_access", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_shared_model_access", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "publish_shared_model_dir", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)

    create_environment(env, account_root=account)

    assert old.exists()
    assert (old / "blobs" / "sha256-old").exists()
    assert models.is_dir()
    assert not (models / "blobs" / "sha256-old").exists()




def test_localized_windows_console_output_does_not_use_python_utf8(monkeypatch):
    from integrations.windows import acl

    seen = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        seen["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(acl, "on_windows", lambda windows=None: True)
    monkeypatch.setattr(acl.subprocess, "run", fake_run)

    result = acl.run(["setx", "OLLAMA_MODELS", r"C:\LocalAI\models", "/M"])

    assert result.returncode == 0
    assert seen["kwargs"]["encoding"] == "mbcs"
    assert seen["kwargs"]["errors"] == "replace"
    assert seen["kwargs"]["text"] is True


def test_shared_runtime_access_grants_read_execute_to_environment_and_ollama(monkeypatch, tmp_path):
    from installer.core import filesystem
    touched = []
    monkeypatch.setattr(
        "integrations.ollama.sharing.ensure_readable",
        lambda path, **kwargs: touched.append(Path(path)) or True,
    )
    env = tmp_path / "LocalAI" / "environment"
    broker = tmp_path / "LocalAI" / "ollama"
    assert filesystem.ensure_shared_runtime_access((env, broker), windows=True) is True
    assert touched == [env, broker]

def test_users_parent_allows_standard_accounts_to_create_only_their_child(monkeypatch, tmp_path):
    users = tmp_path / "LocalAI" / "users"
    users.mkdir(parents=True)
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "integrations.windows.acl.run",
        lambda command, **kwargs: calls.append(list(command)) or Result(),
    )

    assert ensure_accounts_parent_access(users, windows=True) is True
    assert calls == [[
        "icacls", str(users), "/grant",
        "*S-1-5-32-545:(RD,X,AD,RA,REA)", "/Q",
    ]]
    assert all("(OI)" not in part and "(CI)" not in part for part in calls[0]), (
        "the Users grant must not inherit into private account folders"
    )


def test_shared_runtime_lock_grants_only_file_read_write(monkeypatch, tmp_path):
    lock = tmp_path / "LocalAI" / "environment" / "desktop-runtime.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"\0")
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "integrations.windows.acl.run",
        lambda command, **kwargs: calls.append(list(command)) or Result(),
    )
    assert ensure_shared_runtime_lock_access(lock, windows=True) is True
    assert calls == [[
        "icacls", str(lock), "/grant",
        "*S-1-5-32-545:(R,W)", "/Q",
    ]]


def test_publish_shared_model_dir_updates_current_process_immediately(monkeypatch, tmp_path):
    from installer.core import filesystem
    store = tmp_path / "LocalAI" / "models"
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.setattr(
        "integrations.ollama.sharing.publish_machine_variable",
        lambda path, **kwargs: True,
    )
    assert filesystem.publish_shared_model_dir(store, windows=True) is True
    assert filesystem.os.environ["OLLAMA_MODELS"] == str(store)


def test_shared_model_access_grants_builtin_users_modify(monkeypatch, tmp_path):
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
        "*S-1-5-32-545:(OI)(CI)(M)", "/T", "/Q",
    ]


def test_explicit_model_dir_is_not_published_or_reacled(tmp_path, monkeypatch):
    from installer.core import filesystem
    touched = []
    monkeypatch.setattr(filesystem, "ensure_shared_model_access",
                        lambda *a, **k: touched.append("acl"))
    monkeypatch.setattr(filesystem, "publish_shared_model_dir",
                        lambda *a, **k: touched.append("setx"))
    monkeypatch.setattr(filesystem, "ensure_private_account", lambda *a, **k: True)
    monkeypatch.setattr(filesystem, "ensure_shared_runtime_access", lambda *a, **k: True)
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
    monkeypatch.setattr(filesystem, "ensure_shared_runtime_access", lambda *a, **k: True)
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
