# Task 1 Report: M23 Immutability Gate and M25 Schema Dispatch

- Base commit: `b224be3`
- Head commit: `9e6607d`
- Files changed: `scripts/m23_mode_evaluation.py`, `tests/test_m25_mode_evaluation.py`

## RED

Command:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py::test_validate_protocol_dispatches_m23_and_m25_without_changing_m23_dump tests/test_m25_mode_evaluation.py::test_unknown_schema_fails_before_model_parsing
```

Result: expected failure, `1 failed, 3 passed`. The M25 protocol was sent to
`EvaluationProtocol`, which rejected its M25 schema, `model_ids`, and task
`family` fields. This confirmed schema dispatch did not exist.

## GREEN

Commands:

```bash
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run pytest -q tests/test_m25_mode_evaluation.py tests/test_m23_mode_evaluation.py
rtk uv --cache-dir /tmp/forgeagent-m25-uv-cache run ruff check scripts/m23_mode_evaluation.py tests/test_m25_mode_evaluation.py
```

Results:

- `14 passed in 0.87s`
- `67 passed in 2.66s`
- `All checks passed!`

The M25 test module locks tracked M23 evidence to base ref
`d7fa30526f829959102b5fb69b4778899d6b1f88` byte-for-byte and recomputes its
checked-in formal summary and report.

## Risk Signals

None observed. M23 Pydantic class bodies and protocol serialization are
unchanged; only schema-first dispatch and M25-specific types were added.
