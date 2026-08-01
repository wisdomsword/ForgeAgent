# M47 Task 2 Implementation Report

Status: DONE

Implementation commit: `98baaf8`
Review-fix commit: pending

## Changes

- `run_once` now closes its owned client after `Task.close()` and also closes clients when context preflight or task construction fails.
- `run_smoke` now closes every per-goal task before closing the model client, including terminal failures and exceptions.
- `run_evaluate_command` now keeps client ownership in one `finally` boundary covering manifest/preflight failure, evaluator failure, persistence failure, and normal rendering.
- HTTP task factories now close request-scoped clients when task construction fails; existing service-owned task/client shutdown ordering remains unchanged.
- Added lifecycle regression tests for success, preflight, persistence, smoke, and task/client ordering.
- Review follow-up covers stream callback setup, evaluator import, and regular/loop/collaboration HTTP Task construction failures.

## TDD Evidence

- RED: focused lifecycle tests failed 5/5 before implementation: clients were not closed by `run_once`, smoke, or evaluate paths (`close_calls == 0` / missing client close events).
- GREEN: focused lifecycle tests -> `5 passed`; CLI/HTTP/collaboration lifecycle suite -> `487 passed in 6.34s`.

## Risk Signals

- Existing shared REPL and HTTP service resources remain owned by their session/service shutdown paths; this task only closes request-scoped or entry-point-owned clients.
- The HTTP task factory still relies on `TaskService._close_task_resources` for normal task completion; construction failures are now explicitly covered at the factory boundary.
