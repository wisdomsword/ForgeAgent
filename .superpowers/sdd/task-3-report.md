# Task 3 Report: CLI Loop command

## Status

DONE

## RED

The first focused test run failed during collection before the command existed:

```text
ImportError: cannot import name 'run_loop_once' from 'forgeagent.cli'
```

## GREEN

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q tests/test_cli.py -k 'loop'
14 passed, 249 deselected

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_cli.py tests/test_task.py tests/test_cli_startup_blackbox.py \
  tests/test_loop_runner.py
322 passed

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check \
  src/forgeagent/cli.py tests/test_cli.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check \
  src/forgeagent/cli.py tests/test_cli.py
2 files already formatted

git diff --check
passed
```

`tests/test_startup_information.py` from the plan is not present in this checkout;
the equivalent existing startup regression file is `tests/test_cli_startup_blackbox.py`.

## Scope

- `src/forgeagent/cli.py`
- `tests/test_cli.py`

Committed as `798173e feat: expose loop CLI` and self-review correction
`94782b2 fix: retain supplied loop console`.

## Risk Signals

- CLI output deliberately renders only the `LoopReport` projection. It never renders
  the frozen goal, checkpoint path/body, handoff, failure text, or model output.
- The LoopRunner tool registry receives the existing MCP and skills snapshots through
  the Task2 follow-up commit `0f8ecde`; no ordinary `run` or REPL code path creates a
  checkpoint or imports the evaluator.
- Self-review caught that a supplied empty `Console(record=True)` is falsey. The renderer
  now checks explicitly for `None`, retaining the supplied console and its safe output.

## Review Fix 1: Cooperative CLI Ctrl+C

### RED

The deterministic SIGINT test invoked the active handler while a Loop Task was running.
Before the fix, the combined cancellation signal passed to the Task remained unset:

```text
FAILED tests/test_cli.py::test_run_loop_once_sigint_requests_cancel_and_restores_handler
E assert False
E  + where False = cancel_event.is_set()
```

### GREEN

`run_loop_once()` now installs a main-thread SIGINT handler for the duration of
`LoopRunner.run()`. The first signal sets a `threading.Event` passed to the runner; a
second signal delegates to the previous callable handler or raises `KeyboardInterrupt`.
The previous handler is restored in `finally`. If signal installation raises `ValueError`
outside the main thread, the existing behavior is preserved.

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q \
  tests/test_cli.py tests/test_task.py tests/test_cli_startup_blackbox.py \
  tests/test_loop_runner.py
324 passed in 3.81s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check \
  src/forgeagent/cli.py tests/test_cli.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check \
  src/forgeagent/cli.py tests/test_cli.py
2 files already formatted

git diff --check
passed
```

The test verifies CLI exit code 1, durable `cancelled` checkpoint status and stop reason,
handler restoration, second-interrupt escalation, and the non-main-thread fallback. It
does not claim an in-flight model/tool call is immediately interruptible; persistence
occurs at the runner's next cooperative safe boundary.
