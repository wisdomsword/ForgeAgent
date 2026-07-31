"""Contract and integration tests for structured collaboration handoffs."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from forgeagent.client import MockClient
from forgeagent.collaboration import (
    HANDOFF_SCHEMA,
    AcceptanceItem,
    CollaborationRunner,
    CollaborationState,
    HandoffPacket,
    build_handoff_packet,
    handoff_digest,
    plan_digest,
)
from forgeagent.models import AssistantMessage, TokenUsage
from forgeagent.task import Task


def _state(**overrides: object) -> CollaborationState:
    plan = (AcceptanceItem(id="output", behavior="Write output", acceptance="Output exists"),)
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


class _Registry:
    def arg_schemas(self):
        return {"FileRead": object, "SubmitCandidate": object}


def test_handoff_packet_is_strict_bounded_and_frozen():
    state = _state()
    packet = build_handoff_packet(state, "generator", registry=_Registry())

    assert packet.schema == HANDOFF_SCHEMA
    assert packet.attempt == 0
    assert packet.return_owner == "evaluator"
    assert packet.receipt_visibility == "unavailable"
    assert packet.capabilities[0].name == "FileRead"
    assert (
        next(item for item in packet.capabilities if item.name == "SubmitCandidate").read_only
        is False
    )
    assert packet.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        HandoffPacket.model_validate(packet.model_dump(mode="python") | {"extra": "no"})
    masked = HandoffPacket.model_validate(
        packet.model_dump(mode="python") | {"goal": "/tmp/secret"}
    )
    assert "/tmp/secret" not in masked.goal
    with pytest.raises(ValidationError):
        HandoffPacket.model_validate(packet.model_dump(mode="python") | {"goal": "x" * 4001})


def test_handoff_projection_logs_fixed_exception_type_without_raw_details(caplog):
    class BrokenRegistry:
        def arg_schemas(self):
            raise RuntimeError("secret-path /tmp/private")

    with caplog.at_level(logging.WARNING, logger="forgeagent.collaboration"):
        packet = build_handoff_packet(_state(), "generator", registry=BrokenRegistry())

    assert packet.capabilities == ()
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "handoff.capability_projection_failed" in message
    assert "exception_type=RuntimeError" in message
    assert "secret-path" not in message
    assert "/tmp/private" not in message


def test_handoff_digest_is_deterministic_and_changes_with_checkpoint():
    state = _state()
    first = build_handoff_packet(state, "generator", registry=_Registry())
    second = build_handoff_packet(state, "generator", registry=_Registry())
    assert handoff_digest(first) == handoff_digest(second)

    changed = build_handoff_packet(
        _state(revision=1, generator_attempts=1),
        "generator",
        registry=_Registry(),
        attempt=2,
    )
    assert handoff_digest(first) != handoff_digest(changed)

    assert handoff_digest(first) != handoff_digest(
        build_handoff_packet(state, "generator", registry=_Registry(), attempt=1)
    )


def test_handoff_packet_has_bounded_public_facts_and_no_raw_receipt_identity():
    state = _state(
        last_evaluation=(
            {
                "id": "output",
                "passed": False,
                "observed": "missing secret-value",
                "expected": "Output exists",
                "location": "result.txt",
            },
        )
    )
    packet = build_handoff_packet(
        state,
        "generator",
        registry=_Registry(),
        rejection=state.last_evaluation,
    )
    rendered = json.dumps(packet.model_dump(mode="json"), ensure_ascii=True)
    assert "secret-value" not in rendered
    assert "/tmp/" not in rendered
    assert all(
        "action_id" not in json.dumps(item.model_dump(mode="json"))
        for item in packet.open_side_effects
    )


def test_handoff_receipt_projection_is_public_and_unavailable_is_explicit():
    class ReceiptStore:
        def list_pending(self, *, loop_id=None, task_id=None):
            del loop_id, task_id
            return (
                type(
                    "Receipt",
                    (),
                    {
                        "server_label": "server",
                        "tool_label": "tool",
                        "phase": "unknown",
                        "dispatch_certainty": "unknown",
                        "action_id": "private-action-id",
                    },
                )(),
            )

    packet = build_handoff_packet(
        _state(),
        "generator",
        registry=_Registry(),
        receipt_store=ReceiptStore(),
        task_id="task",
        loop_id="b" * 32,
    )
    assert packet.receipt_visibility == "available"
    assert packet.open_side_effects[0].phase == "unknown"
    assert "private-action-id" not in json.dumps(packet.model_dump(mode="json"))


def test_role_task_data_contains_handoff_and_audit_is_bounded(tmp_path):
    events = []

    class Sink:
        def emit(self, event):
            events.append(event)

    class Client(MockClient):
        def __init__(self, script):
            super().__init__(script)

    def reply(marker: dict[str, object]) -> AssistantMessage:
        return AssistantMessage(
            content=f"<!-- ToolCall: {json.dumps(marker)} -->",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_prompt_tokens=1),
            stop_reason="end_turn",
        )

    scripts = {
        ("generator", 1): [reply({"name": "SubmitCandidate", "arguments": {}})],
        ("evaluator", 1): [
            reply(
                {
                    "name": "SubmitEvaluation",
                    "arguments": {
                        "results": [
                            {
                                "id": "goal",
                                "passed": True,
                                "observed": "ok",
                                "expected": "ok",
                                "location": "artifact.txt",
                            }
                        ]
                    },
                }
            )
        ],
    }

    class Builder:
        def __call__(self, role, attempt, registry, system_prompt):
            del system_prompt
            return Task(Client(scripts[(role, attempt)]), tool_registry=registry)

    report = CollaborationRunner.create(
        mode="duo",
        goal="private goal",
        allowed_root=str(tmp_path),
        role_task_builder=Builder(),
        audit_sink=Sink(),
    ).run("private goal")

    assert report.status == "completed"
    handoffs = [event for event in events if event.event_type == "collaboration.handoff"]
    assert {event.parameters["role"] for event in handoffs} == {"generator", "evaluator"}
    assert all("private goal" not in repr(event.parameters) for event in handoffs)
