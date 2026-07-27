# Task 4 Report: Fixture Solvability and Check Strength

- Base commit: `5958eb0`
- Head commit: `fa5c590`
- Commits: `8a9fd7d`, `fa5c590`
- Files changed: `tests/test_m25_mode_evaluation.py`, `docs/evaluation/m25/protocol.json`

## RED

The six reference audits initially failed with `NameError` before reference transformations existed. A later artifact-completeness assertion correctly failed the JSONL reference because isolated checks do not copy generated files back to the candidate workspace.

## GREEN

- Six initial-failure/reference-pass cases: passed
- Six weak-mutation and immutable-tamper cases: passed
- All declared reference artifacts hash with status `ok`
- Focused fixture audits: `12 passed`
- Full M23/M25 suites: `89 passed`
- Ruff and diff checks: passed

The topological fixture was strengthened with a late-inserted lexicographically earlier isolated node so removing `sorted()` cannot pass accidentally.
