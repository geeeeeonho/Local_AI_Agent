# Network and Privacy Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a canonical four-state network policy, fail-closed protected runtimes, and deterministic outbound privacy enforcement without mixing in later Open Interpreter or Docker-topology migrations.

**Architecture:** `launcher.network_policy` becomes the semantic owner of `warp | tor | direct | block`; Host and Container proxy addresses are explicit and never inferred from a boolean. `launcher.privacy_policy` becomes the deterministic outbound-query guard used by the copied `local_search` MCP runtime. Agent and AnythingLLM consume these policies and refuse protected startup when WARP/Tor cannot be proven ready.

**Tech Stack:** Python 3.11 stdlib, Docker CLI, Open Interpreter App Server, AnythingLLM container, pytest, GitHub Actions/windows-latest.

**Spec:** `src/docs/superpowers/specs/2026-09-08-network-privacy-boundary-design.md`

## Global Constraints

- Baseline is `main` commit `c0a2dbe174ead3b580781e925f472cc06ddc6268` with 228 tests reported by the commit.
- Do not change model catalog/model roles/model files/model classes/Ollama model ownership/shared `C:\LLM_Models` behavior.
- Do not combine OI version update, SDK migration, Permissions, session migration, Open WebUI retirement, or Docker hard-egress topology into this patch.
- WARP Host HTTP is `127.0.0.1:8119`; WARP Host SOCKS is `127.0.0.1:1080`.
- Tor Host HTTP is `127.0.0.1:8118`; Tor Host SOCKS is `127.0.0.1:9050`.
- Protected mode failure must not downgrade to Direct.
- Host Block must refuse startup until a real OS/network boundary exists.
- Sandbox Block remains the existing DNS-level interim guard and must be described honestly.
- Tests are written and pushed before implementation; GitHub Actions is the execution environment because the current sandbox cannot clone the private repository.

---

### Task 1: Add failing network-policy contract tests

**Files:**
- Create: `src/tests/test_network_policy_contract.py`
- Modify: `src/tests/test_sandbox_policy.py`
- Modify: `src/tests/test_agent_chat_boundary.py`

**Interfaces:**
- Produces expected API for later implementation:
  - `NetworkMode`
  - `normalize_mode(value)`
  - `display_label(value)`
  - `host_proxy_env(value)`
  - `container_proxy_env(value)`
  - `set_mode(value)`
  - `prepare_runtime(value, env_path=None, log=None)`
- Produces new Agent contract: `network_mode` canonical string instead of `tor_proxy` boolean.

- [ ] **Step 1: Create contract tests for canonical values and exact endpoints.**

Tests assert WARP/Tor Host and Container HTTP/SOCKS addresses exactly, Direct/Block have no non-empty proxy routes, and legacy `none` normalizes to Direct.

- [ ] **Step 2: Change sandbox-policy tests to call `build_sandbox_docker_command(network_mode=...)`.**

Expected contracts:

```python
warp = _command(network_mode="warp")
tor = _command(network_mode="tor")
direct = _command(network_mode="direct")
blocked = _command(network_mode="block")

assert "LOCAL_AI_NETWORK_MODE=warp" in warp
assert "http://llm_httpbridge:8118" in " ".join(warp)
assert "http://llm_tor:8118" in " ".join(tor)
assert "--dns=0.0.0.0" not in direct
assert "--dns=0.0.0.0" in blocked
```

- [ ] **Step 3: Change Agent boundary tests to require canonical `network_mode` and no `tor_proxy` symbol in the runtime path.**

- [ ] **Step 4: Push the tests-only commit and confirm GitHub Actions fails because the new module/signatures do not exist.**

Expected: red CI for the intended missing-contract failures, not syntax/collection failures unrelated to the test.

---

### Task 2: Implement canonical `network_policy.py`

**Files:**
- Create: `src/launcher/network_policy.py`
- Modify: `src/launcher/config.py`

**Interfaces:**
- Consumes existing constants from `launcher.config` lazily.
- Produces the APIs defined by Task 1.

- [ ] **Step 1: Implement `NetworkMode` and normalization.**

`warp`, `tor`, `direct`, `block` are canonical. `none` is a legacy alias for `direct`.

- [ ] **Step 2: Implement exact Host and Container env builders.**

Both return `LOCAL_AI_NETWORK_MODE`. WARP/Tor additionally return HTTP/HTTPS, ALL_PROXY, and NO_PROXY variants. Direct/Block return no non-empty proxy route.

- [ ] **Step 3: Implement `set_mode()` as the only write path for product network mode.**

It updates `os.environ["NET_MODE"]`, `os.environ["LOCAL_AI_NETWORK_MODE"]`, and compatibility `launcher.config.NET_MODE`.

- [ ] **Step 4: Implement `prepare_runtime()`.**

WARP delegates to `warp_runtime.start`; Tor delegates to `tor_runtime.start`; Direct/Block succeed without a proxy runtime. Runtime import/start exceptions return `False`.

- [ ] **Step 5: Keep old config helpers as compatibility wrappers only where existing non-Agent callers still require them.**

No new policy decisions are added to `config.py`.

- [ ] **Step 6: Run/push tests and require the new network-policy contract to pass.**

---

### Task 3: Make WARP readiness include the HTTP bridge

**Files:**
- Modify: `src/launcher/warp_runtime.py`
- Add coverage: `src/tests/test_network_policy_contract.py`

**Interfaces:**
- `warp_runtime.start(...) -> bool` means both SOCKS and the HTTP bridge needed by urllib/AnythingLLM are available.

- [ ] **Step 1: Add a failing test where WARP is already running but `_ensure_bridge()` returns `False`.**

Expected: `start()` must return `False`.

- [ ] **Step 2: Add a failing test where fresh WARP SOCKS readiness succeeds but bridge startup fails.**

Expected: `start()` must return `False`.

- [ ] **Step 3: Change `start()` to propagate bridge failure instead of warning-and-success.**

- [ ] **Step 4: Run/push tests.**

---

### Task 4: Migrate Agent to canonical mode and explicit Host env

**Files:**
- Modify: `src/launcher/agent/entry_dialog.py`
- Modify: `src/launcher/actions/agent_chat.py`
- Modify: `src/launcher/agent/sandbox_policy.py`
- Modify: `src/launcher/agent/interpreter_backend.py`
- Modify: `src/tools/evaluate_local_search_e2e.py`
- Modify tests from Task 1

**Interfaces:**
- `entry_dialog` returns `network_mode`.
- `build_sandbox_docker_command(..., network_mode: str)` consumes canonical mode.
- `AgentConfig.network_mode` contains one of the four canonical strings.

- [ ] **Step 1: Make entry UI independent of execution location.**

Rename the section from `인터넷 (샌드박스)` to `인터넷`, add explicit Direct with warning, and always call `network_policy.set_mode()` for the selected value.

- [ ] **Step 2: Replace `_tor_on`/`tor_proxy` flow in `agent_chat.py` with `network_mode`.**

No command inspection or boolean may decide WARP versus Tor.

- [ ] **Step 3: Prepare protected runtime before Agent startup.**

If `prepare_runtime("warp"|"tor")` returns `False`, show an error and return before `service.start()`.

- [ ] **Step 4: Refuse Host Block.**

Host Block exits before Open Interpreter starts with an explanation that hard Host egress enforcement is not implemented in this patch.

- [ ] **Step 5: Build Sandbox commands from `container_proxy_env()`.**

WARP/Tor receive proxy env and canonical marker; Direct receives marker only; Block receives marker plus the interim DNS suppression.

- [ ] **Step 6: Normalize Host process environment in `OpenInterpreterBackend._runtime_env()`.**

Use canonical mode to remove inherited proxy variables for Direct/Block and inject exact Host WARP/Tor values. Preserve local Ollama/SearXNG bypasses.

- [ ] **Step 7: Make labels come from `network_policy.display_label()` rather than command-string inference.**

Block wording must not claim a proven raw-IP firewall.

- [ ] **Step 8: Update the local-search E2E helper to use `network_mode` instead of `tor_proxy`.

- [ ] **Step 9: Run/push Agent and sandbox tests.**

---

### Task 5: Make AnythingLLM protected startup fail closed

**Files:**
- Modify: `src/launcher/anythingllm_runtime.py`
- Create: `src/tests/test_anythingllm_network.py`

**Interfaces:**
- AnythingLLM recognizes all four canonical modes.
- `ensure_proxy_stack()` uses the same network-policy runtime preparation.
- `start()` returns `False` before container start/reuse when WARP/Tor preparation fails.

- [ ] **Step 1: Add failing tests for `block` normalization and protected proxy-stack failure.**

Mock `_run`/runtime startup so tests perform no Docker/network I/O.

- [ ] **Step 2: Delegate mode semantics and protected runtime preparation to `network_policy`.**

Keep the AnythingLLM-specific omission of `ALL_PROXY` because Node's proxy stack expects HTTP proxy URLs.

- [ ] **Step 3: Make `start()` stop immediately when WARP/Tor preparation fails.**

Do not reuse an already-running AnythingLLM container when the newly selected protected stack cannot be prepared.

- [ ] **Step 4: Make Node bootstrap terminate protected startup when `undici.ProxyAgent` is unavailable.**

The generated JS must no longer contain the direct-fallback behavior `fetch 는 직접 나갑니다`.

- [ ] **Step 5: Ensure `build_run_cmd()` carries `LOCAL_AI_NETWORK_MODE` into the container and handles `block` as a distinct mode rather than silently mapping it to WARP.**

- [ ] **Step 6: Run/push AnythingLLM tests.**

---

### Task 6: Add deterministic outbound privacy guard and Block enforcement to MCP

**Files:**
- Create: `src/launcher/privacy_policy.py`
- Modify: `src/launcher/agent/search_mcp.py`
- Modify: `src/launcher/agent/runtime_assets.py`
- Modify: `src/tests/test_search_mcp.py`
- Modify: `src/tests/test_runtime_assets.py`

**Interfaces:**
- `blocked_outbound_reason(text: str) -> str | None`
- `search_mcp` package-first imports `launcher.privacy_policy`, then sibling `privacy_policy` for the copied runtime.

- [ ] **Step 1: Add failing privacy tests.**

Cover API/token/password patterns, known token prefixes, `file://`, Windows/UNC/local path forms, credential URLs, and localhost/private-IP literals. Assert returned errors do not echo the secret value.

- [ ] **Step 2: Add non-blocking regression tests.**

Normal queries and searches containing an email address or phone number remain allowed.

- [ ] **Step 3: Add Block-mode no-network tests.**

Monkeypatch `_read_json_url`/opener with functions that fail the test if called. With `LOCAL_AI_NETWORK_MODE=block`, both search and fetch_page must return MCP errors without invoking network code.

- [ ] **Step 4: Implement `privacy_policy.py` with high-confidence stdlib patterns only.**

Error reasons contain categories, not matched values.

- [ ] **Step 5: Enforce policy in `_search()` before URL encoding/request construction and enforce Block before both tools.**

- [ ] **Step 6: Update `runtime_assets.py` to install the privacy module beside the copied MCP script and test its managed-block paths/config.**

- [ ] **Step 7: Run/push search/runtime-assets tests.**

---

### Task 7: Regression and structure checks

**Files:**
- Modify: `src/tests/test_structure_cleanup.py` if present and appropriate
- Modify docs only if behavior text changed elsewhere

**Interfaces:**
- Enforces that removed `tor_proxy` runtime semantics do not return.

- [ ] **Step 1: Search tracked Python files for runtime uses of `tor_proxy`.**

Tests may mention the forbidden string only in an assertion that it is absent.

- [ ] **Step 2: Compile every tracked module via the existing workflow.**

Expected: `python -m compileall -q src` succeeds.

- [ ] **Step 3: Run the complete Windows test suite.**

Expected: all prior tests plus new tests pass.

- [ ] **Step 4: Review the diff for accidental model/catalog/Ollama/shared-model-store changes.**

Expected: none.

---

### Task 8: PR verification and handoff

**Files:** none unless review finds a defect.

- [ ] **Step 1: Open a PR from `patch/p0-network-privacy-boundary` to `main` with the design, threat model, test evidence, and explicit Block limitation.**

- [ ] **Step 2: Inspect GitHub Actions job status and logs.**

Do not merge on a red or missing required verification state.

- [ ] **Step 3: Review PR diff independently against the design spec.**

Confirm endpoint correctness, no protected fail-open paths, no secret echoing, and no unrelated subsystem edits.

- [ ] **Step 4: If all verification is green, mark ready and merge using the repository's normal merge method.**

- [ ] **Step 5: Record follow-up boundary.**

The next security PR is the Windows/Docker Desktop hard-egress topology spike. OI Permissions/upgrade/SDK/session work follows only after network behavior is stable.
