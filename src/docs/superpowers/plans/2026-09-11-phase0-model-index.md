# LocalAI architecture plan: Phase 0 model inventory slice

## Scope and reviewed baseline

The user-supplied LocalAI integrated/standalone architecture plan, sections 10-12,
24, 28-31 and 36, is the source of requirements. This patch implements the
canonical model inventory only. It does NOT complete Phase 0 or Phases 1-10.

Reviewed main: `0cbb00765e9f7c6aa3559d5113a1854fdac88939`.
The current installer uses a standalone Ollama ZIP in `llm_environment/ollama_runtime`;
`project_paths.py` still defaults to `C:\LLM_Models` (or `LLM_MODEL_DIR`).
The launcher rejects an unrelated listener. Therefore the plan's official
`C:\Ollama` installation, persisted model directory, copy/verify/preserve migration,
shared-server ownership and independent official-update requirements are NOT
already satisfied. Those must be completed and tested before the large app split.

No runtime, configured model path, user_data, AnythingLLM storage, Open Interpreter
session, Host/Sandbox policy or Block/Direct/WARP/Tor behavior is changed here.
No new provider, empty service stub, GUI or migration is introduced.

## Implemented tasks

- [x] Add `launcher.models.model_index` as a stdlib-only read-only scanner.
- [x] Preserve model -> manifest -> blobs and reverse references, including registry identity.
- [x] Count unique present logical bytes, shared/exclusive sizes, and missing/unavailable files.
- [x] Treat partial downloads and unreadable/invalid metadata conservatively; never authorize deletion.
- [x] Keep `FileRow`, CSV fields, role lookup, `scan`, `write_csv`, and `refresh` compatibility.
- [x] Make `refresh` publish canonical JSON and derived CSV from one in-memory inventory.
- [x] Use unique temporary files, flush/fsync and atomic per-file replacement.
- [x] Put CSV SHA-256 in JSON to detect interrupted/concurrent two-file mismatches.
- [x] Replace the destructive fixed-name write probe with a unique temporary probe.
- [x] Add a one-shot / explicit foreground polling command and behavior tests.
- [x] Use fresh `Path.lstat()` identities, not Windows `DirEntry.stat()` zero identities.
- [x] Distinguish inaccessible blob directories from proven missing files.
- [ ] Run the complete repository suite and real Windows/Ollama integration checks.
- [ ] Complete the remaining official-runtime Phase 0 requirements before the app refactor.

## Data and compatibility contract

`MODEL_INDEX.json` is the canonical output. `MODEL_FILES.csv` is a derived human
view with the existing column order, UTF-8 BOM and CRLF. Formula-like CSV labels
are escaped as text; JSON retains the raw labels. `refresh()` still returns the
CSV Path (or None on publication failure). Existing installer and model-management
refresh calls consequently produce both files. Direct `write_csv()` calls remain
CSV-only exports.

Schema version 1 includes generated_at, model_storage, models, blobs, files, errors,
scan_complete and unique store totals. `size_bytes` is logical file length, not
allocated disk blocks. Missing/unavailable declared sizes are excluded from
installed totals. Blob contents are not read or cryptographically verified.

Statuses: ok, missing, size_mismatch, partial, orphan, unknown, unavailable,
unreferenced_unknown. Symlinks/reparse points encountered in the scanned subtrees
are rejected. Invalid/inaccessible metadata makes orphan conclusions uncertain.
Even orphan means only an observed unreferenced candidate. A concurrent pull may
still need it. `deletion_safe` and `blob_hashes_verified` are always false.
The scanner is not a garbage collector or a transactional live-store snapshot.

Each output is replaced atomically; the pair is NOT a filesystem transaction.
JSON is published first with csv_sha256. A locked CSV may leave intact newer JSON
and intact older CSV; refresh returns None, the mismatch is detectable and a later
refresh repairs the pair. Concurrent writers have the same limitation.
Writable stores receive both files at the root. The existing user_data/models
fallback is preserved when the root is not writable. A missing store is never
created as a probing side effect.

## Running from the source checkout

Use the actual configured model directory, not an assumed future migration path.
In a Windows command prompt at the repository root:

```bat
set PYTHONPATH=%CD%\src
python -m launcher.models.model_index "C:\LLM_Models"
python -m launcher.models.model_index "C:\LLM_Models" --watch 5
```

Watch is explicit foreground polling, not an installed background service or an
instantaneous filesystem watcher. Ctrl+C returns 130; publication errors return 1;
invalid intervals return 2. Exit 0 confirms publication, not model health: inspect
scan_complete, errors and per-blob statuses in JSON.

## Verification evidence and limits

A sparse isolated source snapshot was assembled through the GitHub connector;
it is not a complete checkout. The original model_files.py and original
src/tests/test_model_files.py were verified against Git blob SHAs before testing.
No catalogue substitute was added to production.

- New behavior tests: 51 passing.
- Original model-files tests: 13 passing, 1 real-catalogue-dependent test deselected
  because model_catalog.py is not present in the sparse local snapshot.
- Combined result: 64 passed, 1 deselected.
- Compilation and `git diff --check`: passed for the patch files.
- Red/green evidence: the restored upstream failed 47 of the first 48 new tests;
  the implementation passed all 48. Windows identity and directory-permission
  review added two reproduced failures, then all 51 new tests passed.
- A separate injected role-boundary test passes, but does not replace the excluded
  real-catalogue test. Windows behavior was simulated at the filesystem API boundary;
  this is NOT a real Windows execution, Docker test or live Ollama test.
- No full-repository or overall architecture completion is claimed.

Commands (legacy test path is the byte-identical separately fetched file):

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest src/tests/test_model_index.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest src/tests/test_model_index.py /mnt/data/localai-work/upstream_tests/test_model_files.py -q -k 'not catalog_role_is_attached_when_the_model_is_known'
python -m compileall -q src/launcher/models src/tests/test_model_index.py
git diff --check
```

The repository's Windows CI should run the original test without deselection in
a complete checkout. No workflow configuration is changed by this patch.

## Remaining sequence from the supplied plan

Finish official Ollama discovery/installation, persisted OLLAMA_MODELS, verified
copy-first migration with source preservation, shared-server ownership and official
update validation. Then proceed to Core contracts, Model/Inference/Container
services, NetworkManager, Search/Chat/Agent services, compatibility integrations,
standalone apps, Studio, user-data migration and shared-library EXE packaging.
Preserve the existing Block fail-closed and Host/Sandbox boundaries throughout.

External verification used for the Windows identity fix:
https://docs.python.org/3.11/library/os.html#os.DirEntry.stat
