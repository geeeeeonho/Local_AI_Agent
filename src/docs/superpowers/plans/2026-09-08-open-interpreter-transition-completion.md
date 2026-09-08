# Open Interpreter Transition Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the remaining Local_AI_Agent transition by enforcing hard Block-mode container egress isolation, centralizing Open Interpreter execution policy, revalidating App Server/session ownership, retiring active Open WebUI remnants, decomposing the agent chat controller, and documenting the final architecture.

**Architecture:** Keep the working AnythingLLM → Ollama chat path and Open Interpreter 0.0.38 App Server automation path. Docker remains the mandatory Sandbox boundary; a dedicated `--internal` bridge becomes the Block-mode hard egress boundary. Open Interpreter owns approvals/sessions, while product code owns UI selection, folder mounts, canonical networking, and runtime lifecycle.

**Tech Stack:** Python 3.11, pytest, Tkinter launcher, Docker Desktop/CLI, Open Interpreter 0.0.38 App Server, Ollama, AnythingLLM, SearXNG.

**Spec:** `src/docs/superpowers/specs/2026-09-08-open-interpreter-transition-completion-design.md`

## Global Constraints

- Baseline is `main` commit `fe18a0e7c1e38408df1a791bf0d756506e664e78`.
- Keep `OPEN_INTERPRETER_VERSION = "0.0.38"`; 0.0.38 is the latest upstream release as of 2026-09-08.
- Do not change model catalog, model-role ladders, model files, Ollama ownership/provider semantics, or shared `C:\LLM_Models` behavior unless a transition regression proves it necessary.
- Never silently downgrade WARP/Tor/Block to Direct.
- Sandbox Docker remains the outer isolation boundary; OI stays `danger-full-access` only inside that container.
- Host OI remains `workspace-write`; approvals remain `on-request` and reviewer `user` in both modes.
- Keep direct Open Interpreter App Server stdio transport; do not add an SDK dependency without a missing protocol capability.
- Every behavior change follows RED → GREEN TDD and every phase ends with the full Windows test workflow green.

---

### Task 1: Product-managed internal Block network

**Files:**
- Modify: `src/launcher/network_policy.py`
- Test: `src/tests/test_network_policy_contract.py`

**Interfaces:**
- Produces: `block_network_name() -> str`
- Produces: `ensure_block_network(run=None, log=None) -> bool`
- Uses Docker CLI only through an injectable runner so unit tests do not require Docker.

- [ ] **Step 1: Write failing network contract tests.**

Add tests that inject a fake runner and assert:

```python
def test_block_network_is_created_as_internal_bridge(monkeypatch):
    # first inspect: missing, create succeeds, second inspect: true|bridge
    assert policy.ensure_block_network(run=fake_run) is True
    assert ["docker", "network", "create", "--driver", "bridge", "--internal", policy.block_network_name()] in calls


def test_existing_non_internal_block_network_fails_closed():
    # inspect returns false|bridge
    assert policy.ensure_block_network(run=fake_run) is False
```

Also assert `block_network_name()` defaults to `llm_block_net`.

- [ ] **Step 2: Run only the new tests and verify RED.**

Run: `python -m pytest -q src\tests\test_network_policy_contract.py`
Expected: failures because `block_network_name`/`ensure_block_network` do not exist.

- [ ] **Step 3: Implement the minimal canonical helper.**

Implementation rules:

```python
def block_network_name() -> str:
    return str(getattr(_config(), "BLOCK_NETWORK", "llm_block_net"))


def ensure_block_network(run=None, log=None) -> bool:
    # inspect with --format '{{.Internal}}|{{.Driver}}'
    # if missing: create --driver bridge --internal NAME
    # re-inspect and require exact true|bridge
    # return False on command exception, timeout, nonzero create, or unsafe properties
```

Use `subprocess.run(..., capture_output=True, text=True, timeout=...)` only in the default runner. Never recreate or mutate an existing unsafe network automatically.

- [ ] **Step 4: Run targeted and full tests.**

Run:
- `python -m pytest -q src\tests\test_network_policy_contract.py`
- `python -m pytest -q src\tests`
- `python -m compileall -q src`

Expected: zero failures.

- [ ] **Step 5: Commit.**

Commit message: `security: add managed internal block network`

---

### Task 2: Enforce the internal network for Sandbox Block mode

**Files:**
- Modify: `src/launcher/agent/sandbox_policy.py`
- Modify: `src/launcher/agent/sandbox_backend.py`
- Modify: `src/launcher/actions/agent_chat.py`
- Test: `src/tests/test_sandbox_policy.py`
- Test: `src/tests/test_agent_chat_boundary.py`

**Interfaces:**
- `build_sandbox_docker_command(..., block_internet=True, tor_proxy=False)` keeps its public signature.
- Block command includes `--network <block_network_name>`, `LOCAL_AI_NETWORK_MODE=block`, and `--dns=0.0.0.0`.
- `SandboxOpenInterpreterBackend.start(config)` fails before spawning Docker if canonical mode is Block and `ensure_block_network()` fails.

- [ ] **Step 1: Add failing Block command/startup tests.**

Tests must assert:

```python
cmd = build_sandbox_docker_command(..., block_internet=True, tor_proxy=False)
assert "--network" in cmd
assert policy.block_network_name() in cmd
assert "LOCAL_AI_NETWORK_MODE=block" in cmd
assert "--dns=0.0.0.0" in cmd
```

and that a Block backend never calls its client factory when `ensure_block_network()` returns `False`.

Add a regression test for `_select_internet_mode`: selecting Block must call the canonical `network_policy.set_mode("block")`, not merely return `False` while leaving a previous WARP/Tor selection active.

- [ ] **Step 2: Verify RED on the targeted tests.**

Run:
- `python -m pytest -q src\tests\test_sandbox_policy.py`
- `python -m pytest -q src\tests\test_agent_chat_boundary.py`

Expected: new Block topology and canonical-selection tests fail.

- [ ] **Step 3: Implement minimal Block enforcement.**

In `sandbox_policy.py`, derive the canonical current mode. For Block, append the internal network and mode marker before runtime tail; proxy modes remain unchanged. In `sandbox_backend.py`, gate `start()` before `super().start(config)` when `config.network_mode`/canonical mode resolves to Block. In `agent_chat.py`, route all three menu choices through `network_policy.set_mode(choice)`.

- [ ] **Step 4: Run full verification.**

Run `python -m compileall -q src` and `python -m pytest -q src\tests`.

- [ ] **Step 5: Commit.**

Commit message: `security: enforce hard block network for sandbox agent`

---

### Task 3: Enforce the same hard Block boundary for AnythingLLM

**Files:**
- Modify: `src/launcher/anythingllm_runtime.py`
- Modify: `src/launcher/config.py`
- Test: `src/tests/test_anythingllm_network.py`

**Interfaces:**
- `network_for_mode(mode=None) -> str` returns the internal Block network only for Block; all other modes return the existing shared network.
- AnythingLLM port publishing is loopback-only: `127.0.0.1:<HOST_PORT>:<CONTAINER_PORT>`.
- Block startup calls `ensure_block_network()` before `is_running()` and fails closed on failure.

- [ ] **Step 1: Add failing tests.**

Assert:

```python
cmd = runtime.build_run_cmd(memory="2g", cpus="1")
assert cmd[cmd.index("--network") + 1] == "llm_block_net"
assert "127.0.0.1:3001:3001" in cmd
```

when mode is Block; verify WARP still uses `runtime.NETWORK`. Add a startup test where Block network preparation fails and `is_running()` must not be called.

- [ ] **Step 2: Verify RED.**

Run: `python -m pytest -q src\tests\test_anythingllm_network.py`
Expected: Block network/loopback/fail-closed assertions fail.

- [ ] **Step 3: Implement.**

Add `BLOCK_NETWORK = "llm_block_net"` (configurable by `LOCAL_AI_BLOCK_NETWORK` through config), use canonical policy for network selection, include the selected network in `config_signature`, bind the host port to loopback, and gate Block startup before container reuse.

- [ ] **Step 4: Run targeted/full verification.**

Run targeted test, full tests, and compileall.

- [ ] **Step 5: Commit.**

Commit message: `security: isolate AnythingLLM block mode`

---

### Task 4: Add an opt-in real Docker egress diagnostic

**Files:**
- Create: `src/tools/verify_block_egress.py`
- Create: `src/tests/test_block_egress_diagnostic.py`
- Modify: `README.md`

**Interfaces:**
- `verify_block_egress.py --image <image>` exits 0 only if internal-network inspection passes, host gateway connectivity test succeeds when requested, and public egress probes fail.
- Default mode performs no package installs and uses Python in the existing sandbox image for socket probes.

- [ ] **Step 1: Write source-contract tests first.**

Tests import probe-command builders and assert they target the canonical Block network, `host.docker.internal`, and a public raw-IP TCP probe; no live Docker call runs in pytest.

- [ ] **Step 2: Verify RED.**

Run: `python -m pytest -q src\tests\test_block_egress_diagnostic.py`
Expected: module missing.

- [ ] **Step 3: Implement the CLI diagnostic.**

The script must print a three-part verdict: network internal property, host-service reachability, public raw-IP/DNS denial. It must explicitly state that a skipped host-service probe is not proof of host reachability.

- [ ] **Step 4: Test/compile.**

Run targeted/full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `test: add real Docker block egress diagnostic`

---

### Task 5: Centralize Open Interpreter execution policy

**Files:**
- Create: `src/launcher/agent/execution_policy.py`
- Modify: `src/launcher/agent/interpreter_backend.py`
- Test: `src/tests/test_interpreter_backend.py`
- Create: `src/tests/test_execution_policy.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ExecutionPolicy:
    approval_policy: str
    approvals_reviewer: str
    sandbox_mode: str


def policy_for_mode(mode: str) -> ExecutionPolicy:
    ...
```

Host returns `on-request/user/workspace-write`. Sandbox returns `on-request/user/danger-full-access`. Unknown modes raise `ValueError`.

- [ ] **Step 1: Add failing policy tests.**

Assert exact values for Host/Sandbox and rejection of an unknown mode. Add a backend test asserting `_thread_params()` receives the centralized values.

- [ ] **Step 2: Verify RED.**

Run `python -m pytest -q src\tests\test_execution_policy.py src\tests\test_interpreter_backend.py`.

- [ ] **Step 3: Implement and delegate backend values.**

Remove hard-coded approval/reviewer values from `_thread_params()`. Make `_thread_sandbox_mode()` delegate through `policy_for_mode`; Sandbox subclass may keep only its boundary-specific mode identity, not duplicate literals.

- [ ] **Step 4: Full verification.**

Run full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `refactor: centralize Open Interpreter execution policy`

---

### Task 6: Revalidate and centralize App Server protocol ownership

**Files:**
- Create: `src/launcher/agent/app_server_protocol.py`
- Modify: `src/launcher/agent/interpreter_backend.py`
- Modify: `src/launcher/agent/app_server_client.py`
- Test: `src/tests/test_interpreter_backend.py`
- Test: `src/tests/test_app_server_client.py`

**Interfaces:**
- Constants: `INITIALIZE`, `THREAD_START`, `THREAD_RESUME`, `TURN_START`, `TURN_INTERRUPT`.
- `client_info()` returns the product initialize payload.
- Existing public `AppServerClient` and `AgentService` methods stay source-compatible.

- [ ] **Step 1: Add failing protocol tests.**

Verify the backend uses the canonical method constants and that resume still sends the same model/provider/cwd/approval/sandbox/developer-instruction overrides as thread start.

- [ ] **Step 2: Verify RED.**

Run targeted backend/client tests.

- [ ] **Step 3: Implement central protocol constants and initialization payload.**

No transport rewrite. No new SDK dependency. Keep JSONL stdio behavior.

- [ ] **Step 4: Full verification.**

Run full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `refactor: centralize Open Interpreter app server protocol`

---

### Task 7: Retire executable Open WebUI remnants

**Files:**
- Modify: `src/installer/steps/python_tools.py`
- Modify: `src/installer/__init__.py`
- Modify: `src/installer/i18n.py`
- Modify: `src/launcher/actions/chat.py`
- Modify: `src/launcher/app.py`
- Modify: `src/launcher/core/docker_maint.py`
- Test: `src/tests/test_structure_cleanup.py`
- Test: relevant installer/chat tests discovered by `pytest --collect-only`

**Interfaces:**
- AnythingLLM remains the only active ChatService UI.
- Old Open WebUI container/image name patterns may remain only in a clearly named legacy-cleanup constant.

- [ ] **Step 1: Write failing structure tests.**

Assert active installer/launcher source does not expose `install_open_webui`, `open-webui.exe`, or menu text that describes Open WebUI as an active chat engine. Permit the explicit legacy cleanup constant in `docker_maint.py`.

- [ ] **Step 2: Verify RED.**

Run `python -m pytest -q src\tests\test_structure_cleanup.py`.

- [ ] **Step 3: Remove unreachable installer function and stale active copy.**

Delete the Open WebUI venv installer path only after confirming no live caller. Update active chat strings/docs to AnythingLLM. Rename cleanup patterns to make migration-only intent explicit.

- [ ] **Step 4: Full verification.**

Run full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `cleanup: retire active Open WebUI remnants`

---

### Task 8: Decompose agent chat setup and runtime construction

**Files:**
- Create: `src/launcher/agent/setup_flow.py`
- Create: `src/launcher/agent/runtime_config.py`
- Modify: `src/launcher/actions/agent_chat.py`
- Modify: `src/tools/evaluate_local_search_e2e.py`
- Test: `src/tests/test_agent_chat_boundary.py`
- Test: existing setup/model/folder policy tests

**Interfaces:**
- `setup_flow` owns profile/model/workspace/mode/network selection helpers.
- `runtime_config.build_cmd_for_mode(...)` owns the existing `_build_cmd_for_mode` behavior.
- `runtime_config.network_label(...)` owns canonical display labeling.
- `actions.agent_chat._build_cmd_for_mode` remains a forwarding compatibility wrapper until the evaluation tool is migrated in the same task.

- [ ] **Step 1: Add failing architecture tests.**

Require new modules to exist and assert `agent_chat.py` no longer defines model-selection/network-command construction internals directly.

- [ ] **Step 2: Verify RED.**

Run `python -m pytest -q src\tests\test_agent_chat_boundary.py`.

- [ ] **Step 3: Move setup/runtime helpers without behavior changes.**

Keep signatures and tests stable; avoid unrelated GUI changes.

- [ ] **Step 4: Full verification.**

Run full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `refactor: split agent chat setup and runtime config`

---

### Task 9: Extract the agent chat session controller

**Files:**
- Create: `src/launcher/agent/chat_session_controller.py`
- Modify: `src/launcher/actions/agent_chat.py`
- Test: `src/tests/test_agent_chat_boundary.py`
- Create: `src/tests/test_chat_session_controller.py`

**Interfaces:**
- Controller owns serialized service calls, slash-command dispatch, session/resume, model restart, folder-policy reload, stop/restart, and event polling hooks.
- `agent_chat.run()` remains responsible for top-level setup and creating the GUI panel.

- [ ] **Step 1: Write failing controller tests.**

Test slash command parsing as pure behavior where possible:
- `/session` reports current thread id;
- `/resume X` calls `AgentService.resume("X")`;
- `/model TAG` schedules a controlled restart;
- `/reload` is a no-op when mount signature is unchanged.

- [ ] **Step 2: Verify RED.**

Run controller and boundary tests.

- [ ] **Step 3: Extract controller incrementally.**

Move one responsibility at a time while keeping `ChatPanel` callback contracts unchanged. Do not change visible command names or Korean UI copy except stale legacy wording.

- [ ] **Step 4: Full verification.**

Run full tests and compileall.

- [ ] **Step 5: Commit.**

Commit message: `refactor: extract agent chat session controller`

---

### Task 10: Final architecture audit and documentation

**Files:**
- Modify: `README.md`
- Modify: `src/docs/open-interpreter-native-tools.md`
- Modify: `src/tests/test_structure_cleanup.py`
- Modify: `src/docs/superpowers/specs/2026-09-08-open-interpreter-transition-completion-design.md` only if implementation discovered a factual mismatch.

**Interfaces:**
- README architecture must name AnythingLLM, Open Interpreter App Server 0.0.38, Ollama, SearXNG, canonical network modes, internal Block network, and Host/Sandbox boundaries.

- [ ] **Step 1: Add final structure guards.**

Assert retired runtime files remain absent; exactly one `class DockerService` exists under active `src`; Open WebUI has no active launcher/installer entrypoint; OI version remains centralized.

- [ ] **Step 2: Run the structure test to verify any new guard fails before docs/cleanup adjustments.**

Run `python -m pytest -q src\tests\test_structure_cleanup.py`.

- [ ] **Step 3: Update documentation and any last stale comments.**

Document that hosted CI proves command/policy contracts, while `src/tools/verify_block_egress.py` is the real Docker Desktop proof path.

- [ ] **Step 4: Run the complete completion gate.**

Run:

```text
python -m compileall -q src
python -m pytest -q src\tests
```

Then compare branch against `main` and confirm no model catalog/model-role/Ollama/shared-model-store changes.

- [ ] **Step 5: Open the completion PR.**

PR title: `refactor: complete Open Interpreter project transition`

PR body must list each phase, exact full-test result, Block-mode limitation/real-Docker diagnostic status, and the deliberate decision to retain OI 0.0.38 App Server transport.
