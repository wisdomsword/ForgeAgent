# M16 HTTP Task Service Verification

Date: 2026-07-22

## Acceptance coverage

- The no-bind HTTP handler harness submitted eight tasks concurrently, observed eight
  distinct task ids, and verified that every terminal projection retained its own id.
- TaskService shutdown was checked for worker/cleanup thread exit and one-time shared
  MCP manager close.
- Offline golden G13 used equivalent MockClient scripts through direct Task and
  TaskService paths. Both produced `completed`, three rounds, and two tool outcomes;
  the HTTP projection omitted tool stdout, errors, and model text.
- Existing tests continue to cover capacity/TTL, strict schema, exact typed allowlist,
  cancellation races, safe result projection, and audit masking/degraded behavior.

## Commands and results

| Command | Result |
| --- | --- |
| `.venv/bin/ruff check src tests` | PASS (`All checks passed!`) |
| `.venv/bin/ruff format --check tests/test_http_server.py tests/test_mock_replay_e2e.py` | PASS (`2 files already formatted`) |
| `.venv/bin/pytest -q tests/test_http_server.py tests/test_mock_replay_e2e.py` | PASS: 62 passed, 10 skipped |
| `.venv/bin/python -m tests.golden.runner` | PASS: offline report 20/20 (100%) |
| `openspec validate http-task-service --strict` | PASS |
| `git diff --check` | PASS (no output) |
| `.venv/bin/pytest -q --ignore=tests/test_packaging.py` | INCOMPLETE in this sandbox: process ended at 46% with no pytest failure summary; no individual failure was printed |
| `.venv/bin/pytest -q tests/test_packaging.py` | 2 passed, 1 failed because `uv build` could not resolve build requirements |
| `UV_CACHE_DIR=/tmp/forgeagent-task7-uv-cache uv build --out-dir /tmp/forgeagent-task7-build` | Environment failure: DNS lookup for `https://pypi.org/simple/hatchling/` failed after three retries |

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
