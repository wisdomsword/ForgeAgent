"""Deterministic collaboration mode routing tests."""

from __future__ import annotations

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.collaboration import (
    ModeDecision,
    emit_collaboration_route,
    resolve_collaboration_mode,
)


@pytest.mark.parametrize("goal", ["Add a unit test", "修改 Main.java", "Explain Python"])
def test_unqualified_goals_default_to_single(goal: str) -> None:
    assert resolve_collaboration_mode(goal, None) == ModeDecision(mode="single", reason="default")


def test_bound_checks_select_triad_without_exposing_check_content() -> None:
    decision = resolve_collaboration_mode("Add a unit test", None, has_bound_checks=True)

    assert decision == ModeDecision(mode="triad", reason="bound_checks")


@pytest.mark.parametrize("mode", ["single", "duo", "triad"])
@pytest.mark.parametrize("allow_weaker_override", [False, True])
def test_explicit_mode_wins_over_bound_checks(mode: str, allow_weaker_override: bool) -> None:
    decision = resolve_collaboration_mode(
        "Add a unit test",
        mode,  # type: ignore[arg-type]
        has_bound_checks=True,
        allow_weaker_override=allow_weaker_override,
    )

    assert decision.mode == mode
    assert decision.reason == "explicit"
    assert decision.override_required is False


def test_bound_checks_route_audit_excludes_goal_and_check_details() -> None:
    events: list[AuditEvent] = []

    class Sink:
        def emit(self, event: AuditEvent) -> bool:
            events.append(event)
            return True

    decision = resolve_collaboration_mode("PRIVATE_GOAL", None, has_bound_checks=True)
    assert emit_collaboration_route(Sink(), decision, None) is True

    event = events[0]
    assert event.parameters == {
        "mode": "triad",
        "reason": "bound_checks",
        "requested_mode": "default",
        "override_required": False,
    }
    rendered = repr(event)
    for secret in ("PRIVATE_GOAL", "argv", "path", "check-id"):
        assert secret not in rendered
