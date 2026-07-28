# Task 3 Report: Fixed Protocol and Programming Fixtures

- Base commit: `820a87e`
- Head commit: `a4d4b80`
- Files changed: `docs/evaluation/m25/protocol.json`, `tests/test_m25_mode_evaluation.py`

## RED

The checked-in protocol contract failed with `FileNotFoundError` because the independent M25 protocol did not exist.

## GREEN

- Protocol contract and drift tests: `9 passed, 15 deselected`
- Full M23 and M25 suites: `77 passed in 2.08s`
- Ruff and `git diff --check`: passed

The protocol fixes the two models, five repetitions, nine tasks, family counts 3/2/2/2, exact M23 baseline task bodies, and six programming task IDs with immutable checks and artifact contracts.
