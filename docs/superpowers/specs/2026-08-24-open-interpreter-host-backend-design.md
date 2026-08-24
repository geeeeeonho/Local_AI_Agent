# Open Interpreter Runtime Migration — Stage 2 Host Backend Design

## Status

Approved continuation of the Open Interpreter migration after the Stage 1 AgentService boundary.

Stage 2 migrates **Host mode only** to the current standalone Rust Open Interpreter via its structured App Server stdio protocol. Sandbox mode remains on `LegacyBackend -> UnifiedAgent` until the separate Docker compatibility gate.

## Goals

1. Install a product-managed standalone Open Interpreter runtime pinned to `0.0.38`.
2. Keep installed program binaries under `llm_environment/open_interpreter/`.
3. Keep Open Interpreter runtime state, sessions, and configuration under `user_data/open_interpreter/`.
4. Launch `interpreter app-server --listen stdio://` rather than scraping the interactive TUI.
5. Connect Host mode to local Ollama through the built-in `ollama` provider.
6. Preserve the selected Local_AI_Agent profile through App Server `developerInstructions`.
7. Map streamed text, reasoning/tool progress, errors, approvals, cancellation, and thread resume into the AgentService contract.
8. Keep the old Python Open Interpreter venv and Legacy Host path as a fallback for this stage.

## Non-goals

Stage 2 does not migrate the Docker Sandbox runtime, remove the custom REPL, remove `agent_runner.py`, enable MCP, add Skills, or delete legacy sessions.

## Official protocol facts used by this design

The current Open Interpreter distribution is the Rust application. Its official standalone installer exposes `OPEN_INTERPRETER_INSTALL_DIR`, `OPEN_INTERPRETER_RELEASE`, `OPEN_INTERPRETER_NONINTERACTIVE`, and `INTERPRETER_HOME`.

The App Server stdio transport uses newline-delimited JSON messages. The client performs `initialize`, sends `initialized`, creates or resumes a thread, and sends turns with `turn/start`.

Stable thread fields used here include:

- `model`
- `modelProvider`
- `cwd`
- `approvalPolicy`
- `approvalsReviewer`
- `sandbox`
- `serviceName`
- `baseInstructions`
- `developerInstructions`

Open Interpreter/Codex v2 protocol serializes `approvalPolicy` as `on-request` and `sandbox` as `workspace-write`.

Command and file approval responses use the result payload `{ "decision": "accept" | "acceptForSession" | "decline" | "cancel" }`.

## Managed installation layout

```text
Local_AI_Agent/
├─ llm_environment/
│  └─ open_interpreter/
│     ├─ bin/                 # visible interpreter.exe installed by official installer
│     └─ home/                # installer package store / standalone releases
└─ user_data/
   └─ open_interpreter/       # runtime INTERPRETER_HOME: sessions/config/history
```

The installer runs the official Open Interpreter PowerShell installer with:

```text
OPEN_INTERPRETER_INSTALL_DIR=<llm_environment/open_interpreter/bin>
OPEN_INTERPRETER_RELEASE=0.0.38
OPEN_INTERPRETER_NONINTERACTIVE=1
INTERPRETER_HOME=<llm_environment/open_interpreter/home>
```

At runtime, Local_AI_Agent deliberately changes `INTERPRETER_HOME` to `user_data/open_interpreter`. This prevents application package files from being mixed with user session data while retaining portable state.

Automatic self-update checks are disabled for managed runs. Version changes happen through Local_AI_Agent's installer so the product remains reproducible.

## Runtime selection and fallback

Host mode selects backends in this order:

1. If the managed standalone executable exists, use `OpenInterpreterBackend`.
2. Otherwise, if the legacy Python Open Interpreter venv exists, use `LegacyBackend` with the current legacy Host command.
3. Otherwise, show the current installation error.

Sandbox mode always uses `LegacyBackend` in Stage 2.

This preserves rollback and allows an existing installation to continue working even before the next full INSTALL run.

## App Server process

The managed backend launches:

```text
<interpreter.exe>
  -c check_for_update_on_startup=false
  -c web_search="disabled"
  app-server --listen stdio://
```

The process environment includes:

```text
INTERPRETER_HOME=<user_data/open_interpreter>
CODEX_OSS_BASE_URL=http://127.0.0.1:11434/v1
NO_PROXY/no_proxy includes localhost, 127.0.0.1, ::1
```

Any existing Host proxy environment selected by Local_AI_Agent is overlaid, while local Ollama remains in `NO_PROXY`.

No `--yolo` or `danger-full-access` setting is used.

## Thread creation

After `initialize` / `initialized`, the backend requests `thread/start` with:

```json
{
  "model": "<selected Ollama model tag>",
  "modelProvider": "ollama",
  "cwd": "<absolute workspace>",
  "approvalPolicy": "on-request",
  "approvalsReviewer": "user",
  "sandbox": "workspace-write",
  "serviceName": "Local_AI_Agent",
  "developerInstructions": "<profile system message + workspace policy addendum>"
}
```

The returned `thread.id` is the session identifier exposed through AgentService.

## Turn execution

`AgentService.send(text)` maps to:

```text
turn/start
  threadId=<current thread>
  input=[{type:"text", text:<user text>}]
```

The returned `turn.id` is tracked as the active turn.

`AgentService.cancel()` maps to `turn/interrupt` for the active turn and does not terminate the App Server process.

`AgentService.stop()` terminates the managed App Server process after a best-effort active-turn interrupt.

## Resume

`AgentService.resume(thread_id)` maps to `thread/resume` using the same model/provider/cwd/approval/sandbox/developer-instruction overrides as thread creation.

Successful resume replaces the current thread id and emits `SESSION_STARTED` with metadata indicating resume.

Stage 2 provides `/resume <thread-id>` in the Agent chat command handler. A richer session picker can be migrated in a later UI stage.

## Approval handling

Server-initiated requests:

- `item/commandExecution/requestApproval`
- `item/fileChange/requestApproval`

become `AgentEventType.APPROVAL_REQUIRED` events containing:

- protocol request id
- approval kind (`command` or `file_change`)
- thread/turn/item ids
- reason
- command/cwd or file-change payload

The GUI handles each event once on the Tk main thread, displays a dangerous-action confirmation, and responds through:

```text
service.approve(request_id, "accept")
```

or:

```text
service.approve(request_id, "decline")
```

The backend serializes the server-request response as:

```json
{"id": <request-id>, "result": {"decision": "accept"}}
```

Only `accept`, `acceptForSession`, `decline`, and `cancel` are accepted by the Local_AI_Agent API in Stage 2. Complex policy-amendment decisions remain unsupported and fail closed.

## Event normalization

Stage 2 extends `AgentEventType` while preserving every Stage 1 legacy event mapping.

New event types:

- `STARTED`
- `SESSION_STARTED`
- `TEXT_DELTA`
- `REASONING`
- `TOOL_STARTED`
- `TOOL_PROGRESS`
- `TOOL_COMPLETED`
- `FILE_CHANGED`
- `APPROVAL_REQUIRED`

`AgentEvent` gains optional `request_id` and `data` fields.

Important App Server mappings:

| App Server message | Agent event |
| --- | --- |
| `item/agentMessage/delta` | `TEXT_DELTA` |
| `item/reasoning/summaryTextDelta` | `REASONING` |
| `item/started` command/file/tool | `TOOL_STARTED` |
| `item/commandExecution/outputDelta` | `TOOL_PROGRESS` |
| `item/completed` command/tool | `TOOL_COMPLETED` |
| completed fileChange item | `FILE_CHANGED` |
| approval server request | `APPROVAL_REQUIRED` |
| protocol/runtime error | `ERROR` |
| process exit | `TERMINATED` |

Unknown notifications are not fatal; they may be ignored or represented as status metadata, but malformed JSON and protocol errors must surface as `ERROR`.

## AppServerClient responsibilities

`launcher/agent/app_server_client.py` owns only transport and RPC correlation:

- subprocess lifetime
- stdin JSONL writes
- stdout JSONL parsing
- stderr capture
- monotonically increasing client request ids
- pending request queues
- raw server request/notification queue
- response to server-initiated request ids
- process termination sentinel

It does not know AgentEvent semantics, Ollama, GUI, or approval UI.

## OpenInterpreterBackend responsibilities

`launcher/agent/interpreter_backend.py` owns:

- executable discovery
- runtime environment construction
- App Server startup/handshake
- thread start/resume
- turn start/interrupt
- approval response validation
- raw App Server message to AgentEvent mapping
- current thread/turn state
- lifecycle registration

## AgentService contract changes

The common contract adds:

```python
def approve(request_id, decision: str) -> bool: ...
def cancel() -> bool: ...
def resume(session_id: str) -> bool: ...
def session_id() -> str | None: ...
```

`LegacyBackend` implements unsupported structured operations by returning `False`; it does not fake semantics.

`AgentConfig.legacy_runtime` becomes optional and `instructions: str = ""` is added. This allows future non-legacy backends to consume shared configuration without requiring a fake legacy command.

## Security

Host Open Interpreter runs with:

- `approvalPolicy = on-request`
- `approvalsReviewer = user`
- `sandbox = workspace-write`
- web search disabled at OI level
- selected workspace as cwd
- local Ollama base URL via loopback
- Local_AI_Agent's existing Host danger gate retained

No container privilege or OS sandbox relaxation is introduced.

The existing profile privacy clause remains supplementary instruction text; security does not depend on the prompt alone.

## Tests

Stage 2 adds tests for:

1. extended event compatibility
2. AgentService structured-operation delegation
3. App Server JSONL request/response correlation and server-request response payloads
4. App Server notification conversion
5. Open Interpreter launch command/environment
6. thread/start exact params
7. turn/start, cancel, approve, and resume exact RPC shapes
8. installer pinned version and managed paths
9. Host backend selection/fallback source-level boundary

Tests use fake processes/clients and do not require Docker, Ollama, or a real Open Interpreter binary.

## Gate 1 acceptance criteria

Stage 2 may proceed to Sandbox migration only after local verification confirms:

- full test suite passes
- touched modules compile
- managed `interpreter.exe --version` reports `0.0.38`
- Host App Server initializes
- Host thread starts with local Ollama
- streaming response reaches GUI
- command approval can be accepted and declined
- cancellation interrupts a turn without orphaning the process
- thread id is exposed and can resume
- shutdown leaves no Host interpreter process
- Sandbox mode still uses the existing LegacyBackend unchanged

## Rollback

The old Python Host runtime is intentionally retained. Removing the managed Open Interpreter directory or disabling its availability causes Host mode to fall back to the legacy runtime.

No legacy user session files are migrated or deleted in Stage 2.
