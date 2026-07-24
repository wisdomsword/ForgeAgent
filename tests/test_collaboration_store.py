"""Threat-boundary tests for durable collaboration snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import pytest

from forgeagent.collaboration import (
    MAX_GOAL_CHARS,
    MAX_STATE_BYTES,
    AcceptanceItem,
    CollaborationError,
    CollaborationStore,
    CollaborationUsage,
    EvaluationItem,
    plan_digest,
)


def test_store_creates_loads_and_atomically_saves_private_state(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="b" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / ("b" * 32 + ".json")

    assert store.load(created.collaboration_id) == created
    assert created.status == "active"
    assert created.phase == "generator"
    assert created.plan[0].behavior == "Satisfy the original task goal"
    assert path.stat().st_mode & 0o777 == 0o600
    saved = store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)
    assert saved.revision == 1
    assert json.loads(path.read_text())["revision"] == 1


def test_store_create_is_total_for_valid_goals_and_accepts_only_configuration(
    tmp_path: Path,
):
    store = CollaborationStore(str(tmp_path))
    created = store.create(
        "x" * MAX_GOAL_CHARS,
        "duo",
        collaboration_id="0" * 32,
        planner_model="planner",
        generator_model="generator",
        evaluator_model="evaluator",
        evaluator_tier="container",
        max_rejections=3,
        usage_available=False,
    )

    assert created.phase == "generator"
    assert created.plan_digest == plan_digest(created.plan)
    assert created.generator_model == "generator"
    assert created.max_rejections == 3
    assert created.usage_available is False

    lifecycle_values = {
        "phase": "evaluator",
        "status": "completed",
        "plan": created.plan,
        "plan_digest": created.plan_digest,
        "revision": 1,
        "rounds": 1,
        "last_evaluation": (),
    }
    for name, value in lifecycle_values.items():
        with pytest.raises(TypeError):
            store.create("another", "duo", **{name: value})


def test_store_rejects_stale_corrupt_oversized_and_unknown_schema(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    saved = store.save(created, expected_revision=0)
    with pytest.raises(CollaborationError):
        store.save(created, expected_revision=0)

    path = tmp_path / ".forgeagent" / "collaborations" / ("d" * 32 + ".json")
    path.write_bytes(b'{"schema":"unknown"}')
    with pytest.raises(CollaborationError):
        store.load("d" * 32)
    path.write_bytes(b"x" * (MAX_STATE_BYTES + 1))
    with pytest.raises(CollaborationError):
        store.load("d" * 32)
    assert saved.revision == 1


def test_store_rejects_symlink_and_directory_replacement(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    store = CollaborationStore(str(root))
    created = store.create("Build an artifact", "duo", collaboration_id="e" * 32)
    path = root / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    path.unlink()
    path.symlink_to(outside / "state.json")
    with pytest.raises(CollaborationError):
        store.load(created.collaboration_id)

    directory = root / ".forgeagent" / "collaborations"
    original = tmp_path / "original"
    directory.rename(original)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(CollaborationError):
        store.create("Another", "duo", collaboration_id="f" * 32)


def test_store_replace_failure_preserves_old_state_and_close_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="1" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    old = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    with pytest.raises(CollaborationError):
        store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)
    assert path.read_bytes() == old
    store.close()
    store.close()
    with pytest.raises(CollaborationError):
        store.load(created.collaboration_id)


def test_store_refuses_replacing_a_frozen_plan(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="2" * 32)
    replacement = (AcceptanceItem(id="other", behavior="other", acceptance="other"),)

    with pytest.raises(CollaborationError):
        store.save(
            created.model_copy(
                update={"plan": replacement, "plan_digest": plan_digest(replacement)}
            ),
            expected_revision=0,
        )


@pytest.mark.parametrize(
    ("updates", "label"),
    [
        ({"phase": "generator"}, "phase"),
        ({"status": "active", "phase": "generator", "stop_reason": None}, "terminal status"),
        ({"generator_attempts": 1}, "generator attempts"),
        ({"evaluator_attempts": 1}, "evaluator attempts"),
        ({"rejections": 0}, "rejections"),
        ({"rounds": 4}, "rounds"),
        ({"usage": CollaborationUsage(input_tokens=4)}, "usage"),
        ({"goal": "Changed goal"}, "goal"),
        ({"mode": "triad"}, "mode"),
        ({"generator_model": "changed"}, "role config"),
    ],
)
def test_store_rejects_nonmonotonic_state_transitions(
    tmp_path: Path, updates: dict[str, object], label: str
):
    evaluation = (EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),)
    store = CollaborationStore(str(tmp_path))
    created = store.create(
        "Build an artifact",
        "duo",
        collaboration_id="3" * 32,
        generator_model="generator",
        evaluator_model="evaluator",
    )
    evaluated = store.save(
        created.model_copy(
            update={
                "phase": "evaluator",
                "generator_attempts": 2,
                "evaluator_attempts": 2,
                "rejections": 1,
                "rounds": 5,
                "usage": CollaborationUsage(input_tokens=5, output_tokens=3, cost=1.0),
                "last_evaluation": evaluation,
            }
        ),
        expected_revision=0,
    )
    current = store.save(
        evaluated.model_copy(
            update={"status": "completed", "phase": "completed", "stop_reason": "completed"}
        ),
        expected_revision=1,
    )

    expected_error = "state|transition" if label == "goal" else "transition"
    with pytest.raises(CollaborationError, match=expected_error):
        store.save(current.model_copy(update=updates), expected_revision=2)


def test_store_rejects_completed_status_in_an_execution_phase(tmp_path: Path):
    evaluation = (EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),)
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="7" * 32)
    current = store.save(
        created.model_copy(update={"phase": "evaluator", "last_evaluation": evaluation}),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError):
        store.save(
            current.model_copy(update={"status": "completed", "stop_reason": "completed"}),
            expected_revision=1,
        )


@pytest.mark.parametrize(
    ("mode", "values"),
    [
        ("duo", {"phase": "planning"}),
        ("duo", {"phase": "needs_confirmation"}),
        ("triad", {"phase": "generator"}),
        ("triad", {"phase": "evaluator"}),
        ("triad", {"plan_digest": "f" * 64}),
    ],
)
def test_store_create_rejects_lifecycle_state_injection(
    tmp_path: Path, mode: Literal["duo", "triad"], values: dict[str, object]
):
    store = CollaborationStore(str(tmp_path))
    with pytest.raises(TypeError):
        store.create(
            "Build an artifact",
            mode,
            collaboration_id="8" * 32,
            **values,
        )


def test_store_rejects_a_caller_supplied_duo_plan(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    with pytest.raises(TypeError):
        store.create(
            "Build an artifact",
            "duo",
            collaboration_id="9" * 32,
            plan=(AcceptanceItem(id="other", behavior="other", acceptance="other"),),
        )


def test_store_rejects_plan_fact_loss_before_plan_freezes(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    current = store.create("Build an artifact", "triad", collaboration_id="4" * 32)
    plan = (AcceptanceItem(id="output", behavior="output", acceptance="exists"),)
    saved = store.save(
        current.model_copy(
            update={"plan": plan, "plan_digest": plan_digest(plan), "phase": "needs_confirmation"}
        ),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(
            saved.model_copy(update={"plan": (), "plan_digest": "", "phase": "planning"}),
            expected_revision=1,
        )


def test_store_rejects_evaluation_fact_loss(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="5" * 32)
    current = store.save(
        created.model_copy(
            update={
                "phase": "evaluator",
                "last_evaluation": (
                    EvaluationItem(id="goal", passed=False, observed="missing", expected="present"),
                ),
            }
        ),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(current.model_copy(update={"last_evaluation": ()}), expected_revision=1)


def test_store_rejects_restoring_unavailable_usage(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    current = store.create(
        "Build an artifact",
        "duo",
        collaboration_id="6" * 32,
        usage_available=False,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(current.model_copy(update={"usage_available": True}), expected_revision=0)


def test_store_projects_direct_state_evidence_before_environment_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = "store-boundary-secret-value"
    host_path = "/Users/admin/private/result.txt"
    monkeypatch.setenv("COLLABORATION_STORE_SECRET", secret)
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="a" * 32)
    unsafe = EvaluationItem.model_construct(
        id="goal",
        passed=False,
        observed=f"found {secret} at {host_path}",
        expected=f"remove {secret} from {host_path}",
        location="result.txt",
    )

    saved = store.save(
        created.model_copy(update={"phase": "evaluator", "last_evaluation": (unsafe,)}),
        expected_revision=0,
    )
    path = tmp_path / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    persisted = path.read_text()
    monkeypatch.delenv("COLLABORATION_STORE_SECRET")
    loaded = store.load(created.collaboration_id)

    assert secret not in persisted
    assert host_path not in persisted
    assert secret not in loaded.model_dump_json()
    assert host_path not in loaded.model_dump_json()
    assert loaded == saved


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_DIRECTORY"])
def test_store_fails_closed_without_safe_open_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
):
    monkeypatch.delattr(os, flag, raising=False)

    with pytest.raises(CollaborationError, match="safe file access is unavailable"):
        CollaborationStore(str(tmp_path))
