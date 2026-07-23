# M20 Task 1 Report: Trusted Golden Manifest Baseline

## Status

Complete. The runner now authenticates the canonical 20-scenario identity list before
the existing ID, real-model ID, catalog, or output-directory checks.

## Changes

- Added `tests/golden/manifest_baseline.json` with all 20 ordered scenario rows and
  SHA-256 fingerprint `4b16cd26437bdd4a565821f1623bc438957e6ba4d5c0867fa4da48459ab3a680`.
- Added manifest fingerprinting and strict baseline parsing/authentication.
- Made canonical-baseline validation the first `validate_manifest()` guard.
- Added drift, success, malformed baseline, and no-output-directory regression tests.

## TDD Evidence

RED command:

```text
uv run pytest tests/test_golden_runner.py -k 'baseline or manifest_fingerprint' -v
```

RED output: collection failed with `ImportError: cannot import name
'load_manifest_baseline' from 'tests.golden.manifest'`, because the required API did
not yet exist.

## Verification

```text
uv run pytest tests/test_golden_runner.py -k 'baseline or manifest or preflight' -v
15 passed, 71 deselected in 0.30s

uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m20-manifest-golden
report.md: Summary: 20/20 passed (100.0%)

uv run ruff check tests/golden/manifest.py tests/golden/runner.py tests/test_golden_runner.py
All checks passed!

git diff --check
exit 0
```

## Commit

Pending commit at report creation; commit hash is added by the implementer after the
scoped commit completes.

## Concerns

None. The baseline intentionally accepts only the 20-row, three-scalar-field v1
payload and rejects malformed or drifted manifests before any output directory exists.
