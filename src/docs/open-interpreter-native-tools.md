# Open Interpreter Native Tools / Web Search Architecture

## Current agent boundary

Local_AI_Agent uses Open Interpreter 0.0.38 as the automation runtime and Ollama as the local model provider. The active boundary is:

```text
User
  -> Local_AI_Agent GUI
  -> AgentService
  -> Open Interpreter App Server
       -> local Ollama model
       -> native command/file execution
       -> approvals
       -> Open Interpreter thread/session IDs
       -> MCP tools
```

Open Interpreter owns the agent loop, command/file execution, approval protocol and thread lifecycle. Local_AI_Agent owns product setup, workspace/folder mounts, Docker isolation, network posture, model selection and UI lifecycle.

The App Server transport intentionally remains JSONL over stdio. The transition did not replace a working App Server boundary with another SDK layer merely for abstraction. App Server method names and initialize payload ownership are centralized in `launcher/agent/app_server_protocol.py` so protocol drift is isolated to one module.

## Execution and approval policy

Open Interpreter execution policy is centralized in `launcher/agent/execution_policy.py`.

- Host: `approval_policy="on-request"`, reviewer `user`, sandbox mode `workspace-write`.
- Sandbox: `approval_policy="on-request"`, reviewer `user`, inner Open Interpreter sandbox mode `danger-full-access` because Docker is the outer security boundary.

The Sandbox setting does **not** remove Docker isolation. Workspace mounts, denied-path masks, network selection and container resource limits remain outside Open Interpreter.

Live UI/service operations such as `/session`, `/resume <thread-id>`, `/model`, `/reload`, stop/restart, approval responses and event routing are owned by `launcher/agent/chat_session_controller.py`. The GUI no longer scans legacy `session_*.json` files or converts list indexes into fake session IDs; resume uses the native Open Interpreter thread ID.

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

The product-managed MCP configuration is written into the active Open Interpreter home before App Server startup. `launcher/agent/runtime_assets.py` owns those runtime assets and propagates the selected network mode into them.

## Canonical network modes

`launcher/network_policy.py` is the single source of truth for Direct, WARP, Tor and Block.

- **Direct**: no proxy variables; Sandbox still joins the product shared Docker network so it can resolve local services such as `llm_searxng`.
- **WARP**: public egress is routed through the WARP proxy stack. Startup fails closed if the protected route cannot be prepared.
- **Tor**: public egress is routed through Tor. Startup fails closed if the protected route cannot be prepared.
- **Block**: Sandbox and AnythingLLM use the product-managed Docker internal network `llm_block_net`; proxy variables are absent and the Sandbox also receives the DNS block guard.

`llm_block_net` is created with Docker's internal-network topology and is re-inspected before use. AnythingLLM also binds its UI port to loopback in Block mode.

**Host Block is intentionally unsupported.** The program can control process proxy environment on Host, but that is not equivalent to a hard OS-level public-egress boundary for arbitrary child processes. A user asking for hard Block must use Sandbox.

The repository includes `python -m tools.verify_block_egress` for a real Windows + Docker Desktop check of raw-IP egress, DNS egress and local-host service reachability. Hosted CI validates command construction and verdict logic; it does not claim to prove a live Docker Desktop firewall path.

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
- `fetch_page` allows only public `http`/`https` targets and rejects private/local addresses.
- WARP/Tor protected modes do not silently fall back to Direct.
- Host execution uses the centralized Open Interpreter workspace/approval policy.
- Sandbox execution uses Docker as the outer security boundary.
- Block uses `llm_block_net`; real-machine egress behavior should be checked with `tools.verify_block_egress` when deploying on a new Docker Desktop environment.

## Current module ownership

- `launcher/agent/execution_policy.py` — Host/Sandbox approval and Open Interpreter sandbox policy.
- `launcher/agent/app_server_protocol.py` — App Server method names and initialize payload.
- `launcher/agent/interpreter_backend.py` — managed Host App Server backend.
- `launcher/agent/sandbox_backend.py` — Docker-wrapped App Server backend.
- `launcher/agent/native_backend.py` — common App Server client/event lifecycle.
- `launcher/agent/setup_flow.py` — profile/model/workspace/execution-mode setup helpers.
- `launcher/agent/runtime_config.py` — resource resolution and Host/Sandbox runtime command construction.
- `launcher/agent/chat_session_controller.py` — live session commands, approvals, restart/resume and event routing.
- `launcher/agent/runtime_assets.py` — MCP/runtime configuration assets.
- `launcher/network_policy.py` — canonical Direct/WARP/Tor/Block policy and Block network creation.
- `tools/verify_block_egress.py` — opt-in real Docker Block diagnostic.

## Version policy

The Open Interpreter version is assigned only in `runtime_versions.py`. At the completion of this transition on 2026-09-08 the project remains pinned to 0.0.38; installer, image labels and runtime checks consume that single value rather than duplicating version literals.
