# Task 1 Report: bounded MCP startup diagnostics

## Status

`DONE_WITH_CONCERNS`

## RED

To preserve a real pre-implementation baseline, cloned the committed `HEAD` into
`/tmp/forgeagent-task1-red.PD1kIu`, copied the current
`tests/test_mcp_manager.py` into that clone, then ran:

```sh
uv run --directory /tmp/forgeagent-task1-red.PD1kIu pytest tests/test_mcp_manager.py -q -k 'bounded_stderr_capture or diagnostics or generation'
```

The test collection failed as expected with:

```text
ImportError: cannot import name '_BoundedStderrCapture' from 'forgeagent.mcp_manager'
```

## GREEN

Implemented a per-holder bounded stderr pipe reader, fixed diagnostic projection,
generation-bounded publication, and lifecycle cleanup. The public diagnostic
projection never stores or returns raw stderr or exception text.

Verified with:

```text
uv run pytest tests/test_mcp_manager.py -q -k 'bounded_stderr_capture or diagnostics or generation or close_terminates_child_processes'
17 passed, 181 deselected in 0.88s

uv run pytest tests/test_mcp_manager.py -q
197 passed, 1 skipped in 5.53s

uv run ruff check src/forgeagent/mcp_manager.py tests/test_mcp_manager.py
All checks passed!
```

## Files

- `src/forgeagent/mcp_manager.py`
- `tests/test_mcp_manager.py`

## Self-review

- `_BoundedStderrCapture` drains beyond 8192 bytes, decodes invalid UTF-8 with
  replacement, and closes its writer before joining its daemon reader.
- Failure publication is guarded by the holder generation and uses only fixed
  diagnostic codes. A stale generation cannot replace the newer state.
- The fixed `MCPServerDiagnostic` projection uses public server labels, masked
  status, deterministic configured-server order, and fixed user-facing prose.
- Success, cancellation, and close paths are covered by the focused lifecycle
  tests; no reader thread remains after capture close.

## Risk Signals

- Concurrency/locking: the capture buffer is lock-protected and reader cleanup is
  joined; generation checks protect stale holders. This is covered by unit tests,
  but production subprocess timing remains inherently asynchronous.
- Public diagnostic API: `MCPManager.diagnostics()` adds a stable projection; its
  dataclass field contract is now externally visible and should be treated as
  compatibility-sensitive.
- Diff size: the two-file diff is greater than 200 lines (399 lines before this
  report), primarily due to explicit lifecycle and boundary tests. It is larger
  than the desired minimal surface, but directly corresponds to the requested
  capture, projection, and regression coverage.

## Commit

Pending commit: `feat: add bounded MCP startup diagnostics`
