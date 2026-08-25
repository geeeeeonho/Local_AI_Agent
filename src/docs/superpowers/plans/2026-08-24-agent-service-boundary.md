# Agent Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the existing GUI Agent runtime through a stable `AgentService -> LegacyBackend -> UnifiedAgent` boundary without changing current Host/Sandbox behavior.

**Architecture:** Add immutable normalized events and a backend protocol, wrap the existing `UnifiedAgent` in `LegacyBackend`, and expose it through `AgentService`. `agent_chat.py` keeps all current mode/model/network/folder orchestration in this stage, but no longer imports `UnifiedAgent` or reaches into its `_proc`. The existing command builders and custom runtime remain unchanged.

**Tech Stack:** Python 3.11+, stdlib `dataclasses`, `enum`, `typing.Protocol`, `pathlib`, existing pytest/unittest-style test suite, existing `UnifiedAgent` subprocess runtime.

**Spec:** `docs/superpowers/specs/2026-08-24-open-interpreter-agent-boundary-design.md`

## Global Constraints

- Stage 1 changes no Agent intelligence, installer behavior, Docker image, Ollama provider syntax, or persisted user data.
- Do not remove or edit the behavior of `_AGENT_REPL_SRC_B64`, `_AGENT_REPL_BOOTSTRAP`, `build_sandbox_pipe_cmd`, or `build_host_pipe_cmd`.
- Keep existing folder policy, WARP/Tor/block networking, CPU/RAM limits, model rollback, session UI, logging, and cleanup behavior intact.
- `launcher/actions/agent_chat.py` must not import or instantiate `UnifiedAgent` after this plan is complete.
- The GUI must not access `UnifiedAgent._proc` after this plan is complete.
- `LegacyBackend` is the compatibility boundary allowed to know `UnifiedAgent` internals.
- Existing `tests/test_structure_cleanup.py` must remain unchanged and pass.
- No standalone Rust Open Interpreter/App Server/ACP code is introduced in this plan.

---

## File Structure

### Create

- `launcher/agent/events.py` — normalized UI/backend event types and legacy level conversion.
- `launcher/agent/backend.py` — `LegacyRuntimeSpec`, `AgentConfig`, and `AgentBackend` protocol.
- `launcher/agent/service.py` — UI-facing runtime façade.
- `launcher/agent/legacy_backend.py` — adapter from the new backend contract to current `UnifiedAgent`.
- `tests/test_agent_events.py` — event conversion coverage.
- `tests/test_agent_service_contract.py` — service delegation/state contract.
- `tests/test_legacy_backend.py` — legacy adapter and host cleanup coverage.
- `tests/test_agent_lifecycle.py` — protocol-only lifecycle registry coverage.
- `tests/test_agent_chat_boundary.py` — source-level architectural regression guard.

### Modify

- `launcher/agent/agent_lifecycle.py` — generalize annotations from `UnifiedAgent` to a small `StoppableAgent` protocol only.
- `launcher/actions/agent_chat.py` — replace direct `UnifiedAgent` usage with `AgentService(LegacyBackend())` and normalized events.

### Must remain behaviorally unchanged

- `launcher/agent/agent_runner.py`
- `launcher/agent/folder_policy.py`
- installer modules
- Sandbox image build logic
- model selection/rollback modules
- `launcher/core/user_data.py`

---

### Task 1: Normalized Agent events

**Files:**
- Create: `launcher/agent/events.py`
- Create: `tests/test_agent_events.py`

**Interfaces:**
- Produces: `AgentEventType`, `AgentEvent`, `from_legacy_message(message) -> AgentEvent`
- Consumes: any object exposing `.level` and `.text`, including current `AgentMessage`.

- [ ] **Step 1: Write the failing event tests**

```python
from types import SimpleNamespace

from launcher.agent.events import AgentEventType, from_legacy_message


def _msg(level: str, text: str = "payload"):
    return SimpleNamespace(level=level, text=text)


def test_maps_current_legacy_levels():
    cases = {
        "stdout": AgentEventType.TEXT,
        "stderr": AgentEventType.ERROR,
        "info": AgentEventType.STATUS,
        "warn": AgentEventType.WARNING,
        "error": AgentEventType.ERROR,
        "terminated": AgentEventType.TERMINATED,
    }
    for level, expected in cases.items():
        event = from_legacy_message(_msg(level))
        assert event.type is expected
        assert event.content == "payload"
        assert event.source_level == level


def test_unknown_legacy_level_becomes_status_without_losing_level_or_text():
    event = from_legacy_message(_msg("custom-level", "keep me"))
    assert event.type is AgentEventType.STATUS
    assert event.content == "keep me"
    assert event.source_level == "custom-level"
```

- [ ] **Step 2: Run the test and verify it fails because `launcher.agent.events` does not exist**

Run:

```bash
pytest tests/test_agent_events.py -q
```

Expected: collection/import failure for `launcher.agent.events`.

- [ ] **Step 3: Implement `events.py` minimally**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


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


_LEGACY_TYPES = {
    "stdout": AgentEventType.TEXT,
    "stderr": AgentEventType.ERROR,
    "info": AgentEventType.STATUS,
    "warn": AgentEventType.WARNING,
    "error": AgentEventType.ERROR,
    "terminated": AgentEventType.TERMINATED,
}


def from_legacy_message(message: Any) -> AgentEvent:
    level = str(getattr(message, "level", ""))
    text = str(getattr(message, "text", ""))
    return AgentEvent(
        type=_LEGACY_TYPES.get(level, AgentEventType.STATUS),
        content=text,
        source_level=level,
    )
```

- [ ] **Step 4: Run event tests**

```bash
pytest tests/test_agent_events.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/agent/events.py tests/test_agent_events.py
git commit -m "feat: add normalized agent events"
```

---

### Task 2: Backend contract and service façade

**Files:**
- Create: `launcher/agent/backend.py`
- Create: `launcher/agent/service.py`
- Create: `tests/test_agent_service_contract.py`

**Interfaces:**
- Consumes: `AgentEvent` from Task 1.
- Produces:
  - `LegacyRuntimeSpec(command: tuple[str, ...], env: Mapping[str, str] | None = None, cwd: Path | None = None)`
  - `AgentConfig(workspace: Path, mode: str, model: str, network_mode: str, profile_name: str, legacy_runtime: LegacyRuntimeSpec)`
  - `AgentBackend` protocol
  - `AgentService(backend)` with `start/send/stop/poll_events/is_running/current_config`

- [ ] **Step 1: Write service contract tests with a fake backend**

```python
from pathlib import Path

from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEvent, AgentEventType
from launcher.agent.service import AgentService


class FakeBackend:
    def __init__(self):
        self.running = False
        self.started = []
        self.sent = []
        self.stops = []
        self.poll_limits = []
        self.events = [AgentEvent(AgentEventType.STATUS, "ready", "info")]

    def start(self, config):
        if self.running:
            return False
        self.started.append(config)
        self.running = True
        return True

    def send(self, message):
        self.sent.append(message)
        return self.running

    def stop(self, timeout=3.0):
        self.stops.append(timeout)
        self.running = False

    def poll_events(self, max_n=200):
        self.poll_limits.append(max_n)
        return list(self.events)

    def is_running(self):
        return self.running


def _config():
    return AgentConfig(
        workspace=Path("workspace"),
        mode="sandbox",
        model="model:tag",
        network_mode="block",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(command=("python", "-V")),
    )


def test_service_delegates_and_keeps_current_config():
    backend = FakeBackend()
    service = AgentService(backend)
    config = _config()

    assert service.start(config) is True
    assert backend.started == [config]
    assert service.current_config is config
    assert service.send("hello") is True
    assert backend.sent == ["hello"]
    assert service.poll_events(17) == backend.events
    assert backend.poll_limits == [17]
    assert service.is_running() is True
    service.stop(timeout=1.5)
    assert backend.stops == [1.5]
    assert service.is_running() is False


def test_service_rejects_second_start_while_running():
    backend = FakeBackend()
    service = AgentService(backend)
    first = _config()
    second = _config()

    assert service.start(first) is True
    assert service.start(second) is False
    assert backend.started == [first]
    assert service.current_config is first
```

- [ ] **Step 2: Run and verify import failure**

```bash
pytest tests/test_agent_service_contract.py -q
```

Expected: FAIL because backend/service modules do not exist.

- [ ] **Step 3: Implement `backend.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .events import AgentEvent


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
    def poll_events(self, max_n: int = 200) -> list[AgentEvent]: ...
    def is_running(self) -> bool: ...
```

- [ ] **Step 4: Implement `service.py`**

```python
from __future__ import annotations

from .backend import AgentBackend, AgentConfig
from .events import AgentEvent


class AgentService:
    def __init__(self, backend: AgentBackend):
        self._backend = backend
        self._current_config: AgentConfig | None = None

    @property
    def current_config(self) -> AgentConfig | None:
        return self._current_config

    def start(self, config: AgentConfig) -> bool:
        if self._backend.is_running():
            return False
        started = self._backend.start(config)
        if started:
            self._current_config = config
        return started

    def send(self, message: str) -> bool:
        return self._backend.send(message)

    def stop(self, timeout: float = 3.0) -> None:
        self._backend.stop(timeout=timeout)

    def poll_events(self, max_n: int = 200) -> list[AgentEvent]:
        return self._backend.poll_events(max_n=max_n)

    def is_running(self) -> bool:
        return self._backend.is_running()
```

- [ ] **Step 5: Run Task 1-2 tests**

```bash
pytest tests/test_agent_events.py tests/test_agent_service_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add launcher/agent/backend.py launcher/agent/service.py tests/test_agent_service_contract.py
git commit -m "feat: add agent backend service contract"
```

---

### Task 3: LegacyBackend adapter and Host cleanup ownership

**Files:**
- Create: `launcher/agent/legacy_backend.py`
- Create: `tests/test_legacy_backend.py`

**Interfaces:**
- Consumes: `AgentConfig`, `LegacyRuntimeSpec`, `AgentEvent`, `UnifiedAgent`.
- Produces: `LegacyBackend` implementing `AgentBackend`.
- Host cleanup remains `lifelog.register_host_process_cleanup(get_pid_fn)`, but GUI no longer owns the callback.

**Ruling:** `LegacyBackend.stop()` remains a transparent adapter and delegates every explicit stop call to `UnifiedAgent.stop()`. Idempotence remains owned by `UnifiedAgent`; the adapter must not keep a second lifecycle state machine.

- [ ] **Step 1: Write adapter tests using a fake UnifiedAgent factory**

```python
from pathlib import Path
from types import SimpleNamespace

from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEventType
from launcher.agent.legacy_backend import LegacyBackend


class FakeUnifiedAgent:
    def __init__(self):
        self.running = False
        self.starts = []
        self.inputs = []
        self.stops = []
        self._proc = SimpleNamespace(pid=4321)
        self.messages = []

    def start(self, cmd, env=None, cwd=None):
        self.starts.append((cmd, env, cwd))
        self.running = True
        return True

    def send_input(self, message):
        self.inputs.append(message)
        return self.running

    def stop(self, timeout=3.0):
        self.stops.append(timeout)
        self.running = False

    def drain_messages(self, max_n=200):
        return list(self.messages[:max_n])

    def is_running(self):
        return self.running


def _config(mode="sandbox"):
    return AgentConfig(
        workspace=Path("workspace"),
        mode=mode,
        model="model:tag",
        network_mode="block",
        profile_name="coding",
        legacy_runtime=LegacyRuntimeSpec(
            command=("docker", "run", "--rm"),
            env={"X": "1"},
            cwd=Path("cwd"),
        ),
    )


def test_legacy_backend_preserves_runtime_arguments_and_delegation():
    agent = FakeUnifiedAgent()
    backend = LegacyBackend(agent_factory=lambda: agent)

    assert backend.start(_config()) is True
    assert agent.starts == [(["docker", "run", "--rm"], {"X": "1"}, Path("cwd"))]
    assert backend.send("hello") is True
    assert agent.inputs == ["hello"]
    assert backend.is_running() is True
    backend.stop(timeout=2.0)
    backend.stop(timeout=2.0)
    assert agent.stops == [2.0, 2.0]


def test_legacy_backend_converts_messages():
    agent = FakeUnifiedAgent()
    agent.messages = [
        SimpleNamespace(level="stdout", text="answer"),
        SimpleNamespace(level="terminated", text="done"),
    ]
    backend = LegacyBackend(agent_factory=lambda: agent)
    events = backend.poll_events(10)
    assert [e.type for e in events] == [AgentEventType.TEXT, AgentEventType.TERMINATED]
    assert [e.content for e in events] == ["answer", "done"]


def test_host_cleanup_callback_is_registered_by_adapter(monkeypatch):
    agent = FakeUnifiedAgent()
    callbacks = []

    import launcher.core.lifelog as lifelog
    monkeypatch.setattr(lifelog, "register_host_process_cleanup", callbacks.append)

    backend = LegacyBackend(agent_factory=lambda: agent)
    assert backend.start(_config(mode="host")) is True
    assert len(callbacks) == 1
    assert callbacks[0]() == 4321
```

- [ ] **Step 2: Run and verify import failure**

```bash
pytest tests/test_legacy_backend.py -q
```

Expected: FAIL because `legacy_backend.py` does not exist.

- [ ] **Step 3: Implement `LegacyBackend`**

```python
from __future__ import annotations

from collections.abc import Callable

from .backend import AgentConfig
from .events import AgentEvent, from_legacy_message


class LegacyBackend:
    def __init__(self, agent_factory: Callable[[], object] | None = None):
        if agent_factory is None:
            from .agent_runner import UnifiedAgent
            agent_factory = UnifiedAgent
        self._agent = agent_factory()
        self._host_cleanup_registered = False

    def start(self, config: AgentConfig) -> bool:
        runtime = config.legacy_runtime
        started = self._agent.start(
            list(runtime.command),
            env=runtime.env,
            cwd=runtime.cwd,
        )
        if started and config.mode == "host" and not self._host_cleanup_registered:
            self._register_host_cleanup()
        return started

    def _register_host_cleanup(self) -> None:
        from launcher.core import lifelog

        def _get_pid():
            try:
                proc = getattr(self._agent, "_proc", None)
                return proc.pid if proc else None
            except Exception:
                return None

        lifelog.register_host_process_cleanup(_get_pid)
        self._host_cleanup_registered = True

    def send(self, message: str) -> bool:
        return self._agent.send_input(message)

    def stop(self, timeout: float = 3.0) -> None:
        self._agent.stop(timeout=timeout)

    def poll_events(self, max_n: int = 200) -> list[AgentEvent]:
        return [from_legacy_message(msg) for msg in self._agent.drain_messages(max_n=max_n)]

    def is_running(self) -> bool:
        return self._agent.is_running()
```

- [ ] **Step 4: Run adapter tests and earlier unit tests**

```bash
pytest tests/test_agent_events.py tests/test_agent_service_contract.py tests/test_legacy_backend.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/agent/legacy_backend.py tests/test_legacy_backend.py
git commit -m "feat: adapt legacy unified agent backend"
```

---

### Task 4: Generalize lifecycle typing without changing registry behavior

**Files:**
- Modify: `launcher/agent/agent_lifecycle.py:1-55`
- Create: `tests/test_agent_lifecycle.py`

**Interfaces:**
- Produces: `StoppableAgent` protocol used only for typing.
- Keeps runtime behavior: `WeakSet`, `RLock`, `register`, `unregister`, `count_active`, `cleanup_all`.

- [ ] **Step 1: Write protocol-only lifecycle regression test**

```python
from launcher.agent import agent_lifecycle


class Stoppable:
    def __init__(self):
        self.timeouts = []

    def stop(self, timeout=3.0):
        self.timeouts.append(timeout)


def test_lifecycle_registry_does_not_require_unified_agent():
    before = agent_lifecycle.count_active()
    item = Stoppable()
    agent_lifecycle.register(item)
    try:
        assert agent_lifecycle.count_active() == before + 1
        assert agent_lifecycle.cleanup_all(timeout=1.25) >= 1
        assert item.timeouts == [1.25]
    finally:
        agent_lifecycle.unregister(item)
```

- [ ] **Step 2: Run lifecycle test against current code**

```bash
pytest tests/test_agent_lifecycle.py -q
```

Expected: runtime behavior may already pass, which is acceptable; this is a characterization test protecting the generalization.

- [ ] **Step 3: Replace `TYPE_CHECKING` UnifiedAgent dependency with protocol typing**

Use:

```python
from typing import Protocol


class StoppableAgent(Protocol):
    def stop(self, timeout: float = 3.0) -> None: ...


_active: "weakref.WeakSet[StoppableAgent]" = weakref.WeakSet()


def register(agent: StoppableAgent) -> None: ...
def unregister(agent: StoppableAgent) -> None: ...
```

Keep all function bodies otherwise unchanged.

- [ ] **Step 4: Run lifecycle and structure tests**

```bash
pytest tests/test_agent_lifecycle.py tests/test_structure_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/agent/agent_lifecycle.py tests/test_agent_lifecycle.py
git commit -m "refactor: generalize agent lifecycle contract"
```

---

### Task 5: Route `agent_chat.py` through AgentService

**Files:**
- Modify: `launcher/actions/agent_chat.py` around `_run_gui_chat_unified`, callbacks, restart/reload start sites, initial start site, and poll loop.
- Create: `tests/test_agent_chat_boundary.py`

**Interfaces:**
- Consumes: `AgentService`, `LegacyBackend`, `AgentConfig`, `LegacyRuntimeSpec`, `AgentEventType`.
- Produces: the same GUI behavior, with runtime calls routed through the service.

**Ruling:** Stage 1 deliberately keeps `_build_cmd_for_mode()` and live command mutation/rebuild logic in `agent_chat.py`. Moving command construction into the backend is deferred because it would change the security/runtime boundary in the same patch.

- [ ] **Step 1: Add source-level boundary test before modifying `agent_chat.py`**

```python
from pathlib import Path


def test_agent_chat_uses_service_boundary_without_unified_agent_private_access():
    source = Path("launcher/actions/agent_chat.py").read_text(encoding="utf-8")

    assert "AgentService" in source
    assert "LegacyBackend" in source
    assert "UnifiedAgent" not in source
    assert "agent._proc" not in source
    assert "build_sandbox_pipe_cmd" in source
    assert "build_host_pipe_cmd" in source
```

- [ ] **Step 2: Run and verify boundary test fails on direct `UnifiedAgent` usage**

```bash
pytest tests/test_agent_chat_boundary.py -q
```

Expected: FAIL because current source imports/constructs `UnifiedAgent` and accesses `agent._proc`.

- [ ] **Step 3: Replace direct runtime construction**

At the start of `_run_gui_chat_unified`, replace:

```python
from launcher.agent.agent_runner import UnifiedAgent
from launcher.agent.agent_runner import LEVEL_TERMINATED
...
agent = UnifiedAgent()
```

with:

```python
from launcher.agent.backend import AgentConfig, LegacyRuntimeSpec
from launcher.agent.events import AgentEventType
from launcher.agent.legacy_backend import LegacyBackend
from launcher.agent.service import AgentService
...
service = AgentService(LegacyBackend())
```

Delete the GUI-owned Host cleanup block that reaches into `agent._proc`; Task 3 now owns that compatibility callback.

- [ ] **Step 4: Add one local config builder inside `_run_gui_chat_unified`**

Use the already available function arguments/closures and current command list:

```python
def _service_config(runtime_cmd, runtime_env=None, runtime_cwd=None):
    return AgentConfig(
        workspace=workspace,
        mode="host" if is_host else "sandbox",
        model=_current_model_tag(runtime_cmd),
        network_mode=_net_mode_label(runtime_cmd),
        profile_name=str(getattr(profile, "name", "agent")),
        legacy_runtime=LegacyRuntimeSpec(
            command=tuple(str(part) for part in runtime_cmd),
            env=runtime_env,
            cwd=runtime_cwd,
        ),
    )
```

Add a focused helper near it for extracting the model tag without changing commands:

```python
def _current_model_tag(runtime_cmd):
    try:
        idx = runtime_cmd.index("--model")
        value = str(runtime_cmd[idx + 1])
        return value[len("ollama/"):] if value.startswith("ollama/") else value
    except (ValueError, IndexError):
        return ""
```

The value is metadata only in Stage 1; the actual legacy command remains the source of runtime behavior.

- [ ] **Step 5: Replace send/stop/restart/reload calls**

Perform exact semantic substitutions:

```python
# user input
ok = service.send(text)

# stop
service.stop(timeout=2.0)

# restart/reload
service.stop(timeout=2.0)
service.start(_service_config(_cmd_holder[0], runtime_env=_renv))
```

For the initial launch, preserve the existing Host Tor environment logic and pass the same env to the service config instead of directly to `UnifiedAgent.start()`.

Every current `agent.start(cmd...)` site must become `service.start(_service_config(...))`; do not change when those sites execute.

- [ ] **Step 6: Replace polling conversion/rendering**

Replace direct legacy message polling:

```python
msgs = agent.drain_messages(max_n=100)
for m in msgs:
    if m.level == LEVEL_TERMINATED:
        ...
```

with:

```python
events = service.poll_events(max_n=100)
for event in events:
    level = event.source_level or event.type.value
    if event.type is AgentEventType.TERMINATED:
        panel.append_message("terminated", event.content)
        panel.disable_send()
    else:
        panel.append_message(level, event.content)
```

This preserves current ChatPanel level styling for legacy events while establishing the normalized event boundary.

- [ ] **Step 7: Replace any remaining runtime-object references**

Search:

```bash
grep -n "UnifiedAgent\|agent\._proc\|agent\.send_input\|agent\.drain_messages\|agent\.start\|agent\.stop" launcher/actions/agent_chat.py
```

Expected after migration: no runtime-object hits. Mentions of the natural-language word "agent" unrelated to the runtime object are allowed.

- [ ] **Step 8: Run boundary and unit tests**

```bash
pytest \
  tests/test_agent_chat_boundary.py \
  tests/test_agent_events.py \
  tests/test_agent_service_contract.py \
  tests/test_legacy_backend.py \
  tests/test_agent_lifecycle.py \
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add launcher/actions/agent_chat.py tests/test_agent_chat_boundary.py
git commit -m "refactor: route gui agent through service boundary"
```

---

### Task 6: Stage 1 regression verification

**Files:**
- Verify only; no production change unless a failing test exposes a Stage 1 regression.

**Interfaces:**
- Verifies the complete Stage 1 acceptance criteria.

- [ ] **Step 1: Run all tests**

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Compile touched Python modules**

```bash
python -m py_compile \
  launcher/agent/events.py \
  launcher/agent/backend.py \
  launcher/agent/service.py \
  launcher/agent/legacy_backend.py \
  launcher/agent/agent_lifecycle.py \
  launcher/actions/agent_chat.py
```

Expected: exit code 0.

- [ ] **Step 3: Confirm `agent_runner.py` was not modified**

```bash
git diff main...HEAD -- launcher/agent/agent_runner.py
```

Expected: empty diff.

- [ ] **Step 4: Inspect all changed files**

```bash
git diff --check
git status --short
git diff main...HEAD --stat
```

Expected:
- `git diff --check`: no output.
- Only planned Stage 1 code/tests/docs are changed.
- No `user_data`, installer, Sandbox image, model, or settings files are modified.

- [ ] **Step 5: Verify architecture guard explicitly**

```bash
python - <<'PY'
from pathlib import Path
p = Path("launcher/actions/agent_chat.py")
s = p.read_text(encoding="utf-8")
assert "UnifiedAgent" not in s
assert "agent._proc" not in s
assert "AgentService" in s
assert "LegacyBackend" in s
print("agent service boundary: OK")
PY
```

Expected: `agent service boundary: OK`.

- [ ] **Step 6: Commit verification-only fixes if needed**

If and only if Task 6 uncovered a Stage 1 defect and a fix was required:

```bash
git add <only-the-files-fixed-for-the-regression>
git commit -m "fix: close agent boundary regressions"
```

If no fix was required, do not create an empty commit.
