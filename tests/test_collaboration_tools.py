"""Contract tests for isolated collaboration role tools."""

from __future__ import annotations

from pathlib import Path

from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationStore,
    SubmitEvaluationArgs,
    SubmitEvaluationTool,
    SubmitPlanArgs,
    SubmitPlanTool,
    build_evaluator_registry,
    build_planner_registry,
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
    state = store.create(
        "Build an artifact",
        "duo",
        collaboration_id="b" * 32,
        plan=(
            AcceptanceItem(id="first", behavior="first", acceptance="first"),
            AcceptanceItem(id="second", behavior="second", acceptance="second"),
        ),
    )
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
