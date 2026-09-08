# Host Resume Permission Lifecycle Implementation Plan

> **Scope:** Phase 1 only. Do not mix Direct fetch pinning, Open Interpreter version changes, SDK migration, Docker abstraction, or UI refactors into this branch.

## Goal

Guarantee that a resumed Host Open Interpreter thread always runs under the **current** Local_AI_Agent folder policy. A thread created under an older policy must never continue in an App Server process whose filesystem permission profile was loaded from that older policy.

Security invariant:

```text
current Local_AI_Agent folder policy
=
filesystem permission loaded by the Host OI App Server process used for resume
```

Policy preparation, fingerprinting, App Server shutdown/startup, and permission-profile loading are fail-closed.

## Task 1 — Define a deterministic Host policy fingerprint

Files:
- Modify: `src/launcher/agent/host_permissions.py`
- Modify: `src/tests/test_host_permissions.py`

Steps:
1. RED: add tests proving the fingerprint changes when workspace, allowed roots, denied paths, or profile version change, and is stable across ordering/duplicates.
2. RED: add tests proving `folder_policy.list_allowed()` / `list_denied()` failures propagate instead of becoming permissive empty lists.
3. Implement an explicit profile version and canonical fingerprint over the primary workspace, allowed roots, denied paths, and profile version.
4. Preserve existing `local-ai-host` TOML behavior and path deduplication.
5. Run `python -m pytest -q src/tests/test_host_permissions.py` and require green.

## Task 2 — Return the fingerprint for the exact permission block written

Files:
- Modify: `src/launcher/agent/runtime_assets.py`
- Modify: `src/tests/test_runtime_assets.py`

Steps:
1. RED: add a test that Host asset preparation can return the fingerprint of the exact `HostPermissionSpec` used to write `config.toml`.
2. Implement a Host-specific preparation helper returning `(config_path, policy_fingerprint)` while keeping the existing path-only helper for compatibility.
3. Any spec/render/write failure must propagate; no fallback permission block.
4. Run focused runtime-asset tests and require green.

## Task 3 — Make App Server termination verifiable

Files:
- Modify: `src/launcher/agent/app_server_client.py`
- Modify: the existing App Server client test module

Steps:
1. RED: add tests for graceful stop success, terminate timeout followed by kill success, and process-still-running failure.
2. Make `AppServerClient.stop()` return a boolean indicating that the child is actually no longer running.
3. After `kill()`, wait again and verify process state; do not report success while the process can still be live.
4. Existing callers may ignore the return value; the Host security restart path must consume it.
5. Run the focused client tests and require green.

## Task 4 — Restart Host App Server when the policy fingerprint changes

Files:
- Modify: `src/launcher/agent/native_backend.py`
- Modify: `src/launcher/agent/interpreter_backend.py` only for a small reusable client-initialize helper if needed
- Modify: `src/tests/test_native_host_permissions.py`

Steps:
1. RED: same fingerprint -> no process restart.
2. RED: changed fingerprint -> old client stops, a new client starts/initializes, then `thread/resume` is sent to the new client with `config.default_permissions = local-ai-host`.
3. RED: unknown process fingerprint -> restart before resume.
4. RED: policy preparation/fingerprint failure -> return false and make no `thread/resume` call.
5. RED: old process stop failure -> return false and do not start/resume.
6. RED: new process start/initialize/profile preparation failure -> return false and do not resume on the old client.
7. On initial Host start, record the fingerprint of the policy assets used to launch that App Server process.
8. On resume, prepare current policy first. Reuse the process only if its recorded fingerprint exactly matches; otherwise replace the process boundary before resuming.
9. Preserve Sandbox behavior and the existing OI thread ID as the session source of truth.
10. Run focused Host backend tests and require green.

## Task 5 — Regression and branch verification

Commands:

```text
python -m compileall -q src
python -m pytest -q src/tests/test_host_permissions.py src/tests/test_runtime_assets.py src/tests/test_native_host_permissions.py <app-server-client-tests>
python -m pytest -q src/tests
```

Completion conditions for this branch:
- Host start records current policy fingerprint.
- Host resume reuses a process only when current fingerprint matches.
- Policy changes force an App Server process replacement before resume.
- Policy preparation, stop, start, initialize, or profile-loading failures fail closed.
- No legacy `workspace-write` fallback is introduced.
- No OI version/SDK/network-mode behavior changes.

## Real-machine follow-up gate

This branch cannot be called security-complete until the Windows Host E2E is run on the target machine:
1. Thread starts with folder B allowed.
2. B is changed to deny.
3. The same thread ID is resumed.
4. B read and write both fail.
5. Approval cannot override the product deny.

The E2E result is recorded separately; it is not simulated by unit tests.