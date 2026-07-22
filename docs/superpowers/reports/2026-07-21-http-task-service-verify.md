# M16 HTTP Task Service Verification

Date: 2026-07-22

## Acceptance coverage

- The no-bind HTTP handler harness used `socket.socketpair()` and the real
  `ForgeRequestHandler` request loop with complete request lines, Bearer headers,
  JSON framing, and response parsing. It submitted eight tasks concurrently,
  observed eight distinct task ids, verified all eight were `queued` or `running`
  while workers were deterministically blocked, then polled each `GET /tasks/{id}`
  to a terminal state under a five-second deadline. Every terminal projection
  retained its own id.
- TaskService shutdown was checked for worker/cleanup thread exit and one-time shared
  MCP manager close.
- Offline golden G13 used equivalent MockClient scripts through direct Task and the
  complete socketpair HTTP `POST /tasks` plus polled `GET /tasks/{id}` path. Both
  produced `completed`, three rounds, and two tool outcomes; the HTTP projection
  omitted tool stdout, errors, and model text.
- Existing tests continue to cover capacity/TTL, strict schema, exact typed allowlist,
  cancellation races, safe result projection, and audit masking/degraded behavior.
- The real `serve` task factory was exercised through `Task`, `Step`, and `MCPTool`
  with an empty HTTP allowlist and an MCP server-side `autoApprove` entry. The HTTP
  path neither queried that entry nor executed the operation: `serve` explicitly
  disables MCP auto-approval while CLI/REPL tasks retain the compatible default.

## Commands and results

| Command | Result |
| --- | --- |
| `.venv/bin/ruff check src tests` | PASS: exit code 0 (`All checks passed!`) |
| `.venv/bin/ruff format --check tests/test_http_server.py tests/test_mock_replay_e2e.py` | PASS: both changed test files formatted |
| `.venv/bin/pytest -q tests/test_http_server.py tests/test_mock_replay_e2e.py` | PASS: 62 passed, 10 skipped |
| Focused HTTP auto-approval regression, tools, and headless tests | PASS: 63 passed |
| Focused concurrency/shutdown/golden command repeated five times | PASS: 3 passed per run, 5/5 runs |
| `.venv/bin/python -m tests.golden.runner` | PASS: exit code 0; generated `artifacts/golden/offline/report.md` records 20/20 (100%) |
| `openspec validate http-task-service --strict` | PASS: exit code 0 (`Change 'http-task-service' is valid`) |
| `git diff --check` | PASS: exit code 0, no output |
| `PYTHONPATH=src .venv/bin/pytest -q --ignore=tests/test_packaging.py` | PASS: exit code 0; 1221 passed, 23 skipped in 50.99s |
| `PYTHONPATH=src .venv/bin/pytest -q tests/test_packaging.py` | Environment failure: 1 failed, 2 passed in 8.14s; `uv build` exited 2 |
| `UV_CACHE_DIR=/tmp/forgeagent-m16-final-uv-cache uv build --out-dir /tmp/forgeagent-m16-final-build` | Environment failure: after three retries, `https://pypi.org/simple/hatchling/` could not be fetched because DNS lookup failed |

The repository-wide format check also reports six pre-existing files that would be
reformatted (`executor.py`, `model_discovery.py`, `protocol.py`, and three existing
tests). Task7's changed Python files pass the format check; unrelated files were not
rewritten.

The ten focused skips are the existing real-loopback HTTP tests. This execution
environment rejects `bind(('127.0.0.1', 0))` with `PermissionError: [Errno 1]
Operation not permitted`. The tests still attempt the real bind and skip only for
that explicit permission failure. The handler/framing/concurrency suite runs without
a listener and passed. This is an environment restriction, not evidence that a real
listener ran successfully here.

The whole-change re-review after commit `f4a3ef7` passed with no Critical or
Important findings.

## Security boundaries and residuals

- FileWrite uses canonical path validation before pathname open; a hostile concurrent
  symlink replacement can still create a TOCTOU race.
- Cancellation is cooperative and cannot interrupt an in-flight provider operation.
- Startup audit compaction can read a whole old log file into memory.
- Unix path behavior is covered; Windows UNC paths have no dedicated acceptance run.
- A client disconnect while an error envelope is written may cause a socketserver
  diagnostic traceback outside the response.
- Real bind permission and packaging DNS are verification-environment limitations,
  not product fallbacks or relaxed runtime behavior.
