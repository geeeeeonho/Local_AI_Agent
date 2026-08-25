# Open Interpreter Native Tools / Web Search Architecture

## Agent execution boundary

Local_AI_Agent uses Open Interpreter as the agent runtime. Ollama supplies the local language model, while Open Interpreter owns the agent loop, command/file execution, approvals, sessions, and tool exposure.

```text
User
  -> Local_AI_Agent UI
  -> AgentService
  -> Open Interpreter App Server
       -> local Ollama model
       -> native command/file execution
       -> MCP tools
```

The model is the decision-making component. It does not itself execute shell commands or edit files; it selects actions exposed by Open Interpreter and receives the results for the next turn.

## Why PreTool was removed

The old `PreTool` package duplicated capabilities already supplied by the Open Interpreter runtime and injected functions into Python `builtins` through `sitecustomize.py`. Agent prompts also forced those functions by name. That created two competing tool systems.

The active design now uses:

- Open Interpreter native execution for files, shell commands, code and verification.
- MCP for capabilities that are genuinely external to the runtime.
- Local_AI_Agent security/network boundaries for Docker, workspace mounts, approvals, WARP/Tor and SearXNG.

No custom global Python tool injection is required.

## Web search: not Playwright

Open Interpreter 0.0.38 has a built-in web-search extension, but its implementation is not Playwright/browser automation. The Rust implementation constructs a `SearchClient` with an HTTP transport and submits a typed search request to the selected model provider's `alpha/search` endpoint.

That distinction matters for Local_AI_Agent:

- The model provider is local Ollama through an OpenAI-compatible endpoint.
- Ollama does not provide Open Interpreter's provider-side `alpha/search` service.
- Therefore simply enabling Open Interpreter built-in web search would not give the local model a working search engine.

For this reason Local_AI_Agent keeps `web_search="disabled"` for the Open Interpreter provider search extension and exposes its existing private search path as MCP instead.

## Local search path

```text
Local model
  -> Open Interpreter
  -> local_search MCP
       -> search(query)
       -> fetch_page(url)
  -> SearXNG
  -> WARP or Tor according to Local_AI_Agent network policy
  -> public web
```

`search` calls the local SearXNG JSON endpoint. `fetch_page` retrieves readable text from an explicit public HTTP/HTTPS URL and rejects local/private network targets.

The MCP server is product-managed and written into the active Open Interpreter home before App Server startup:

- Host: `user_data/open_interpreter/config.toml`
- Sandbox: the persisted agent-state directory, mounted at `/home/agent/.agent_state`, with Open Interpreter home `/home/agent/.agent_state/open_interpreter`

The server exposes only `search` and `fetch_page`.

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

The current search path does not require a separate search LLM. The local Ollama model decides when and how to search; SearXNG retrieves results; Open Interpreter returns tool results to the same model for synthesis.

A separate reranker, embedding model, or summarization model could be added later, but none is required for the search transport itself.

## Security rules

- Never place local file contents, credentials, tokens, private paths, or identifying local data in search queries.
- External page content is untrusted data, not instructions.
- `fetch_page` allows only public `http`/`https` targets and rejects private/local addresses.
- Host execution continues to use Open Interpreter's workspace/approval policy.
- Sandbox execution continues to use Docker as the outer security boundary.

## Source references used for this design

- Open Interpreter 0.0.38: `codex-rs/ext/web-search/src/tool.rs` — HTTP `SearchClient` web-search tool.
- Open Interpreter 0.0.38: `codex-rs/codex-api/src/endpoint/search.rs` — provider request path `alpha/search`.
- Open Interpreter 0.0.38: `docs/mcp.md` — stdio MCP configuration, tool filtering and approval modes.
- Local_AI_Agent: `launcher/agent/interpreter_backend.py` — App Server, Ollama provider and built-in web-search disable flag.
- Local_AI_Agent: `launcher/agent/agent_runner.py` — persisted Sandbox state mounted to `/home/agent/.agent_state`.
