# Final Security Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining outbound-privacy, protected-DNS/SSRF, and Host filesystem-enforcement gaps without changing Chat/RAG or agent-loop ownership.

**Architecture:** `launcher.network_policy` remains the only network-mode semantic source. `search_mcp` delegates URL validation/resolution/connection pinning to `agent.web_safety`. Host folder policy is translated into an Open Interpreter permission profile managed inside `INTERPRETER_HOME/config.toml`; Host thread start/resume selects that profile through App Server `config.default_permissions`, while Sandbox keeps Docker as the outer boundary and OI `danger-full-access` only inside the container.

**Tech Stack:** Python 3.11 stdlib, Open Interpreter 0.0.38 App Server JSONL/stdio, Docker Desktop, SearXNG, pytest, GitHub Actions Windows.

**Spec:** User-provided `Local_AI_Agent 전환 완료 후 보안·구조 보완 지시서` (2026-09-08).

---

## Task 1 — Guard `fetch_page` privacy before all I/O

**Files:**
- Modify: `src/launcher/agent/search_mcp.py`
- Modify as needed: `src/launcher/privacy_policy.py`
- Test: `src/tests/test_search_mcp.py`

1. Add RED tests proving secret/credential/file/private inputs are rejected before `socket.getaddrinfo` or `urllib.request.build_opener`.
2. Ensure returned errors redact credentials/tokens.
3. Reorder `_fetch_page`: Block → `blocked_outbound_reason(url)` → syntax → destination → opener/request.
4. Run `python -m pytest -q src\tests\test_search_mcp.py`.

## Task 2 — Extract URL and address safety primitives

**Files:**
- Create: `src/launcher/agent/web_safety.py`
- Modify: `src/launcher/agent/search_mcp.py`
- Test: `src/tests/test_search_mcp.py`
- Test: `src/tests/test_web_safety.py`

1. Add RED tests for schemes, credentials, localhost, literal private/link-local/loopback IPv4/IPv6, and public literals.
2. Implement pure parsing/address predicates and a resolver interface.
3. Direct mode may use local `getaddrinfo`, but all resolved addresses must be global/public.
4. Route search MCP validation through this module.

## Task 3 — Protected resolver/fetch boundary for WARP and Tor

**Files:**
- Modify: `src/launcher/agent/web_safety.py`
- Modify: `src/launcher/agent/search_mcp.py`
- Test: `src/tests/test_web_safety.py`
- Test: `src/tests/test_search_mcp.py`

1. RED: patch `socket.getaddrinfo` to fail and prove WARP/Tor target validation still works through an injected protected resolver.
2. Implement protected resolution over the selected SOCKS route. Use a fixed public DoH resolver through the protected SOCKS tunnel; never resolve the target hostname locally in WARP/Tor.
3. Validate every returned target IP as public/global.
4. Pin actual SOCKS CONNECT to one validated literal IP; for HTTPS keep original hostname as TLS SNI and HTTP `Host`.
5. Revalidate every redirect through the same boundary.
6. Any resolver/proxy/redirect validation failure is fail-closed.
7. Run privacy/network targeted tests.

## Task 4 — Translate Local_AI_Agent folder policy to OI permissions

**Files:**
- Create: `src/launcher/agent/host_permissions.py`
- Test: `src/tests/test_host_permissions.py`

1. RED tests for workspace root, valid allow roots, canonical/deduped paths, deny rules, Windows normcase semantics, and valid TOML (`tomllib`).
2. Implement `HostPermissionSpec`, `build_host_permission_spec(workspace)`, and `render_host_permission_toml(spec)`.
3. Denied paths must be explicit `deny`; workspace roots receive write access; minimal baseline remains read as required by OI profile syntax.
4. Do not put proxy URLs in this profile.

## Task 5 — Manage Host permission assets without overwriting user config

**Files:**
- Modify: `src/launcher/agent/runtime_assets.py`
- Modify: `src/launcher/agent/native_backend.py`
- Test: `src/tests/test_runtime_assets.py`
- Test: `src/tests/test_host_permissions.py`

1. RED tests proving unrelated user TOML survives and only `LOCAL_AI_AGENT_HOST_PERMISSIONS` managed block is replaced.
2. Extend `prepare_host_runtime_assets` to accept workspace/folder policy and write the managed permission profile plus `default_permissions` selection safely.
3. Sandbox runtime assets must not receive the Host profile.

## Task 6 — Select OI permission profile in Host thread start/resume

**Files:**
- Modify: `src/launcher/agent/execution_policy.py`
- Modify: `src/launcher/agent/interpreter_backend.py`
- Modify as needed: `src/launcher/agent/service.py`, `native_backend.py`
- Test: `src/tests/test_execution_policy.py`
- Test: `src/tests/test_interpreter_backend.py` or nearest existing backend test

1. RED: Host params have no `sandbox` key and include `config.default_permissions=local-ai-host`; Sandbox keeps `sandbox=danger-full-access` with no Host profile.
2. Make `sandbox_mode: str | None`, add `permission_profile: str | None`.
3. Recompute/write current Host permission assets before start and before resume.
4. Resume sends current `config.default_permissions`; if current profile cannot be prepared, Host resume returns false rather than reusing unknown historical permissions.
5. Verify both same-process and new-process resume code paths by unit tests.

## Task 7 — Real-environment diagnostics

**Files:**
- Extend: `src/tools/verify_block_egress.py`
- Add if needed: `src/tools/verify_security_boundaries.py`
- Test command-building/verdict logic under `src/tests/`.

Cover:
- Block raw public IP fails.
- Block public DNS fails.
- Block host Ollama succeeds.
- WARP/Tor protected startup fails when proxy/bridge is unavailable, with no Direct fallback.
- Privacy secret search/fetch rejects before external I/O.
- Host allow/deny read/write test fixture and resume-policy scenario.

Hosted CI validates the tool logic only. Target-PC execution remains a release gate and must not be claimed without evidence.

## Task 8 — Documentation and full security regression

**Files:**
- Modify: `README.md`
- Modify: `src/docs/open-interpreter-native-tools.md`
- Modify: `src/tests/test_structure_cleanup.py`

Document only implemented/proven boundaries. Add structure guards for Host permission translator and ownership invariants.

Verification:
```powershell
python -m compileall -q src
python -m pytest -q src\tests
```
Then require a green Windows GitHub Actions run before opening the security PR.
