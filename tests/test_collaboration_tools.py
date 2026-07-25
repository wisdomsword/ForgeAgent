"""Contract tests for isolated collaboration role tools."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from forgeagent.check_runner import CheckDefinition, CheckResult
from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationStore,
    RunCheckArgs,
    RunCheckTool,
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
    behavior_how = SubmitPlanTool(store, state).run(
        SubmitPlanArgs(
            items=[
                AcceptanceItem(
                    id="behavior-how",
                    behavior="Implement with the requests library",
                    acceptance="The client returns HTTP 200",
                )
            ]
        ),
        None,
    )
    assert duplicate.success is False
    assert how_only.success is False
    assert behavior_how.success is False


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


def test_evaluator_registry_adds_only_host_defined_checks(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "duo", collaboration_id="e" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-m", "pytest", "-q"))}

    evaluator = build_evaluator_registry(store=store, state=state, checks=checks)

    assert set(evaluator.arg_schemas()) == {
        "FileRead",
        "FileList",
        "RunCheck",
        "SubmitEvaluation",
    }
    with pytest.raises(ValidationError):
        RunCheckArgs.model_validate({"check_id": "unit", "argv": ["sh", "-c", "id"]})


def test_run_check_rejects_unknown_id_without_starting_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def unexpected_runner(*args, **kwargs):  # noqa: ANN002, ANN003
        pytest.fail("unknown check id must not start a process")

    monkeypatch.setattr("forgeagent.collaboration.run_check", unexpected_runner)
    tool = RunCheckTool(
        {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-m", "pytest", "-q"))}
    )

    outcome = tool.run(
        RunCheckArgs(check_id="missing"),
        SimpleNamespace(allowed_root=str(tmp_path), cancel_event=None),
    )

    assert outcome.success is False
    assert outcome.detail == "RunCheck rejected: unknown check_id 'missing'"


def test_run_check_reports_structured_host_check_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    expected = CheckResult(status="failed", exit_code=3, duration_ms=12, stdout="out", stderr="err")
    monkeypatch.setattr("forgeagent.collaboration.run_check", lambda *args, **kwargs: expected)
    tool = RunCheckTool({"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))})

    outcome = tool.run(
        RunCheckArgs(check_id="unit"),
        SimpleNamespace(allowed_root=str(tmp_path), cancel_event=None),
    )

    assert outcome.success is False
    assert "check=unit status=failed exit_code=3 duration_ms=12" in outcome.detail
    assert "stdout:\nout" in outcome.detail
    assert "stderr:\nerr" in outcome.detail


def test_run_check_rejects_invalid_direct_arguments_without_raising(tmp_path: Path):
    tool = RunCheckTool({"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))})
    invalid = RunCheckArgs.model_construct(check_id="not valid")

    outcome = tool.run(
        invalid,
        SimpleNamespace(allowed_root=str(tmp_path), cancel_event=None),
    )

    assert outcome.success is False
    assert outcome.detail == "RunCheck rejected: invalid arguments"


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
