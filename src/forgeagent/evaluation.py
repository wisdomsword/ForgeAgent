"""Offline evaluation record boundary for forgeagent.evaluation.v1."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
            first_pass_correctness = 100.0 * n_first_pass / n_total

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


# ---------------------------------------------------------------------------
# Persistence types
# ---------------------------------------------------------------------------

_TREND_SCHEMA = "forgeagent.evaluation-trend.v1"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class TrendComparison:
    """Per-metric deltas between the current run and the latest prior compatible run."""

    current_run_id: str
    prior_run_id: str | None
    deltas: dict[str, float | None]  # metric name → delta or None if either value is null


@dataclass(frozen=True)
class TrendAppendResult:
    """Result of appending a record to a trend index."""

    record_path: Path
    comparison: TrendComparison
    diagnostics: tuple[str, ...]


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------


def write_record(path: Path, record: EvaluationRecord) -> Path:
    """Write *record* as JSON to *path* using an atomic temp-then-replace strategy.

    Raises ValueError if *path* is not absolute.
    """
    if not path.is_absolute():
        raise ValueError(f"path must be absolute, got {path!r}")

    data = record.model_dump(mode="python")
    # Convert tuple diagnostics to list for JSON serialisation.
    if isinstance(data.get("diagnostics"), tuple):
        data["diagnostics"] = list(data["diagnostics"])

    json_text = json.dumps(data, ensure_ascii=True, allow_nan=False, indent=2)

    # Write to a sibling temp file, then atomically replace the destination.
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as tmp:
            tmp.write(json_text)
            tmp_name = tmp.name
        os.replace(tmp_name, path)
    except Exception:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise

    return path


def read_record(path: Path) -> EvaluationRecord:
    """Read and validate a forgeagent.evaluation.v1 record from *path*.

    Raises ValueError for wrong schema; raises ValidationError for extra keys or bad values.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected a JSON object, got {type(raw).__name__}")
    schema_field = raw.get("schema")
    if schema_field != EVALUATION_SCHEMA:
        raise ValueError(f"Unsupported schema {schema_field!r}; expected {EVALUATION_SCHEMA!r}")
    # model_validate with extra="forbid" (set on EvaluationRecord) rejects unknown keys.
    return EvaluationRecord.model_validate(raw)


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------


def _load_index(record_dir: Path) -> dict[str, Any]:
    """Return the parsed index or an empty-run-ids dict if missing/corrupt."""
    index_path = record_dir / "index.json"
    if not index_path.exists():
        return {"schema": _TREND_SCHEMA, "run_ids": []}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("run_ids"), list):
            return {"schema": _TREND_SCHEMA, "run_ids": []}
        return data
    except Exception:
        return {"schema": _TREND_SCHEMA, "run_ids": []}


def _write_index(record_dir: Path, run_ids: list[str]) -> None:
    """Atomically write the trend index."""
    data = {"schema": _TREND_SCHEMA, "run_ids": run_ids}
    json_text = json.dumps(data, ensure_ascii=True, allow_nan=False, indent=2)
    index_path = record_dir / "index.json"
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=record_dir, suffix=".tmp", delete=False
        ) as tmp:
            tmp.write(json_text)
            tmp_name = tmp.name
        os.replace(tmp_name, index_path)
    except Exception:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise


def _compute_deltas(
    current: EvaluationRecord, prior: EvaluationRecord | None
) -> dict[str, float | None]:
    """Return per-metric deltas; None when either side is null."""
    deltas: dict[str, float | None] = {}
    for name in METRIC_NAMES:
        cur_val: float | None = getattr(current.metrics, name)
        pri_val: float | None = getattr(prior.metrics, name) if prior is not None else None
        if cur_val is None or pri_val is None:
            deltas[name] = None
        else:
            deltas[name] = cur_val - pri_val
    return deltas


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compare_latest(record_dir: Path, record: EvaluationRecord) -> TrendComparison:
    """Compare *record* with the latest compatible record stored in *record_dir*.

    Returns TrendComparison with prior_run_id=None when no prior record exists.
    """
    index = _load_index(record_dir)
    run_ids: list[str] = index.get("run_ids", [])

    prior: EvaluationRecord | None = None
    for rid in reversed(run_ids):
        candidate_path = record_dir / f"{rid}.json"
        if not candidate_path.exists():
            continue
        try:
            candidate = read_record(candidate_path)
            if candidate.schema == EVALUATION_SCHEMA:
                prior = candidate
                break
        except Exception:
            continue

    return TrendComparison(
        current_run_id=record.run_id,
        prior_run_id=prior.run_id if prior is not None else None,
        deltas=_compute_deltas(record, prior),
    )


def append_trend(
    record_dir: Path,
    record: EvaluationRecord,
    limit: int = 20,
) -> TrendAppendResult:
    """Append *record* to the bounded trend index in *record_dir*.

    - *record_dir* must be absolute (after resolve).
    - *limit* must be >= 1.
    - Raises ValueError on duplicate run_id, invalid run_id format, or bad arguments.
    - Old record files are deleted only after the new index is written.
    - Corrupt/incompatible history files encountered during comparison emit
      ``ignored_invalid_history:N`` as a diagnostic.
    """
    if not record_dir.is_absolute():
        raise ValueError(f"record_dir must be absolute, got {record_dir!r}")

    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")

    if not _RUN_ID_RE.match(record.run_id):
        raise ValueError(f"run_id {record.run_id!r} does not match required pattern")

    index = _load_index(record_dir)
    run_ids: list[str] = list(index.get("run_ids", []))

    if record.run_id in run_ids:
        raise ValueError(f"Duplicate run_id {record.run_id!r} already in index")

    # Count files listed in the index that exist (we'll report corrupt/incompatible ones).
    invalid_count = 0
    # Also track any non-index files we stumble upon (we must not delete those).
    prior: EvaluationRecord | None = None

    # Read previous compatible record from index BEFORE any writes.
    for rid in reversed(run_ids):
        candidate_path = record_dir / f"{rid}.json"
        if not candidate_path.exists():
            # Listed in index but missing on disk — count as invalid.
            invalid_count += 1
            continue
        try:
            candidate = read_record(candidate_path)
            if candidate.schema == EVALUATION_SCHEMA:
                prior = candidate
                break
            else:
                invalid_count += 1
        except Exception:
            invalid_count += 1

    # Also scan for files in the directory that are NOT listed in the index
    # (e.g. a corrupt JSON the caller placed there) — count them towards invalid.
    index_set = set(run_ids)
    for f in record_dir.iterdir():
        if f.suffix == ".json" and f.stem not in index_set and f.name != "index.json":
            try:
                candidate = read_record(f)
                if candidate.schema != EVALUATION_SCHEMA:
                    invalid_count += 1
            except Exception:
                invalid_count += 1

    # Write the new record file atomically.
    record_path = record_dir / f"{record.run_id}.json"
    write_record(record_path, record)

    # Build updated run_ids list, trim to limit (keep newest).
    new_run_ids = run_ids + [record.run_id]
    evicted_ids = new_run_ids[:-limit] if len(new_run_ids) > limit else []
    trimmed_ids = new_run_ids[-limit:]

    # Write new index atomically.
    _write_index(record_dir, trimmed_ids)

    # Delete evicted record files ONLY after the new index exists.
    # Only delete files that were listed in the OLD index (evicted_ids is a subset).
    for rid in evicted_ids:
        evicted_path = record_dir / f"{rid}.json"
        try:
            evicted_path.unlink()
        except OSError:
            pass

    diagnostics: tuple[str, ...] = ()
    if invalid_count > 0:
        diagnostics = (f"ignored_invalid_history:{invalid_count}",)

    comparison = TrendComparison(
        current_run_id=record.run_id,
        prior_run_id=prior.run_id if prior is not None else None,
        deltas=_compute_deltas(record, prior),
    )

    return TrendAppendResult(
        record_path=record_path,
        comparison=comparison,
        diagnostics=diagnostics,
    )
