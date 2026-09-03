import json
from pathlib import Path

from installer.core.filesystem import (
    create_environment,
    ensure_shared_model_access,
    write_install_manifest,
)
from launcher.services.ollama import OllamaService
from project_paths import MODEL_STORAGE_DIR


def test_default_model_storage_is_machine_shared_location():
    assert str(MODEL_STORAGE_DIR).lower() == r"c:\llm_models"


def test_create_environment_keeps_models_outside_project_environment(tmp_path):
    env = tmp_path / "project" / "llm_environment"
    shared_models = tmp_path / "shared" / "LLM_Models"

    paths = create_environment(env, model_dir=shared_models)

    assert paths["models"] == shared_models
    assert shared_models.is_dir()
    assert not (env / "llm_models").exists()


def test_create_environment_migrates_legacy_models_when_shared_storage_is_empty(tmp_path):
    env = tmp_path / "project" / "llm_environment"
    legacy = env / "llm_models"
    shared_models = tmp_path / "shared" / "LLM_Models"
    (legacy / "blobs").mkdir(parents=True)
    (legacy / "blobs" / "sha256-test").write_text("model", encoding="utf-8")

    paths = create_environment(env, model_dir=shared_models)

    assert paths["models"] == shared_models
    assert (shared_models / "blobs" / "sha256-test").read_text(encoding="utf-8") == "model"
    assert not legacy.exists()


def test_shared_model_access_grants_builtin_users_read_execute(monkeypatch, tmp_path):
    model_dir = tmp_path / "LLM_Models"
    model_dir.mkdir()
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("installer.core.filesystem.subprocess.run", fake_run)

    assert ensure_shared_model_access(model_dir, windows=True) is True
    assert calls[0][0] == [
        "icacls",
        str(model_dir),
        "/grant",
        "*S-1-5-32-545:(OI)(CI)(RX)",
        "/Q",
    ]


def test_ollama_service_uses_same_shared_model_directory(tmp_path):
    env = tmp_path / "llm_environment"
    shared_models = tmp_path / "LLM_Models"
    svc = OllamaService(env, model_dir=shared_models)

    values = svc.env_vars({})

    assert values["OLLAMA_MODELS"] == str(shared_models)


def test_install_manifest_identifies_product_and_external_model_storage(tmp_path):
    project_root = tmp_path / "Local_AI_Agent"
    env = project_root / "llm_environment"
    shared_models = tmp_path / "LLM_Models"
    paths = create_environment(env, model_dir=shared_models)

    manifest = write_install_manifest(
        paths,
        project_root=project_root,
        status="installed",
        components=["ollama", "open_webui", "open_interpreter"],
    )

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest == env / "LOCAL_AI_AGENT_INSTALL.json"
    assert data["product"] == "Local AI Agent"
    assert data["repository"] == "geeeeeonho/Local_AI_Agent"
    assert data["status"] == "installed"
    assert Path(data["environment_path"]) == env
    assert Path(data["model_storage"]) == shared_models
    assert data["components"] == ["ollama", "open_webui", "open_interpreter"]
