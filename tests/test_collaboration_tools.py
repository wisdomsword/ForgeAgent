"""Contract tests for isolated collaboration role tools."""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import forgeagent.collaboration as collaboration_module
from forgeagent.audit import AuditEvent
from forgeagent.check_runner import CheckDefinition, CheckResult
from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationStore,
    EvaluationItem,
    RunCheckArgs,
    RunCheckTool,
    SubmitCandidateArgs,
    SubmitCandidateTool,
    SubmitEvaluationArgs,
    SubmitEvaluationTool,
    SubmitPlanArgs,
    SubmitPlanTool,
    build_evaluator_registry,
    build_generator_registry,
    build_planner_registry,
    candidate_snapshot_digest,
    normalize_required_candidate_files,
    plan_digest,
)
from forgeagent.executor import TrustedBackend
from forgeagent.policy import CodeAnalyzer
from forgeagent.runtime import Runtime
from forgeagent.tools import CodeBlockStore, ToolContext, default_registry


class _AuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def _tool_context(root: Path, *, audit_sink: _AuditSink | None = None) -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        tier="trusted",
        allowed_root=str(root),
        audit_sink=audit_sink,
        task_id="task-123",
        operation_id="operation-456",
    )


def test_required_candidate_files_are_bounded_safe_top_level_names():
    assert normalize_required_candidate_files(["calc.py", "test_calc.py"]) == (
        "calc.py",
        "test_calc.py",
    )
    assert normalize_required_candidate_files(()) == ()

    invalid = (
        "not-a-sequence",
        [""],
        ["a", "a"],
        ["a"] * 17,
        ["a" * 129],
        ["."],
        [".."],
        ["a/b"],
        ["a\\b"],
        ["/tmp/a"],
        ["control\n.py"],
        ["calc-测试.py"],
        [1],
    )
    for value in invalid:
        with pytest.raises(ValueError, match="required candidate files are invalid"):
            normalize_required_candidate_files(value)


def test_submit_candidate_requires_configured_regular_files(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifacts", "duo", collaboration_id="8" * 32)
    tool = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py", "test_calc.py"),
    )
    before = store.load(state.collaboration_id)

    missing = tool.run(SubmitCandidateArgs(), _tool_context(tmp_path))

    assert missing.success is False
    assert missing.detail.endswith("calc.py, test_calc.py")
    assert store.load(state.collaboration_id) == before

    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    partial = tool.run(SubmitCandidateArgs(), _tool_context(tmp_path))
    assert partial.success is False
    assert partial.detail.endswith("test_calc.py")
    assert store.load(state.collaboration_id) == before

    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    submitted = tool.run(SubmitCandidateArgs(), _tool_context(tmp_path))
    persisted = store.load(state.collaboration_id)
    assert submitted.success is True
    assert submitted.completes_task is True
    assert persisted.phase == "evaluator"
    assert persisted.generator_attempts == 1


def test_collaboration_artifacts_remain_project_scoped_after_full_disk_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "calc.py").write_text("pass\n", encoding="utf-8")
    state_root = tmp_path / "state"
    state_root.mkdir()
    store = CollaborationStore(str(state_root))
    generator = store.create("Build artifact", "duo", collaboration_id="0" * 32)
    ctx = _tool_context(project)
    ctx.allowed_root = project.anchor
    ctx.project_root = str(project)

    submitted = SubmitCandidateTool(
        store,
        generator,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), ctx)
    evaluator_state = store.load(generator.collaboration_id)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    captured_roots = []

    def pass_check(definition, *, allowed_root, cancel_event):
        captured_roots.append(allowed_root)
        return CheckResult(
            status="passed",
            snapshot_digest=candidate_snapshot_digest(allowed_root),
        )

    monkeypatch.setattr("forgeagent.collaboration.run_check", pass_check)
    registry = build_evaluator_registry(store=store, state=evaluator_state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None

    checked = run.run(RunCheckArgs(check_id="unit"), ctx)
    evaluated = submit.run(_passing_evaluation(), ctx)

    assert submitted.success is True
    assert checked.success is True
    assert evaluated.success is True
    assert captured_roots == [str(project)]


@pytest.mark.parametrize("unsafe_kind", ["directory", "symlink", "fifo"])
def test_submit_candidate_rejects_non_regular_required_file(tmp_path: Path, unsafe_kind: str):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifact", "duo", collaboration_id="7" * 32)
    target = tmp_path / "calc.py"
    if unsafe_kind == "directory":
        target.mkdir()
    elif unsafe_kind == "symlink":
        real = tmp_path / "real.py"
        real.write_text("pass\n", encoding="utf-8")
        target.symlink_to(real)
    else:
        os.mkfifo(target)
    before = store.load(state.collaboration_id)

    outcome = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), _tool_context(tmp_path))

    assert outcome.success is False
    assert outcome.detail.endswith("calc.py")
    assert store.load(state.collaboration_id) == before


def test_candidate_file_check_fails_closed_for_invalid_root(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifact", "duo", collaboration_id="4" * 32)
    before = store.load(state.collaboration_id)

    outcome = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), SimpleNamespace(allowed_root="\0"))

    assert outcome.success is False
    assert outcome.detail.endswith("calc.py")
    assert store.load(state.collaboration_id) == before


def test_candidate_file_check_uses_nonblocking_open(tmp_path: Path, monkeypatch):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifact", "duo", collaboration_id="6" * 32)
    original_open = os.open
    candidate_flags = []
    root_flags = []

    def recording_open(path, flags, *args, **kwargs):
        if path == "calc.py":
            candidate_flags.append(flags)
            raise OSError(errno.ENOENT, "missing")
        if Path(path) == tmp_path:
            root_flags.append(flags)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)

    outcome = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), _tool_context(tmp_path))

    assert outcome.success is False
    assert candidate_flags[0] & os.O_NONBLOCK
    assert candidate_flags[0] & os.O_NOFOLLOW
    assert root_flags[0] & os.O_DIRECTORY
    assert root_flags[0] & os.O_NOFOLLOW


def test_candidate_file_check_fails_closed_when_root_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifact", "duo", collaboration_id="5" * 32)
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    before = store.load(state.collaboration_id)
    original_open = os.open
    original_close = os.close
    root_fd = None

    def recording_open(path, flags, *args, **kwargs):
        nonlocal root_fd
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == tmp_path:
            root_fd = descriptor
        return descriptor

    def failing_close(descriptor):
        if descriptor == root_fd:
            original_close(descriptor)
            raise OSError(errno.EIO, "close failed")
        original_close(descriptor)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "close", failing_close)

    outcome = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), _tool_context(tmp_path))

    assert outcome.success is False
    assert outcome.detail.endswith("calc.py")
    assert store.load(state.collaboration_id) == before


def test_candidate_file_check_fails_closed_when_root_binding_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build artifact", "duo", collaboration_id="3" * 32)
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    before = store.load(state.collaboration_id)
    binding_checks = iter((True, False))
    monkeypatch.setattr(
        collaboration_module,
        "_root_binding_matches",
        lambda *_args: next(binding_checks),
    )

    outcome = SubmitCandidateTool(
        store,
        state,
        required_candidate_files=("calc.py",),
    ).run(SubmitCandidateArgs(), _tool_context(tmp_path))

    assert outcome.success is False
    assert outcome.detail.endswith("calc.py")
    assert store.load(state.collaboration_id) == before


def test_submit_plan_commits_before_success_and_rejects_duplicate_and_how_only(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "triad", collaboration_id="a" * 32)
    tool = SubmitPlanTool(store, state)
    valid = SubmitPlanArgs(
        items=[AcceptanceItem(id="artifact", behavior="Writes output", acceptance="Output exists")]
    )

    outcome = tool.run(valid, None)

    assert outcome.success is True
    assert outcome.completes_task is True
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


def test_submit_candidate_atomically_advances_attempt_and_clears_old_verdict(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    initial = store.create("Build an artifact", "duo", collaboration_id="f" * 32)
    rejected = store.save(
        initial.model_copy(
            update={
                "last_evaluation": (
                    EvaluationItem(
                        id="goal",
                        passed=False,
                        observed="old",
                        expected="fixed",
                    ),
                )
            }
        ),
        expected_revision=0,
    )
    tool = SubmitCandidateTool(store, rejected)

    outcome = tool.run(SubmitCandidateArgs(), None)
    persisted = store.load(initial.collaboration_id)

    assert outcome.success is True
    assert outcome.completes_task is True
    assert persisted.phase == "evaluator"
    assert persisted.generator_attempts == 1
    assert persisted.last_evaluation == ()

    duplicate = tool.run(SubmitCandidateArgs(), None)
    assert duplicate.success is False
    assert store.load(initial.collaboration_id) == persisted


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
    generator = store.save(submitted.model_copy(update={"phase": "generator"}), expected_revision=1)
    candidate = SubmitCandidateTool(store, generator).run(SubmitCandidateArgs(), None)
    assert candidate.success is True
    state = store.load(initial.collaboration_id)
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
    assert correct.completes_task is True
    persisted = store.load(state.collaboration_id)
    assert persisted.evaluator_attempts == 1
    assert persisted.phase == "evaluator"
    assert tuple(item.id for item in persisted.last_evaluation) == (
        "first",
        "second",
    )
    assert set(planner.arg_schemas()) == {"SubmitPlan"}
    assert set(evaluator.arg_schemas()) == {"FileRead", "FileList", "SubmitEvaluation"}
    assert planner.required_completion_tool == "SubmitPlan"
    assert evaluator.required_completion_tool == "SubmitEvaluation"


def test_generator_registry_preserves_existing_tools_and_requires_candidate(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    state = store.create("Build an artifact", "duo", collaboration_id="9" * 32)
    registry = default_registry()

    result = build_generator_registry(registry=registry, store=store, state=state)

    assert result is registry
    assert "FileWrite" in result.arg_schemas()
    assert "SubmitCandidate" in result.arg_schemas()
    assert result.required_completion_tool == "SubmitCandidate"


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
    with pytest.raises(ValidationError):
        RunCheckArgs.model_validate({"check_id": "unit", "snapshot_digest": "model-controlled"})
    with pytest.raises(ValidationError):
        SubmitEvaluationArgs.model_validate(
            {
                "results": [
                    {
                        "id": "goal",
                        "passed": True,
                        "observed": "yes",
                        "expected": "yes",
                    }
                ],
                "check_results": {"unit": "passed"},
            }
        )


def _pending_duo_evaluation(
    tmp_path: Path, collaboration_id: str
) -> tuple[CollaborationStore, object]:
    store = CollaborationStore(str(tmp_path))
    generator = store.create("Build an artifact", "duo", collaboration_id=collaboration_id)
    assert SubmitCandidateTool(store, generator).run(SubmitCandidateArgs(), None).success is True
    return store, store.load(generator.collaboration_id)


def _passing_evaluation() -> SubmitEvaluationArgs:
    return SubmitEvaluationArgs(
        results=[
            {
                "id": "goal",
                "passed": True,
                "observed": "yes",
                "expected": "yes",
            }
        ]
    )


def test_registered_check_must_run_before_all_pass_evaluation_is_saved(tmp_path: Path):
    store, state = _pending_duo_evaluation(tmp_path, "1" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    submit = registry.get("SubmitEvaluation")
    assert submit is not None

    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))
    after = store.load(state.collaboration_id)

    assert outcome.success is False
    assert "unit" in outcome.detail
    assert after == before
    assert after.evaluator_attempts == 0


@pytest.mark.parametrize("status", ["failed", "timeout", "cancelled", "copy_error", "start_error"])
def test_nonpassing_check_evidence_cannot_be_overridden_by_all_pass_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
):
    store, state = _pending_duo_evaluation(tmp_path, "2" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status=status, snapshot_digest="snapshot"),
    )
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None

    assert run.run(RunCheckArgs(check_id="unit"), _tool_context(tmp_path)).success is False
    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))

    assert outcome.success is False
    assert store.load(state.collaboration_id) == before


def test_all_pass_evaluation_rejects_checks_from_different_candidate_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, state = _pending_duo_evaluation(tmp_path, "3" * 32)
    checks = {
        check_id: CheckDefinition(id=check_id, argv=(sys.executable, "-c", "pass"))
        for check_id in ("unit", "lint")
    }
    digests = iter(("snapshot-a", "snapshot-b"))
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status="passed", snapshot_digest=next(digests)),
    )
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None
    for check_id in checks:
        assert run.run(RunCheckArgs(check_id=check_id), _tool_context(tmp_path)).success is True

    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))

    assert outcome.success is False
    assert store.load(state.collaboration_id) == before


def test_all_pass_evaluation_rejects_candidate_changed_after_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, state = _pending_duo_evaluation(tmp_path, "4" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status="passed", snapshot_digest="old-snapshot"),
    )
    monkeypatch.setattr(
        "forgeagent.collaboration.candidate_snapshot_digest", lambda root: "current-snapshot"
    )
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None
    assert run.run(RunCheckArgs(check_id="unit"), _tool_context(tmp_path)).success is True

    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))

    assert outcome.success is False
    assert store.load(state.collaboration_id) == before


def test_all_pass_evaluation_rejects_check_evidence_from_another_generator_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, state = _pending_duo_evaluation(tmp_path, "8" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    evidence = {}
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status="passed", snapshot_digest="snapshot"),
    )
    run = RunCheckTool(checks, evidence, state.generator_attempts)
    assert run.run(RunCheckArgs(check_id="unit"), _tool_context(tmp_path)).success is True
    later_attempt = state.model_copy(update={"generator_attempts": state.generator_attempts + 1})
    submit = SubmitEvaluationTool(store, later_attempt, checks, evidence)

    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))

    assert outcome.success is False
    assert store.load(state.collaboration_id) == before


def test_all_checks_on_current_snapshot_allow_all_pass_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, state = _pending_duo_evaluation(tmp_path, "5" * 32)
    checks = {
        check_id: CheckDefinition(id=check_id, argv=(sys.executable, "-c", "pass"))
        for check_id in ("unit", "lint")
    }
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status="passed", snapshot_digest="snapshot"),
    )
    monkeypatch.setattr(
        "forgeagent.collaboration.candidate_snapshot_digest", lambda root: "snapshot"
    )
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None
    for check_id in checks:
        assert run.run(RunCheckArgs(check_id=check_id), _tool_context(tmp_path)).success is True

    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))
    persisted = store.load(state.collaboration_id)

    assert outcome.success is True
    assert persisted.evaluator_attempts == 1
    assert all(item.passed for item in persisted.last_evaluation)


def test_failing_evaluation_can_be_saved_without_running_registered_checks(tmp_path: Path):
    store, state = _pending_duo_evaluation(tmp_path, "6" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    submit = registry.get("SubmitEvaluation")
    assert submit is not None

    outcome = submit.run(
        SubmitEvaluationArgs(
            results=[
                {
                    "id": "goal",
                    "passed": False,
                    "observed": "missing",
                    "expected": "present",
                }
            ]
        ),
        _tool_context(tmp_path),
    )

    assert outcome.success is True
    assert store.load(state.collaboration_id).evaluator_attempts == 1


def test_candidate_digest_error_rejects_without_leaking_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, state = _pending_duo_evaluation(tmp_path, "7" * 32)
    checks = {"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))}
    monkeypatch.setattr(
        "forgeagent.collaboration.run_check",
        lambda *args, **kwargs: CheckResult(status="passed", snapshot_digest="secret-digest"),
    )
    monkeypatch.setattr(
        "forgeagent.collaboration.candidate_snapshot_digest",
        lambda root: (_ for _ in ()).throw(OSError("/private/candidate/path")),
    )
    registry = build_evaluator_registry(store=store, state=state, checks=checks)
    run = registry.get("RunCheck")
    submit = registry.get("SubmitEvaluation")
    assert run is not None and submit is not None
    assert run.run(RunCheckArgs(check_id="unit"), _tool_context(tmp_path)).success is True

    before = store.load(state.collaboration_id)
    outcome = submit.run(_passing_evaluation(), _tool_context(tmp_path))

    assert outcome.success is False
    assert "/private/candidate/path" not in outcome.detail
    assert "secret-digest" not in outcome.detail
    assert store.load(state.collaboration_id) == before


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


def test_run_check_audits_only_safe_stable_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sink = _AuditSink()
    expected = CheckResult(
        status="failed",
        exit_code=3,
        duration_ms=12,
        stdout="PRIVATE_STDOUT",
        stderr="PRIVATE_STDERR",
        snapshot_digest="PRIVATE_DIGEST",
    )
    definition = CheckDefinition(
        id="unit",
        argv=(sys.executable, "-c", "print('PRIVATE_ARGV')"),
    )
    monkeypatch.setattr("forgeagent.collaboration.run_check", lambda *args, **kwargs: expected)
    tool = RunCheckTool({"unit": definition}, generator_attempt=7)

    outcome = tool.run(
        RunCheckArgs(check_id="unit"),
        _tool_context(tmp_path, audit_sink=sink),
    )

    assert outcome.success is False
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event_type == "collaboration.check"
    assert event.task_id == "task-123"
    assert event.operation_id == "operation-456"
    assert event.attempt == 7
    assert event.parameters == {"check_id": "unit"}
    assert event.result_status == "failed"
    assert event.duration_ms == 12
    rendered = repr(event)
    for private_value in (
        "PRIVATE_ARGV",
        str(tmp_path),
        "PRIVATE_STDOUT",
        "PRIVATE_STDERR",
        "PRIVATE_DIGEST",
    ):
        assert private_value not in rendered


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
    generator = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    assert SubmitCandidateTool(store, generator).run(SubmitCandidateArgs(), None).success is True
    state = store.load(generator.collaboration_id)
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
    generator = store.create("Build an artifact", "duo", collaboration_id="d" * 32)
    assert SubmitCandidateTool(store, generator).run(SubmitCandidateArgs(), None).success is True
    state = store.load(generator.collaboration_id)
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
