"""Focused M39 tests for Collaboration stop and goal projection."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from forgeagent.attention import attention_for_reason
from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationReport,
    CollaborationRunner,
    CollaborationState,
    CollaborationUsage,
    HandoffPacket,
    _project_collaboration_stop,
    _role_task_data,
    build_handoff_packet,
    plan_digest,
)
from forgeagent.execution_evidence import ExecutionEvidence, ToolExecutionRecord
from forgeagent.http_task_service import TaskRecord
from forgeagent.step import RoundResult
from forgeagent.task import TaskOutcome, TaskStatus


def _plan() -> tuple[AcceptanceItem, ...]:
    return (AcceptanceItem(id="output", behavior="Write output", acceptance="Output exists"),)


def _state(**overrides: object) -> CollaborationState:
    plan = _plan()
    values: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "triad",
        "goal": "Create an artifact",
        "phase": "generator",
        "plan": plan,
        "plan_digest": plan_digest(plan),
    }
    values.update(overrides)
    return CollaborationState(**values)


def _report(**overrides: object) -> CollaborationReport:
    values: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "duo",
        "status": "active",
        "stop_reason": None,
        "phase": "generator",
        "plan_item_count": 1,
        "passed_item_count": 0,
        "failed_item_count": 0,
        "generator_attempts": 0,
        "evaluator_attempts": 0,
        "rejections": 0,
        "rounds": 0,
        "usage": CollaborationUsage(),
        "usage_available": True,
    }
    values.update(overrides)
    return CollaborationReport(**values)


@pytest.mark.parametrize(
    ("reason", "status", "projected"),
    [
        ("completed", "completed", "completed"),
        ("needs_confirmation", "stopped", "needs_confirmation"),
        ("rejection_limit", "stopped", "rejection_limit"),
        ("wall_clock", "stopped", "wall_clock"),
        ("token_budget", "stopped", "token_budget"),
        ("token_usage_unavailable", "stopped", "token_usage_unavailable"),
        ("max_rounds", "stopped", "max_rounds"),
        ("needs_info", "stopped", "needs_input"),
        ("blocked", "stopped", "blocked"),
        ("external_action_pending", "stopped", "external_action_pending"),
        ("cancelled", "cancelled", "cancelled"),
        ("client_error:auth", "failed", "unrecoverable_failure"),
        ("client_error:network", "failed", "client_error:network"),
        ("unknown", "failed", "role_failed"),
    ],
)
def test_stop_projection_covers_task_and_loop_reason_vocabulary(
    reason: str, status: str, projected: str
):
    projected_status, projected_reason, _ = _project_collaboration_stop(reason)
    assert (projected_status, projected_reason) == (status, projected)


@pytest.mark.parametrize(
    ("reason", "attention_reason", "attention_state"),
    [
        ("max_rounds", "max_rounds", None),
        ("wall_clock", "wall_clock", None),
        ("token_budget", "token_budget", None),
        ("token_usage_unavailable", "token_usage_unavailable", None),
        ("consecutive_failures", "consecutive_failures", None),
        ("needs_input", "needs_info", "needs_input"),
        ("blocked", "blocked", "blocked"),
        ("external_action_pending", "external_action_pending", "blocked"),
    ],
)
def test_stopped_state_preserves_resource_and_attention_reasons(
    reason: str, attention_reason: str, attention_state: str | None
):
    attention = attention_for_reason(attention_reason) if attention_state is not None else None
    state = _state(status="stopped", phase="stopped", stop_reason=reason, attention=attention)
    report = CollaborationReport.from_state(state)

    assert report.status == "stopped"
    assert report.stop_reason == reason
    assert (report.attention.state if report.attention is not None else None) == attention_state


def test_attention_state_must_match_the_collaboration_stop_reason():
    with pytest.raises(ValidationError, match="attention"):
        _state(
            status="stopped",
            phase="stopped",
            stop_reason="needs_input",
            attention=attention_for_reason("blocked"),
        )

    with pytest.raises(ValidationError, match="attention"):
        _report(
            status="failed",
            phase="failed",
            stop_reason="role_failed",
            attention=attention_for_reason("needs_info"),
        )


def test_unknown_collaboration_stop_reason_is_rejected():
    with pytest.raises(ValidationError, match="stop reason"):
        _report(status="stopped", phase="stopped", stop_reason="invented_reason")


def test_execution_goal_keeps_legal_path_while_public_handoff_masks_it(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COLLABORATION_SECRET", "secret-value")
    state = _state(goal="Process /data/input.csv with secret-value")
    task_data = json.loads(_role_task_data(state, ()))
    packet = build_handoff_packet(state, "generator")

    assert "/data/input.csv" in task_data["goal"]
    assert "secret-value" in task_data["goal"]
    public = json.dumps(packet.model_dump(mode="json"), ensure_ascii=True)
    assert "/data/input.csv" not in public
    assert "secret-value" not in public


def test_handoff_goal_projection_remains_bounded_and_frozen():
    packet = build_handoff_packet(_state(goal="Process /data/input.csv"), "generator")
    assert "/data/input.csv" not in packet.goal
    assert packet.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        HandoffPacket.model_validate(packet.model_dump(mode="python") | {"goal": "x" * 4001})


class _OutcomeRoleBuilder:
    def __init__(self, reason: str):
        self.reason = reason
        self.calls: list[tuple[str, int]] = []

    def __call__(self, role, attempt, registry, system_prompt):
        del registry, system_prompt
        self.calls.append((role, attempt))
        reason = self.reason

        class OutcomeTask:
            def run(self, goal, *, cancel_event=None):
                del goal, cancel_event
                return TaskOutcome(
                    status=TaskStatus(
                        completed=False,
                        reason=reason,
                        attention=attention_for_reason(reason),
                    ),
                    rounds=[RoundResult(text="")],
                    execution_evidence=ExecutionEvidence(
                        records=(
                            ToolExecutionRecord(
                                sequence=1,
                                tool="Exec",
                                status="failed",
                            ),
                        )
                    ),
                )

            def close(self):
                pass

        return OutcomeTask()


@pytest.mark.parametrize(
    ("task_reason", "status", "stop_reason", "attention_state"),
    [
        ("needs_info", "stopped", "needs_input", "needs_input"),
        ("blocked", "stopped", "blocked", "blocked"),
        ("max_rounds", "stopped", "max_rounds", None),
        ("client_error:auth", "failed", "unrecoverable_failure", None),
        ("unexpected_reason", "failed", "role_failed", None),
    ],
)
def test_runner_projects_role_task_stop_reasons(
    tmp_path, task_reason: str, status: str, stop_reason: str, attention_state: str | None
):
    builder = _OutcomeRoleBuilder(task_reason)
    runner = CollaborationRunner.create(
        mode="duo",
        goal="write PRIVATE_GOAL artifact",
        allowed_root=str(tmp_path),
        role_task_builder=builder,
        generator_model="generator-model",
        evaluator_model="evaluator-model",
    )

    report = runner.run("write PRIVATE_GOAL artifact")

    assert report.status == status
    assert report.stop_reason == stop_reason
    assert (report.attention.state if report.attention is not None else None) == attention_state
    assert builder.calls == [("generator", 1)]
    assert [(record.role, record.attempt) for record in report.execution_evidence.records] == [
        ("generator", 1)
    ]


def test_http_record_uses_collaboration_attention_without_private_goal():
    attention = attention_for_reason("blocked", "private dependency detail")
    record = TaskRecord(
        task_id="a" * 32,
        goal="private goal",
        options={"mode": "duo"},
        status="stopped",
        reason="blocked",
        collaboration_report=_report(
            status="stopped",
            stop_reason="blocked",
            phase="stopped",
            attention=attention,
        ),
        ended_at=1.0,
    )

    view = record.public_view()

    assert view["status"] == "stopped"
    assert view["reason"] == "blocked"
    assert view["attention"]["state"] == "blocked"
    assert "private goal" not in repr(view)
