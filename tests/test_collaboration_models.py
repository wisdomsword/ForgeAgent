"""Contract tests for the durable collaboration state models."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from forgeagent.collaboration import (
    COLLABORATION_SCHEMA,
    MAX_ITEM_TEXT_CHARS,
    AcceptanceItem,
    CollaborationReport,
    CollaborationState,
    CollaborationUsage,
    EvaluationItem,
    plan_digest,
)


def _plan() -> tuple[AcceptanceItem, ...]:
    return (
        AcceptanceItem(id="output", behavior="Writes an output file", acceptance="File exists"),
    )


def _state(**overrides: object) -> CollaborationState:
    values: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "triad",
        "goal": "Create an artifact",
        "plan": _plan(),
        "plan_digest": plan_digest(_plan()),
    }
    values.update(overrides)
    return CollaborationState(**values)


def test_models_reject_bool_coercion_nonfinite_and_extra_fields():
    with pytest.raises(ValidationError):
        CollaborationUsage(input_tokens=True)
    with pytest.raises(ValidationError):
        CollaborationUsage(cost=math.inf)
    with pytest.raises(ValidationError):
        AcceptanceItem(id="item", behavior="Do it", acceptance="Observe it", extra="no")
    with pytest.raises(ValidationError):
        EvaluationItem(id="item", passed=1, observed="yes", expected="yes")


@pytest.mark.parametrize("character", ["\x00", "\u0085", "\u2028", "\u202e", "\ud800"])
def test_models_reject_control_and_format_characters(character: str):
    with pytest.raises(ValidationError):
        AcceptanceItem(id="item", behavior=f"unsafe{character}", acceptance="observable")


def test_plan_items_are_bounded_unique_and_digest_is_stable():
    with pytest.raises(ValidationError):
        AcceptanceItem(id="item", behavior="x" * (MAX_ITEM_TEXT_CHARS + 1), acceptance="ok")
    with pytest.raises(ValidationError):
        _state(plan=(_plan()[0], _plan()[0]))

    assert plan_digest(_plan()) == plan_digest(list(_plan()))


def test_evaluation_requires_exact_coverage_and_failed_evidence():
    with pytest.raises(ValidationError):
        _state(
            last_evaluation=(
                EvaluationItem(id="other", passed=True, observed="yes", expected="yes"),
            )
        )
    with pytest.raises(ValidationError):
        EvaluationItem(id="output", passed=False, observed="", expected="expected")
    with pytest.raises(ValidationError):
        EvaluationItem(id="output", passed=True, observed="yes", expected="yes", location="/tmp/a")


def test_completed_state_requires_all_passing_evaluation_and_public_report_masks_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COLLABORATION_SECRET", "secret-value-for-test")
    with pytest.raises(ValidationError):
        _state(status="completed", phase="completed", stop_reason="completed")

    state = _state(
        status="completed",
        phase="completed",
        stop_reason="completed",
        last_evaluation=(
            EvaluationItem(
                id="output",
                passed=True,
                observed="contains secret-value-for-test",
                expected="file exists",
                location="result.txt",
            ),
        ),
    )
    report = CollaborationReport.from_state(state)

    assert report.schema == COLLABORATION_SCHEMA
    assert report.passed_item_count == 1
    assert "secret-value-for-test" not in report.evidence[0]
    assert "Create an artifact" not in report.model_dump_json()
