# P0 Network and Privacy Boundary Design

## Status

Approved implementation slice derived from the 2026-09-08 architecture revalidation proposal.

This design intentionally implements only the first security boundary. Open Interpreter version upgrades, SDK migration, OI Permissions, session migration, Open WebUI retirement, Docker topology hardening, and controller decomposition remain separate follow-up changes.

## Goal

Make `Local_AI_Agent` the single owner of network-mode semantics and deterministic outbound privacy checks so that Host Agent, Sandbox Agent, AnythingLLM, and local search all interpret `warp | tor | direct | block` consistently.

## Architecture invariant

External engines may own execution mechanics, but they do not own product policy.

- Local_AI_Agent owns network, privacy, folder, logging, model, install, and sandbox policy.
- AnythingLLM consumes those policies as the Chat/RAG engine.
- Open Interpreter consumes those policies as the Agent runtime.
- Changing or upgrading either engine must not silently change WARP/Tor/Direct/Block semantics.

## Confirmed current defects

The design is based on direct inspection of `main` at `c0a2dbe174ead3b580781e925f472cc06ddc6268`.

1. `entry_dialog.py` only sets `tor=True` for Sandbox sessions. Host WARP/Tor selections therefore become direct Host sessions.
2. `tor_proxy: bool` conflates WARP and Tor. If Host WARP were represented by `True`, the current `build_tor_env()` would inject Tor endpoints anyway.
3. WARP Host and Container endpoints differ. Host HTTP must use `127.0.0.1:8119`; Container HTTP must use `llm_httpbridge:8118`.
4. `anythingllm_runtime.start()` discards the boolean from `ensure_proxy_stack()`, so a protected mode can continue after proxy preparation fails.
5. `warp_runtime.start()` itself can report success while the HTTP bridge is unavailable.
6. AnythingLLM's Node bootstrap logs and continues direct when `undici.ProxyAgent` is unavailable.
7. `search_mcp._search()` only checks that a query is non-empty. Privacy policy is currently prompt-only.
8. Sandbox `block` currently means DNS suppression via `--dns=0.0.0.0`, not a proven raw-IP egress boundary.

## Scope

### In scope

- Add canonical `NetworkMode` values: `warp`, `tor`, `direct`, `block`.
- Add explicit Host and Container proxy environment builders.
- Remove Agent runtime dependence on `tor_proxy: bool`.
- Carry canonical mode through `AgentConfig.network_mode` and `LOCAL_AI_NETWORK_MODE`.
- Make Host WARP use HTTP `127.0.0.1:8119` and SOCKS `127.0.0.1:1080`.
- Make Host Tor use HTTP `127.0.0.1:8118` and SOCKS `127.0.0.1:9050`.
- Keep local Ollama/SearXNG endpoints in `NO_PROXY`.
- Refuse to start protected Agent/AnythingLLM runtimes if the selected WARP/Tor runtime cannot be prepared.
- Treat WARP HTTP bridge health as part of WARP readiness.
- Make AnythingLLM Node proxy bootstrap fail closed in protected modes instead of falling back to direct fetch.
- Add deterministic outbound query checks for obvious secrets, local file paths/URLs, credential URLs, and private/local addresses.
- Make local search and page fetch reject all public network operations when `LOCAL_AI_NETWORK_MODE=block`.
- Preserve ordinary public searches, including email addresses/phone numbers, because ambiguous PII must not be blanket-blocked without an approval protocol.
- Keep current DNS-level Sandbox block but label/document it honestly as an interim boundary until the Docker egress topology spike.
- Refuse Host `block` sessions rather than falsely claim enforcement that does not exist.

### Out of scope

- Docker `--internal` or equivalent hard-egress topology. That requires Windows + Docker Desktop integration validation with Ollama/SearXNG/proxy reachability.
- Open Interpreter Permissions or Host filesystem-policy enforcement.
- Open Interpreter 0.0.38 -> newer version changes.
- App Server SDK migration.
- Agent session migration.
- AnythingLLM search-gateway proxying. This P0 patch protects Agent `local_search`; a shared HTTP search gateway is a later change after request-shape characterization.
- Open WebUI compatibility cleanup.

## Network policy API

Create `src/launcher/network_policy.py` as the semantic source of truth.

```python
class NetworkMode(str, Enum):
    WARP = "warp"
    TOR = "tor"
    DIRECT = "direct"
    BLOCK = "block"
```

Required public functions:

```python
def normalize_mode(value=None) -> NetworkMode: ...
def current_mode() -> NetworkMode: ...
def set_mode(value) -> NetworkMode: ...
def display_label(value) -> str: ...
def allows_public_egress(value) -> bool: ...
def host_proxy_env(value) -> dict[str, str]: ...
def container_proxy_env(value) -> dict[str, str]: ...
def prepare_runtime(value, *, env_path=None, log=None) -> bool: ...
```

Rules:

- Unknown values normalize to the configured/default WARP mode only at legacy input boundaries; canonical internal paths always carry a valid enum/value.
- `set_mode()` updates both `NET_MODE` and `LOCAL_AI_NETWORK_MODE` environment markers plus `launcher.config.NET_MODE` for legacy consumers.
- `host_proxy_env()` and `container_proxy_env()` never infer which address form is required from a hostname argument.
- Both env builders include `LOCAL_AI_NETWORK_MODE=<canonical>`.
- Direct/Block return no non-empty proxy routes. Consumers must remove inherited proxy variables for those modes before spawning managed runtimes.

### Expected endpoints

| Mode | Host HTTP | Host SOCKS | Container HTTP | Container SOCKS |
| --- | --- | --- | --- | --- |
| WARP | `http://127.0.0.1:8119` | `socks5h://127.0.0.1:1080` | `http://llm_httpbridge:8118` | `socks5h://llm_warp:1080` |
| Tor | `http://127.0.0.1:8118` | `socks5h://127.0.0.1:9050` | `http://llm_tor:8118` | `socks5h://llm_tor:9050` |
| Direct | none | none | none | none |
| Block | none | none | none | none |

## Agent flow

The entry dialog returns `network_mode`, not a proxy boolean. It always commits the selected canonical mode whether execution mode is Host or Sandbox.

```text
entry dialog
  -> NetworkMode
  -> prepare_runtime(mode) for warp/tor
  -> build Sandbox command OR Host runtime env
  -> AgentConfig.network_mode = canonical value
  -> Open Interpreter
```

### Host

- WARP/Tor must prepare the selected runtime before Open Interpreter starts.
- `OpenInterpreterBackend._runtime_env()` normalizes the process environment according to the canonical mode. Protected modes inject explicit proxy values. Direct/Block strip inherited proxy keys.
- Host Block is rejected before startup because this patch has no OS-level outbound network boundary. Refusing to run is safer than silently running direct.

### Sandbox

- `build_sandbox_docker_command()` accepts `network_mode`.
- WARP/Tor inject Container proxy env plus `LOCAL_AI_NETWORK_MODE`.
- Direct injects only the marker and no proxy/DNS block.
- Block injects the marker and retains the existing `--dns=0.0.0.0` interim guard.
- The UI/log label for this state must not claim a proven raw-IP egress block.

## Runtime fail-closed rules

`prepare_runtime()` is successful only when all required components are ready.

- WARP: WARP SOCKS handshake **and** HTTP bridge start/readiness must succeed.
- Tor: Tor SOCKS readiness and HTTP port exposure must succeed.
- Direct/Block: no proxy runtime is required.

If WARP/Tor preparation fails:

- Agent startup stops before Open Interpreter.
- AnythingLLM startup returns `False` before container launch/reuse.
- The product does not silently downgrade to Direct.

AnythingLLM's Node `--require proxy-bootstrap.js` must also fail the Node process in protected modes if a compatible `undici.ProxyAgent` cannot be loaded. A log-only fallback to direct fetch is prohibited.

## Privacy policy

Create `src/launcher/privacy_policy.py` as a stdlib-only deterministic guard.

Public API:

```python
def blocked_outbound_reason(text: str) -> str | None: ...
```

It blocks high-confidence outbound-sensitive forms only:

- common API key/token/secret/password assignments and known token prefixes,
- Windows absolute/UNC paths,
- POSIX home/system absolute paths when clearly path-shaped,
- `file://` URLs,
- URLs containing embedded credentials,
- localhost/private/link-local network literals.

It does **not** blanket-block names, email addresses, phone numbers, or ordinary public search phrases.

`search_mcp` checks the guard before constructing the SearXNG request. In Block mode both `search` and `fetch_page` return an MCP error without performing network I/O.

Because `search_mcp.py` is copied into the managed Open Interpreter state directory, `runtime_assets.py` must install a matching standalone copy of `privacy_policy.py` beside it. `search_mcp` imports package-first and sibling-module-second so Host and Sandbox use the same implementation.

## Logging and redaction

The patch must not add raw rejected secrets to logs or error text. Privacy guard errors identify only the category, for example `blocked outbound secret/token` or `blocked local file path`.

Canonical network mode values may be recorded in traces; proxy credentials are not used by current WARP/Tor configurations and must not be logged if added later.

## Compatibility

- Existing `config.NET_MODE` remains as a compatibility value but no new policy decisions should be implemented directly against it outside `network_policy.py`.
- `none` is accepted as a legacy alias for `direct` at input normalization only.
- Tests and call sites using `tor_proxy` are migrated. No new compatibility boolean is introduced.
- Model catalog, model selection, Ollama store layout, and shared `C:\LLM_Models` behavior are untouched.

## Testing

The first implementation commit is tests-only and must fail on current `main`.

Minimum contract coverage:

1. Network mode normalization and labels.
2. Exact Host/Container endpoints for WARP/Tor.
3. Direct/Block contain no proxy route.
4. WARP readiness fails if HTTP bridge fails.
5. AnythingLLM refuses protected startup when proxy preparation fails.
6. Agent Host WARP/Tor carry canonical mode and Host proxy endpoints.
7. Sandbox modes inject canonical marker and expected proxy/DNS flags.
8. `search_mcp` Block mode performs no network request.
9. Secret/local-path/private-address queries are rejected.
10. Normal public queries and ambiguous public PII searches remain allowed.
11. Full existing suite stays green on Windows.

## Explicit limitation after this patch

`block` is not yet a universal raw-IP egress firewall for Sandbox or AnythingLLM. The Agent's managed search surface is denied, and Host Block is fail-closed by refusing startup, but Docker-level raw-IP isolation remains the next dedicated topology spike. UI/documentation must state this rather than overclaim complete isolation.
