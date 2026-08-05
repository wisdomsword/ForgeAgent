# Context Limits and Execution Guidance Verification

## Result

The implementation passed the focused behavioral checks and the environment-
dependent failures were isolated. No product-code fix was required after the
final two-pass review.

## Evidence

- Focused regression: `742 passed, 10 skipped` across context, CLI, identity,
  protocol, Task, and HTTP tests.
- Full suite: `2953 passed, 23 skipped, 15 failed` in the restricted sandbox.
  The failures were loopback binding, audit-file permission, and `uv build`
  permission failures. The same affected group passed in an escalated rerun:
  `52 passed in 27.02s`.
- `ruff check src tests scripts`: passed.
- `ruff format --check src tests scripts`: reports only the pre-existing
  formatter diff in `tests/test_task.py`; `git diff b2716e2 -- tests/test_task.py`
  confirms the unrelated lines were not changed by this milestone.
- `mypy src`: unavailable in the environment (`Failed to spawn: mypy`).
- `openspec validate improve-context-limits-and-execution-guidance --strict`:
  passed.
- Real-model injected-audit REPL smoke in an in-repository temporary root:
  `repl-finished=true`, report exists, `Exec` evidence present, and the report
  contains 4 scanned files, 1 duplicate group, and 2 duplicate files. The
  second request used the same REPL session; its audit contained only `Exec`.
  The default TTY invocation was blocked before model execution because its
  default audit sink is `~/.forgeagent/audit.jsonl`, which requires explicit
  project-external write approval.

## Review

Two passes checked that the resolver preserves the existing formulas and
validation semantics; REPL rendering is interactive-only, secret-free, and
closes injected probes; candidate model/reload failures retain old state; and
the protocol keeps every ToolCall schema, runtime API, sandbox boundary, and
honest completion rule while adding Survey/Exec/file-delivery routing. The
diff contains only the planned source, tests, and Comet/OpenSpec artifacts.

The external config post-check confirms both authorized target lines are absent,
mode is `0600`, and `load_context_config` reports adaptive defaults. The
precheck filtered digest did not equal the post-edit digest; line-ending,
line-count, final-newline, and trailing-whitespace checks found no malformed
result, but byte-for-byte preservation of every non-target byte could not be
proven after the external edit and remains explicitly recorded as residual risk.
