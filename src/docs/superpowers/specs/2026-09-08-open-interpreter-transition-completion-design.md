# Open Interpreter Transition Completion Design

## Status

Approved continuation of the existing Open Interpreter migration and the 2026-09-08 network/privacy work.

Baseline: `main` at `fe18a0e7c1e38408df1a791bf0d756506e664e78`.

## Goal

Finish the project-wide transition without replacing working pieces that are already migrated. The finished architecture keeps AnythingLLM as the chat/RAG surface, Open Interpreter App Server as the automation-agent runtime, Ollama as the local model provider, and Docker as the mandatory Sandbox isolation boundary.

## Revalidated current state

The repository is already beyond the earlier migration plans in several areas:

- Open Interpreter is pinned centrally in `src/runtime_versions.py` and the current upstream latest Rust release remains `0.0.38` (`rust-v0.0.38`). No version bump is required for this transition.
- Host and Sandbox automation both use Open Interpreter App Server through `launcher.agent.backend_factory`; there is no custom agent-loop fallback.
- The retired `agent_runner.py`/legacy backend/direct-agent compatibility paths are already deleted and guarded by repository-structure tests.
- `AgentService` already exposes App Server thread start, turn start, approval response, interrupt, session id, and thread resume.
- Sandbox session state already persists under product-owned `user_data` state and Host state uses `INTERPRETER_HOME` under `user_data/open_interpreter`.
- AnythingLLM WARP/Tor startup is fail-closed after PR #8.

Therefore this design does **not** reimplement those completed migrations.

## External contracts used

### Open Interpreter

Open Interpreter 0.0.38 remains the latest release as of 2026-09-08. Its current configuration exposes `approval_policy`, `approvals_reviewer`, `sandbox_mode`, and `default_permissions`. The official configuration reference recommends permissions profiles for finer-grained access rather than mixing two independent filesystem policy systems in one active configuration.

The product will continue to use App Server directly. This is deliberate: the GUI needs streamed events, approval requests, thread lifecycle, and resume behavior; those are already modeled by the current App Server client and backend. Switching to a language SDK solely for abstraction would add a dependency and transport layer without changing the runtime contract.

### Docker

Docker's `--internal` network mode is the hard egress primitive for Block mode. Docker documents that containers on an internal network can communicate with one another and the network gateway/appropriately configured host services, while no default route to other networks is configured and firewall rules block traffic to/from other networks.

This allows Block-mode agent containers to retain access to host Ollama through `host.docker.internal` while denying public egress at the Docker network boundary.

## Target architecture

```text
Local_AI_Agent
├─ ChatService
│  └─ AnythingLLM
│     ├─ Ollama (host)
│     ├─ RAG / LanceDB
│     └─ SearXNG (only when the selected network posture permits it)
│
└─ AgentService
   └─ Open Interpreter 0.0.38 App Server
      ├─ Host mode
      │  ├─ user-approved execution
      │  ├─ product folder policy + OI approval contract
      │  └─ Direct / WARP / Tor / Block network policy
      └─ Sandbox mode
         ├─ Docker outer sandbox
         ├─ mounted workspace / allowed paths only
         ├─ App Server inside container
         └─ Direct / WARP / Tor / hard-Block Docker network
```

## Phase 1 — hard Block egress boundary

### Dedicated internal network

Add one product-managed Docker network name, defaulting to `llm_block_net`. A canonical helper must:

1. inspect the network;
2. create it with `docker network create --driver bridge --internal` when absent;
3. verify an existing network reports `Internal=true` and `Driver=bridge`;
4. return failure for an existing network with the expected name but unsafe properties;
5. never silently fall back to the default/shared network.

### Sandbox agent

When canonical network mode is `block`, `build_sandbox_docker_command()` must:

- join only the internal Block network;
- carry `LOCAL_AI_NETWORK_MODE=block`;
- retain `--dns=0.0.0.0` as defense in depth;
- retain the host-gateway mapping used for Ollama;
- avoid proxy environment routes.

The runtime must verify/create the internal network **before** Docker starts the agent container. If the network cannot be established safely, startup fails closed.

WARP/Tor/Direct behavior stays unchanged.

### AnythingLLM

Block mode must also use the dedicated internal network. Startup must verify the network before container inspection/reuse/start. The UI port must bind to loopback, not all host interfaces. Block remains a local chat/RAG mode; public search is unavailable.

AnythingLLM WARP/Tor keep the existing shared network and fail-closed proxy bootstrap.

### Validation

Unit/contract tests must prove command construction and fail-closed behavior. Add an opt-in Docker Desktop diagnostic that verifies, on a real machine:

- host Ollama endpoint remains reachable from the Block network;
- public DNS/public TCP are unavailable;
- the test container is attached to an `Internal=true` network.

The diagnostic is not required by hosted CI and its absence must not be represented as real-container proof.

## Phase 2 — Open Interpreter permissions and approval contract

Open Interpreter already owns command approvals (`approvalPolicy=on-request`, reviewer=`user`). Preserve that ownership rather than adding a second custom execution-approval engine.

Product policy remains split by boundary:

- **Host:** OI App Server remains `workspace-write` and `on-request`; product folder policy and structured instructions describe the selected workspace/allowed paths. Host mode retains the explicit high-risk confirmation before the runtime starts.
- **Sandbox:** Docker is the mandatory filesystem/network outer boundary. OI runs `danger-full-access` *inside that container* so nested sandboxing does not weaken or break Docker behavior, while approvals remain `on-request` and user-reviewed.

Add a single typed/runtime policy builder so these values are not duplicated in backend code. It must reject unsupported execution modes and produce deterministic thread parameters. Tests must lock the Host/Sandbox approval and sandbox-mode contract.

Do not add a beta OI permissions profile on top of the current sandbox modes unless the active 0.0.38 App Server exposes a stable per-thread permissions-profile field. The official config reference warns against mixing independent permission systems; YAGNI applies. The transition is complete when OI approval/sandbox ownership is explicit, centralized, and tested.

## Phase 3 — App Server and session compatibility revalidation

Keep the existing stdio JSON-RPC App Server transport. Centralize protocol method names and initialization metadata so compatibility drift is visible in one module.

Required supported operations:

- initialize / initialized;
- thread/start;
- thread/resume;
- turn/start;
- turn/interrupt;
- approval responses;
- streamed notifications and termination/protocol errors.

Session persistence remains Open Interpreter-owned under product `INTERPRETER_HOME`; `/session` and `/resume` remain product UI affordances. Do not invent a parallel session database.

If upstream 0.0.38 does not provide a stable operation needed for session listing, do not create a fragile parser of internal OI files. Existing explicit thread-id resume is sufficient.

## Phase 4 — remove retired Open WebUI surface

AnythingLLM is the current ChatService. Remove executable/install paths that can still install or start Open WebUI when they are no longer reachable from the current launcher.

Keep only narrowly useful migration cleanup identifiers (for example, recognizing an old `llm_openwebui` container during cleanup) and mark them as legacy cleanup rather than an active component.

Update comments, installer descriptions, i18n strings, action documentation, and README so they do not present Open WebUI as an active option.

Do not remove AnythingLLM, SearXNG, LanceDB, or Ollama behavior.

## Phase 5 — split `agent_chat.py`

`launcher/actions/agent_chat.py` remains a large patch-history orchestration module. Split by responsibility without changing UI behavior:

- setup/selection flow: profile, workspace, execution mode, model, network choice;
- runtime command/config construction: sandbox command, canonical network label, `AgentConfig` creation;
- session UI controller: slash commands, restart, model switch, folder-policy reload, service serialization;
- `actions/agent_chat.py`: thin entrypoint and GUI assembly only.

Public/reused helper compatibility required by tests/tools (notably `_build_cmd_for_mode`) should either remain as a small forwarding wrapper or move together with all consumers in the same commit.

Add architecture regression tests that cap responsibilities/import directions rather than brittle line-count-only checks.

## Phase 6 — cleanup audit, documentation, and final verification

### DockerService

There is currently one canonical `launcher.services.docker.DockerService`. Do not create another abstraction merely to satisfy an old plan item. Verify all active launcher callers use it; remove only genuinely duplicated low-level daemon helpers when equivalence is proven by tests.

### Models and storage

These are hard non-goals unless a failing transition test proves a necessary compatibility fix:

- model catalog and model-role ladders;
- Ollama ownership/provider semantics;
- shared `C:\LLM_Models` behavior;
- existing installed-model selection/rollback logic.

### Final gate

The branch is complete only when:

1. `python -m compileall -q src` succeeds;
2. `python -m pytest -q src\tests` has zero failures;
3. retired custom runtime files remain absent;
4. Open Interpreter stays pinned to latest `0.0.38` unless upstream releases a newer version during implementation and it is separately revalidated;
5. Block-mode command contracts use the internal network and fail closed on unsafe/missing topology;
6. WARP/Tor AnythingLLM fail-closed tests remain green;
7. Host/Sandbox OI approval/sandbox contracts are explicit and tested;
8. README describes the actual architecture, not historical Open WebUI/custom-loop architecture.

## Non-goals

- Replacing AnythingLLM with Open Interpreter.
- Replacing Ollama.
- Changing model classes or quantization ladders.
- Building a new agent loop.
- Replacing the working App Server transport with a second SDK solely for stylistic reasons.
- Claiming hosted CI proves Docker Desktop raw-IP isolation.
