# LocalAI Studio and standalone applications

## Run

- `RUN.bat` or `STUDIO.bat`: LocalAI Studio.
- `CHAT.bat` or `RUN.bat --app chat`: LocalAI Chat.
- `INTERPRETER.bat` or `RUN.bat --app interpreter`: LocalAI Interpreter.
- `SETUP.bat` or `RUN.bat --app setup`: LocalAI Setup.

With `PYTHONPATH=src`, the equivalent modules are `apps.studio`, `apps.chat`,
`apps.interpreter` and `apps.setup`. They use one parser, shared views and one
service composition. `--help` does not load a runtime. Python 3.11+ with Tk is
required for the desktop. The current copy contains both Korean and English
labels; `--lang` initializes the retained installer/runtime language preference,
not a complete translation of the new shell.

`RUN.bat --tui` retains the legacy terminal launcher. `SETUP.bat --install`
(and the existing `--skip-model`, `--skip-sandbox`, `--skip-build`, `--skip-search`
flags) runs the retained installer explicitly. `SETUP.bat --manage` opens the
retained maintenance interface. The old Python modules remain compatibility
entrypoints, not copies of a new backend. Launching Studio on an uninstalled PC
opens the shell and Setup guidance, rather than silently downloading programs.

## Appearance and navigation

Settings > Screen theme offers Dark and Light. The preference is stored under
`appearance.theme` in the existing `user_data/settings/localai.json`, shared by
Studio/Chat/Interpreter/Setup. It is applied in place after a successful save;
text, panel identities, selections and running sessions are not reconstructed.
Other active windows refresh the preference on focus and during normal polling.
An invalid/unreadable preference uses the dark fallback at startup with a warning,
without overwriting the original file. Failed saves retain the previous theme.

The shell, its raw Tk text areas and recognized retained Agent/Presenter colors
are themed, including warning/error tags. AnythingLLM in the browser and native
OS dialogs keep their own appearance settings; the shell does not modify them.

Chat and Agent lead the sidebar with larger typography and one restrained
blue-gray accent in both themes. Home gives them the two principal action cards.
Models and Setup / Repair use a separate group with neutral surfaces and outlined
buttons, not a competing accent color. Card borders/body copy are quiet; selection
uses a soft fill rather than a large solid accent. Deletion, warnings and success
keep independent semantic colors, so reducing feature colors does not hide risk.
Static forms and cards scroll at small window sizes, with local mouse-wheel and
keyboard-focus scrolling rather than application-wide wheel bindings.

## Views and workflow

Studio provides Home, Chat, Agent, Models, Network, System, Settings, and
Setup / Repair. Each standalone app exposes the relevant subset of those
same views. Navigation retains the Agent panel and active conversation instead
of destroying the session when switching pages.

Chat prepares the shared services, then opens the actual local AnythingLLM UI
in the default browser. This release uses the browser fallback, not an embedded
WebView or an iframe. Documents, workspaces, uploads, RAG and conversation history
remain owned by AnythingLLM. Project/Workspace creation and document management happen inside the actual
AnythingLLM Chat UI. Chat's "Create/manage projects" action opens that UI, preparing
Chat first if needed. No LocalAI connection record is required for normal Chat.
There is no separate Projects navigation item or global project toolbar.

The previous LocalAI Project registry is preserved as optional "Agent connection"
linkage inside Chat's second tab. It connects an existing AnythingLLM workspace
slug to an Agent working folder, without creating/cloning/deleting the real
workspace. Standalone Interpreter exposes the same optional records in its
nested Chat connection tab. The old `navigate('projects')` request routes to this
nested editor. Existing saved IDs/fields/files and policy precedence are retained.
A Project's workspace slug remains linkage information only; Chat's initial model can
come from the Project. The Agent model field is a reference value; the existing
Agent wizard still confirms its model, execution mode and folder permissions.

Agent uses the existing RuntimeCoordinator, native Open Interpreter thread IDs,
approval descriptions and ChatSessionController. Its conversation, command
output, file sidebar, model controls, stop/restart and approvals use the retained
Agent panel. A Project folder is only a dialog default: it never grants Host or
Sandbox access automatically. Host Block remains rejected.

Models shows the canonical MODEL_INDEX.json observation: manifest/blob links,
shared/exclusive bytes and missing/mismatched files. Setup is the explicit entry
for pull/remove and repair. An orphan observation is never permission for this
shell to delete blobs. Model downloads use the local Ollama server's own network;
WARP/Tor routing is not promised for these management downloads. Saved Setup Block
intent or a currently pinned Block mode rejects the model download action.

## Ownership, policy and shutdown

Network preferences resolve Session > Project > App > Global, falling back to
the retained launcher's current mode when no new global setting exists. A
selected Project is read again before session startup. Changing preferences
does not reconfigure an existing session's network mid-operation.

One window per checkout owns managed runtime mutations via a permanent OS-backed
lock under `user_data/cache`. That window can run Chat and Agent together with
the same network mode; other windows may inspect state. Stop its sessions before
another window starts or repairs managed runtimes. This is a deliberately coarse
first desktop coordination policy, not a machine-wide multi-user service or a
cross-checkout lock. External clients can still use Ollama's API. Old launchers
invoked directly outside the new entrypoints do not participate in this lock.

Block calls the original relay quiescence and internal-network verification;
protected preparation failures never select Direct. Search runs only after the
NetworkManager prepares the selected mode. Direct search no longer starts WARP.
A mode-specific SearXNG settings derivative is stored under `user_data/cache/search`.
The original installer settings are not rewritten. Unrecognized custom outgoing
proxy sections fail closed for search and require explicit configuration repair.
The official image may initialize the writable derived configuration directory.

Closing a window cancels new startup, waits for active operations, and verifies
its Agent/Chat/Search shutdown before releasing ownership. Finish an open
approval or installer prompt when requested. Unverified shutdown retains the
window and lock. Previously running shared Chat containers are not stopped;
containers recreated by this window are tracked by their immutable ID. Shared
Ollama and proxy runtimes are not indiscriminately killed on every window close.

## Paths and scope

Existing `project_paths` remains authoritative for the desktop: project-local
`llm_environment`, existing `user_data`, and `C:\LLM_Models` (or `LLM_MODEL_DIR`).
The shell does not silently enable the separately staged official Ollama
installer, move models to `C:\Ollama\models`, relocate user data, or rebuild
AnythingLLM/OI data. That earlier unpublished migration proposal is not shipped
with this UI commit.

The layering is Apps -> Services -> transition Integrations, with UI-independent
Core contracts. Existing reviewed launcher implementations are reused behind
adapters; their physical relocation and the elimination of every historical
import/direct CLI call are not claimed complete. The original DockerService
remains the single concrete Docker CLI primitive implementation.

This is a Python-source desktop release. Four Windows EXE packages, embedded
WebView distribution, official Ollama migration activation and user-data
relocation are separate work, not artifacts produced by this change.

## Validation

Run the full repository suite in a complete checkout:

```bat
set PYTHONPATH=%CD%\src
python -m compileall -q src
python -m pytest -q src\tests
```

For the desktop/core/index tests on Linux, provide a real display such as Xvfb.
UI tests inject external runtimes but instantiate real Tk windows; without Tk
those modules skip instead of aborting collection.

### Verified

On a live Linux Docker daemon (29.3.1), against the real `LegacyBackend` rather
than a stand-in:

- the full repository suite, on the CI Python (3.11) headless and with Tk under Xvfb;
- `tools.verify_block_egress` end to end, with a normal-bridge baseline proving
  the same probe does reach public DNS and raw-IP TCP (see README, "Linux Docker
  에서 실제로 확인된 것", including the one item that fails there);
- `integrations.searxng.runtime` against the daemon: derived per-fingerprint
  config, loopback-bound published port, labels, idempotent restart, container
  replacement on a mode change, `Block` refusal, verified stop;
- Ollama ownership: a foreign listener answering on 11434 is not adopted
  (`is_managed_running()` and `ensure_running()` both stay False);
- Studio started on the real backend: Docker reported ready, the model index
  scanned an empty store, and Chat failed closed with the Setup guidance.

### Not verified here

Native Windows and Docker Desktop, the official Ollama runtime, the AnythingLLM
and SearXNG images (the registry CDN is blocked from this environment), and
end-to-end Open Interpreter acceptance. Record CI runner failures separately
from code-test failures; no executed steps is not a pass. Do not change branch
protection or force-push to bypass checks.
