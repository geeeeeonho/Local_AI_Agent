# Open Interpreter Host Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Host mode from the legacy Python Open Interpreter runtime to managed Open Interpreter 0.0.38 using App Server stdio while preserving a legacy fallback and leaving Sandbox mode unchanged.

**Architecture:** Add a focused JSONL App Server transport, a structured `OpenInterpreterBackend`, and a backend factory that selects managed Host or legacy fallback. Extend the existing service contract for approvals, cancellation, resume, session id, and instruction text. Update the installer to use the official standalone Windows installer into product-managed directories.

**Tech Stack:** Python stdlib (`subprocess`, `threading`, `queue`, `json`, `pathlib`, `urllib.request`), Open Interpreter 0.0.38 App Server JSONL protocol, Ollama local provider, Tk GUI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-open-interpreter-host-backend-design.md`

## Global Constraints

- Managed Open Interpreter version is pinned to `0.0.38`.
- Managed binary location is `llm_environment/open_interpreter/bin/interpreter.exe`.
- Installer package home is `llm_environment/open_interpreter/home`.
- Runtime `INTERPRETER_HOME` is `user_data/open_interpreter`.
- Host App Server command is `interpreter -c check_for_update_on_startup=false -c web_search="disabled" app-server --listen stdio://`.
- Host threads use `modelProvider=ollama`, `approvalPolicy=on-request`, `approvalsReviewer=user`, `sandbox=workspace-write`.
- Do not use `--yolo` or `danger-full-access`.
- Keep existing Host danger confirmation.
- Keep old Python `agent/venv` and legacy Host command as fallback.
- Sandbox mode remains `LegacyBackend -> UnifiedAgent` and its command builders are not modified.
- Do not delete or migrate legacy session files.

---

### Task 1: Extend shared event/backend/service contracts

**Files:**
- Modify: `launcher/agent/events.py`
- Modify: `launcher/agent/backend.py`
- Modify: `launcher/agent/service.py`
- Modify: `launcher/agent/legacy_backend.py`
- Modify: `tests/test_agent_events.py`
- Modify: `tests/test_agent_service_contract.py`
- Modify: `tests/test_legacy_backend.py`

**Interfaces:**
- `AgentEvent` adds `request_id: int | str | None` and `data: Mapping[str, Any] | None`.
- `AgentEventType` adds `STARTED`, `SESSION_STARTED`, `TEXT_DELTA`, `REASONING`, `TOOL_STARTED`, `TOOL_PROGRESS`, `TOOL_COMPLETED`, `FILE_CHANGED`, `APPROVAL_REQUIRED`.
- `AgentConfig.legacy_runtime` becomes optional; `instructions: str = ""` is added.
- `AgentBackend` adds `approve`, `cancel`, `resume`, `session_id`.
- `AgentService` delegates those methods.
- `LegacyBackend` returns `False` for unsupported structured methods and `None` for `session_id`.

- [ ] Write failing contract tests for the new fields and methods.
- [ ] Verify they fail before production edits.
- [ ] Implement the minimal contract extensions while preserving every existing legacy mapping.
- [ ] Verify Task 1 tests pass.
- [ ] Commit with `feat: extend agent backend protocol`.

---

### Task 2: Add App Server JSONL transport

**Files:**
- Create: `launcher/agent/app_server_client.py`
- Create: `tests/test_app_server_client.py`

**Interfaces:**

```python
class AppServerClient:
    def __init__(self, command: list[str], env: Mapping[str, str], cwd: Path): ...
    def start(self) -> bool: ...
    def request(self, method: str, params: dict, timeout: float = 10.0) -> dict: ...
    def notify(self, method: str, params: dict | None = None) -> bool: ...
    def respond(self, request_id: int | str, result: dict) -> bool: ...
    def drain_messages(self, max_n: int = 200) -> list[dict]: ...
    def stop(self, timeout: float = 3.0) -> None: ...
    def is_running(self) -> bool: ...
    def pid(self) -> int | None: ...
```

Implementation requirements:
- `subprocess.Popen` with text UTF-8 pipes and `CREATE_NO_WINDOW` on Windows.
- Dedicated stdout reader parses one JSON object per line.
- Response messages containing `id` + `result/error` are routed to per-request queues.
- Notifications and server-initiated requests (`method` plus optional `id`) go to a bounded inbound queue.
- stderr lines become synthetic inbound messages: `{"method":"local/stderr","params":{"text":...}}`.
- process exit emits `{"method":"local/terminated","params":{"returncode":...}}`.
- request ids are monotonic integers starting at 1.
- malformed stdout JSON becomes `local/protocolError` and is not silently discarded.

Tests use a fake Popen/process with StringIO/queue-backed streams and assert exact JSONL payloads for request, notify, server response, malformed data, and termination.

- [ ] Write failing transport tests.
- [ ] Implement minimal client.
- [ ] Verify tests.
- [ ] Commit with `feat: add app server stdio client`.

---

### Task 3: Add OpenInterpreterBackend

**Files:**
- Create: `launcher/agent/interpreter_backend.py`
- Create: `tests/test_interpreter_backend.py`

**Interfaces:**

```python
OI_VERSION = "0.0.38"

def managed_interpreter_exe(project_root: Path | None = None) -> Path: ...

def managed_interpreter_home(project_root: Path | None = None) -> Path: ...

class OpenInterpreterBackend:
    def __init__(self, client_factory=AppServerClient): ...
    def start(self, config: AgentConfig) -> bool: ...
    def send(self, message: str) -> bool: ...
    def approve(self, request_id, decision: str) -> bool: ...
    def cancel(self) -> bool: ...
    def resume(self, session_id: str) -> bool: ...
    def stop(self, timeout: float = 3.0) -> None: ...
    def poll_events(self, max_n: int = 200) -> list[AgentEvent]: ...
    def is_running(self) -> bool: ...
    def session_id(self) -> str | None: ...
```

Exact startup command:

```python
[
    str(exe),
    "-c", "check_for_update_on_startup=false",
    "-c", 'web_search="disabled"',
    "app-server", "--listen", "stdio://",
]
```

Runtime environment:
- copy `os.environ`
- set `INTERPRETER_HOME` to `user_data/open_interpreter`
- set `CODEX_OSS_BASE_URL=http://127.0.0.1:11434/v1`
- merge `config.legacy_runtime.env` if present to preserve Host proxy selection
- force loopback Ollama entries into `NO_PROXY` and `no_proxy`

Handshake request:

```json
{"method":"initialize","params":{"clientInfo":{"name":"local_ai_agent","title":"Local_AI_Agent","version":"1"},"capabilities":{"experimentalApi":false}}}
```

Then notification `initialized` with `{}`.

Thread start params:

```python
{
    "model": config.model,
    "modelProvider": "ollama",
    "cwd": str(config.workspace.resolve()),
    "approvalPolicy": "on-request",
    "approvalsReviewer": "user",
    "sandbox": "workspace-write",
    "serviceName": "Local_AI_Agent",
    "developerInstructions": config.instructions,
}
```

`send()` calls `turn/start` with a single text input and records `turn.id`.

`cancel()` calls `turn/interrupt` for current thread + turn.

`approve()` only accepts `accept`, `acceptForSession`, `decline`, `cancel`, then responds to the server request id with `{"decision": decision}`.

`resume()` calls `thread/resume` with the current config overrides and updates thread id from response.

Event mapping tests cover `item/agentMessage/delta`, reasoning delta, item started/completed for command and file change, command output delta, approval requests, stderr, protocol error, and termination.

- [ ] Write failing backend tests.
- [ ] Implement backend.
- [ ] Verify tests.
- [ ] Commit with `feat: add open interpreter host backend`.

---

### Task 4: Add backend selection factory

**Files:**
- Create: `launcher/agent/backend_factory.py`
- Create: `tests/test_backend_factory.py`

**Interfaces:**

```python
def create_backend(mode: str, env: Path):
    if mode == "host" and managed_interpreter_exe(...).exists():
        return OpenInterpreterBackend()
    return LegacyBackend()
```

Rules:
- Sandbox always returns `LegacyBackend` in Stage 2.
- Host returns `OpenInterpreterBackend` only when the managed standalone executable exists.
- Host without it returns `LegacyBackend`.

- [ ] Write failing selection tests using monkeypatch on executable existence/factories.
- [ ] Implement factory.
- [ ] Verify tests.
- [ ] Commit with `feat: select managed host interpreter backend`.

---

### Task 5: Route Host GUI through factory and structured operations

**Files:**
- Modify: `launcher/actions/agent_chat.py`
- Modify: `tests/test_agent_chat_boundary.py`

Requirements:
- `_run_gui_chat_unified` creates `AgentService(create_backend("host" if is_host else "sandbox", env))`.
- `_service_config()` passes `instructions=profile.system_message`; for Sandbox the legacy command remains authoritative.
- Host `/model` restart remains supported by stopping and starting a new structured thread with the updated model metadata.
- Add `/session` to print current structured session id or a legacy notice.
- Add `/resume <thread-id>` to call `service.resume()` and report success/failure.
- Stop button behavior:
  - if Host managed backend has an active turn, call `service.cancel()` first; keep App Server alive and re-enable input after interruption.
  - explicit panel teardown/restart still calls `service.stop()`.
- Poll loop renders:
  - `TEXT_DELTA` as `stdout`
  - `REASONING` as `info`
  - tool progress/status as `system`
  - `ERROR` as `error`
  - `TERMINATED` as current termination behavior.
- On `APPROVAL_REQUIRED`, call `p.confirm_dangerous()` on the Tk main thread with command/file summary. Respond `accept` on confirmation and `decline` otherwise. Do not auto-approve.
- Retain current Host danger gate before entering GUI.
- Retain all Sandbox folder policy and Docker/network preparation logic.

Boundary test asserts `create_backend` is used and direct construction of `LegacyBackend()` is absent from `agent_chat.py`.

- [ ] Write/modify failing boundary tests first.
- [ ] Patch GUI integration minimally.
- [ ] Verify boundary tests.
- [ ] Commit with `refactor: select structured host backend in gui`.

---

### Task 6: Replace Python OI installer with managed standalone installer while retaining fallback venv

**Files:**
- Modify: `installer/core/filesystem.py`
- Modify: `installer/steps/python_tools.py`
- Create: `tests/test_open_interpreter_installer.py`

Filesystem additions:

```python
"open_interpreter": env / "open_interpreter",
"open_interpreter_bin": env / "open_interpreter" / "bin",
"open_interpreter_home": env / "open_interpreter" / "home",
```

Installer behavior:
- `install_open_interpreter` first checks `open_interpreter_bin/interpreter.exe --version`.
- Treat exact `0.0.38` as installed.
- Download official `scripts/install/install.ps1` using Python `urllib.request` to a temporary file.
- Execute with Windows PowerShell using environment:
  - `OPEN_INTERPRETER_INSTALL_DIR=<.../bin>`
  - `OPEN_INTERPRETER_RELEASE=0.0.38`
  - `OPEN_INTERPRETER_NONINTERACTIVE=1`
  - `INTERPRETER_HOME=<.../home>`
- Verify installed executable with `--version`; error if version is not `0.0.38`.
- Do **not** delete `agent/venv`; if it already exists it remains a fallback.
- Do not create/install the Python OI venv for new installs.

Tests monkeypatch URL download/subprocess and assert exact environment and version pin.

- [ ] Write failing installer tests.
- [ ] Implement managed installer.
- [ ] Verify tests.
- [ ] Commit with `feat: install managed open interpreter runtime`.

---

### Task 7: Final Stage 2 verification

**Files:** verify only.

- [ ] Run targeted tests for Stage 1 + Stage 2.
- [ ] Run full `pytest -q`.
- [ ] Compile touched Python modules.
- [ ] Compare branch against main and verify `launcher/agent/agent_runner.py` and Sandbox installer/image behavior have no Stage 2 changes.
- [ ] Verify no installer code removes `agent/venv`.
- [ ] Verify no `--yolo` or `danger-full-access` exists in new Host backend code.
- [ ] Inspect current branch commit status/CI if available.
- [ ] Record any verification limitation honestly; do not claim runtime validation without actual command output.
