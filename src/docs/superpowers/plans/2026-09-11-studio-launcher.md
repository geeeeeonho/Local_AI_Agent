# Studio and standalone launcher plan

Implement the supplied Studio / Chat / Interpreter / Setup design through one shared service composition. Preserve the existing model store, user_data, AnythingLLM data, Agent approval flow, Host/Sandbox policy and Block fail-closed implementation.

Order: service contracts and tests; compatibility integrations; persistent Tk views; unified source entrypoints; regression and visual verification; PR review and merge.

The desktop composition explicitly injects the currently active project_paths. It does not silently activate the separately staged official Ollama migration. User-data relocation and Windows EXE packaging are not part of this UI/launcher change.

Each app uses the same services. Existing runtime implementations remain behind transitional integration adapters rather than being copied. Runtime mutations are coordinated across windows. The real AnythingLLM UI is opened without iframe security changes; existing Open Interpreter panels retain the current approval and session behavior.

Verification must distinguish local related-source tests and real Tk tests from full-repository and native Windows/Docker/Ollama acceptance. Do not treat absent CI steps as passing tests.
