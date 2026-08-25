# Open Interpreter Sandbox Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Open Interpreter 0.0.38 App Server inside the existing Local_AI_Agent Docker Sandbox while preserving the outer Docker security policy and legacy fallback.

**Architecture:** Keep `build_sandbox_pipe_cmd()` as the current Docker-policy source. A new `SandboxOpenInterpreterBackend` transforms only the legacy custom-REPL tail into an App Server tail, strips legacy REPL payloads, and reuses Stage 2's structured transport/events/session/approval code. The Sandbox image is rebuilt only when pinned runtime labels are missing or stale.

**Tech Stack:** Python stdlib, Docker CLI, Open Interpreter 0.0.38 standalone Linux installer, App Server stdio JSONL, existing AgentService and folder/network policy code.

**Spec:** `docs/superpowers/specs/2026-08-24-open-interpreter-sandbox-backend-design.md`

## Global Constraints

- Open Interpreter version is exactly `0.0.38`.
- Do not add `--privileged`, `CAP_SYS_ADMIN`, `seccomp=unconfined`, host PID namespace, or host network namespace.
- Host Open Interpreter remains `sandbox=workspace-write`.
- Structured Sandbox Open Interpreter uses `sandbox=danger-full-access` only because Docker remains the outer mandatory isolation boundary.
- Both structured modes use `approvalPolicy=on-request` and `approvalsReviewer=user`.
- Preserve existing workspace/allowed mounts, denied tmpfs masks, WARP/Tor/block modes, CPU/RAM limits, persistent state, PreTool, and SearXNG startup/network wiring.
- Keep `_AGENT_REPL_SRC_B64`, `_AGENT_REPL_BOOTSTRAP`, `build_sandbox_pipe_cmd`, `UnifiedAgent`, and the old Python Host venv as fallback.
- Open Interpreter built-in web search stays disabled.

---

### Task 1: Restore shared structured privacy/search instructions

**Files:**
- Create: `launcher/agent/instructions.py`
- Create: `tests/test_structured_instructions.py`
- Modify: `launcher/actions/agent_chat.py`

**Interfaces:**

```python
def build_structured_instructions(profile_message: str, *, sandbox: bool) -> str: ...
```

The output always appends the same privacy requirements as the legacy runtime: never send names, addresses, phones, email, credentials/tokens, payment identifiers, local paths/content, host/network identifiers, or location to external services. If uncertain, do not transmit.

When `sandbox=True`, append exact operational guidance:

```text
This session runs inside the Local_AI_Agent Docker sandbox.
Only mounted paths are available. Do not attempt to escape the container.
Open Interpreter built-in web search is disabled.
For current external information use PreTool.search.web_search, search_summary, or research.
Prefer the local SearXNG path and never include private local content in search queries.
```

Tests assert privacy text exists for Host and Sandbox, Sandbox contains PreTool/SearXNG guidance, and Host does not claim to be Docker-isolated.

- [ ] Write `tests/test_structured_instructions.py` before production code.
- [ ] Verify the test initially fails because module is absent.
- [ ] Implement `instructions.py` with immutable string constants plus the builder.
- [ ] Change `_service_config()` in `agent_chat.py` from raw `profile.system_message` to `build_structured_instructions(..., sandbox=not is_host)`.
- [ ] Run the focused tests.
- [ ] Commit `feat: preserve structured agent instructions`.

---

### Task 2: Make structured backend runtime hooks extensible

**Files:**
- Modify: `launcher/agent/interpreter_backend.py`
- Modify: `tests/test_interpreter_backend.py`

**Interfaces added to `OpenInterpreterBackend`:**

```python
def _runtime_available(self, config: AgentConfig) -> bool: ...
def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]: ...
def _thread_sandbox_mode(self, config: AgentConfig) -> str: ...
```

Host defaults:
- available iff managed `interpreter.exe` exists
- client spec uses current Host App Server command/env/workspace
- thread sandbox is `workspace-write`

`start()` must depend only on those hooks rather than hard-coded Host executable checks/client construction.

Tests characterize Host behavior before refactor and assert `thread/start.sandbox == "workspace-write"` after it.

- [ ] Add the Host sandbox-mode assertion/refactor-hook test first.
- [ ] Refactor without changing current Host command, environment, RPC shape, events, lifecycle, or fallback behavior.
- [ ] Run Stage 2 backend tests.
- [ ] Commit `refactor: expose structured runtime hooks`.

---

### Task 3: Add Sandbox Docker command transformation

**Files:**
- Create: `launcher/agent/sandbox_backend.py`
- Create: `tests/test_sandbox_backend.py`

**Interfaces:**

```python
SANDBOX_RUNTIME_LABEL = "local-ai-agent.runtime"
SANDBOX_RUNTIME_VALUE = "app-server"
SANDBOX_OI_LABEL = "local-ai-agent.open-interpreter-version"

def sandbox_image_supports_app_server(image: str | None = None) -> bool: ...

def transform_legacy_sandbox_command(command: tuple[str, ...] | list[str]) -> list[str]: ...

class SandboxOpenInterpreterBackend(OpenInterpreterBackend): ...
```

`transform_legacy_sandbox_command` requirements:
- require `docker run` and configured Sandbox image
- retain all tokens before image except `-e <value>` pairs whose value begins `AGENT_REPL_SRC=`, `AGENT_MODEL_LADDER=`, or `LITELLM_LOG=`
- preserve mounts/tmpfs/network/resource/proxy/no-display/PYTHONPATH flags
- before image inject environment pairs for:
  - `INTERPRETER_HOME=/home/agent/.agent_state/open_interpreter`
  - `CODEX_OSS_BASE_URL=http://host.docker.internal:11434/v1`
  - `NO_PROXY=host.docker.internal,localhost,127.0.0.1,::1,llm_searxng`
  - `no_proxy=host.docker.internal,localhost,127.0.0.1,::1,llm_searxng`
  - `SEARXNG_URL=http://llm_searxng:8080`
  - `PYTHONPATH=/home/agent/.agent_state`
- append image followed by:
  `interpreter -c check_for_update_on_startup=false -c web_search="disabled" app-server --listen stdio://`

`SandboxOpenInterpreterBackend`:
- availability uses image labels
- client spec uses transformed `legacy_runtime.command`, process cwd remains host selected workspace
- thread cwd is overridden to `/home/agent/workspace`
- thread sandbox mode returns `danger-full-access`
- stop calls parent stop then `docker stop -t 2 <name>` and `docker rm -f <name>` best-effort
- container name is parsed from `--name`.

Tests build a representative legacy Docker command containing workspace mount, allowed mount, tmpfs mask, network/proxy, CPU, memory and REPL envs, then assert exact preservation/removal/addition. Another test asserts no forbidden privilege flags are introduced. Cleanup test mocks `subprocess.run` and checks stop/rm exact commands.

- [ ] Write failing transform/backend tests.
- [ ] Implement transform helpers and subclass.
- [ ] Run focused tests.
- [ ] Commit `feat: add structured sandbox backend`.

---

### Task 4: Select structured Sandbox only for labelled image

**Files:**
- Modify: `launcher/agent/backend_factory.py`
- Modify: `tests/test_backend_factory.py`

Rules:

```text
host + managed executable -> OpenInterpreterBackend
host otherwise -> LegacyBackend
sandbox + app-server/0.0.38 image labels -> SandboxOpenInterpreterBackend
sandbox otherwise -> LegacyBackend
```

Factory detection must fail closed on Docker errors/timeouts.

- [ ] Extend factory tests first for labelled/unlabelled Sandbox outcomes.
- [ ] Implement selection.
- [ ] Run factory tests.
- [ ] Commit `feat: select structured sandbox backend`.

---

### Task 5: Build labelled standalone OI Sandbox image

**Files:**
- Modify: `installer/steps/sandbox.py`
- Create: `tests/test_sandbox_installer_runtime.py`

Dockerfile requirements:
- retain `FROM python:3.11-slim`
- retain current developer utilities and Python capability
- do not pip-install `open-interpreter`
- as `agent`, run the pinned official `rust-v0.0.38/scripts/install/install.sh`
- install standalone binary into `/home/agent/.local/bin`
- package home `/home/agent/.openinterpreter-package`
- verify with `interpreter --version`
- add labels:
  - `local-ai-agent.runtime="app-server"`
  - `local-ai-agent.open-interpreter-version="0.0.38"`

Installer behavior:
- inspect image labels when image exists
- skip only when both labels exactly match
- wrong/missing labels cause Dockerfile rewrite/build instead of early return
- preserve existing build memory/CPU limits.

Tests assert Dockerfile contains pin/labels/standalone installer and excludes `pip install --user --no-cache-dir open-interpreter`; image-inspection tests simulate correct and stale labels.

- [ ] Write installer tests before production change.
- [ ] Replace Dockerfile/install skip logic minimally.
- [ ] Run installer tests.
- [ ] Commit `feat: build managed sandbox interpreter image`.

---

### Task 6: Preserve GUI semantics and structured Sandbox session controls

**Files:**
- Modify: `tests/test_agent_chat_boundary.py` only if an additional boundary guard is needed.
- Verify: `launcher/actions/agent_chat.py`

The existing Stage 2 GUI already calls `create_backend()` for both modes, so production GUI changes should be limited to Task 1's instruction builder unless a failing boundary test proves otherwise.

Required behavior:
- Sandbox Stop still terminates backend/container because `agent_chat.py` only uses `cancel()` first for Host.
- `/model` restarts the backend using the current legacy policy command and new model metadata.
- `/reload` rebuilds policy command/container name and restarts backend.
- `/session` and `/resume` work automatically for structured Sandbox.
- current WARP/Tor/SearXNG/PreTool preparation stays before `service.start()`.

Boundary test adds forbidden-token checks on `launcher/agent/sandbox_backend.py`:

```python
for forbidden in ("--privileged", "CAP_SYS_ADMIN", "seccomp=unconfined", "--network=host"):
    assert forbidden not in sandbox_backend_source
```

- [ ] Add/adjust boundary test first.
- [ ] Make only changes required by failing tests.
- [ ] Run boundary tests.
- [ ] Commit only if production/test changes occur.

---

### Task 7: Stage 3 verification

**Files:** verification only unless failures require scoped fixes.

- [ ] Run targeted Stage 1–3 tests.
- [ ] Run full `pytest -q`.
- [ ] Compile all touched Python modules.
- [ ] Compare branch to main and verify `agent_runner.py` legacy runtime remains unchanged.
- [ ] Confirm Host code contains no `danger-full-access` path.
- [ ] Confirm Sandbox backend contains none of the forbidden Docker privilege relaxations.
- [ ] Confirm Dockerfile pin and labels are exactly 0.0.38/app-server.
- [ ] Confirm old custom REPL and old Host venv are still present as fallback.
- [ ] Inspect Windows CI evidence when available.
- [ ] Do not claim Docker runtime parity until an actual Docker run verifies mount/network/resource/approval behavior.
