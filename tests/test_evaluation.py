"""Contract tests for the forgeagent.evaluation.v1 boundary module."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from forgeagent.audit import AuditEvent
from forgeagent.evaluation import (
    EVALUATION_SCHEMA,
    EvaluationMetrics,
    EvaluationRecord,
    TaskOutcomeProjection,
    aggregate_metrics,
    append_trend,
    project_audit_event,
    read_record,
    write_record,
)

# ---------------------------------------------------------------------------
# Helper factories (plain functions, not pytest fixtures)
# ---------------------------------------------------------------------------


def valid_golden_report(total: int = 1, passed: int = 1) -> dict[str, object]:
    return {
        "schema": "forgeagent.golden.v1",
        "total": total,
        "passed": passed,
        "results": [{}],
    }


def valid_outcome(cached: int, prompt: int) -> AuditEvent:
    return AuditEvent(
        event_type="llm.outcome",
        result_status="success",
        parameters={"usage": {"cached_tokens": cached, "total_prompt_tokens": prompt}},
    )


# ---------------------------------------------------------------------------
# 1. Core metric aggregate — parametrized contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra_events", "task_outcomes", "expected"),
    [
        # cached=20/100 → cache_hit_rate=0.2; 1 completed round_count=1
        (
            [valid_outcome(cached=20, prompt=100)],
            [TaskOutcomeProjection(True, 1)],
            (100.0, 1.0, 0.0, 0.2),
        ),
        # no cache events, no task_outcomes → last three None
        (
            [],
            None,
            (100.0, None, None, None),
        ),
        # cached(11) > prompt(10) → invalid → cache_hit_rate None
        # round_count=2 → first_pass=0.0, correction_rounds=1.0
        (
            [valid_outcome(cached=11, prompt=10)],
            [TaskOutcomeProjection(True, 2)],
            (100.0, 0.0, 1.0, None),
        ),
    ],
)
def test_aggregate_metrics_never_fabricates_missing_values(
    extra_events: list[AuditEvent],
    task_outcomes: list[TaskOutcomeProjection] | None,
    expected: tuple[float | None, ...],
) -> None:
    report = valid_golden_report(total=1, passed=1)
    record = aggregate_metrics(report, audit_events=extra_events, task_outcomes=task_outcomes)
    assert record.metrics.golden_pass_rate == expected[0]
    assert record.metrics.first_pass_correctness == expected[1]
    assert record.metrics.correction_rounds == expected[2]
    assert record.metrics.cache_hit_rate == expected[3]


# ---------------------------------------------------------------------------
# 2. project_audit_event drops unknown / sensitive parameters
# ---------------------------------------------------------------------------


def test_project_audit_event_drops_unknown_and_sensitive_parameters() -> None:
    projected = project_audit_event(
        AuditEvent(
            event_type="llm.outcome",
            task_id="task-1",
            attempt=1,
            result_status="success",
            duration_ms=7,
            parameters={
                "usage": {"cached_tokens": 2, "total_prompt_tokens": 10},
                "cache_hit_rate": 0.2,
                "prompt": "secret",
                "arbitrary": "drop",
            },
        )
    )
    assert projected == {
        "event_type": "llm.outcome",
        "task_id": "task-1",
        "attempt": 1,
        "result_status": "success",
        "duration_ms": 7,
        "usage": {"cached_tokens": 2, "total_prompt_tokens": 10},
        "cache_hit_rate": 0.2,
    }


# ---------------------------------------------------------------------------
# 3. Invalid golden schema → null pass rate + diagnostic
# ---------------------------------------------------------------------------


def test_invalid_golden_schema_yields_null_pass_rate() -> None:
    bad_report = {
        "schema": "wrong.schema.v99",
        "total": 1,
        "passed": 1,
        "results": [{}],
    }
    record = aggregate_metrics(bad_report)
    assert record.metrics.golden_pass_rate is None
    assert any("invalid_golden_schema" in d for d in record.diagnostics)


# ---------------------------------------------------------------------------
# 4. passed > total → null pass rate
# ---------------------------------------------------------------------------


def test_invalid_golden_counts_yields_null_pass_rate() -> None:
    bad_report = valid_golden_report(total=2, passed=5)
    record = aggregate_metrics(bad_report)
    assert record.metrics.golden_pass_rate is None


# ---------------------------------------------------------------------------
# 5. NaN / Infinity rejected at model construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_golden_nan_infinity_rejected(bad_value: float) -> None:
    with pytest.raises(ValidationError):
        EvaluationMetrics(
            golden_pass_rate=bad_value,
            first_pass_correctness=None,
            correction_rounds=None,
            cache_hit_rate=None,
        )


# ---------------------------------------------------------------------------
# 6. Malformed audit mapping → None
# ---------------------------------------------------------------------------


def test_malformed_audit_mapping_returns_none() -> None:
    # dict missing event_type — should return None, not raise
    result = project_audit_event({"task_id": "t1", "result_status": "success"})
    assert result is None


# ---------------------------------------------------------------------------
# 7. Non-success llm.outcome events excluded from cache calculation
# ---------------------------------------------------------------------------


def test_non_success_cache_events_excluded() -> None:
    failed_event = AuditEvent(
        event_type="llm.outcome",
        result_status="error",
        parameters={"usage": {"cached_tokens": 50, "total_prompt_tokens": 100}},
    )
    record = aggregate_metrics(valid_golden_report(), audit_events=[failed_event])
    assert record.metrics.cache_hit_rate is None


# ---------------------------------------------------------------------------
# 8. total_prompt_tokens == 0 → null cache
# ---------------------------------------------------------------------------


def test_zero_prompt_tokens_yields_null_cache() -> None:
    event = valid_outcome(cached=0, prompt=0)
    record = aggregate_metrics(valid_golden_report(), audit_events=[event])
    assert record.metrics.cache_hit_rate is None


# ---------------------------------------------------------------------------
# 9. cached_tokens > total_prompt_tokens → null cache
# ---------------------------------------------------------------------------


def test_overcached_tokens_yields_null_cache() -> None:
    event = valid_outcome(cached=200, prompt=100)
    record = aggregate_metrics(valid_golden_report(), audit_events=[event])
    assert record.metrics.cache_hit_rate is None


# ---------------------------------------------------------------------------
# 10. All outcomes incomplete → correction_rounds None, first_pass = 0.0
# ---------------------------------------------------------------------------


def test_no_completed_outcomes_yields_null_correction_rounds() -> None:
    outcomes = [TaskOutcomeProjection(False, 1), TaskOutcomeProjection(False, 1)]
    record = aggregate_metrics(valid_golden_report(), task_outcomes=outcomes)
    assert record.metrics.correction_rounds is None
    assert record.metrics.first_pass_correctness == 0.0


# ---------------------------------------------------------------------------
# 11. Completed outcome with round_count < 1 is invalid
# ---------------------------------------------------------------------------


def test_completed_outcome_with_round_count_less_than_1_is_invalid() -> None:
    with pytest.raises(ValueError):
        TaskOutcomeProjection(True, 0)


# ---------------------------------------------------------------------------
# 12. Diagnostics are fixed identifiers, not raw event text
# ---------------------------------------------------------------------------


def test_diagnostics_are_fixed_identifiers_not_raw_text() -> None:
    bad_schema_report = {"schema": "bad.schema", "total": 1, "passed": 1, "results": [{}]}
    record = aggregate_metrics(bad_schema_report)
    for diag in record.diagnostics:
        assert isinstance(diag, str)
        # Must be a fixed identifier pattern — no spaces, no JSON-like characters
        assert " " not in diag or diag.count(":") == 1  # allow "key:N" counters
        # Must not contain raw event data (quotes, braces, brackets indicate raw text)
        assert "{" not in diag
        assert "[" not in diag


# ---------------------------------------------------------------------------
# 13. task_outcomes=None → both metrics None (not zero)
# ---------------------------------------------------------------------------


def test_null_task_outcomes_yields_both_null_not_zero() -> None:
    record = aggregate_metrics(valid_golden_report(), task_outcomes=None)
    assert record.metrics.first_pass_correctness is None
    assert record.metrics.correction_rounds is None


# ---------------------------------------------------------------------------
# 14. Schema constant is correct
# ---------------------------------------------------------------------------


def test_evaluation_record_schema_constant() -> None:
    record = aggregate_metrics(valid_golden_report())
    assert record.schema == EVALUATION_SCHEMA
    assert EVALUATION_SCHEMA == "forgeagent.evaluation.v1"


# ---------------------------------------------------------------------------
# 15. Empty task_outcomes list → first_pass_correctness is None (not 0.0)
# ---------------------------------------------------------------------------


def test_empty_task_outcomes_yields_null_first_pass_not_zero():
    record_obj = aggregate_metrics(
        {"schema": "forgeagent.golden.v1", "total": 1, "passed": 1, "results": [{}]},
        [],
        task_outcomes=[],
    )
    assert record_obj.metrics.first_pass_correctness is None
    assert record_obj.metrics.correction_rounds is None


# ---------------------------------------------------------------------------
# Helpers for persistence / trend tests
# ---------------------------------------------------------------------------


def make_record(run_id: str = "test-run", golden_pass_rate: float = 90.0) -> EvaluationRecord:
    return EvaluationRecord(
        schema=EVALUATION_SCHEMA,
        run_id=run_id,
        created_at="2026-07-24T00:00:00.000Z",
        source_schema="forgeagent.golden.v1",
        metrics=EvaluationMetrics(
            golden_pass_rate=golden_pass_rate,
            first_pass_correctness=None,
            correction_rounds=None,
            cache_hit_rate=None,
        ),
        diagnostics=(),
    )


def read_index(record_dir: Path) -> dict:
    return json.loads((record_dir / "index.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 16. append_trend compares latest compatible record and bounds index
# ---------------------------------------------------------------------------


def test_append_trend_compares_latest_compatible_record_and_bounds_index(tmp_path):
    old = make_record(run_id="20260724-old", golden_pass_rate=90.0)
    new = make_record(run_id="20260724-new", golden_pass_rate=95.0)
    append_trend(tmp_path, old, limit=1)
    appended = append_trend(tmp_path, new, limit=1)
    assert appended.comparison.prior_run_id == "20260724-old"
    assert appended.comparison.deltas["golden_pass_rate"] == 5.0
    assert read_index(tmp_path)["run_ids"] == ["20260724-new"]


# ---------------------------------------------------------------------------
# 17. Corrupt or incompatible history is ignored with fixed diagnostic
# ---------------------------------------------------------------------------


def test_corrupt_or_incompatible_history_is_ignored_with_fixed_diagnostic(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    result = append_trend(tmp_path, make_record(run_id="current"))
    assert result.diagnostics == ("ignored_invalid_history:1",)


# ---------------------------------------------------------------------------
# 18. write_record leaves no temp file on success
# ---------------------------------------------------------------------------


def test_write_record_leaves_no_temp_file_on_success(tmp_path):
    rec = make_record()
    dest = tmp_path / "eval.json"
    write_record(dest, rec)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"
    assert dest.exists()


# ---------------------------------------------------------------------------
# 19. read_record rejects unknown schema
# ---------------------------------------------------------------------------


def test_read_record_rejects_unknown_schema(tmp_path):
    dest = tmp_path / "bad.json"
    data = {
        "schema": "wrong.schema.v99",
        "run_id": "abc",
        "created_at": "2026-07-24T00:00:00.000Z",
        "source_schema": None,
        "metrics": {
            "golden_pass_rate": None,
            "first_pass_correctness": None,
            "correction_rounds": None,
            "cache_hit_rate": None,
        },
        "diagnostics": [],
    }
    dest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_record(dest)


# ---------------------------------------------------------------------------
# 20. read_record rejects extra key
# ---------------------------------------------------------------------------


def test_read_record_rejects_extra_key(tmp_path):
    dest = tmp_path / "extra.json"
    data = {
        "schema": EVALUATION_SCHEMA,
        "run_id": "abc",
        "created_at": "2026-07-24T00:00:00.000Z",
        "source_schema": None,
        "metrics": {
            "golden_pass_rate": None,
            "first_pass_correctness": None,
            "correction_rounds": None,
            "cache_hit_rate": None,
        },
        "diagnostics": [],
        "unexpected_field": "boom",
    }
    dest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_record(dest)


# ---------------------------------------------------------------------------
# 21. Non-absolute path rejected
# ---------------------------------------------------------------------------


def test_non_absolute_path_rejected(tmp_path):
    rec = make_record()
    with pytest.raises(ValueError):
        write_record(Path("relative/path.json"), rec)


def test_non_absolute_dir_rejected_in_append_trend():
    rec = make_record()
    with pytest.raises(ValueError):
        append_trend(Path("relative/dir"), rec)


# ---------------------------------------------------------------------------
# 22. Invalid limit rejected
# ---------------------------------------------------------------------------


def test_invalid_limit_rejected(tmp_path):
    rec = make_record()
    with pytest.raises(ValueError):
        append_trend(tmp_path, rec, limit=0)


# ---------------------------------------------------------------------------
# 23. Duplicate run_id rejected
# ---------------------------------------------------------------------------


def test_duplicate_run_id_rejected(tmp_path):
    rec = make_record(run_id="dup-run")
    append_trend(tmp_path, rec)
    with pytest.raises(ValueError):
        append_trend(tmp_path, rec)


# ---------------------------------------------------------------------------
# 24. Retention removes only index-listed files
# ---------------------------------------------------------------------------


def test_retention_removes_only_index_listed_files(tmp_path):
    r1 = make_record(run_id="run-1", golden_pass_rate=80.0)
    r2 = make_record(run_id="run-2", golden_pass_rate=85.0)
    # Write an unrelated file that should NOT be removed
    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text("{}", encoding="utf-8")
    append_trend(tmp_path, r1, limit=1)
    append_trend(tmp_path, r2, limit=1)
    # run-1 should be evicted, but unrelated.json must survive
    assert not (tmp_path / "run-1.json").exists()
    assert unrelated.exists()


# ---------------------------------------------------------------------------
# 25. Storage write failure does not mutate valid index
# ---------------------------------------------------------------------------


def test_storage_write_failure_does_not_mutate_valid_index(tmp_path):
    # Seed a valid index with one record
    r1 = make_record(run_id="safe-run", golden_pass_rate=70.0)
    append_trend(tmp_path, r1, limit=5)
    original_index = read_index(tmp_path)

    # Make the record directory read-only so the next write_record call fails
    os.chmod(tmp_path, 0o555)
    try:
        r2 = make_record(run_id="fail-run", golden_pass_rate=75.0)
        with pytest.raises(OSError):
            append_trend(tmp_path, r2, limit=5)
    finally:
        os.chmod(tmp_path, 0o755)

    # Index must be unchanged
    assert read_index(tmp_path) == original_index
