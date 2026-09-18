import pytest

import json
from pathlib import Path

from installer.core.filesystem import (
    create_environment,
    ensure_shared_model_access,
    write_install_manifest,
)
from launcher.services.ollama import OllamaService
from project_paths import MODEL_STORAGE_DIR


def test_the_model_store_follows_ollama_rather_than_being_forced():
    """This project no longer picks the location; Ollama does.

    Forcing OLLAMA_MODELS to C:\\LLM_Models made the models ours rather than
    Ollama's: nothing else on the machine could see them, and a user who had
    already moved their store off C: had that silently overridden.
    """
    from core import ollama_paths
    assert MODEL_STORAGE_DIR == ollama_paths.models_dir()
    assert str(MODEL_STORAGE_DIR).lower() != r"c:\llm_models"


def test_the_default_store_is_shared_by_every_account_on_the_machine():
    """Ollama's own default is per-user, so a second account re-downloads everything."""
    from core import ollama_paths
    home = {"USERPROFILE": r"C:\Users\someone", "HOME": r"C:\Users\someone"}
    assert ollama_paths.models_dir(home) == ollama_paths.SHARED_MODELS_DIR
    assert ollama_paths.models_dir_is_shared(home)
    assert not ollama_paths.is_per_user_store(ollama_paths.models_dir(home), home)
    # The per-user location Ollama would pick unaided is still named, so the
    # shell can say why it is not being used.
    assert ollama_paths.is_per_user_store(ollama_paths.user_default_models_dir(home), home)


def test_the_shared_store_lives_inside_the_ollama_install():
    from core import ollama_paths
    assert ollama_paths.SHARED_MODELS_DIR.parent == ollama_paths.PROJECT_INSTALL_DIR


def test_a_store_the_user_configured_wins_over_the_shared_default():
    from core import ollama_paths
    home = {"USERPROFILE": r"C:\Users\someone"}
    moved = dict(home, OLLAMA_MODELS=r"D:\models")
    assert str(ollama_paths.models_dir(moved)) == r"D:\models"
    assert not ollama_paths.models_dir_is_shared(moved)
    assert str(ollama_paths.configured_models_dir(moved)) == r"D:\models"
    assert ollama_paths.configured_models_dir(home) is None
    assert ollama_paths.configured_models_dir(dict(home, OLLAMA_MODELS="   ")) is None


def test_the_store_this_project_used_to_force_is_still_known():
    """The installer has to find models left there before it can move them."""
    from project_paths import LEGACY_FORCED_MODEL_DIR
    assert str(LEGACY_FORCED_MODEL_DIR).lower() == r"c:\llm_models"


def test_the_service_tells_ollama_where_the_shared_store_is(tmp_path):
    """Left unsaid, Ollama would use a profile path and the sharing is lost."""
    from core import ollama_paths
    service = OllamaService(tmp_path, model_dir=ollama_paths.SHARED_MODELS_DIR)
    assert service.env_vars({})["OLLAMA_MODELS"] == str(ollama_paths.SHARED_MODELS_DIR)
    directed = OllamaService(tmp_path, model_dir=tmp_path / "elsewhere")
    assert directed.env_vars({})["OLLAMA_MODELS"] == str(tmp_path / "elsewhere")


def test_a_user_who_already_moved_their_store_keeps_their_choice(tmp_path):
    """Their OLLAMA_MODELS is already in the environment; we must not rewrite it."""
    from core import ollama_paths
    chosen = tmp_path / "chosen"
    environ = {"USERPROFILE": str(tmp_path), "OLLAMA_MODELS": str(chosen)}
    service = OllamaService(tmp_path, model_dir=ollama_paths.models_dir(environ))
    assert service.model_dir == chosen
    assert service.env_vars(environ)["OLLAMA_MODELS"] == str(chosen)


def test_being_pointed_elsewhere_overrides_even_a_user_setting(tmp_path):
    """A controlled deployment that names a directory still wins, explicitly."""
    directed = tmp_path / "directed"
    environ = {"USERPROFILE": str(tmp_path), "OLLAMA_MODELS": str(tmp_path / "chosen")}
    service = OllamaService(tmp_path, model_dir=directed)
    assert service.env_vars(environ)["OLLAMA_MODELS"] == str(directed)


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


def test_create_environment_promotes_completed_staging_after_interruption(tmp_path):
    env = tmp_path / "project" / "llm_environment"
    shared_models = tmp_path / "shared" / "LLM_Models"
    staging = shared_models.with_name(shared_models.name + ".migrating")
    (staging / "blobs").mkdir(parents=True)
    (staging / "blobs" / "sha256-complete").write_text("complete", encoding="utf-8")

    paths = create_environment(env, model_dir=shared_models)

    assert paths["models"] == shared_models
    assert (shared_models / "blobs" / "sha256-complete").read_text(encoding="utf-8") == "complete"
    assert not staging.exists()


def test_create_environment_discards_partial_staging_when_legacy_source_remains(tmp_path):
    env = tmp_path / "project" / "llm_environment"
    legacy = env / "llm_models"
    shared_models = tmp_path / "shared" / "LLM_Models"
    staging = shared_models.with_name(shared_models.name + ".migrating")
    (legacy / "blobs").mkdir(parents=True)
    (legacy / "blobs" / "sha256-real").write_text("real", encoding="utf-8")
    (staging / "blobs").mkdir(parents=True)
    (staging / "blobs" / "sha256-partial").write_text("partial", encoding="utf-8")

    paths = create_environment(env, model_dir=shared_models)

    assert (shared_models / "blobs" / "sha256-real").read_text(encoding="utf-8") == "real"
    assert not (shared_models / "blobs" / "sha256-partial").exists()
    assert not staging.exists()
    assert not legacy.exists()


def test_completed_staging_wins_if_source_cleanup_was_interrupted(tmp_path):
    env = tmp_path / "project" / "llm_environment"
    legacy = env / "llm_models"
    shared_models = tmp_path / "shared" / "LLM_Models"
    staging = shared_models.with_name(shared_models.name + ".migrating")

    # Source cleanup has already removed one file, while staging has the complete copy.
    (legacy / "blobs").mkdir(parents=True)
    (legacy / "blobs" / "sha256-still-left").write_text("left", encoding="utf-8")
    (staging / "blobs").mkdir(parents=True)
    (staging / "blobs" / "sha256-still-left").write_text("left", encoding="utf-8")
    (staging / "blobs" / "sha256-already-removed-from-source").write_text(
        "complete-copy", encoding="utf-8"
    )
    (staging / ".LOCAL_AI_MIGRATION_COMPLETE").write_text("complete\n", encoding="utf-8")

    paths = create_environment(env, model_dir=shared_models)

    assert paths["models"] == shared_models
    assert (
        shared_models / "blobs" / "sha256-already-removed-from-source"
    ).read_text(encoding="utf-8") == "complete-copy"
    assert not (shared_models / ".LOCAL_AI_MIGRATION_COMPLETE").exists()
    assert not staging.exists()
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
        "/T",
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
    assert data["model_storage_access"] == (
        "builtin-users-read-execute-requested; existing-acl-preserved"
    )
    assert data["components"] == ["ollama", "open_webui", "open_interpreter"]


# ── moving the old forced store into Ollama's ────────────────────────────
# C:\LLM_Models was this project's own invention. Once Ollama owns the
# location, that folder is invisible to Ollama, so the installer has to move it
# or tens of gigabytes appear to vanish. These pin the data-safety rules.

def store(path, *blobs):
    (path / "blobs").mkdir(parents=True, exist_ok=True)
    for blob in blobs:
        (path / "blobs" / ("sha256-" + blob)).write_text(blob, encoding="utf-8")
    return path


def blobs(path):
    folder = path / "blobs"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def migrate(monkeypatch, forced, env, models):
    from installer.core import filesystem
    monkeypatch.setattr(filesystem, "LEGACY_FORCED_MODEL_DIR", forced)
    filesystem._migrate_legacy_models(env, models)


def test_the_old_forced_store_moves_into_the_ollama_store(monkeypatch, tmp_path):
    forced = store(tmp_path / "LLM_Models", "aaa", "bbb")
    models = tmp_path / "Ollama" / "models"
    migrate(monkeypatch, forced, tmp_path / "env", models)
    assert blobs(models) == ["sha256-aaa", "sha256-bbb"]
    assert not forced.exists()


def test_a_store_already_in_use_is_never_merged_into(monkeypatch, tmp_path):
    forced = store(tmp_path / "LLM_Models", "old")
    models = store(tmp_path / "Ollama" / "models", "new")
    migrate(monkeypatch, forced, tmp_path / "env", models)
    assert blobs(models) == ["sha256-new"]
    assert blobs(forced) == ["sha256-old"], "the source must survive untouched"


def test_only_one_store_moves_and_the_other_is_left_for_the_user(monkeypatch, tmp_path):
    forced = store(tmp_path / "LLM_Models", "forced")
    env = tmp_path / "env"
    older = store(env / "llm_models", "older")
    models = tmp_path / "Ollama" / "models"
    migrate(monkeypatch, forced, env, models)
    assert blobs(models) == ["sha256-forced"]
    assert blobs(older) == ["sha256-older"], "never silently discarded"


def test_a_partial_copy_is_discarded_while_its_source_still_exists(monkeypatch, tmp_path):
    forced = store(tmp_path / "LLM_Models", "real")
    models = tmp_path / "Ollama" / "models"
    store(models.with_name(models.name + ".migrating"), "partial")
    migrate(monkeypatch, forced, tmp_path / "env", models)
    assert blobs(models) == ["sha256-real"]
    assert not models.with_name(models.name + ".migrating").exists()


def test_an_interrupted_rename_is_promoted_not_deleted(monkeypatch, tmp_path):
    """Source already renamed into staging: discarding it destroys the only copy."""
    models = tmp_path / "Ollama" / "models"
    store(models.with_name(models.name + ".migrating"), "only-copy")
    migrate(monkeypatch, forced := tmp_path / "LLM_Models", tmp_path / "env", models)
    assert blobs(models) == ["sha256-only-copy"]
    assert not forced.exists()


def test_a_completed_copy_cleans_up_the_store_it_names(monkeypatch, tmp_path):
    from installer.core.filesystem import _MIGRATION_COMPLETE_MARKER
    forced = store(tmp_path / "LLM_Models", "source")
    env = tmp_path / "env"
    other = store(env / "llm_models", "untouched")
    models = tmp_path / "Ollama" / "models"
    staging = store(models.with_name(models.name + ".migrating"), "copied")
    (staging / _MIGRATION_COMPLETE_MARKER).write_text(
        "complete\n%s\n" % forced, encoding="utf-8")
    migrate(monkeypatch, forced, env, models)
    assert blobs(models) == ["sha256-copied"]
    assert not forced.exists(), "the recorded origin is cleaned up"
    assert blobs(other) == ["sha256-untouched"], "an unrelated store is not touched"


def test_a_completed_copy_with_no_recorded_origin_keeps_ambiguous_sources(monkeypatch, tmp_path):
    """An older marker names no origin; with two candidates, delete neither."""
    from installer.core.filesystem import _MIGRATION_COMPLETE_MARKER
    forced = store(tmp_path / "LLM_Models", "one")
    env = tmp_path / "env"
    other = store(env / "llm_models", "two")
    models = tmp_path / "Ollama" / "models"
    staging = store(models.with_name(models.name + ".migrating"), "copied")
    (staging / _MIGRATION_COMPLETE_MARKER).write_text("complete\n", encoding="utf-8")
    migrate(monkeypatch, forced, env, models)
    assert blobs(models) == ["sha256-copied"]
    assert blobs(forced) == ["sha256-one"] and blobs(other) == ["sha256-two"]


def test_publishing_the_shared_dir_is_skipped_off_windows(tmp_path):
    from installer.core.filesystem import publish_shared_model_dir
    assert publish_shared_model_dir(tmp_path, windows=False) is True


def test_an_explicit_model_dir_is_not_published_or_reacled(tmp_path, monkeypatch):
    """A caller-chosen directory belongs to the caller, not to the machine."""
    from installer.core import filesystem
    touched = []
    monkeypatch.setattr(filesystem, "ensure_shared_model_access",
                        lambda *a, **k: touched.append("acl"))
    monkeypatch.setattr(filesystem, "publish_shared_model_dir",
                        lambda *a, **k: touched.append("setx"))
    filesystem.create_environment(tmp_path / "env", model_dir=tmp_path / "chosen")
    assert touched == []


# ── matching Ollama's own resolution ─────────────────────────────────────
# Verified against a real ollama binary built from source: envconfig.Models is
#     if OLLAMA_MODELS != "" -> it, else <home>/.ollama/models
# and envconfig.Var is strings.Trim(strings.TrimSpace(v), "\"'"). Disagreeing
# with either sends this project looking in a directory that does not exist
# while Ollama serves happily from the real one.

@pytest.mark.parametrize("raw,expected", [
    (r"C:\Ollama\models", r"C:\Ollama\models"),
    # Quotes are easy to end up with from a Windows dialog or a batch file.
    (r'"C:\Ollama\models"', r"C:\Ollama\models"),
    (r"'C:\Ollama\models'", r"C:\Ollama\models"),
    (r'""C:\Ollama\models""', r"C:\Ollama\models"),
    ("  C:\\Ollama\\models  ", r"C:\Ollama\models"),
    # Ollama trims the quotes but not spaces inside them, and so must this.
    (r'" C:\Ollama\models "', r" C:\Ollama\models "),
    (r"D:\내 모델\ollama", r"D:\내 모델\ollama"),
])
def test_ollama_models_is_parsed_the_way_ollama_parses_it(raw, expected):
    from core import ollama_paths
    assert str(ollama_paths.configured_models_dir({"OLLAMA_MODELS": raw})) == expected


@pytest.mark.parametrize("raw", ["", "   ", '""', "''", None])
def test_an_empty_or_quote_only_value_means_unconfigured(raw):
    from core import ollama_paths
    environ = {} if raw is None else {"OLLAMA_MODELS": raw}
    assert ollama_paths.configured_models_dir(environ) is None
    assert ollama_paths.models_dir(environ) == ollama_paths.SHARED_MODELS_DIR
