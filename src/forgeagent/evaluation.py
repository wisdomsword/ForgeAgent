"""Offline evaluation record boundary for forgeagent.evaluation.v1."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .audit import AuditEvent

EVALUATION_SCHEMA = "forgeagent.evaluation.v1"
METRIC_NAMES = (
    "golden_pass_rate",
    "first_pass_correctness",
    "correction_rounds",
    "cache_hit_rate",
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskOutcomeProjection:
    """Immutable projection of one task execution outcome."""

    completed: bool
    round_count: int

    def __post_init__(self) -> None:
        if self.completed and self.round_count < 1:
            raise ValueError(
                f"round_count must be >= 1 for completed outcomes, got {self.round_count}"
            )


def _reject_non_finite(value: float | None) -> float | None:
    if value is None:
        return value
    if not math.isfinite(value):
        raise ValueError(f"metric value must be finite, got {value!r}")
    return value


class EvaluationMetrics(BaseModel):
    """Computed metrics for one evaluation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    golden_pass_rate: float | None = None
    first_pass_correctness: float | None = None
    correction_rounds: float | None = None
    cache_hit_rate: float | None = None

    @field_validator(
        "golden_pass_rate",
        "first_pass_correctness",
        "correction_rounds",
        "cache_hit_rate",
        mode="before",
    )
    @classmethod
    def _validate_finite(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"metric value must be finite, got {v!r}")
        return v


class EvaluationRecord(BaseModel):
    """Top-level forgeagent.evaluation.v1 record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema: str = EVALUATION_SCHEMA
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    )
    source_schema: str | None = None
    metrics: EvaluationMetrics
    diagnostics: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

# Only these parameter sub-keys may appear in projected output.
_ALLOWED_PARAMETER_KEYS = frozenset({"cache_hit_rate"})
_ALLOWED_USAGE_KEYS = frozenset({"cached_tokens", "total_prompt_tokens"})


def project_audit_event(
    event: AuditEvent | Mapping[str, object],
) -> dict[str, object] | None:
    """Project only safe fields from an audit event.

    Returns None if the event is malformed and cannot be projected.
    Output keys (when present and valid): event_type, task_id, attempt,
    result_status, duration_ms, usage, cache_hit_rate.
    NEVER serializes raw parameters dict or any other parameter key.
    """
    try:
        if isinstance(event, AuditEvent):
            event_type: object = event.event_type
            task_id: object = event.task_id
            attempt: object = event.attempt
            result_status: object = event.result_status
            duration_ms: object = event.duration_ms
            parameters: object = event.parameters
        else:
            # Must be a Mapping — require event_type at minimum
            event_type = event.get("event_type")
            if not isinstance(event_type, str) or not event_type:
                return None
            task_id = event.get("task_id")
            attempt = event.get("attempt")
            result_status = event.get("result_status")
            duration_ms = event.get("duration_ms")
            parameters = event.get("parameters", {})
    except Exception:
        return None

    out: dict[str, object] = {"event_type": event_type}

    if task_id is not None:
        out["task_id"] = task_id
    if attempt is not None:
        out["attempt"] = attempt
    if result_status is not None:
        out["result_status"] = result_status
    if duration_ms is not None:
        out["duration_ms"] = duration_ms

    # Extract only the allowed sub-keys from parameters
    if isinstance(parameters, dict):
        usage_raw = parameters.get("usage")
        if isinstance(usage_raw, dict):
            usage_projected = {k: v for k, v in usage_raw.items() if k in _ALLOWED_USAGE_KEYS}
            if usage_projected:
                out["usage"] = usage_projected

        if "cache_hit_rate" in parameters:
            out["cache_hit_rate"] = parameters["cache_hit_rate"]

    return out


def aggregate_metrics(
    golden_report: Mapping[str, object],
    audit_events: Iterable[AuditEvent | Mapping[str, object]] = (),
    task_outcomes: Iterable[TaskOutcomeProjection] | None = None,
) -> EvaluationRecord:
    """Build a forgeagent.evaluation.v1 record from evidence."""
    diagnostics: list[str] = []
    source_schema: str | None = None

    # ---- golden_pass_rate ----
    golden_pass_rate: float | None = None
    raw_schema = golden_report.get("schema")
    if isinstance(raw_schema, str):
        source_schema = raw_schema

    if raw_schema != "forgeagent.golden.v1":
        diagnostics.append("invalid_golden_schema")
    else:
        total = golden_report.get("total")
        passed = golden_report.get("passed")
        if (
            isinstance(total, int)
            and isinstance(passed, int)
            and total > 0
            and 0 <= passed <= total
        ):
            golden_pass_rate = passed * 100.0 / total
        else:
            diagnostics.append("invalid_golden_counts")

    # ---- cache_hit_rate ----
    cache_hit_rate: float | None = None
    cache_valid = True
    cached_sum = 0
    prompt_sum = 0
    n_non_success_skipped = 0

    for raw_event in audit_events:
        projected = project_audit_event(raw_event)
        if projected is None:
            continue
        if projected.get("event_type") != "llm.outcome":
            continue
        if projected.get("result_status") != "success":
            n_non_success_skipped += 1
            continue

        usage = projected.get("usage")
        if not isinstance(usage, dict):
            cache_valid = False
            break

        cached = usage.get("cached_tokens")
        total_prompt = usage.get("total_prompt_tokens")

        if (
            not isinstance(cached, int)
            or not isinstance(total_prompt, int)
            or cached < 0
            or total_prompt <= 0
            or cached > total_prompt
        ):
            cache_valid = False
            break

        cached_sum += cached
        prompt_sum += total_prompt

    if n_non_success_skipped > 0:
        diagnostics.append(f"ignored_non_success_attempts:{n_non_success_skipped}")

    if cache_valid and prompt_sum > 0:
        cache_hit_rate = cached_sum / prompt_sum

    # ---- task outcome metrics ----
    first_pass_correctness: float | None = None
    correction_rounds_value: float | None = None

    if task_outcomes is not None:
        outcomes_list = list(task_outcomes)
        n_total = len(outcomes_list)

        if n_total > 0:
            n_first_pass = sum(1 for o in outcomes_list if o.completed and o.round_count == 1)
            first_pass_correctness = n_first_pass / n_total

        completed = [o for o in outcomes_list if o.completed]
        if completed:
            correction_rounds_value = sum(o.round_count - 1 for o in completed) / len(completed)
        # else correction_rounds stays None

    return EvaluationRecord(
        schema=EVALUATION_SCHEMA,
        source_schema=source_schema,
        metrics=EvaluationMetrics(
            golden_pass_rate=golden_pass_rate,
            first_pass_correctness=first_pass_correctness,
            correction_rounds=correction_rounds_value,
            cache_hit_rate=cache_hit_rate,
        ),
        diagnostics=tuple(diagnostics),
    )
