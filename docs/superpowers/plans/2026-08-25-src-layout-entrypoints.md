# src Layout and Unified Entrypoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tracked program/development files under `src/` while preserving root `user_data` and runtime paths, and replace four batch entrypoints with `SETUP.bat` and `RUN.bat`.

**Architecture:** Add `src/project_paths.py` as the canonical repository-path resolver. Batch files add `src` to `PYTHONPATH`; Python packages continue importing as `launcher` and `installer`. `installer.__main__` chooses install/manage mode while existing installer and management components remain intact.

**Tech Stack:** Python 3.11, Windows batch, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-25-src-layout-entrypoints-design.md`

## Global Constraints

- Keep `user_data/` at repository root.
- Keep generated `llm_environment/` at repository root.
- Keep `.github/`, `.gitignore`, `README.md`, `SETUP.bat`, and `RUN.bat` at repository root.
- Move `launcher/`, `installer/`, `tools/`, `tests/`, and `docs/` under `src/`.
- Do not change Open Interpreter, AnythingLLM, SearXNG, Ollama behavior except where paths/entrypoints require it.
- Preserve all CLI arguments by forwarding `%*`.

---

### Task 1: Define the new structure contract with failing tests

**Files:**
- Modify: `tests/test_structure_cleanup.py`

**Interfaces:**
- Consumes: current repository structure.
- Produces: assertions for new root entrypoints, `src/` locations, and canonical path module.

- [ ] Replace old assertions requiring `INSTALL.bat`, `MANAGE.bat`, and `RUN_TUI.bat` with assertions requiring only `SETUP.bat` and `RUN.bat`.
- [ ] Assert `src/launcher`, `src/installer`, `src/tools`, `src/tests`, and `src/docs` exist and old top-level counterparts do not.
- [ ] Assert `user_data` remains at the repository root.
- [ ] Add a path-contract test loading `src/project_paths.py` and checking `PROJECT_ROOT`, `ENV_DIR`, and `USER_DATA_DIR`.
- [ ] Run hosted pytest and verify this commit fails because the new structure does not exist yet.

### Task 2: Add canonical project paths and relocate tracked source trees

**Files:**
- Create: `src/project_paths.py`
- Move: `launcher/**` → `src/launcher/**`
- Move: `installer/**` → `src/installer/**`
- Move: `tools/**` → `src/tools/**`
- Move: `tests/**` → `src/tests/**`
- Move: `docs/**` → `src/docs/**`

**Interfaces:**
- Produces: `SRC_ROOT: Path`, `PROJECT_ROOT: Path`, `USER_DATA_DIR: Path`, `ENV_DIR: Path`.

- [ ] Create `project_paths.py` with constants derived from `Path(__file__).resolve().parent`.
- [ ] Relocate trees by reusing existing Git blob SHAs so file contents are unchanged during the move.
- [ ] Keep `user_data/` untouched.

### Task 3: Replace depth-dependent project-root calculations

**Files:**
- Modify every relocated Python file that currently derives repository root from `__file__` depth, including installer/launcher entrypoints and agent/runtime helpers.

**Interfaces:**
- Consumes: `project_paths.PROJECT_ROOT`, `project_paths.ENV_DIR`, `project_paths.USER_DATA_DIR`.

- [ ] Replace repository-root assumptions with imports from `project_paths` where the code intends the repository root.
- [ ] Preserve package-local path calculations where they intentionally refer to a package directory.
- [ ] Update user-facing references from `INSTALL.bat`/`MANAGE.bat` to `SETUP.bat`.

### Task 4: Unify setup and run entrypoints

**Files:**
- Create: `SETUP.bat`
- Modify: `RUN.bat`
- Modify: `src/installer/__main__.py`
- Delete: `INSTALL.bat`
- Delete: `MANAGE.bat`
- Delete: `RUN_TUI.bat`

**Interfaces:**
- `SETUP.bat [--install|--manage] [other args]`
- `RUN.bat [--gui|--tui] [other args]`

- [ ] Add `PYTHONPATH=%~dp0src` to both batch entrypoints.
- [ ] Make `SETUP.bat` prefer managed Python, then system `python`, then `py -3`.
- [ ] Add installer mode parsing: default `auto`, explicit `--install`, explicit `--manage`.
- [ ] In auto mode, select management when `ENV_DIR` exists, otherwise installation.
- [ ] Keep launcher GUI/TUI selection inside `launcher.__main__`; `RUN.bat --tui` simply forwards the option.

### Task 5: Update CI and documentation references

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `README.md`
- Modify moved docs/source strings that reference old paths or batch files.

- [ ] Set workflow `PYTHONPATH` to `${{ github.workspace }}\src`.
- [ ] Change compile paths to `src/...` and pytest target to `src/tests`.
- [ ] Update README quick-start references to `SETUP.bat`, `RUN.bat`, and `RUN.bat --tui`.
- [ ] Remove stale mentions that instruct users to execute deleted batch files.

### Task 6: Hosted verification

**Files:** none.

- [ ] Run GitHub Actions on the implementation commit.
- [ ] Verify compile step succeeds.
- [ ] Verify pytest succeeds with zero failures.
- [ ] Inspect changed-file list to ensure no tracked `launcher/`, `installer/`, `tools/`, `tests/`, or `docs/` remain at root.
- [ ] Verify `user_data/` remains at root and no migration of its contents occurred.
