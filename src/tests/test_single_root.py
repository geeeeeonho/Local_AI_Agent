"""Fresh installs keep shared assets and private account state under one root."""
import ast
from pathlib import Path

from core import runtime_root

SRC = Path(__file__).resolve().parents[1]


def test_layout_splits_shared_machine_assets_from_private_account_data():
    env = {"USERNAME": "Tester", "LOCAL_AI_ROOT": r"C:\LocalAI"}
    layout = runtime_root.layout(env, windows=True)

    assert layout["env"] == Path(r"C:\LocalAI") / "environment"
    assert layout["ollama"] == Path(r"C:\LocalAI") / "ollama"
    assert layout["models"] == Path(r"C:\LocalAI") / "models"
    assert layout["account"] == Path(r"C:\LocalAI") / "users" / "Tester"
    assert layout["user_data"] == layout["account"] / "user_data"
    assert layout["logs"] == layout["account"] / "logs"
    assert layout["workspace"] == layout["account"] / "workspace"


def test_every_shared_asset_is_inside_the_runtime_root(monkeypatch, tmp_path):
    root = tmp_path / "LocalAI"
    monkeypatch.setenv("LOCAL_AI_ROOT", str(root))
    monkeypatch.setenv("LOCAL_AI_ACCOUNT", "Tester")
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)

    import project_paths

    assert project_paths.runtime_dir() == root
    assert project_paths.env_dir() == root / "environment"
    assert project_paths.model_dir() == root / "models"
    assert project_paths.OLLAMA_INSTALL_DIR == root / "ollama"

    account = project_paths.account_dir()
    assert account == root / "users" / "Tester"
    assert project_paths.user_data_dir() == account / "user_data"
    assert project_paths.logs_dir() == account / "logs"
    assert project_paths.workspace_dir() == account / "workspace"


def composed_runtime_names(tree):
    watched = {"user_data", "llm_environment"}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        right = node.right
        if isinstance(right, ast.Constant) and right.value in watched:
            found.append((right.lineno, right.value))
    return found


def test_modules_that_write_use_canonical_path_helpers():
    allowed = {
        "project_paths.py",
        "core/runtime_root.py",
        "core/ollama_paths.py",
        "installer/core/filesystem.py",
        "launcher/core/user_data.py",
        "launcher/settings_store.py",
        "launcher/agent/interpreter_backend.py",
        "services/desktop.py",
        "integrations/legacy/desktop.py",
    }
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        if relative.parts[0] == "tests" or relative.as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, name in composed_runtime_names(tree):
            offenders.append(f'{relative}:{lineno}  / "{name}"')
    assert offenders == [], "런타임 경로를 직접 조립하는 곳:\n  " + "\n  ".join(offenders)


def test_user_chosen_model_store_remains_an_explicit_override(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_MODEL_DIR", raising=False)
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "their-drive"))
    monkeypatch.setenv("LOCAL_AI_ROOT", str(tmp_path / "LocalAI"))
    import project_paths
    assert project_paths.model_dir() == tmp_path / "their-drive"


def wired_paths():
    import project_paths
    from core.projects.registry import ProjectRegistry
    from core.settings.store import SettingsStore
    from launcher import anythingllm_runtime, searxng_runtime, tor_runtime
    from launcher.agent import folder_policy, interpreter_backend
    from launcher.core import lifelog, user_data
    from launcher.models import model_files, model_roles
    from launcher.services.ollama import OllamaService
    from launcher import settings_store

    env = project_paths.ENV_DIR
    service = OllamaService(env, model_dir=project_paths.MODEL_STORAGE_DIR)
    return [
        ("models", project_paths.MODEL_STORAGE_DIR),
        ("ollama", project_paths.OLLAMA_INSTALL_DIR),
        ("environment", env),
        ("user_data", user_data.root()),
        ("session logs", lifelog._llm_session_log_dir()),
        ("agent traces", user_data.logs_dir()),
        ("ollama run log", service.log_file),
        ("ollama runtime state", service.runtime_state_file),
        ("searxng config", searxng_runtime._cfg_dir(env)),
        ("tor torrc", Path(tor_runtime._write_torrc(env) or (env / "tor" / "torrc"))),
        ("anythingllm storage", anythingllm_runtime.storage_dir()),
        ("sandbox state", user_data.interpreter_dir("sandbox")),
        ("interpreter home", interpreter_backend.runtime_interpreter_home()),
        ("interpreter binary", interpreter_backend.managed_interpreter_exe()),
        ("user settings", settings_store.path()),
        ("desktop settings", SettingsStore().store.path),
        ("folder policy", folder_policy._store_path()),
        ("project registry", ProjectRegistry().store.path),
        ("model registry", Path(model_roles._registry_path())),
        ("model csv", model_files.default_csv_path(project_paths.MODEL_STORAGE_DIR)),
    ]


def test_every_feature_reads_or_writes_inside_the_one_root():
    import project_paths
    root = Path(project_paths.RUNTIME_ROOT).resolve()
    outside = []
    for name, path in wired_paths():
        try:
            Path(path).resolve().relative_to(root)
        except ValueError:
            outside.append(f"{name} -> {path}")
    assert outside == [], "런타임 루트 밖을 보는 기능:\n  " + "\n  ".join(outside)


def test_wiring_check_covers_shared_and_private_runtime_assets():
    names = {name for name, _ in wired_paths()}
    for required in (
        "models", "ollama", "environment", "user_data", "anythingllm storage",
        "interpreter home", "ollama run log", "session logs",
    ):
        assert required in names
