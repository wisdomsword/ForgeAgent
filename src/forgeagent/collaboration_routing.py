"""Pure collaboration mode routing and its minimal audit projection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .audit import AuditEvent, AuditSink, emit_audit

CollaborationMode = Literal["single", "duo", "triad"]


class ModeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: CollaborationMode
    reason: Literal["explicit", "bound_checks", "default", "override_required"]
    override_required: bool = False

    @field_validator("override_required", mode="before")
    @classmethod
    def _validate_override_required(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("override_required must be a bool")
        return value


def emit_collaboration_route(
    audit_sink: AuditSink | None,
    decision: ModeDecision,
    requested_mode: CollaborationMode | None,
    *,
    task_id: str | None = None,
    loop_id: str | None = None,
) -> bool:
    """Audit a deterministic routing decision without retaining the task goal."""
    return emit_audit(
        audit_sink,
        AuditEvent(
            event_type="collaboration.route",
            task_id=task_id,
            risk_level="low",
            parameters={
                "mode": decision.mode,
                "reason": decision.reason,
                "requested_mode": requested_mode or "default",
                "override_required": decision.override_required,
                **({"loop_id": loop_id} if loop_id is not None else {}),
            },
            result_status=decision.reason,
            duration_ms=0,
        ),
    )


def resolve_collaboration_mode(
    goal: str,
    requested_mode: CollaborationMode | None,
    *,
    has_bound_checks: bool = False,
    allow_weaker_override: bool = False,
) -> ModeDecision:
    del goal, allow_weaker_override
    if requested_mode is not None:
        return ModeDecision(mode=requested_mode, reason="explicit")
    if has_bound_checks:
        return ModeDecision(mode="triad", reason="bound_checks")
    return ModeDecision(mode="single", reason="default")
