# Task 3 Report: Read-Only Skill Protocol and Conditional Registration

## Implementation

- Added `SkillArgs` to the dynamic protocol schemas. Names use the required
  non-path-like pattern and sections are limited to `full`, `steps`,
  `failure_branches`, and `completion_criteria`.
- Added low-risk `SkillTool`, which reads one immutable `SkillRegistry` section
  and exposes the existing bounded-feedback fields (`continuation` and
  `truncation_mode="head"`). Unknown valid names return the recoverable
  `Skill is unavailable` outcome.
- Extended `default_registry` with an optional `skills` snapshot. `Skill` is
  registered only when that snapshot has a non-empty catalog, so existing
  parsing behavior is unchanged without a registry.

## TDD Evidence

- RED: `rtk uv --cache-dir /tmp/forgeagent-m19-uv-cache run pytest tests/test_protocol.py tests/test_tools.py -k skill -v`
  failed during collection exactly because `SkillArgs` did not exist in
  `forgeagent.protocol` (and therefore `SkillTool` could not yet be imported).
- GREEN: the same command passed: `4 passed, 53 deselected`.
- Full changed-module coverage:
  `rtk uv --cache-dir /tmp/forgeagent-m19-uv-cache run pytest tests/test_protocol.py tests/test_tools.py -q`
  passed: `57 passed in 0.09s`.

## Verification

- `rtk uv --cache-dir /tmp/forgeagent-m19-uv-cache run ruff check src/forgeagent/protocol.py src/forgeagent/tools.py tests/test_protocol.py tests/test_tools.py`: passed.
- `rtk uv --cache-dir /tmp/forgeagent-m19-uv-cache run ruff format --check src/forgeagent/protocol.py src/forgeagent/tools.py tests/test_protocol.py tests/test_tools.py`: passed (`4 files already formatted`).
- `rtk git diff --check`: passed.
- Full suite: `rtk uv --cache-dir /tmp/forgeagent-m19-uv-cache run pytest -q`
  completed with `1379 passed, 23 skipped, 13 failed in 65.04s`.
  The failures are unrelated sandbox constraints: eleven M16 blackbox tests and
  one golden-runner test cannot allocate loopback ports (`PermissionError:
  Operation not permitted`); the packaging test's nested `uv build` exits 2.
  The failures do not involve the Skill protocol or tool modules.

## Self-Review

- No filesystem paths, confirmation handling, audit-content handling, parser
  branches, Task/Step wiring, dependencies, or new abstractions were added.
- `SkillTool` is `low` risk and only delegates to the immutable registry read
  API. It does not touch `ToolContext` capabilities.
- Tests cover malformed names and undeclared sections, normal section reads,
  recoverable unknown names, empty-registry omission, conditional parser
  validation, and continuation metadata.

## Files

- `src/forgeagent/protocol.py`
- `src/forgeagent/tools.py`
- `tests/test_protocol.py`
- `tests/test_tools.py`
- `.superpowers/sdd/task-3-report.md`

## Concern

The full suite cannot pass inside this sandbox because loopback binding is not
permitted and nested packaging builds fail there. The focused protocol/tool
suites and all static checks pass.
