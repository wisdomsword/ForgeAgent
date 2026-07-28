# Task 2 Report: Deterministic Schedule, Identity, and Resume

- Base commit: `4e9b2e9`
- Head commit: `8aa1e6e`
- Files changed: `scripts/m23_mode_evaluation.py`, `tests/test_m25_mode_evaluation.py`

## RED

`rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py -k 'schedule or resume or identity'`

Result: expected failure, `9 failed, 14 deselected`. The old harness produced 81 M23-shaped runs and had no M25 run ID or protocol-specific resume validation.

## GREEN

- Focused schedule/resume/identity tests: `13 passed, 63 deselected`
- Full M23 and M25 suites: `76 passed in 2.06s`
- Ruff: `All checks passed!`
- `git diff --check`: clean

The M25 schedule contains 270 unique identities, 135 runs per model, 90 runs per mode, and 30 appearances per mode in each global triplet position. Resume validation binds schema, terminal state, filename, task family, model, route hash, protocol, environment, and RunSpec hash while retaining M23 behavior.
