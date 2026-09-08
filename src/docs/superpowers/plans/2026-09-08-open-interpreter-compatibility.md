# Open Interpreter Compatibility Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evaluate a future Open Interpreter 0.0.42 candidate without destabilizing the security-hardening baseline.

**Architecture:** Keep `runtime_versions.py` pinned to 0.0.38 until a real 0.0.42 release/candidate is available and the complete matrix passes. Reuse current App Server JSONL/stdio transport for evaluation. SDK migration is a separate decision/PR.

**Tech Stack:** Open Interpreter standalone Rust distribution, App Server v2 JSONL/stdio, Ollama, Docker Desktop, pytest, Windows integration scripts.

**Spec:** User-provided `Local_AI_Agent 전환 완료 후 보안·구조 보완 지시서` (2026-09-08), Phase 4.

---

## Task 1 — Preserve the 0.0.38 baseline

- Do not edit `src/runtime_versions.py` in the security PR.
- Add/retain a structure assertion that the OI version assignment has one source.
- Record current 0.0.38 App Server protocol fields used by start/resume, including arbitrary `config` overrides.

## Task 2 — Add a version-parameterized compatibility harness

**Files:**
- Add under `src/tools/` a compatibility runner that accepts a candidate interpreter executable/version without changing the product pin.
- Add unit tests for command construction and result reporting.

Matrix:
- initialize / initialized
- thread/start
- Ollama provider
- turn/start and text/reasoning streaming
- command execution and file changes
- approval request + accept/decline
- turn/interrupt
- native thread ID + thread/resume
- MCP startup + local_search
- WARP/Tor environment propagation
- Host Permission Profile
- Sandbox Docker
- Block

## Task 3 — Evaluate 0.0.42 only when a real candidate exists

1. Download/install the candidate into a temporary isolated location.
2. Run the complete matrix on Windows.
3. Keep 0.0.38 if any required row fails or candidate provenance cannot be verified.
4. Only after all rows pass, open a dedicated version-bump PR.

## Task 4 — SDK migration remains separate

Compare current `AppServerClient` with the official Python integration/SDK only in another PR. Evaluate streaming, approvals, cancellation, resume, lifecycle, stderr, timeout, proxy env, custom `INTERPRETER_HOME`, MCP, `AgentEvent` conversion, API stability, and maintenance reduction. Remove `app_server_client.py` only if the SDK fully replaces it.
