# Open Interpreter Native Tools Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the PreTool agent surface and make Open Interpreter the sole agent runtime/tool orchestrator while preserving Local_AI_Agent's private SearXNG/WARP/Tor search path through an explicit MCP search server.

**Architecture:** Open Interpreter remains the host/sandbox runtime and Ollama remains the model provider. A small stdio MCP server exposes `search` and `fetch_page`; runtime assets write an Open Interpreter `config.toml` under each managed `INTERPRETER_HOME`. Legacy PreTool builtins injection and prompt mandates are removed, and backend selection no longer falls back to the custom legacy agent loop.

**Tech Stack:** Python 3.11 stdlib, Open Interpreter 0.0.38 App Server, MCP stdio JSON-RPC, SearXNG, Docker, Ollama, pytest.

**Spec:** Approved direction from the current project conversation; follows the existing Open Interpreter runtime migration specs under `docs/superpowers/specs/`.

## Global Constraints

- Keep Open Interpreter pinned to `0.0.38` in this patch.
- Keep Open Interpreter built-in web search disabled because the local Ollama provider does not implement Open Interpreter's provider `alpha/search` endpoint.
- Preserve SearXNG plus WARP/Tor/block networking.
- Do not send local/private content to external search queries.
- Host mode keeps `workspace-write` plus `on-request` approvals.
- Docker remains the outer security boundary for Sandbox mode.
- Remove active PreTool injection/mandates and do not introduce a replacement global Python builtins layer.

---

### Task 1: Define OI-only behavior with failing tests

**Files:**
- Modify: `tests/test_structured_instructions.py`
- Modify: `tests/test_backend_factory.py`
- Create: `tests/test_search_mcp.py`
- Create: `tests/test_runtime_assets.py`

**Interfaces:**
- Consumes: existing `build_structured_instructions()` and `create_backend()`.
- Produces: required behavior for `launcher.agent.search_mcp` and `launcher.agent.runtime_assets`.

- [ ] **Step 1: Write failing tests** asserting no PreTool wording, MCP search guidance, no legacy backend fallback, MCP protocol behavior, and generated OI config.
- [ ] **Step 2: Run CI/pytest and confirm failures are caused by missing migration code.**

### Task 2: Add the Local Search MCP server

**Files:**
- Create: `launcher/agent/search_mcp.py`

**Interfaces:**
- Produces: `handle_request(message: dict) -> dict | None`, tools `search` and `fetch_page`, and `main()` stdio loop.

- [ ] **Step 1: Implement JSON-RPC initialize/ping/tools-list/tools-call handling using stdlib only.**
- [ ] **Step 2: Implement SearXNG JSON search using `SEARXNG_URL`.**
- [ ] **Step 3: Implement bounded HTML text fetch for explicit URLs.**
- [ ] **Step 4: Run focused tests.**

### Task 3: Configure managed OI runtimes to load the MCP server

**Files:**
- Create: `launcher/agent/runtime_assets.py`
- Modify: `launcher/agent/interpreter_backend.py`
- Modify: `launcher/agent/sandbox_backend.py`

**Interfaces:**
- Produces: `prepare_host_runtime_assets()` and `prepare_sandbox_runtime_assets()`.

- [ ] **Step 1: Generate managed `config.toml` with `[mcp_servers.local_search]`.**
- [ ] **Step 2: Copy the MCP server into managed user-data runtime state.**
- [ ] **Step 3: Preserve built-in `web_search="disabled"`; add `SEARXNG_URL` to host runtime env.**
- [ ] **Step 4: Prepare assets before App Server startup.**
- [ ] **Step 5: Run focused backend/config tests.**

### Task 4: Remove PreTool behavior and legacy fallback

**Files:**
- Modify: `launcher/agent/instructions.py`
- Modify: `launcher/agent/profiles.py`
- Modify: `launcher/agent/backend_factory.py`
- Modify: `launcher/actions/agent_chat.py`
- Modify: `launcher/config.py`
- Delete: `PreTool/*`

**Interfaces:**
- Open Interpreter native shell/file tools remain primary.
- Search is exposed only through MCP.

- [ ] **Step 1: Replace PreTool search mandates with concise MCP/native-tool guidance.**
- [ ] **Step 2: Remove PreTool sync/PYTHONPATH injection from active GUI startup.**
- [ ] **Step 3: Make backend factory always return managed OI backends; availability errors are surfaced by those backends instead of silently switching runtimes.**
- [ ] **Step 4: Remove obsolete PreTool environment/config helpers.**
- [ ] **Step 5: Delete the `PreTool` package.**
- [ ] **Step 6: Run regression tests.**

### Task 5: Documentation and complete verification

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `README.md`

- [ ] **Step 1: Compile new runtime/MCP modules in CI.**
- [ ] **Step 2: Document that general web search is SearXNG MCP, not Playwright and not a search LLM; browser automation is a separate optional capability.**
- [ ] **Step 3: Run the complete pytest suite in GitHub Actions.**
- [ ] **Step 4: Review the branch diff for surviving active `PreTool` imports/references.**
- [ ] **Step 5: Open a PR only after verification evidence is available.**
