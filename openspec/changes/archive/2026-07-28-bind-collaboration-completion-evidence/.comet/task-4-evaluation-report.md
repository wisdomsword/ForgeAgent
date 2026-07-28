# Task 4 Evaluation Harness Report

## Scope

- Added the independent M26 four-run completion-evidence harness.
- Added the fixed Duo/Triad x skip-check-first/all-pass protocol.
- Added controlled Task/Step/CollaborationRunner evidence and safe auto fallback.
- Did not modify M23/M25 harnesses or evidence.

## TDD Evidence

Initial RED:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-task4-uv-cache uv run pytest -q tests/test_m26_completion_evidence_evaluation.py
9 failed in 0.06s
```

All nine tests failed because `scripts/m26_completion_evidence_evaluation.py` did not exist.
The first command without the temporary cache exited 2 before collection because the sandbox could
not initialize `/Users/admin/.cache/uv`; it was not counted as the RED result.

Review-gap RED:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-task4-uv-cache uv run pytest -q tests/test_m26_completion_evidence_evaluation.py
2 failed, 9 passed in 5.91s
```

The failures proved that a raw record could be changed with a matching hash update and that the
environment manifest lacked the frozen run identity fields.

Provider-fallback RED:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-task4-uv-cache uv run pytest -q tests/test_m26_completion_evidence_evaluation.py::test_auto_falls_back_when_real_provider_run_is_unavailable
1 failed in 0.14s
```

The failure proved that auto mode kept `selected=real` after a provider failure instead of running
the controlled fallback.

Final GREEN:

```text
UV_CACHE_DIR=/tmp/forgeagent-m26-task4-uv-cache uv run pytest -q tests/test_m26_completion_evidence_evaluation.py
12 passed in 7.00s
```

## Verification

```text
uv run ruff check scripts/m26_completion_evidence_evaluation.py tests/test_m26_completion_evidence_evaluation.py
All checks passed!

uv run ruff format --check scripts/m26_completion_evidence_evaluation.py tests/test_m26_completion_evidence_evaluation.py
2 files already formatted

git diff --check
exit 0
```

The harness verifies the fixed matrix and exact evaluator tool sequence, binds raw records to the
protocol and environment hashes, records safe repository/package/harness identity, rejects unsafe
output paths and semantic tampering, supports idempotent replay, and confirms M23/M25 evidence
hashes remain unchanged.

## Thorough Review Fixes

Combined review RED:

```text
18 failed, 14 passed in 17.02s
```

The failures covered unsafe fixture paths and symlink parents, incompatible execution reuse,
coherently rehashed evidence-contract tampering, and a precreated temporary-file symlink.

The direct invalid-request classification RED was:

```text
1 failed in 0.15s
```

The strict unknown-field schema RED was:

```text
3 failed, 32 passed in 19.60s
```

Final GREEN after all findings:

```text
35 passed in 19.63s
```

The fixes add fail-closed relative fixture validation, descriptor-relative writes with no symlink
traversal, execution-compatible evidence reuse, invalid-request provider fallback classification,
strict evidence schemas and cross-file execution/fallback/protocol consistency, and unique safe
atomic temporary files.

Final full-diff review RED:

```text
1 failed in 1.09s
```

The failure proved that dirty-worktree evidence recorded only `tracked_dirty=true` and did not bind
the exact M26 runtime source that produced the results. The final environment now includes SHA-256
for `check_runner.py` and `collaboration.py`.

A second review RED was:

```text
3 failed, 13 passed in 13.72s
```

Those failures proved the verifier also had to enforce the exact two runtime paths and 64-hex
values. `2026-07-28-final-v3` and `final-v4` are retained as superseded; `final-v5` is authoritative.
The complete harness suite is `38 passed`.
