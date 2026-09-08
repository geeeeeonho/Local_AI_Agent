# Final Legacy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove retired compatibility code only after security boundaries are green, while preserving active migration cleanup and ownership contracts.

**Architecture:** Open Interpreter thread IDs remain the session source of truth; `TkPresenter`/Presenter APIs remain the GUI source of truth; current sandbox/network policy remains canonical. Active Open WebUI runtime/install/UI remains absent, while migration-only Docker cleanup patterns may stay.

**Tech Stack:** Python 3.11, pytest, GitHub code search/Actions.

**Spec:** User-provided `Local_AI_Agent 전환 완료 후 보안·구조 보완 지시서` (2026-09-08), Phases 5-6.

---

## Task 1 — Retired custom session helpers

Search `new_session_id`, `session_path`, `list_sessions`, `latest_session`, `session_meta`. If runtime callers are zero, add RED structure assertions then remove helpers/tests tied only to local `session_*.json`. Do not restore local session scanning.

## Task 2 — `_sandbox_options.py`

Search `build_sandbox_options`. If only self-definition/history remains, add RED guard then delete the module. Do not copy old `auto_run`, `allow_internet`, privileged, or DNS-block concepts elsewhere.

## Task 3 — GUI compatibility shims

Search live references to `launcher.gui`, `launcher.checkbox`, `gui.main_menu`, and `checkbox.run`. If none, add structure guards and remove the shims. Keep `launcher.presenter.gui.TkPresenter` and `Presenter.show_checkbox` as canonical APIs.

## Task 4 — Legacy AgentEvent adapter

Search `from_legacy_message` and `_LEGACY_TYPES`. If only historical docs/tests remain, add RED structure guard, remove adapter, and migrate tests to the current `AgentEvent` contract.

## Task 5 — Open WebUI residue

Search `OPEN_WEBUI_PORT` and `OPEN_WEBUI_URL`. Delete unused active constants/callers. Keep `_LEGACY_OPENWEBUI_*` Docker cleanup patterns if still required for upgrades from old installs.

## Task 6 — Final structure and documentation audit

Update `src/tests/test_structure_cleanup.py` to assert:
- no legacy session ownership
- no dead sandbox options
- no dead GUI/checkbox shim
- no legacy AgentEvent adapter
- no active OpenWebUI runtime
- one OI version assignment source
- `network_policy.py` owns NetworkMode semantics
- Host permission translator exists

Then run:
```powershell
python -m compileall -q src
python -m pytest -q src\tests
```
Require a green Windows GitHub Actions run before the cleanup PR is considered ready. Do not combine this PR with a future OI version bump or SDK migration.
