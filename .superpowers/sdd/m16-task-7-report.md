# M16 Task 7 Report

Implemented the M16 documentation and security-acceptance layer.

## Changes

- Added the HTTP service runbook with configuration priority, restart semantics,
  routes/schema, bounded projection, cancellation, typed allowlist, audit lifecycle,
  owner shutdown, and residual risks.
- Added the HTTP threat-model boundary and a short README entry.
- Added complete socketpair `ForgeRequestHandler` request-loop coverage for concurrent
  handler isolation, shutdown resource cleanup, and offline golden parity. Requests
  include real request lines, Bearer authentication, JSON framing, and parsed HTTP
  responses without binding a network port.
- Made existing real-loopback tests skip only when the environment explicitly denies
  `bind()` with `PermissionError`; no-bind protocol tests remain mandatory.
- Recorded verification evidence in
  `docs/superpowers/reports/2026-07-21-http-task-service-verify.md`.

## TDD evidence

The first concurrent real-loopback acceptance run failed at server construction with
`PermissionError: [Errno 1] Operation not permitted`. The acceptance was moved to a
no-bind handler harness and passed (2/2 new concurrency/shutdown tests). The golden
parity test first failed because its leak assertion searched for the single character
`4`, which also occurs in random task ids; the assertion was narrowed to actual raw
tool markers (`stdout`, `NameError`, and `undefined_variable`) and then passed.
The first complete socketpair harness run also timed out while waiting for EOF because
the peer socket remained open; response `Content-Length` framing and explicit handler
socket closure were added, after which the real request loop passed reliably.

## Verification

- Ruff check: PASS.
- Changed-file format check: PASS.
- Focused HTTP/golden tests: 62 passed, 10 environment skips.
- Golden runner: exit code 0; its generated offline report records 20/20 (100%).
- OpenSpec strict validation and `git diff --check`: PASS.
- Full non-packaging pytest did not produce a completion summary in this sandbox; it
  ended at 46% without printing a test failure. This is recorded as incomplete, not
  as passing.
- Packaging: 2 passed, 1 environment failure; `uv build` cannot resolve `hatchling`
  because PyPI DNS lookup is unavailable.
