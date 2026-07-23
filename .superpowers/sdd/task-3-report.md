# Task 3 Report: Startup Summary, MCP Details, and Sanitized Startup Errors

## Implementation

- Changed `build_mcp_manager()` to accept no `Console`, emit no startup output, retain bounded connect/required cleanup, and return only fixed `MCPStartupError` codes: `startup_failed` or `required_server_unavailable`.
- Sanitized cleanup logs to fixed messages without exception type, raw `ExceptionGroup`, command, arguments, environment, secret, or path content. `KeyboardInterrupt` and `SystemExit` are preserved, including when nested in a `BaseExceptionGroup`.
- Added `_render_startup_summary()` for interactive startup: selected model, sandbox tier, resolved project root, enabled-server MCP numerator/denominator, and one fixed optional degradation line per unavailable optional server. Disabled servers are excluded.
- Moved MCP output ownership to the REPL and added bare `/mcp` diagnostic details rendered with `Text`; `/mcp status`, `/mcp tools`, `/mcp enable`, `/mcp disable`, and timeout pending behavior remain accepted.
- `main()` now routes startup/config/container/identity/MCP errors through a separate stderr `Console`; normal task output remains stdout. `MCPStartupError` normalizes hostile constructor input to a fixed code.

## TDD Evidence

- RED: the initial focused contract run failed 7 tests: missing startup summary, builder still requiring `Console`, builder output ownership, old bare `/mcp` rendering, and stdout startup-error routing.
- GREEN: the focused contract run passed `7 passed` after the minimal implementation.
- RED: hostile `BaseExceptionGroup` and hostile `MCPStartupError` boundary tests failed 4 tests: raw exception groups escaped and hostile error text reached stderr.
- GREEN: fixed-code normalization and recursive process-control extraction passed `4 passed`.
- RED/GREEN: `/mcp tools` behavior failed `1 failed`, then passed after adding the minimal branch.

## Verification

- `UV_CACHE_DIR=/tmp/forgeagent-task3-uv-cache rtk uv run pytest tests/test_cli.py -q -k "build_mcp_manager or startup_summary or optional_failure or required_mcp or mcp_command or runtime_toggle_of_required or mcp_slash or exception_group"`: **41 passed, 192 deselected**.
- `UV_CACHE_DIR=/tmp/forgeagent-task3-uv-cache rtk uv run pytest tests/test_cli.py -q`: **233 passed**.
- `UV_CACHE_DIR=/tmp/forgeagent-task3-uv-cache rtk uv run pytest tests/test_mcp_manager.py -q`: **211 passed, 1 skipped**.
- `UV_CACHE_DIR=/tmp/forgeagent-task3-uv-cache rtk uv run ruff check src/forgeagent/cli.py tests/test_cli.py`: passed.
- `UV_CACHE_DIR=/tmp/forgeagent-task3-uv-cache rtk uv run ruff format --check src/forgeagent/cli.py tests/test_cli.py`: passed; both files already formatted.
- `git diff --check`: passed.

## Carried Finding Closure

Task 1 carried a Critical finding that `cli.py` formatted exception types in the startup boundary. This is closed: connect and required failures now expose fixed codes only; cleanup warnings are fixed category messages; nested non-control exception groups are sanitized; process-control exceptions are preserved; no later manager handle is exposed on required startup failure.

## Files and Commits

- Modified: `src/forgeagent/cli.py`, `tests/test_cli.py`.
- Implementation commit: `4f9c694` (`feat: report MCP startup capability safely`).
- This report is committed separately after the implementation commit.

## Self-Review and Risk Signals

- No new dependency, configuration surface, manager abstraction, or global cleanup registry was added.
- Public diagnostic fields are rendered as literal `Text`; raw manager status and child failure text are not projected into startup summary or bare `/mcp` output.
- Remaining risk signal: MCP lifecycle behavior is concurrency-sensitive and remains owned by Task 1's manager implementation; this task only consumes its diagnostics tuple and bounded close contract.
- Task 4 non-TTY reader/blackbox behavior was not changed.
