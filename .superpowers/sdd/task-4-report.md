# Task 4 Report: HTTP Loop mode

## Status

DONE

## RED

The first service-focused run failed on the missing mode projection and because the
worker assumed every result was a `TaskOutcome`:

```text
KeyError: 'mode'
AttributeError: 'str' object has no attribute 'reason'
5 failed, 1 passed, 17 deselected
```

The server assembly RED test then proved that Loop options still constructed an
ordinary `Task`:

```text
FAILED test_serve_factory_selects_server_owned_new_and_resumed_loop
assert isinstance(created, FakeRunner)
```

## GREEN

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_http_task_service.py tests/test_http_server.py tests/test_cli.py \
  tests/test_http_config.py tests/test_headless.py
467 passed, 10 skipped in 0.69s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check \
  src/forgeagent/http_task_service.py src/forgeagent/http_server.py \
  src/forgeagent/cli.py tests/test_http_task_service.py \
  tests/test_http_server.py tests/test_cli.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check \
  src/forgeagent/http_task_service.py src/forgeagent/http_server.py \
  src/forgeagent/cli.py tests/test_http_task_service.py \
  tests/test_http_server.py tests/test_cli.py
6 files already formatted

git diff --check
passed
```

The ten skips are existing loopback-bind environment skips. Handler tests run over
socket pairs and cover the Loop request schemas without weakening network tests.

## Scope

- `src/forgeagent/http_task_service.py`
- `src/forgeagent/http_server.py`
- `src/forgeagent/cli.py`
- `tests/test_http_task_service.py`
- `tests/test_http_server.py`

`tests/test_cli.py` required no modification; its existing serve regressions pass.

## Risk Signals

- `/tasks` remains the sole submission endpoint and accepts exactly ordinary Task,
  full new-Loop, or resume-Loop key sets. Unknown and security-sensitive fields fail
  before service submission; numeric validation rejects bool, non-finite, and
  non-positive values.
- HTTP derives checkpoint storage solely from configured `allowed_root`. A new Loop
  uses the server task ID as its Loop ID; resume accepts only a 32-character lowercase
  hex ID. No caller-supplied path, tier, model, identity, confirmer, or credential is
  forwarded.
- `TaskRecord` stores `LoopReport` privately. Public terminal views expose only mode,
  stable status/stop reason, Loop ID, and bounded counters; running views do not
  fabricate counters or expose checkpoint text/path, goal, handoff, or failure text.
- The existing registry owns queued/running/cancelled/TTL/capacity lifecycle for both
  modes. A process-local active Loop ID map rejects overlapping same-ID submissions
  before constructing a second runner and releases the ID on every terminal path.
- Loop runner close is sufficient at the service boundary. Each Loop iteration owns
  and closes its Task and client together; ordinary Task retains the existing
  Task-then-client cleanup behavior.
