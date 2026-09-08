# Direct Fetch IP Pinning + Unicode URL Plan

> **Scope:** Phase 2 only. No Host permission lifecycle, OI version/SDK, Docker abstraction, or UI changes.

## Goal

Make Direct/WARP/Tor share the same outbound invariant:

```text
validated public IP == actual TCP connect target
```

Also normalize IDN hostnames and Unicode path/query text into an ASCII-safe HTTP request without double-encoding existing percent escapes.

## Tasks

1. Add URL normalization tests for IDNA hostnames, Korean path/query, mixed ASCII/Unicode query, existing `%XX`, and fragment removal.
2. Add Direct request tests proving literal-IP TCP connection while TLS SNI/Host use the normalized original hostname.
3. Implement `direct_request(ValidationResult)` beside `protected_request()` and share request-target/Host-header generation.
4. Replace urllib public Direct fetch with application-level redirect handling. Every redirect must repeat privacy check, URL validation, public-IP check, and literal-IP connection.
5. Apply privacy checks to both the raw redirect URL and normalized URL before request I/O.
6. Add regressions for DNS rebinding/second-resolution avoidance, redirect-to-private blocking, Unicode redirect, and sensitive Unicode URL blocking.
7. Run focused web/search tests, then full suite. Windows Actions remains the final CI gate when runners are available.
