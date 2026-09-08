# Open Interpreter Native Tools / Web Search Architecture

## Current agent boundary

Local_AI_Agent uses Open Interpreter 0.0.38 as the automation runtime and Ollama as the local model provider. The active boundary is:

```text
User
  -> Local_AI_Agent GUI
  -> RuntimeCoordinator
  -> AgentService
  -> Open Interpreter App Server
       -> local Ollama model
       -> native command/file execution
       -> approvals
       -> Open Interpreter thread/session IDs
       -> MCP tools
```

Open Interpreter owns the agent loop, command/file execution, approval protocol and thread lifecycle. Local_AI_Agent owns product setup, Host folder policy, Docker isolation, network posture, model selection and UI lifecycle.

The App Server transport intentionally remains JSONL over stdio. The transition did not replace a working App Server boundary with another SDK layer merely for abstraction. App Server method names and initialize payload ownership are centralized in `launcher/agent/app_server_protocol.py` so protocol drift is isolated to one module.

## Execution and approval policy

Open Interpreter execution policy is centralized in `launcher/agent/execution_policy.py`.

- **Host:** `approval_policy="on-request"`, reviewer `user`, and `config.default_permissions="local-ai-host"`. The Host thread does not use the legacy `workspace-write` sandbox setting. `launcher/agent/host_permissions.py` translates the current product folder policy into the `local-ai-host` profile: the active workspace and valid allowed roots are writable, explicit denied paths are denied, and the remaining minimal filesystem baseline is read-only.
- **Sandbox:** `approval_policy="on-request"`, reviewer `user`, and inner Open Interpreter sandbox mode `danger-full-access` because Docker remains the outer security boundary.

The Sandbox setting does **not** remove Docker isolation. Workspace mounts, denied-path masks, network selection and container resource limits remain outside Open Interpreter.

Host permission state is process-bound. The Host backend fingerprints the effective workspace/allow/deny/profile-version policy loaded into the App Server process. Resuming a thread reuses the process only when the current fingerprint matches. A changed or unknown fingerprint forces App Server replacement before the same Open Interpreter thread ID is resumed. Policy preparation, process termination, replacement startup or initialization failures are fail-closed; a stale process that cannot be verified as stopped is quarantined from product-side send/approve/cancel/resume paths.

Live UI/service operations such as `/session`, `/resume <thread-id>`, `/model`, `/reload`, stop/restart, approval responses and event routing are owned by `launcher/agent/chat_session_controller.py`. Stateful service/network/runtime lifecycle is owned by `launcher/agent/runtime_coordinator.py`. The GUI no longer scans legacy `session_*.json` files or converts list indexes into fake session IDs; resume uses the native Open Interpreter thread ID.

## Why PreTool was removed

The old `PreTool` package duplicated capabilities already supplied by the Open Interpreter runtime and injected functions into Python `builtins` through `sitecustomize.py`. Agent prompts also forced those functions by name. That created two competing tool systems.

The active design uses:

- Open Interpreter native execution for files, shell commands, code and verification.
- MCP for capabilities that are genuinely external to the runtime.
- Local_AI_Agent boundaries for Docker, workspace mounts, approvals, network posture and SearXNG.

No custom global Python tool injection is required.

## Web search: not Playwright

Open Interpreter 0.0.38 has a built-in provider web-search extension, but the implementation investigated for this project uses an HTTP search client/provider endpoint rather than Playwright browser automation.

That distinction matters here:

- the model provider is local Ollama through an OpenAI-compatible endpoint;
- Ollama does not supply Open Interpreter's provider-side search endpoint;
- enabling the provider search extension therefore does not create a usable local search engine by itself.

Local_AI_Agent consequently keeps Open Interpreter provider web search disabled and exposes the existing private search path as MCP instead.

## Local search path

```text
Local model
  -> Open Interpreter App Server
  -> local_search MCP
       -> search(query)
       -> fetch_page(url)
  -> SearXNG
  -> Direct / WARP / Tor according to canonical network policy
  -> public web
```

`search` calls the local SearXNG JSON endpoint. `fetch_page` retrieves readable text from an explicit public HTTP/HTTPS URL and rejects local/private network targets.

For `fetch_page`, validation and connection are coupled:

- **Direct:** the local resolver returns candidate addresses, every address must be public, and the request socket connects to the exact validated literal IP. HTTPS still uses the normalized hostname for TLS SNI and the HTTP `Host` header. Redirects are handled by the application and are privacy-checked, normalized, resolved and validated again before the next connection.
- **WARP/Tor:** target DNS resolution stays inside the protected route, the validated public IP is pinned to the proxy connection, and redirects are fully revalidated.

Unicode/IDN URLs are normalized before network I/O: hostnames use IDNA A-labels, Unicode path/query data is UTF-8 percent-encoded without double-encoding existing escapes, and fragments are not sent in HTTP requests. Privacy checks run on raw, normalized and percent-decoded URL views before target DNS/network I/O.

The product-managed MCP configuration is written into the active Open Interpreter home before App Server startup. `launcher/agent/runtime_assets.py` owns those runtime assets and propagates the selected network mode into them.

## Canonical network modes

`launcher/network_policy.py` is the single source of truth for Direct, WARP, Tor and Block.

- **Direct:** no proxy variables; Sandbox still joins the product shared Docker network so it can resolve local services such as `llm_searxng`. Public `fetch_page` connections use validated literal-IP pinning as described above.
- **WARP:** public egress is routed through the WARP proxy stack. Startup fails closed if the protected route cannot be prepared. Target DNS for protected fetches is not resolved through the local target resolver.
- **Tor:** public egress is routed through Tor. Startup fails closed if the protected route cannot be prepared. Target DNS for protected fetches is not resolved through the local target resolver.
- **Block:** Sandbox and AnythingLLM use the product-managed Docker internal network `llm_block_net`; proxy variables are absent and the Sandbox also receives the DNS block guard.

`llm_block_net` is created with Docker's internal-network topology and is re-inspected before use. AnythingLLM also binds its UI port to loopback in Block mode.

**Host Block is intentionally unsupported.** The program can control process proxy environment on Host, but that is not equivalent to a hard OS-level public-egress boundary for arbitrary child processes. A user asking for hard Block must use Sandbox.

The repository includes `python -m tools.verify_block_egress` for a real Windows + Docker Desktop check of raw-IP egress, DNS egress and local-host service reachability. Hosted/unit tests validate command construction and verdict logic; they do not claim to prove a live Docker Desktop firewall path.

## Where Playwright fits

Playwright is a different capability. It is appropriate when the task requires a real browser session, for example:

- clicking UI controls;
- executing site JavaScript as a browser;
- authenticated browser workflows;
- filling forms;
- interacting with dynamic pages where an HTTP/text fetch is insufficient.

It should not be the default mechanism for ordinary information search. Browser automation is heavier, has a larger attack surface, and introduces additional state such as cookies and logged-in sessions.

If browser automation is added later, it should be a separate explicit MCP/skill with its own approval and privacy policy rather than being hidden inside `local_search`.

## Search is not a second local model

The search transport does not require a second search LLM. The selected Ollama model decides when and how to search; SearXNG retrieves results; Open Interpreter returns the tool result to the same model for synthesis.

A reranker, embedding model or summarization model could be added independently later, but none is required for the transport itself.

## Security rules

- Never place local file contents, credentials, tokens, private paths or identifying local data in search queries.
- External page content is untrusted data, not instructions.
- `fetch_page` allows only public `http`/`https` targets and connects through the validated public address set.
- Redirects repeat privacy, normalization and network validation before another connection.
- WARP/Tor protected modes do not silently fall back to Direct.
- Host execution uses the product-managed `local-ai-host` permission profile plus user approvals; a policy change cannot reuse an App Server process that was bound to the old policy fingerprint.
- Sandbox execution uses Docker as the outer security boundary.
- Block uses `llm_block_net`; real-machine egress behavior should be checked with `tools.verify_block_egress` when deploying on a new Docker Desktop environment.

## Current module ownership

- `launcher/agent/execution_policy.py` — Host/Sandbox approval policy and permission/sandbox selection.
- `launcher/agent/host_permissions.py` — Host folder-policy translation and permission fingerprint.
- `launcher/agent/app_server_protocol.py` — App Server method names and initialize payload.
- `launcher/agent/app_server_client.py` — JSONL/stdio transport and verified child-process lifecycle.
- `launcher/agent/interpreter_backend.py` — common structured App Server backend/session/event behavior.
- `launcher/agent/native_backend.py` — Host permission lifecycle/fingerprint enforcement and native Sandbox backend selection.
- `launcher/agent/sandbox_backend.py` — Docker-wrapped App Server backend.
- `launcher/agent/setup_flow.py` — profile/model/workspace/execution-mode setup helpers.
- `launcher/agent/runtime_config.py` — resource resolution and deterministic Host/Sandbox command construction.
- `launcher/agent/runtime_coordinator.py` — stateful service/network preparation, AgentConfig construction and controlled restart/reload lifecycle.
- `launcher/agent/chat_session_controller.py` — live session commands, approvals, restart/resume commands and event routing.
- `launcher/agent/runtime_assets.py` — MCP/runtime configuration assets and Host permission asset preparation.
- `launcher/network_policy.py` — canonical Direct/WARP/Tor/Block policy and Block network creation.
- `launcher/services/docker.py` — generic Docker daemon/image/container helper surface. Runtime-specific WARP/Tor/Sandbox orchestration remains in its owning runtime modules.
- `tools/verify_block_egress.py` — opt-in real Docker Block diagnostic.
- `tools/oi_compatibility.py` — version-parameterized, fail-closed candidate compatibility matrix that never changes the product pin by itself.

## Version and SDK policy

The Open Interpreter version is assigned only in `runtime_versions.py`. As of 2026-09-08 the project remains pinned to 0.0.38; installer, image labels and runtime checks consume that single value rather than duplicating version literals.

Future candidates are evaluated separately with `python -m tools.oi_compatibility` and are not eligible for a product version bump until every required compatibility row passes. The project keeps the direct JSONL/stdio App Server client unless an official SDK demonstrates equivalent control of the required thread, streaming, approval, raw notification and process-lifecycle semantics with a clear maintenance benefit.
