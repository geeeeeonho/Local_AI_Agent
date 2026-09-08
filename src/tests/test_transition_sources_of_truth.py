from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / ".gitignore").is_file()
)
SRC_ROOT = REPO_ROOT / "src"


def _assignment_sources(name: str) -> list[str]:
    sources: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                    sources.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(set(sources))


def test_network_mode_enum_has_one_runtime_definition():
    definitions: list[str] = []
    for path in (SRC_ROOT / "launcher").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "NetworkMode":
                definitions.append(path.relative_to(REPO_ROOT).as_posix())
    assert definitions == ["src/launcher/network_policy.py"]


def test_host_permission_translator_is_an_explicit_transition_boundary():
    path = SRC_ROOT / "launcher" / "agent" / "host_permissions.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert 'HOST_PERMISSION_PROFILE = "local-ai-host"' in text
    assert "def build_host_permission_spec(" in text
    assert "def host_permission_fingerprint(" in text


def test_project_and_shared_model_paths_have_one_assignment_source():
    assert _assignment_sources("PROJECT_ROOT") == ["src/project_paths.py"]
    assert _assignment_sources("MODEL_STORAGE_DIR") == ["src/project_paths.py"]
    text = (SRC_ROOT / "project_paths.py").read_text(encoding="utf-8")
    assert 'Path(r"C:\\LLM_Models")' in text


def test_runtime_coordinator_is_part_of_the_active_agent_boundary():
    assert (SRC_ROOT / "launcher" / "agent" / "runtime_coordinator.py").is_file()


def test_compatibility_matrix_includes_page_fetch_contract():
    text = (SRC_ROOT / "tools" / "oi_compatibility.py").read_text(encoding="utf-8")
    assert '"fetch_page"' in text
