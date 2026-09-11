# Studio and standalone launcher implementation plan

Goal: replace the flat desktop launcher with a persistent multi-view shell and
four source entrypoints using one shared service composition.
Spec: the user-supplied LocalAI integrated/standalone architecture plan in this conversation.

## Scope and compatibility boundary

- Adopt the previously delivered Core/service foundation, but explicitly inject
  current project_paths into the desktop composition. Do NOT silently activate
  C:\Ollama, migrate models, relocate user_data, or change network security code.
- The official-runtime preparation remains staged. Native Windows acceptance of
  that path is not implied by this UI change. Source entrypoints are not EXEs.
- Existing Tk Presenter and Agent panel remain UI compatibility adapters. Existing
  RuntimeCoordinator, host approval, protected DNS, Block quiescence, internal
  network verification, and Host Block refusal remain authoritative.
- Apps import services, not launcher actions or product runtimes. Transitional
  integrations alone may call the existing implementation.
- Shared managed network resources have one session owner per checkout. Other
  windows may inspect state; incompatible runtime mutations are refused rather
  than killing another window's session. Ollama API remains publicly usable on
  localhost by other local programs.

## Execution checklist

- [x] Service tests: safe startup, runtime guard, strict network mode handling,
      Block fail-closed, shared data paths, explicit downloads and cancellation.
      Run: PYTHONPATH=src python -m pytest -q src/tests/test_desktop_services.py
- [x] Shared service composition and lazy legacy integration. No new runtime.
- [x] Persistent Studio views and standalone app specifications. Keep Agent/Chat
      panels alive across navigation. Worker results reach Tk via a queue.
- [x] Entrypoints: RUN -> Studio; Chat/Interpreter/Setup -> same composition;
      preserve installer flags and explicit legacy TUI path.
- [x] Real Tk/Xvfb tests: navigation, settings/projects persistence, model list,
      busy actions, close cancellation, per-app view restrictions.
- [x] Re-run available foundation and UI suite, compile and patch checks; verify
      remote file hashes and main/head freshness before any PR merge.

Native Windows, Docker/Ollama/AnythingLLM/Open Interpreter end-to-end and the full
repository suite must be separately reported, never inferred from sparse tests.

## Implemented desktop slice

- Persistent shared Tk shell with nine Studio views and independent Chat,
  Interpreter and Setup source entrypoints.
- Shared project/settings/event contracts and desktop service composition;
  active paths injected from existing project_paths, not the staged migration.
- Single-window runtime ownership, verified session shutdown and tracked Agent
  startup over the retained coordinator/controller/approval implementations.
- Central model service and loopback-only Ollama API transport, unchanged
  canonical model index, explicit installation/repair only.
- Mode-specific Search integration over canonical Docker primitives, preserving
  source settings and refusing unrecognized custom proxy layouts.
- RUN/SETUP forwarding, thin standalone aliases and retained explicit terminal /
  installer compatibility paths. Original runtime implementation files retained.

## Review and verification limits

Test regressions were run before fixes for service startup, policy failures,
shutdown races, configuration freshness and unified entrypoints. Real Tk tests
exercise shared/persistent views with injected external services. The related
source snapshot also exercises Core process locks and original model indexing.
See STUDIO.md for commands and exact user-visible boundaries.

No independent subagent reviewer or complete repository checkout was available
in the authoring environment. Full Windows/Docker/Ollama acceptance remains a
separate validation requirement, not implied by the focused suite. Do not count
tests from the unpublished official installer draft as tests of this UI release.

Focused release verification: 164 tests passed with no exclusions on Linux /
Python 3.13 and a real Tk/Xvfb display; Python 3.11 grammar was also checked.
The unchanged original model-index tests are included; the complete repository
suite and live Windows/Docker acceptance are not included in that count.
