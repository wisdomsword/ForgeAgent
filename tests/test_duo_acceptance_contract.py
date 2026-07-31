"""Golden tests for deterministic Duo acceptance plans."""

from __future__ import annotations

import json

import pytest

from forgeagent.collaboration import (
    COLLABORATION_SCHEMA,
    AcceptanceItem,
    CollaborationError,
    CollaborationStore,
    _duo_plan,
    plan_digest,
)


@pytest.mark.parametrize(
    ("goal", "behavior_fragment", "acceptance_fragment"),
    [
        ("Write report.md", "inspectable artifact", "relative artifact"),
        ("Run pytest and verify the build", "verification", "check result"),
        ("Analyze the failure and explain the cause", "concrete response", "response excerpt"),
        ("Explain the latest profile setting", "concrete response", "response excerpt"),
    ],
)
def test_duo_plan_has_observable_golden_contracts(
    goal: str, behavior_fragment: str, acceptance_fragment: str
):
    plan = _duo_plan(goal)

    assert len(plan) == 1
    assert plan[0].id == "goal"
    assert behavior_fragment in plan[0].behavior.casefold()
    assert acceptance_fragment in plan[0].acceptance.casefold()


def test_duo_plan_is_deterministic_and_avoids_pseudo_acceptance():
    first = _duo_plan("Write report.md")
    second = _duo_plan("Write report.md")
    rendered = repr(first).casefold()

    assert first == second
    assert plan_digest(first) == plan_digest(second)
    assert "original task goal" not in rendered
    assert "satisfy the user" not in rendered


def test_duo_plan_does_not_copy_goal_paths_or_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUO_CONTRACT_SECRET", "private-value")
    goal = "Process /data/input.csv with private-value"

    rendered = repr(_duo_plan(goal))

    assert goal not in rendered
    assert "/data/input.csv" not in rendered
    assert "private-value" not in rendered


def test_store_loads_legacy_duo_plan_without_recomputing_it(tmp_path):
    store = CollaborationStore(str(tmp_path))
    collaboration_id = "a" * 32
    legacy_plan = (
        AcceptanceItem(
            id="goal",
            behavior="Satisfy the original task goal",
            acceptance="External artifacts satisfy the original task goal",
        ),
    )
    path = tmp_path / ".forgeagent" / "collaborations" / f"{collaboration_id}.json"
    path.write_text(
        json.dumps(
            {
                "schema": COLLABORATION_SCHEMA,
                "collaboration_id": collaboration_id,
                "mode": "duo",
                "phase": "generator",
                "goal": "Build an artifact",
                "plan": [item.model_dump(mode="json") for item in legacy_plan],
                "plan_digest": plan_digest(legacy_plan),
            }
        )
    )

    loaded = store.load(collaboration_id)

    assert loaded.plan == legacy_plan
    assert loaded.plan_digest == plan_digest(legacy_plan)


def test_store_keeps_invalid_goal_errors_inside_the_collaboration_boundary(tmp_path):
    store = CollaborationStore(str(tmp_path))

    with pytest.raises(CollaborationError, match="invalid collaboration state"):
        store.create(123, "duo")  # type: ignore[arg-type]
