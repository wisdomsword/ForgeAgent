# Task 2 Report: Bind Evaluator Completion to Check Evidence

## Status

Implementation, verification, and the implementation commit are complete.

## RED

Command:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-uv-cache rtk uv run pytest tests/test_collaboration_tools.py -q
```

Observed result: `10 failed, 21 passed`.

The primary false-completion test demonstrated the existing defect directly: with a registered `unit` check that had never run, `SubmitEvaluation` returned success and persisted `evaluation saved passed=1 failed=0`. The status matrix also demonstrated that `failed`, `timeout`, `cancelled`, `copy_error`, and `start_error` results did not prevent a model-reported all-pass verdict.

Three additional RED cases initially raised `AttributeError` because `collaboration.py` did not yet import the Task 1 `candidate_snapshot_digest`; the minimal GREEN implementation added that production dependency and all cases then exercised the intended gate.

## GREEN

Commands and results:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-uv-cache rtk uv run pytest tests/test_collaboration_tools.py tests/test_collaboration_models.py -q
65 passed in 0.18s

UV_CACHE_DIR=/tmp/forgeagent-m26-uv-cache rtk uv run ruff format src/forgeagent/collaboration.py tests/test_collaboration_tools.py
1 file reformatted, 1 file left unchanged

UV_CACHE_DIR=/tmp/forgeagent-m26-uv-cache rtk uv run ruff check src/forgeagent/collaboration.py tests/test_collaboration_tools.py
All checks passed!

rtk git diff --check
passed with no output
```

A final targeted rerun after formatting reported `65 passed in 0.16s`.

## Implementation

- `src/forgeagent/collaboration.py`
  - Adds frozen private `_CheckEvidence` containing only status, snapshot digest, and generator attempt.
  - Creates one ordinary private evidence dictionary only when checks are configured and shares it between `RunCheckTool` and `SubmitEvaluationTool`.
  - Records the latest host result for each frozen check ID.
  - Applies the evidence gate only to an all-pass evaluation; a verdict with any failed plan item can still be saved without running checks.
  - Rejects missing, non-passed, stale-attempt, empty/cross-check digest, changed-candidate, and digest-computation cases without saving state or incrementing the evaluator attempt.
  - Keeps failure feedback bounded and does not expose snapshot digests, exception text, or paths.
  - Keeps the no-check registry path and existing model schemas unchanged.

- `tests/test_collaboration_tools.py`
  - Covers the evidence gate, all non-passing check statuses, cross-check snapshot mismatch, post-check Candidate changes, generator-attempt mismatch, successful current-snapshot completion, early failing verdicts, digest fail-closed behavior, no-check compatibility, and Pydantic rejection of model-supplied evidence fields.

## Commit

Requested message:

```text
feat: require current check evidence for collaboration pass
```

Commit: `319297e feat: require current check evidence for collaboration pass`.

## Self-Review

The implementation follows the specified minimal design: no state schema change, no evidence persistence, no new dependency/configuration/manager/factory/framework, and no added model-controlled evidence surface. Evidence remains scoped to one Evaluator registry and each check ID is overwritten with its latest result.

## Risk Signals

- Candidate hashing remains an intentionally non-transactional check against concurrent hostile filesystem mutation, as documented by the design; digest exceptions fail closed.
- The tests use monkeypatched host results and digests for deterministic gate coverage. Task 1 owns the underlying snapshot algorithm and check-runner integration tests.
- The implementation commit contains only the two Task 2 code files; lifecycle and audit coverage remain assigned to Task 3.
