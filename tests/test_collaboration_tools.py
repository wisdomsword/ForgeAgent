"""Contract tests for isolated collaboration role tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationStore,
    SubmitEvaluationArgs,
    SubmitEvaluationTool,
    SubmitPlanArgs,
    SubmitPlanTool,
    build_evaluator_registry,
    build_planner_registry,
    plan_digest,
)


def test_submit_plan_commits_before_success_and_rejects_duplicate_and_how_only(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "triad", collaboration_id="a" * 32)
    tool = SubmitPlanTool(store, state)
    valid = SubmitPlanArgs(
        items=[AcceptanceItem(id="artifact", behavior="Writes output", acceptance="Output exists")]
    )

    outcome = tool.run(valid, None)

    assert outcome.success is True
    assert store.load(state.collaboration_id).plan[0].id == "artifact"
    duplicate = tool.run(
        SubmitPlanArgs.model_construct(
            items=(
                AcceptanceItem(id="same", behavior="one", acceptance="observable"),
                AcceptanceItem(id="same", behavior="two", acceptance="observable"),
            )
        ),
        None,
    )
    how_only = SubmitPlanTool(store, state).run(
        SubmitPlanArgs(
            items=[AcceptanceItem(id="how", behavior="works", acceptance="Use library xyz")]
        ),
        None,
    )
    assert duplicate.success is False
    assert how_only.success is False


def test_submit_evaluation_requires_exact_frozen_ids_and_registry_is_read_only(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    initial = store.create("Build an artifact", "triad", collaboration_id="b" * 32)
    plan = (
        AcceptanceItem(id="first", behavior="first", acceptance="first"),
        AcceptanceItem(id="second", behavior="second", acceptance="second"),
    )
    submitted = store.save(
        initial.model_copy(
            update={"phase": "needs_confirmation", "plan": plan, "plan_digest": plan_digest(plan)}
        ),
        expected_revision=0,
    )
    state = store.save(submitted.model_copy(update={"phase": "generator"}), expected_revision=1)
    tool = SubmitEvaluationTool(store, state)
    missing = tool.run(SubmitEvaluationArgs.model_construct(results=()), None)
    correct = tool.run(
        SubmitEvaluationArgs(
            results=[
                {"id": "second", "passed": True, "observed": "yes", "expected": "yes"},
                {"id": "first", "passed": True, "observed": "yes", "expected": "yes"},
            ]
        ),
        None,
    )
    planner = build_planner_registry(store=store, state=state)
    evaluator = build_evaluator_registry(store=store, state=state)

    assert missing.success is False
    assert correct.success is True
    assert tuple(item.id for item in store.load(state.collaboration_id).last_evaluation) == (
        "first",
        "second",
    )
    assert set(planner.arg_schemas()) == {"SubmitPlan"}
    assert set(evaluator.arg_schemas()) == {"FileRead", "FileList", "SubmitEvaluation"}


def test_submit_evaluation_masks_evidence_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("COLLABORATION_SECRET", "persisted-secret-value")
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    tool = SubmitEvaluationTool(store, state)

    outcome = tool.run(
        SubmitEvaluationArgs(
            results=[
                {
                    "id": "goal",
                    "passed": False,
                    "observed": "found persisted-secret-value",
                    "expected": "not persisted-secret-value",
                    "location": "result.txt",
                }
            ]
        ),
        None,
    )
    monkeypatch.delenv("COLLABORATION_SECRET")
    persisted = store.load(state.collaboration_id)

    assert outcome.success is True
    assert "persisted-secret-value" not in persisted.model_dump_json()


@pytest.mark.parametrize(
    "path", ["C:/Users/admin/private/result.txt", r"C:\Users\admin\private\result.txt"]
)
def test_submit_evaluation_redacts_windows_paths_before_persistence(tmp_path: Path, path: str):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "duo", collaboration_id="d" * 32)
    tool = SubmitEvaluationTool(store, state)

    outcome = tool.run(
        SubmitEvaluationArgs(
            results=[
                {
                    "id": "goal",
                    "passed": False,
                    "observed": f"artifact at {path}",
                    "expected": f"no host path such as {path}",
                    "location": "result.txt",
                }
            ]
        ),
        None,
    )
    persisted = store.load(state.collaboration_id).model_dump_json()

    assert outcome.success is True
    assert path not in persisted
    assert "<redacted-path>" in persisted
