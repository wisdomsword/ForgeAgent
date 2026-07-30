# Task 3 Report: MCPTool receipt state machine

## Status

DONE_WITH_CONCERNS. Implemented receipt threading and protected MCP transitions in commit `01129a8`.

## Verification

RED: new receipt tests initially failed because `ToolContext.receipt_store` was absent.
GREEN: `uv run pytest tests/test_tools.py tests/test_task.py tests/test_step.py -q` -> `141 passed, 1 warning`.

The Pydantic `schema` field shadowing warning remains known. Full suite and Ruff for this task were not run.

## Risk signals

- Cross-module, security-sensitive external dispatch, public context API, and diff over 200 lines: YES.
- No PyPI or release files changed.

<!-- Legacy stale report content below intentionally retained for audit history. -->

## Outcome

DONE. The repository now has a single `0.1.0` Release Candidate entry point,
a short README link near current verification, and an explicit separation
between the configured M28 installed-wheel Linux gate and historical M24
container-only evidence.

## Changed Product Files

- `docs/releases/0.1.0-rc.md`
- `README.md`
- `docs/platform-support.md`
- `tests/test_m28_release_docs.py`

## TDD Evidence

RED:

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_docs.py
4 failed in 0.03s
```

The failures showed the absent RC file, missing README link, and missing M24/M28
evidence separation in the platform matrix.

GREEN:

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q \
  tests/test_m28_release_docs.py tests/test_collaboration_docs.py \
  tests/test_continuous_verification.py
21 passed in 0.10s
```

## Quality Evidence

```text
ruff check tests/test_m28_release_docs.py: All checks passed!
ruff format --check tests/test_m28_release_docs.py: 1 file already formatted
git diff --check: passed
```

## Evidence Boundaries

- Local real-wheel packaging and the complete offline harness are recorded as
  verified from Task 2's nine-test run; no final full-suite count is frozen.
- The M28 installed-wheel Linux job is `configured/pending`: the local Docker
  daemon is unavailable and no new GitLab pipeline/job evidence exists.
- M24 Pipeline 50 / Job 249 is labeled historical container-only evidence and
  is not used to claim an M28 RC smoke pass.
- The page states Release Candidate status only; it does not claim publication,
  a formal tag, or an uploaded package.

## Risks

- Formal release remains blocked until the current candidate's required Linux
  job and final repository verification complete.
- Real-provider smoke stays opt-in and was not executed by this task.

## Review Fix Round 1

Root cause: the original documentation tests searched for independent tokens, so
they did not bind status values to the M28/M24 evidence rows and could not reject
contradictory success prose. The collaboration limitation also described the
whole public API instead of the collaboration-specific endpoint boundary.

RED:

```text
tests/test_m28_release_docs.py: 2 failed, 2 passed
```

The stricter contracts rejected the over-broad resume statement and the missing
explicit M24/M28 separation assertion. Mutation checks additionally prove the
success-claim and duplicate-RC guards reject their targeted contradictions.

GREEN:

```text
tests/test_m28_release_docs.py tests/test_collaboration_docs.py
tests/test_continuous_verification.py: 21 passed
ruff check: passed
ruff format --check: passed
git diff --check: passed
```

The release page now limits the gap to a collaboration-specific resume endpoint
and names the existing Loop `resume_loop_id` task submission field. Tests parse
the exact release/platform evidence rows, preserve `configured/pending` versus
historical evidence, reject unsupported M28 Linux success claims, and require a
single `0.1.0*rc*.md` release entry.
