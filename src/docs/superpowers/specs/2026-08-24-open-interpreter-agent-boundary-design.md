# Open Interpreter Runtime Migration — Stage 1 Agent Boundary Design

## Status

Approved architecture for the first migration patch.

This specification deliberately covers only the first independently testable stage of the larger Open Interpreter migration: introducing an AgentService/AgentBackend boundary while preserving the current agent runtime and observable behavior.

The standalone Rust Open Interpreter runtime, App Server stdio integration, Host migration, Sandbox migration, permissions, sessions, AGENTS.md, Skills, MCP, and legacy removal are later gated stages and are not implemented by this patch.

## Goal

Break the direct dependency between `launcher/actions/agent_chat.py` and `launcher/agent/agent_runner.py` without changing the current Agent runtime behavior.

After this patch the active path is:

```text
GUI / agent_chat.py
        |
        v
   AgentService
        |
        v
   LegacyBackend
        |
        v
   UnifiedAgent
        |
        +-- current Sandbox custom REPL
        +-- current Host Python Open Interpreter
```

The patch is successful only if the user-visible behavior remains equivalent to the current `main` branch.

## Why this stage comes first

The current code couples several responsibilities that must be separated before a second runtime can be introduced safely:

- `launcher/actions/agent_chat.py` selects profile, model, workspace, network mode, Host/Sandbox mode, constructs commands, manages restart/reload behavior, and directly drives `UnifiedAgent`.
- `launcher/agent/agent_runner.py` owns subprocess PIPE I/O, reader/writer threads, queues, process cleanup, Docker cleanup, logging, ErrorGuard, Host/Sandbox command construction, and the custom Sandbox REPL.
- `launcher/agent/agent_lifecycle.py` is typed specifically around `UnifiedAgent` even though its real requirement is only a stoppable running object.

Introducing standalone Open Interpreter before creating a stable service seam would mix runtime replacement, protocol replacement, security changes, and GUI refactoring in the same failure domain.

## Design principles

1. No Agent intelligence changes in Stage 1.
2. No installer changes in Stage 1.
3. No Docker image changes in Stage 1.
4. No Ollama provider changes in Stage 1.
5. No removal of `_AGENT_REPL_SRC_B64`, `_AGENT_REPL_BOOTSTRAP`, or current command builders in Stage 1.
6. `agent_chat.py` must stop importing or instantiating `UnifiedAgent` directly.
7. The new service API must be usable by a future `OpenInterpreterBackend` without making the GUI understand Open Interpreter internals.
8. Existing folder policy, WARP/Tor/block networking, model rollback, session UI, logging, and cleanup behavior must remain intact.
9. Existing `user_data` and settings paths are out of scope and must not be moved or rewritten.
10. Stage 1 must be reversible by reverting its commits without data migration.

## New modules

### `launcher/agent/events.py`

Defines the normalized event object seen by AgentService consumers.

```python
from dataclasses import dataclass
from enum import Enum


class AgentEventType(str, Enum):
    TEXT = "text"
    STATUS = "status"
    WARNING = "warning"
    ERROR = "error"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    content: str
    source_level: str | None = None
```

`source_level` is intentionally retained during Stage 1 so `ChatPanel` can preserve the existing output styling while the rest of the application moves to normalized event types.

Legacy mapping:

| Current `AgentMessage.level` | `AgentEvent.type` | `source_level` |
| --- | --- | --- |
| `stdout` | `TEXT` | `stdout` |
| `stderr` | `ERROR` | `stderr` |
| `info` | `STATUS` | `info` |
| `warn` | `WARNING` | `warn` |
| `error` | `ERROR` | `error` |
| `terminated` | `TERMINATED` | `terminated` |

Unknown legacy levels map to `STATUS` and keep the original value in `source_level`; output must not be silently discarded.

### `launcher/agent/backend.py`

Defines the backend contract and Stage 1 configuration types.

Stage 1 needs a migration-only process launch description because command construction is still performed by the current GUI orchestration code. This is explicitly transitional and is isolated in one nested type so a future Open Interpreter backend never needs to consume raw legacy commands.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class LegacyRuntimeSpec:
    command: tuple[str, ...]
    env: Mapping[str, str] | None = None
    cwd: Path | None = None


@dataclass(frozen=True)
class AgentConfig:
    workspace: Path
    mode: str
    model: str
    network_mode: str
    profile_name: str
    legacy_runtime: LegacyRuntimeSpec


class AgentBackend(Protocol):
    def start(self, config: AgentConfig) -> bool: ...
    def send(self, message: str) -> bool: ...
    def stop(self, timeout: float = 3.0) -> None: ...
    def poll_events(self, max_n: int = 200) -> list["AgentEvent"]: ...
    def is_running(self) -> bool: ...
```

`AgentConfig` already contains the common fields needed by the later runtime migration. `legacy_runtime` is a compatibility payload for Stage 1 only. Later stages may make it optional and then remove it after `LegacyBackend` is retired.

No `OpenInterpreterBackend` is added in Stage 1.

### `launcher/agent/legacy_backend.py`

Adapts the current `UnifiedAgent` to the `AgentBackend` contract.

Responsibilities:

- Own exactly one `UnifiedAgent` instance.
- Translate `AgentConfig.legacy_runtime` into the existing `UnifiedAgent.start(cmd, env, cwd)` call.
- Delegate send/stop/is_running without altering semantics.
- Convert `AgentMessage` instances into `AgentEvent` instances.
- Expose no private `_proc`, `_messages`, `_writer`, or `_readers` member to the GUI.
- Keep the existing `UnifiedAgent` cleanup and lifecycle behavior active.

Stage 1 does not duplicate process/thread/container cleanup in `LegacyBackend`; `UnifiedAgent` remains the owner of those mechanisms until a later dedicated lifecycle extraction.

### `launcher/agent/service.py`

Defines the UI-facing façade.

```python
class AgentService:
    def __init__(self, backend: AgentBackend): ...
    def start(self, config: AgentConfig) -> bool: ...
    def send(self, message: str) -> bool: ...
    def stop(self, timeout: float = 3.0) -> None: ...
    def poll_events(self, max_n: int = 200) -> list[AgentEvent]: ...
    def is_running(self) -> bool: ...
```

The service owns the current `AgentConfig` and delegates runtime operations to its backend.

A repeated `start()` while the backend is already running must return `False`, preserving current `UnifiedAgent.start()` behavior.

Stage 1 does not add approval/resume APIs because the legacy runtime cannot implement them through a stable common protocol. They are added when the Open Interpreter backend is introduced, rather than adding methods that are stubs or have misleading semantics.

## Existing module changes

### `launcher/actions/agent_chat.py`

The UI orchestration remains responsible for all current selections and command manipulation in Stage 1. This intentionally avoids changing security and runtime behavior in the boundary patch.

Required changes:

- Replace direct `UnifiedAgent` construction with `AgentService(LegacyBackend())`.
- Build an `AgentConfig` immediately before each service start/restart using the already selected workspace/mode/model/network/profile values and the current command/env/cwd.
- Replace `agent.send_input(text)` with `service.send(text)`.
- Replace `agent.stop(...)` with `service.stop(...)`.
- Replace `agent.start(...)` with `service.start(...)`.
- Replace `agent.drain_messages(...)` with `service.poll_events(...)`.
- Render `AgentEvent.source_level` when present so existing `ChatPanel` styling remains unchanged.
- Treat `AgentEventType.TERMINATED` exactly as the current `LEVEL_TERMINATED` branch: append termination output and disable send.

The following behavior must remain where it currently is during Stage 1:

- Host danger confirmation.
- Workspace selection.
- Folder allow/deny/reload commands.
- Current command rebuilding for live folder-policy reload.
- Current `/model` restart behavior.
- WARP/Tor/SearXNG/Docker preparation.
- Model prewarm/rollback logic.
- System-message file handling.
- PreTool synchronization.
- Existing session UI.

These responsibilities are intentionally not moved in the first patch because moving them would create behavioral changes unrelated to introducing the service seam.

### Host process cleanup compatibility

`agent_chat.py` currently reaches into `UnifiedAgent._proc` to obtain a PID for `lifelog.register_host_process_cleanup`.

Stage 1 must remove this private-member dependency.

`LegacyBackend` will register the equivalent Host cleanup callback when it starts a config whose `mode == "host"`. It may obtain the PID internally from the wrapped `UnifiedAgent`, because the adapter is the compatibility boundary. The GUI must not access the process object.

### `launcher/agent/agent_lifecycle.py`

Only typing/generalization is allowed in Stage 1.

Replace the type-only dependency on `UnifiedAgent` with a small protocol representing the actual lifecycle requirement:

```python
class StoppableAgent(Protocol):
    def stop(self, timeout: float = 3.0) -> None: ...
```

Do not change registry ownership in Stage 1. The wrapped `UnifiedAgent` continues to register/unregister itself exactly as it does today. This avoids double registration and preserves launcher shutdown behavior.

A future OI backend can register its own stoppable runtime once `UnifiedAgent` is no longer the only process owner.

## No changes to `agent_runner.py` behavior

Stage 1 may add imports or typing compatibility only if required by tests. It must not alter:

- `_AGENT_REPL_SRC_B64`
- `_AGENT_REPL_BOOTSTRAP`
- custom Agent loop
- current Host command construction
- current Sandbox command construction
- folder mounts or tmpfs masks
- network flags
- CPU/RAM limits
- ErrorGuard
- subprocess start/stop sequence
- reader/writer threads
- queue behavior
- Docker cleanup
- logging

This is the main regression boundary of the patch.

## Error handling

The new seam must preserve current failure behavior instead of hiding errors.

- Backend start failures return `False` just as `UnifiedAgent.start()` does.
- Send while stopped returns `False`.
- Stop is idempotent.
- Unknown legacy output levels are emitted as status events instead of dropped.
- Event conversion must not raise because of an unexpected legacy level.
- `AgentService` must not catch and discard backend exceptions that represent programming errors; only runtime return semantics already provided by the backend are preserved.

## Tests

### `tests/test_agent_events.py`

Unit-test all legacy-level mappings, including an unknown level.

Acceptance:

- Every current level maps deterministically.
- Original text is unchanged.
- Original level remains available as `source_level`.

### `tests/test_agent_service_contract.py`

Use a fake backend; do not start Docker, Ollama, or a real subprocess.

Verify:

- `start(config)` delegates the same config instance.
- `send(message)` delegates unchanged text.
- `poll_events(max_n)` delegates the limit and returns backend events.
- `stop(timeout)` delegates the timeout.
- `is_running()` mirrors backend state.
- Starting an already-running backend does not create a second run.

### `tests/test_legacy_backend.py`

Mock/patch `UnifiedAgent`; no external process is started.

Verify:

- command tuple is converted to the list expected by `UnifiedAgent.start()`.
- env/cwd are passed through.
- send delegates to `send_input`.
- stop delegates once and remains safe when repeated.
- `drain_messages()` output is converted into the expected `AgentEvent` sequence.
- Host mode registers the process cleanup callback inside the adapter rather than requiring GUI access to `_proc`.

### `tests/test_agent_lifecycle.py`

Verify the registry accepts an object implementing only `stop(timeout)` and that `cleanup_all()` invokes it.

Do not require importing `UnifiedAgent` for the lifecycle test.

### `tests/test_agent_chat_boundary.py`

Perform a source-level regression guard.

Verify that `launcher/actions/agent_chat.py`:

- imports `AgentService` and `LegacyBackend`.
- does not import `UnifiedAgent`.
- does not reference `._proc` on the runtime object.
- still contains the current Host/Sandbox command-building path in Stage 1.

The purpose is to enforce the new boundary without pretending this patch has already completed later migration phases.

### Existing tests

`tests/test_structure_cleanup.py` must continue to pass unchanged. Its `user_data`/settings/path invariants are outside the migration scope.

## Stage 1 acceptance criteria

All of the following must be true:

1. `agent_chat.py` has no direct import or construction of `UnifiedAgent`.
2. GUI Agent operations pass through `AgentService`.
3. `LegacyBackend` is the only new code that knows both the service contract and `UnifiedAgent` internals.
4. Existing Sandbox command generation is unchanged.
5. Existing Host command generation is unchanged.
6. Existing folder/network/resource policies are unchanged.
7. Existing model selection and rollback behavior are unchanged.
8. Existing session UI behavior is unchanged.
9. Existing process/container cleanup remains active.
10. Existing structure tests pass.
11. New service/backend/event/lifecycle tests pass.
12. No standalone Open Interpreter installation or new runtime is enabled yet.

## Explicit non-goals

Stage 1 does not:

- install the standalone Rust Open Interpreter.
- modify `installer/steps/python_tools.py` Open Interpreter installation.
- modify the Sandbox Dockerfile.
- change Ollama provider syntax.
- introduce App Server stdio.
- introduce ACP.
- add OI approval mapping.
- add OI session resume.
- move profiles to AGENTS.md.
- create Skills.
- create MCP servers.
- delete legacy agent code.
- move or delete user data.

## Follow-up gates

After Stage 1 is merged and verified, later work is split into independent gated designs:

1. **Stage 2 — Managed standalone Open Interpreter + Host backend**
   - product-managed standalone runtime
   - version validation
   - product-specific `INTERPRETER_HOME`
   - App Server over stdio
   - Ollama provider mapping
   - approval/session/event protocol

2. **Stage 3 — Open Interpreter Sandbox spike and migration**
   - OI executable inside Docker
   - current mounts, deny masks, CPU/RAM, WARP/Tor/block policy
   - verify OI internal sandbox compatibility without weakening Docker isolation
   - versioned Sandbox image labels/rebuild

3. **Stage 4 — Functional comparison and default switch**
   - deterministic legacy-vs-OI scenarios
   - success/recovery/security/approval metrics
   - OI becomes default only after Gate criteria pass

4. **Stage 5 — Legacy removal**
   - remove custom REPL/direct Ollama loop/parsers only after real-use validation

## Rollback

Stage 1 contains no persisted-data migration and no installer/runtime replacement. Rollback is a normal code revert to the previous direct `UnifiedAgent` wiring.

No cleanup of user sessions, models, Docker images, or `user_data` is required to roll back this stage.
