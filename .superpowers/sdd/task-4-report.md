# Task 4 Self-Review Report

## Status

Implemented non-TTY input and process-level startup output contracts.

- REPL no longer emits the interactive banner on startup.
- Default non-TTY input and explicitly injected readers receive an empty prompt.
- The `forge> ` prompt remains limited to the real default interactive REPL.
- MCP startup remains active for piped goals, including optional degradation and
  required failure handling.
- The MCP fixture has synthetic `startup_chatter` and `docker_failure` modes; no
  Docker daemon or real secret is required.
- Added subprocess black-box coverage for pipe quit, optional MCP stderr isolation,
  a real fixture MCP call, and sanitized required startup failure.

## TDD Evidence

### RED

Command:

`rtk pytest tests/test_cli_startup_blackbox.py tests/test_cli.py -q -k "pipe or non_tty or startup_bytes or required_mcp_failure"`

Result: `3 passed, 6 failed`.

Observed failures were the expected missing behaviors: piped startup bytes and
`forge> ` prompts, plus the new non-TTY prompt assertion.

### GREEN

Command:

`rtk pytest tests/test_cli_startup_blackbox.py tests/test_cli.py -q -k "pipe or non_tty or startup_bytes or main_reports_required_mcp_startup_error or run"`

Result: `42 passed`.

The pipe-goal test uses a temporary subprocess launcher with `MockClient`, starts
the synthetic MCP fixture, executes the auto-approved `fixture:echo` call, and then
returns `PIPE_RESULT`. It verifies task output contains the MCP result while startup
banner, prompt, readiness summary, and optional failure text are absent.

## Self-Review

- Production diff is limited to `src/forgeagent/cli.py`; no dependency, config,
  production test hook, or new abstraction was added.
- Explicit readers preserve existing EOF, KeyboardInterrupt, empty-input,
  confirmation, and Survey behavior; only the goal prompt argument is empty.
- Non-TTY REPL still calls `build_mcp_manager()`, so connected MCP capabilities are
  available to piped tasks.
- Required MCP failures remain represented by fixed `MCPStartupError` codes and are
  rendered through the dedicated stderr console; no child stderr is projected.
- Fixture stderr is synthetic and test-only. The temporary model launcher is written
  under pytest's temporary directory and is not part of the repository.

## Verification

- Focused RED/GREEN coverage: `42 passed`.
- Full CLI plus black-box coverage: `243 passed`.
- `rtk .venv/bin/ruff check src/forgeagent/cli.py tests/test_cli.py
  tests/mcp_fixture_server.py tests/test_cli_startup_blackbox.py`: passed.
- `rtk .venv/bin/ruff format --check src/forgeagent/cli.py tests/test_cli.py
  tests/mcp_fixture_server.py tests/test_cli_startup_blackbox.py`: passed.
- `tests/test_mcp_manager.py`: `210 passed, 1 failed, 1 skipped` in the final
  full-suite run. Two final isolated reruns reproduced the same failure:
  `test_capture_entry_failure_is_closed_and_marks_holder_unavailable` indexes a
  holder already removed by the failure cleanup path. No manager source or manager
  test was changed for Task 4.

## Risk Signals

- A true OS-level TTY integration run was not performed in the sandbox. Existing
  unit tests still cover prompt-toolkit reader construction and startup display
  gating.
- A local HTTP model server was not used because this sandbox forbids binding local
  sockets; the black-box goal path instead uses a temporary in-process client
  launcher while the MCP server remains a real subprocess.
- The manager-suite failure is outside the Task 4 file scope and remains an
  unresolved verification signal for the owning MCP lifecycle work.

## Review Remediation

Addressed the Task 4 review findings without changing production code or fixture
behavior.

### RED

Command:

`uv run pytest tests/test_cli_startup_blackbox.py -q -k pipe_goal`

Result: `1 failed, 4 deselected`.

The deliberately incomplete `b"PIPE_RESULT\\n"` stdout expectation failed against
the real subprocess bytes. The failure established that the task-result contract is
the exact sequence of completion status, `MCP fixture:echo` result, `PIPE_RESULT`,
and usage line, with no startup bytes.

### GREEN

Command:

`uv run pytest tests/test_cli_startup_blackbox.py tests/test_cli.py -q -k "pipe or non_tty or startup_bytes or main_reports_required_mcp_startup_error or run or noninteractive_commands or serve_builds_server_owned"`

Result: `47 passed, 196 deselected`.

- The pipe-goal black-box test now asserts every stdout byte, closing the gap left
  by a denylist of startup strings.
- `run`, `serve`, `models`, and `smoke` have focused regression coverage that fails
  if they construct the REPL Logo or startup-summary paths, and each asserts no
  `ForgeAgent`, `Ready |`, or MCP summary output.
- The `serve` lifecycle test additionally captures its real command output while
  retaining the existing fake listener/service boundary, so it remains independent
  of Docker, sockets, and external network access.
