# LocalAI Studio and standalone applications

## Run

The project root exposes one launcher:

- `RUN.bat`: LocalAI Studio (default).
- `RUN.bat --app chat`: LocalAI Chat.
- `RUN.bat --app interpreter`: LocalAI Interpreter.
- `RUN.bat --app setup`: LocalAI Setup.
- `RUN.bat --install`: explicit installer flow.
- `RUN.bat --manage`: current LocalAI Setup management app (same management UI as `--app setup`).
- `RUN.bat --tui`: retained legacy terminal launcher.

With `PYTHONPATH=src`, the equivalent modules are `apps.studio`, `apps.chat`,
`apps.interpreter` and `apps.setup`. They use one parser, shared views and one
service composition. `--help` does not load a runtime. Python 3.11+ with Tk is
required for the desktop. The current copy contains both Korean and English
labels; `--lang` initializes the shared installer/runtime language preference,
not a complete translation of the new shell.

The existing `--skip-model`, `--skip-sandbox`, `--skip-build`, and
`--skip-search` flags select the explicit install/repair flow when passed through `RUN.bat`. Naming a
different application alongside installation flags (`--app chat --install`) is
still rejected rather than guessed. The Python application modules are direct entrypoints into the same shared application composition. Launching Studio on an
uninstalled PC opens the shell and Setup guidance, rather than silently
downloading programs.

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

Focus is visible on navigation, buttons and selection checkboxes in both
themes, so the shell stays usable from the keyboard. Failures are shown in the
semantic danger color on the status line and in the activity log rather than as
one more muted line. The window's minimum size fits a 1366x768 laptop, and a
panel host claims layout space only once it has a panel to show.

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

Models is one screen with three tabs, replacing the retained launcher's split
between "installed model info" and "model management" and the first desktop's
free-text tag field.

*Current stack* names the model each role would load right now, its memory
requirement and whether it is on disk. The choice comes from the retained ladder
resolver; this view reports it rather than adding a second selection policy.
Selecting a role shows that role's whole ladder with per-rung disk state, so a
role falling back to a lighter model is visible instead of surprising.

*Choose models* is the catalogue selection, on the same contract as the
installer dialog: checked means the model should exist, so checking installs and
unchecking an installed model removes it. The memory budget's three levels are
pre-checked and the plan behind that choice is spelled out; installed models the
catalogue does not know about are listed too, so removing one is deliberate.
Applying states the downloads and deletions and asks before doing either;
removals run before downloads so a full store is never asked to hold both.

*Disk usage* keeps the canonical MODEL_INDEX.json observation: manifest/blob
links, shared/exclusive bytes and missing/mismatched files. An orphan observation
is never permission for this shell to delete blobs.

All three tabs name the store the models actually land in - one machine-wide
directory, not a project folder, so re-cloning the project does not re-download
anything. Choosing shows the free space there next to what the selection costs,
and says how much is short before the download starts rather than after it fails
partway; the confirmation repeats both. A store that does not exist yet is
measured against the drive it will live on and labelled as not yet created, and
a disk that cannot be read reports unknown rather than a number. Sizes are
ceilings: Ollama shares blob layers between models, so the real cost is usually
lower. Files are never deleted directly - unchecking a model hands it to Ollama,
which knows which layers another model still needs.

*Disk usage* also says whether this store really is shared with every account on
the machine, and offers to put it right. That is a fact about the machine, not
about the path: publishing the machine-scope OLLAMA_MODELS needs administrator
rights and can simply have failed during setup, so the screen reads the stored
value and the store's ACL rather than inferring from the directory name. It
distinguishes four answers - shared, not shared with the reason, an override
this account set for itself, and could-not-tell - and offers the repair only
where there is something the shell may fix. A user-scope OLLAMA_MODELS is that
account's own setting, so it is explained rather than deleted, and other
accounts are granted read and execute, never write: the store decides what the
models on this machine are.

Every reader of "which models are here" goes through one pipeline, with Ollama
as the router: what it serves is what the machine can use, and the store answers
when it is stopped. Both the screen's install state and its stack view
deliberately ask the store alone, so they stay truthful while Ollama is stopped
and so a screen that offers to delete files answers from the directory those
files are in. "Ollama start / check" runs the retained service action and shows
its log in place. Model downloads use the
local Ollama server's own network; WARP/Tor routing is not promised for these
management downloads. Saved Setup Block intent or a currently pinned Block mode
rejects the model download action. Setup keeps installation, repair and the
retained maintenance actions.

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

Ollama does not remember the store on its own. `ollama serve` re-reads
`OLLAMA_MODELS` at every start and keeps nothing; the Ollama desktop app does
remember it, in its own database under `%LOCALAPPDATA%\Ollama`, and injects it
as `OLLAMA_MODELS` when it launches the server - the same mechanism this project
uses. The durable memory is therefore the machine-wide environment variable, and
that variable is also what the Ollama app adopts as its own default when its
setting is empty. Setting it once configures the relay for every way it is
started, by this project or not, and for every account.

The relay is also configured to stay local. `OLLAMA_NO_CLOUD=1` is set on any
server this project launches, which makes Ollama answer 403 "ollama cloud is
disabled" to a cloud model on `/api/chat` and on the OpenAI-compatible
`/v1/chat/completions` alike, while local models are untouched. That closes the
hole at the source rather than only at this project's own name check, which
covers only requests it originates. A server this project did not launch carries
its owner's policy, so it is asked rather than assumed: `GET /api/status` reports
whether cloud is disabled and whether that came from the environment or from
Ollama's `server.json`. Attaching to a relay that still allows cloud is reported,
with the two ways to turn it off, rather than silently accepted.

Ollama cloud tags are refused wherever a model has to stay on this machine.
A tag Ollama marks as cloud is not downloaded: the local daemon attaches the
user's credentials and proxies the request to Ollama's servers, and every
OpenAI-compatible client - this one included - talks to it exactly like a local
model. That would void all three network promises at once, since Block's
no-public-egress, WARP's route and Tor's route cannot see traffic the daemon
makes on its own behalf, and the suffix has been reported stripped from run and
API calls on Windows. So the refusal sits at the model-name boundary, before a
policy that cannot observe it is asked to protect it. Removal stays allowed, so
a tag pulled elsewhere can still be got rid of. The shipped catalogue contains
none, and a test keeps it that way.

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

`src/project_paths.py` is the single assignment source for every path the
product uses - project-local `llm_environment`, existing `user_data`, and the
model store. Core reads it rather than defining a second copy.

Ollama is the intermediary rather than something this project contains. It owns
downloading, storing and serving; an Ollama already on the machine is used as-is,
and only an absent one is installed, officially, with `/DIR=C:\Ollama`. The store
is `C:\Ollama\models`, inside that install and shared by every Windows account,
because Ollama's own default lives in one user profile and a second account would
re-download everything. An `OLLAMA_MODELS` the user set themselves always wins:
overriding that was exactly what the old forced `C:\LLM_Models` got wrong, and
that store is now migrated out of rather than written to.

This was checked against a real ollama binary built from source rather than
from documentation. Pointed at a store by `OLLAMA_MODELS`, Ollama lists a model
placed there; started without it, the same server reports an empty library
because it looks in the user profile - the per-user problem, reproduced. Two
servers under different home directories sharing one `OLLAMA_MODELS` both serve
the same model, and the second home holds no blobs at all: one copy, two
accounts. This project's own resolver, `env_vars`, disk index and store-agreement
check were then run against that live server and agreed with it on every point.

The one divergence the exercise found is fixed: Ollama's `envconfig.Var` strips
surrounding quotes as well as whitespace, so `OLLAMA_MODELS="C:\Ollama\models"`
- quotes included, which a Windows dialog or batch file makes easy - resolves to
the bare path. This project kept the quotes, so it would have reported an empty
store and blocked startup against a perfectly healthy server. The parser now
matches `envconfig.Var` exactly, compared case by case against the real Go
function, and tests pin it.

A server this process did not launch is no longer refused on sight. It is
accepted when it runs from a known install and is demonstrably reading the same
store - what it serves on `/api/tags` has to exist in the on-disk index - and
it is never terminated, because it may be the user's own Windows service. Only
the portable copy in this project's folder stays ours to restart. Ownership is
decided by the pid in our runtime state file, not by the binary path, since the
official install is now the binary we would launch ourselves.
The official Ollama install and the machine-shared store at
`C:\Ollama\models` are shipped: Setup installs Ollama with `/DIR` when the
machine has none, moves an earlier `C:\LLM_Models` there crash-safely, and
publishes the machine-scope `OLLAMA_MODELS` so the other Windows accounts read
the same copy. The shell still does not relocate user data or rebuild
AnythingLLM/OI data, and it does not run any of the above silently - Setup
does it, and the model screen reports and repairs the sharing afterwards.

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

On Linux the desktop tests need a real display, such as Xvfb; they instantiate
real Tk windows while injecting the external runtimes. A Python with no Tk at
all skips them and still runs the rest:

  with Tk:    968 passed
  without Tk: 856 passed, 54 skipped

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

Against a real Ollama built from source, serving the machine-shared store:

- every reader of "which models are here" returns the same set, and store
  agreement reads True; a router pointed elsewhere reads False; a stopped one
  reads unknown rather than empty;
- `OLLAMA_NO_CLOUD=1` answers 403 on both `/api/chat` and `/v1/chat/completions`.

### Not verified here

Native Windows and Docker Desktop, the official Ollama runtime, the AnythingLLM
and SearXNG images (the registry CDN is blocked from this environment), and
end-to-end Open Interpreter acceptance. The machine-shared store's Windows
half - `setx /M`, `icacls`, and the registry read - runs only against stubs
here. Record CI runner failures separately from code-test failures; no executed
steps is not a pass. Do not change branch protection or force-push to bypass
checks.

### GitHub Actions is not running

No workflow run has executed since 2026-09-10. Every attempt, on Windows and on
Linux alike, ends in two to four seconds with `runner_id=0`, an empty step list,
a 404 for its logs and zero billable milliseconds. The workflow is active and
the repository is not disabled; the job is simply refused before any runner is
assigned. On a private repository that is what an exhausted Actions allowance or
a spending limit of zero looks like, and only the account owner can clear it at
https://github.com/settings/billing.

Until then a red check on this repository means "nothing ran", not "the tests
failed", and the two cannot be told apart from the badge. Read the job: zero
steps and `runner_id=0` is not a test result. Re-pushing does not help, and an
empty commit to retry is never the answer.

The substitute is to run what CI would run, against a fresh clone rather than a
working tree, on both a Python with Tk and one without, plus `compileall` on
3.11 to match the workflow's interpreter. Record which of those you actually
ran.

## Transition adapter contract

The desktop reaches the retained launcher through `importlib` and attribute
access, which neither `compileall` nor an AST import check can see, and which
unit-test stubs can satisfy with names that do not exist. Two constants shipped
that way: a context-window name that never existed and made every Chat start
raise, and `launcher.actions.searxng_action`, a package attribute rather than a
submodule, which made two maintenance buttons raise.

`src/tests/test_no_phantom_imports.py` now checks the dynamic references against
the real modules, so a rename on either side fails a test instead of a button.
Stubs in other tests mirror real constant names for the same reason.
