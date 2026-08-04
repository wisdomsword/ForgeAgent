"""Bounded durable Loop execution tests."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from forgeagent.attention import attention_for_reason
from forgeagent.audit import AuditEvent
from forgeagent.collaboration import CollaborationReport, CollaborationUsage
from forgeagent.execution_evidence import ExecutionEvidence, ToolExecutionRecord
from forgeagent.loop import (
    MAX_CHECKPOINT_BYTES,
    MAX_FAILURE_CHARS,
    CheckpointArgs,
    LoopBudgets,
    LoopCheckpointStore,
    LoopRunner,
)
from forgeagent.models import TokenUsage
from forgeagent.skills import SkillDefinition, SkillRegistry
from forgeagent.step import RoundResult
from forgeagent.task import TaskOutcome, TaskStatus
from forgeagent.tools import ToolOutcome, default_registry


def _budgets(**overrides: object) -> LoopBudgets:
    values: dict[str, object] = {
        "token_budget": 100,
        "max_rounds": 10,
        "wall_clock_seconds": 60.0,
        "max_consecutive_failures": 3,
    }
    values.update(overrides)
    return LoopBudgets(**values)


def _outcome(
    *,
    completed: bool = False,
    reason: str = "failed",
    detail: str | None = None,
    usage: TokenUsage | None = None,
    rounds: int = 1,
    execution_evidence: ExecutionEvidence | None = None,
) -> TaskOutcome:
    return TaskOutcome(
        status=TaskStatus(completed=completed, reason=reason, detail=detail),
        rounds=[RoundResult(text="", usage=usage) for _ in range(rounds)],
        execution_evidence=execution_evidence or ExecutionEvidence(),
    )


def _execution_evidence(*, sequence: int = 1, role: str | None = None) -> ExecutionEvidence:
    return ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=sequence,
                tool="Exec",
                status="succeeded",
                role=role,
                attempt=1 if role is not None else None,
            ),
        )
    )


@dataclass
class _FakeTask:
    outcome: TaskOutcome
    goals: list[str] = field(default_factory=list)
    cancel_events: list[threading.Event | None] = field(default_factory=list)
    closed: int = 0

    def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
        self.goals.append(goal)
        self.cancel_events.append(cancel_event)
        return self.outcome

    def close(self) -> None:
        self.closed += 1


class _Builder:
    def __init__(self, outcomes: list[TaskOutcome]) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[tuple[int, int, str, object, _FakeTask]] = []

    def __call__(
        self, iteration: int, remaining_rounds: int, suffix: str, registry: object
    ) -> _FakeTask:
        task = _FakeTask(next(self._outcomes))
        self.calls.append((iteration, remaining_rounds, suffix, registry, task))
        return task


def _runner(tmp_path: Path, builder: _Builder, **kwargs: object) -> LoopRunner:
    return LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=builder,
        goal="finish the work",
        budgets=_budgets(**kwargs),
        trigger="test",
    )


@dataclass
class _FakeCollaborationRunner:
    report: CollaborationReport
    plan_digest: str = "d" * 64
    closed: int = 0

    def run(self, goal: str, *, cancel_event=None) -> CollaborationReport:
        return self.report

    def close(self) -> None:
        self.closed += 1


@dataclass(frozen=True)
class _AggregateOutcome:
    """Task-7-shaped result double used without adding collaboration fields yet."""

    status: str
    stop_reason: str | None
    rounds: int
    usage: CollaborationUsage
    usage_available: bool
    execution_evidence: ExecutionEvidence
    passed_item_count: int = 0
    failed_item_count: int = 1
    rejections: int = 0
    plan_digest: str = "d" * 64


def _collaboration_report(**overrides: object) -> CollaborationReport:
    values: dict[str, object] = {
        "collaboration_id": "c" * 32,
        "mode": "duo",
        "status": "completed",
        "stop_reason": "completed",
        "phase": "completed",
        "plan_item_count": 1,
        "passed_item_count": 1,
        "failed_item_count": 0,
        "generator_attempts": 1,
        "evaluator_attempts": 1,
        "rejections": 0,
        "rounds": 4,
        "usage": CollaborationUsage(input_tokens=5, output_tokens=3),
        "usage_available": True,
        "evidence": (),
    }
    values.update(overrides)
    return CollaborationReport(**values)


def test_collaboration_iteration_accumulates_all_role_rounds_and_tokens(tmp_path: Path):
    single_builder = _Builder([])
    runners: list[_FakeCollaborationRunner] = []

    def collaboration_builder(*args):
        runner = _FakeCollaborationRunner(_collaboration_report())
        runners.append(runner)
        return runner

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=single_builder,
        collaboration_builder=collaboration_builder,
        collaboration_mode="duo",
        collaboration_id="c" * 32,
        goal="finish the work",
        budgets=_budgets(),
        trigger="test",
    )

    report = runner.run()

    assert report.status == "completed"
    assert report.rounds_used == 4
    assert report.tokens_used == 8
    assert report.collaboration_mode == "duo"
    assert single_builder.calls == []
    assert runners[0].closed == 1
    runner.close()


def test_resume_rejects_collaboration_mode_or_digest_mismatch(tmp_path: Path):
    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_builder=lambda *args: None,
        collaboration_mode="triad",
        collaboration_id="c" * 32,
        plan_digest="d" * 64,
        goal="finish the work",
        budgets=_budgets(),
        trigger="test",
    )
    loop_id = runner._checkpoint.loop_id
    runner.close()

    with pytest.raises(ValueError, match="frozen collaboration"):
        LoopRunner.resume(
            allowed_root=str(tmp_path),
            task_builder=_Builder([]),
            loop_id=loop_id,
            trigger="test",
            expected_collaboration_mode="duo",
        )
    with pytest.raises(ValueError, match="frozen collaboration"):
        LoopRunner.resume(
            allowed_root=str(tmp_path),
            task_builder=_Builder([]),
            loop_id=loop_id,
            trigger="test",
            expected_plan_digest="e" * 64,
        )


def test_collaboration_rejection_limit_stops_loop_without_another_iteration(tmp_path: Path):
    reports = iter(
        [
            _collaboration_report(
                status="stopped",
                stop_reason="rejection_limit",
                phase="stopped",
                passed_item_count=0,
                failed_item_count=1,
                rejections=2,
            ),
            _collaboration_report(),
        ]
    )
    built: list[_FakeCollaborationRunner] = []

    def collaboration_builder(*args):
        runner = _FakeCollaborationRunner(next(reports))
        built.append(runner)
        return runner

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_builder=collaboration_builder,
        collaboration_mode="duo",
        collaboration_id="c" * 32,
        goal="finish the work",
        budgets=_budgets(),
        trigger="test",
    )

    report = runner.run()

    assert report.status == "failed"
    assert report.stop_reason == "unrecoverable_failure"
    assert len(built) == 1
    runner.close()


def _skills() -> SkillRegistry:
    return SkillRegistry(
        {
            "review-python": SkillDefinition(
                name="review-python",
                trigger="Review Python changes.",
                steps="Inspect the diff.",
                failure_branches="Stop when the diff is unavailable.",
                completion_criteria="All findings are recorded.",
                source="user",
            )
        }
    )


class _AuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def test_create_runs_one_completed_iteration_and_closes_task(tmp_path: Path):
    builder = _Builder(
        [_outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=4))]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert report.iterations == 1
    assert report.rounds_used == 1
    assert report.tokens_used == 4
    assert len(builder.calls) == 1
    assert builder.calls[0][4].closed == 1
    runner.close()


def test_loop_aggregates_single_execution_evidence_with_iteration_origin(tmp_path: Path):
    builder = _Builder(
        [
            _outcome(reason="retry", execution_evidence=_execution_evidence()),
            _outcome(
                completed=True,
                reason="completed",
                execution_evidence=_execution_evidence(sequence=2),
            ),
        ]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert [
        (record.iteration, record.sequence) for record in report.execution_evidence.records
    ] == [
        (1, 1),
        (2, 2),
    ]
    runner.close()


def test_loop_evidence_is_bounded_with_one_global_omitted_count(tmp_path: Path):
    builder = _Builder(
        [
            _outcome(
                completed=index == 40,
                reason="completed" if index == 40 else "retry",
                execution_evidence=_execution_evidence(sequence=index),
            )
            for index in range(1, 41)
        ]
    )
    runner = _runner(tmp_path, builder, max_rounds=40, max_consecutive_failures=40)

    report = runner.run()

    assert len(report.execution_evidence.records) == 32
    assert report.execution_evidence.truncated is True
    assert report.execution_evidence.omitted_count == 8
    assert (
        tmp_path / ".forgeagent" / "loops" / f"{report.loop_id}.json"
    ).stat().st_size <= MAX_CHECKPOINT_BYTES
    runner.close()


def test_v1_checkpoint_defaults_to_empty_execution_evidence_and_resume_appends(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("finish the work", _budgets(), loop_id="e" * 32)
    state_path = tmp_path / ".forgeagent" / "loops" / f"{checkpoint.loop_id}.json"
    payload = json.loads(state_path.read_text())
    payload.pop("execution_evidence", None)
    state_path.write_text(json.dumps(payload))
    loaded = store.load(checkpoint.loop_id)
    assert loaded.execution_evidence == ExecutionEvidence()

    runner = LoopRunner.resume(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        loop_id=checkpoint.loop_id,
        trigger="test",
    )
    runner._record_outcome(_outcome(reason="retry", execution_evidence=_execution_evidence()))
    first_prefix = runner._checkpoint.execution_evidence.records
    runner.close()

    resumed = LoopRunner.resume(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        loop_id=checkpoint.loop_id,
        trigger="test",
    )
    resumed._record_outcome(
        _outcome(
            completed=True,
            reason="completed",
            execution_evidence=_execution_evidence(sequence=2),
        )
    )

    assert resumed._checkpoint.execution_evidence.records[:1] == first_prefix
    assert [
        (record.iteration, record.sequence)
        for record in resumed._checkpoint.execution_evidence.records
    ] == [
        (1, 1),
        (2, 2),
    ]
    resumed.close()
    store.close()


def test_loop_store_strips_legacy_model_controlled_block_on_load(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("finish the work", _budgets(), loop_id="f" * 32)
    path = tmp_path / ".forgeagent" / "loops" / f"{checkpoint.loop_id}.json"
    payload = json.loads(path.read_text())
    payload["execution_evidence"] = {
        "records": [
            {
                "sequence": 1,
                "tool": "Exec",
                "status": "succeeded",
                "block": "/private/legacy.py RAW_ARG_MARKER PROMPT_MARKER NON_ENV_SECRET_MARKER",
                "iteration": 1,
            }
        ],
        "truncated": False,
        "omitted_count": 0,
    }
    path.write_text(json.dumps(payload))

    loaded = store.load(checkpoint.loop_id)
    saved = store.save(loaded.model_copy(update={"rounds_used": 1}), expected_revision=0)

    assert loaded.execution_evidence.records[0].block is None
    assert saved.execution_evidence.records[0].block is None
    assert "block" not in json.loads(path.read_text())["execution_evidence"]["records"][0]
    store.close()


def test_failed_outcome_save_does_not_advance_counters_or_evidence(tmp_path: Path, monkeypatch):
    runner = _runner(tmp_path, _Builder([]))
    before = runner._checkpoint

    def fail_save(*_args, **_kwargs):
        raise RuntimeError("disk failure")

    monkeypatch.setattr(runner._store, "save", fail_save)

    with pytest.raises(RuntimeError, match="disk failure"):
        runner._record_outcome(_outcome(reason="retry", execution_evidence=_execution_evidence()))

    durable = LoopCheckpointStore(str(tmp_path)).load(before.loop_id)
    assert durable.iterations == before.iterations
    assert durable.rounds_used == before.rounds_used
    assert durable.execution_evidence == before.execution_evidence
    runner.close()


def test_loop_projection_omits_model_controlled_block_from_checkpoint_and_report(tmp_path: Path):
    block = "/private/model-block.py RAW_ARG_MARKER PROMPT_MARKER NON_ENV_SECRET_MARKER"
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool="Exec",
                status="succeeded",
                block=block,
            ),
        )
    )
    runner = _runner(
        tmp_path,
        _Builder([_outcome(completed=True, reason="completed", execution_evidence=evidence)]),
    )

    report = runner.run()
    checkpoint = LoopCheckpointStore(str(tmp_path)).load(report.loop_id)
    serialized = (tmp_path / ".forgeagent" / "loops" / f"{report.loop_id}.json").read_text()

    assert report.execution_evidence.records[0].block is None
    assert checkpoint.execution_evidence.records[0].block is None
    assert '"block"' not in serialized
    for marker in block.split():
        assert marker not in report.model_dump_json()
        assert marker not in serialized
    runner.close()


def test_cumulative_collaboration_evidence_dedupes_roles_across_resume(tmp_path: Path):
    initial = _AggregateOutcome(
        status="failed",
        stop_reason="retry",
        rounds=1,
        usage=CollaborationUsage(input_tokens=1),
        usage_available=True,
        execution_evidence=_execution_evidence(role="generator"),
    )
    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_mode="duo",
        collaboration_id="c" * 32,
        goal="finish the work",
        budgets=_budgets(),
        trigger="test",
    )
    runner._record_outcome(initial)
    runner.close()

    cumulative = ExecutionEvidence(
        records=(
            _execution_evidence(role="generator").records[0],
            _execution_evidence(role="evaluator").records[0],
        )
    )
    resumed = LoopRunner.resume(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_builder=lambda *_args: _FakeCollaborationRunner(
            _AggregateOutcome(
                status="completed",
                stop_reason="completed",
                rounds=2,
                usage=CollaborationUsage(input_tokens=2),
                usage_available=True,
                execution_evidence=cumulative,
            )
        ),
        loop_id=runner._checkpoint.loop_id,
        trigger="test",
    )

    report = resumed.run()

    assert [(record.role, record.iteration) for record in report.execution_evidence.records] == [
        ("generator", 1),
        ("evaluator", 2),
    ]
    assert report.execution_evidence.omitted_count == 0
    resumed.close()


def test_cumulative_collaboration_evidence_keeps_unique_omission_count_on_resume(
    tmp_path: Path,
):
    def cumulative_evidence(count: int) -> ExecutionEvidence:
        return ExecutionEvidence(
            records=tuple(
                ToolExecutionRecord(
                    sequence=index,
                    tool="Exec",
                    status="succeeded",
                    role="generator",
                    attempt=1,
                )
                for index in range(1, count + 1)
            )
        )

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_mode="duo",
        collaboration_id="c" * 32,
        goal="finish the work",
        budgets=_budgets(max_rounds=4),
        trigger="test",
    )
    runner._record_outcome(
        _AggregateOutcome(
            status="failed",
            stop_reason="retry",
            rounds=1,
            usage=CollaborationUsage(input_tokens=1),
            usage_available=True,
            execution_evidence=cumulative_evidence(40),
        )
    )
    runner.close()

    resumed = LoopRunner.resume(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_builder=lambda *_args: _FakeCollaborationRunner(
            _AggregateOutcome(
                status="completed",
                stop_reason="completed",
                rounds=2,
                usage=CollaborationUsage(input_tokens=2),
                usage_available=True,
                execution_evidence=cumulative_evidence(41),
            )
        ),
        loop_id=runner._checkpoint.loop_id,
        trigger="test",
    )

    report = resumed.run()

    assert len(report.execution_evidence.records) == 32
    assert report.execution_evidence.omitted_count == 9
    assert report.execution_evidence.truncated is True
    assert [record.iteration for record in report.execution_evidence.records] == [1] * 32
    resumed.close()


@pytest.mark.parametrize("reason", ["needs_input", "blocked"])
def test_attention_outcome_stops_loop_and_persists_safe_projection(tmp_path: Path, reason: str):
    attention = attention_for_reason(
        "needs_info" if reason == "needs_input" else "blocked", "provide input"
    )
    builder = _Builder([_outcome(reason=reason)])
    builder._outcomes = iter(
        [
            TaskOutcome(
                status=TaskStatus(
                    completed=False,
                    reason=reason,
                    detail="private detail",
                    attention=attention,
                ),
                rounds=[RoundResult(text="private model text", usage=TokenUsage(input_tokens=1))],
            )
        ]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()
    checkpoint = LoopCheckpointStore(str(tmp_path)).load(report.loop_id)

    assert report.status == "stopped"
    assert report.stop_reason == reason
    assert report.attention == attention
    assert checkpoint.attention == attention
    assert checkpoint.consecutive_failures == 0
    assert "private" not in report.attention.required_action
    runner.close()


def test_failure_summary_and_handoff_are_injected_into_next_fresh_task(tmp_path: Path):
    builder = _Builder(
        [
            _outcome(
                reason="max_rounds", detail="failed\x00 detail", usage=TokenUsage(input_tokens=1)
            ),
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=2)),
        ]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "completed"
    assert len(builder.calls) == 2
    suffix = builder.calls[1][2]
    assert "UNTRUSTED LOOP STATE" in suffix
    assert "max_rounds" in suffix
    assert "failed\\u0000 detail" not in suffix
    assert builder.calls[0][3] is not builder.calls[1][3]
    assert builder.calls[0][4].closed == builder.calls[1][4].closed == 1
    runner.close()


def test_resume_terminal_checkpoint_returns_report_without_building_task(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("finish the work", _budgets(), loop_id="a" * 32)
    terminal = store.save(
        checkpoint.model_copy(update={"status": "completed", "stop_reason": "completed"}),
        expected_revision=checkpoint.revision,
    )
    builder = _Builder([_outcome(completed=True, reason="completed")])
    runner = LoopRunner.resume(
        allowed_root=str(tmp_path), task_builder=builder, loop_id=terminal.loop_id, trigger="test"
    )

    report = runner.run()

    assert report.status == "completed"
    assert builder.calls == []
    runner.close()
    store.close()


def test_resume_uses_frozen_goal_and_budgets_and_injects_completed_items(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("frozen goal", _budgets(max_rounds=7), loop_id="b" * 32)
    checkpoint = store.save(
        checkpoint.model_copy(
            update={"completed_items": ("already done",), "handoff": "continue safely"}
        ),
        expected_revision=checkpoint.revision,
    )
    builder = _Builder(
        [_outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))]
    )
    runner = LoopRunner.resume(
        allowed_root=str(tmp_path), task_builder=builder, loop_id=checkpoint.loop_id, trigger="test"
    )

    report = runner.run("frozen goal")

    assert report.status == "completed"
    assert builder.calls[0][1] == 7
    assert "already done" in builder.calls[0][2]
    assert "continue safely" in builder.calls[0][2]
    with pytest.raises(ValueError, match="frozen"):
        runner.run("different goal")
    runner.close()
    store.close()


def test_prose_answer_does_not_complete_a_loop(tmp_path: Path):
    builder = _Builder(
        [
            _outcome(reason="answered_in_prose", usage=TokenUsage(input_tokens=1)),
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1)),
        ]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "completed"
    assert report.iterations == 2
    runner.close()


@pytest.mark.parametrize("resumed", [False, True])
def test_runner_preserves_mcp_and_skill_tool_assembly_for_every_iteration(
    tmp_path: Path, resumed: bool
):
    builder = _Builder(
        [
            _outcome(reason="retry", usage=TokenUsage(input_tokens=1)),
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1)),
        ]
    )
    skills = _skills()
    if resumed:
        store = LoopCheckpointStore(str(tmp_path))
        checkpoint = store.create("finish the work", _budgets(), loop_id="c" * 32)
        store.close()
        runner = LoopRunner.resume(
            allowed_root=str(tmp_path),
            task_builder=builder,
            loop_id=checkpoint.loop_id,
            trigger="test",
            with_mcp=True,
            skills=skills,
        )
    else:
        runner = LoopRunner.create(
            allowed_root=str(tmp_path),
            task_builder=builder,
            goal="finish the work",
            budgets=_budgets(),
            trigger="test",
            with_mcp=True,
            skills=skills,
        )

    report = runner.run()

    assert report.status == "completed"
    assert len(builder.calls) == 2
    assert all(
        {"MCP", "Skill", "Checkpoint"} <= set(call[3].arg_schemas()) for call in builder.calls
    )
    assert builder.calls[0][3] is not builder.calls[1][3]
    assert "MCP" not in default_registry().arg_schemas()
    assert "Skill" not in default_registry().arg_schemas()
    runner.close()


@pytest.mark.parametrize(
    ("budget", "outcome", "reason"),
    [
        ("max_rounds", _outcome(reason="failed", usage=TokenUsage(input_tokens=1)), "max_rounds"),
        (
            "token_budget",
            _outcome(reason="failed", usage=TokenUsage(input_tokens=3)),
            "token_budget",
        ),
    ],
)
def test_budget_stops_at_the_first_safe_boundary(
    tmp_path: Path, budget: str, outcome: TaskOutcome, reason: str
):
    overrides = {budget: 1}
    builder = _Builder([outcome])
    runner = _runner(tmp_path, builder, **overrides)

    report = runner.run()

    assert report.stop_reason == reason
    assert len(builder.calls) == 1
    runner.close()


def test_missing_usage_stops_after_a_successful_zero_usage_iteration(tmp_path: Path):
    builder = _Builder([_outcome(reason="failed", usage=TokenUsage())])
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.stop_reason == "token_usage_unavailable"
    assert report.usage_available is False
    runner.close()


def test_verified_completion_takes_priority_over_zero_usage(tmp_path: Path):
    builder = _Builder([_outcome(completed=True, reason="completed", usage=TokenUsage())])
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert report.usage_available is False
    runner.close()


def test_external_cancel_set_during_completed_task_takes_priority(tmp_path: Path):
    cancelled = threading.Event()

    class _CancellingCompletedTask(_FakeTask):
        def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
            cancelled.set()
            return super().run(goal, cancel_event=cancel_event)

    created: list[_FakeTask] = []

    def builder(iteration: int, remaining: int, suffix: str, registry: object) -> _FakeTask:
        task = _CancellingCompletedTask(
            _outcome(
                completed=True,
                reason="completed",
                usage=TokenUsage(input_tokens=1),
                execution_evidence=_execution_evidence(),
            )
        )
        created.append(task)
        return task

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=builder,
        goal="finish",
        budgets=_budgets(),
        trigger="test",
    )

    report = runner.run(cancel_event=cancelled)
    checkpoint = LoopCheckpointStore(str(tmp_path)).load(report.loop_id)

    assert report.status == checkpoint.status == "cancelled"
    assert report.stop_reason == checkpoint.stop_reason == "cancelled"
    assert [
        (record.iteration, record.sequence) for record in report.execution_evidence.records
    ] == [(1, 1)]
    assert len(created) == 1
    runner.close()


def test_watchdog_set_during_completed_task_takes_priority(monkeypatch, tmp_path: Path):
    class _ImmediateTimer:
        daemon = False

        def __init__(self, interval: float, callback) -> None:
            del interval
            self._callback = callback

        def start(self) -> None:
            self._callback()

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("forgeagent.loop.threading.Timer", _ImmediateTimer)
    builder = _Builder(
        [_outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "stopped"
    assert report.stop_reason == "wall_clock"
    runner.close()


def test_client_errors_are_classified_before_usage_availability(tmp_path: Path):
    (tmp_path / "auth").mkdir()
    auth_builder = _Builder([_outcome(reason="client_error:auth", usage=None)])
    auth_runner = _runner(tmp_path / "auth", auth_builder)

    auth_report = auth_runner.run()

    assert auth_report.stop_reason == "unrecoverable_failure"
    auth_runner.close()

    (tmp_path / "network").mkdir()
    network_builder = _Builder(
        [
            _outcome(reason="client_error:network", usage=None),
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1)),
        ]
    )
    network_runner = _runner(tmp_path / "network", network_builder)

    network_report = network_runner.run()

    assert network_report.status == "completed"
    assert network_report.iterations == 2
    network_runner.close()


def test_failure_summary_is_bounded_after_metadata_is_added(tmp_path: Path):
    builder = _Builder(
        [
            _outcome(
                reason="failed",
                detail="x" * MAX_FAILURE_CHARS,
                usage=TokenUsage(input_tokens=1),
            )
        ]
    )
    runner = _runner(tmp_path, builder, max_consecutive_failures=1)

    report = runner.run()
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.load(report.loop_id)

    assert report.stop_reason == "consecutive_failures"
    assert len(checkpoint.last_failure) == MAX_FAILURE_CHARS
    store.close()
    runner.close()


def test_failure_summary_counts_parse_and_tool_results_without_tool_detail(tmp_path: Path):
    failure = TaskOutcome(
        status=TaskStatus(completed=False, reason="failed", detail="safe status detail"),
        rounds=[
            RoundResult(
                text="",
                usage=TokenUsage(input_tokens=1),
                parse_errors=["first", "second"],
                outcomes=[
                    ToolOutcome(tool="Exec", success=True, detail="private-success-detail"),
                    ToolOutcome(tool="Exec", success=False, detail="private-failure-detail"),
                ],
            ),
            RoundResult(
                text="",
                usage=TokenUsage(input_tokens=1),
                parse_errors=["third"],
                outcomes=[ToolOutcome(tool="Edit", success=False, detail="another-private-detail")],
            ),
        ],
    )
    builder = _Builder(
        [failure, _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))]
    )
    runner = _runner(tmp_path, builder)

    report = runner.run()

    assert report.status == "completed"
    suffix = builder.calls[1][2]
    assert "parse_errors=3" in suffix
    assert "tool_successes=1" in suffix
    assert "tool_failures=2" in suffix
    assert "private-success-detail" not in suffix
    assert "private-failure-detail" not in suffix
    assert "another-private-detail" not in suffix
    runner.close()


def test_external_cancel_stops_without_building_a_task(tmp_path: Path):
    builder = _Builder([_outcome(completed=True, reason="completed")])
    runner = _runner(tmp_path, builder)
    cancelled = threading.Event()
    cancelled.set()

    report = runner.run(cancel_event=cancelled)

    assert report.status == "cancelled"
    assert builder.calls == []
    runner.close()


def test_unrecoverable_client_error_stops_but_network_error_can_recover(tmp_path: Path):
    (tmp_path / "auth").mkdir()
    auth_builder = _Builder([_outcome(reason="client_error:auth", detail="secret", usage=None)])
    auth_runner = _runner(tmp_path / "auth", auth_builder)
    auth_report = auth_runner.run()
    assert auth_report.stop_reason == "unrecoverable_failure"
    auth_runner.close()

    (tmp_path / "network").mkdir()
    network_builder = _Builder(
        [
            _outcome(reason="client_error:network", usage=None),
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1)),
        ]
    )
    network_runner = _runner(tmp_path / "network", network_builder)
    network_report = network_runner.run()
    assert network_report.status == "completed"
    assert network_report.iterations == 2
    network_runner.close()


def test_stop_priority_prefers_cancel_over_all_other_boundaries(tmp_path: Path):
    builder = _Builder([_outcome(reason="failed", usage=TokenUsage(input_tokens=1))])
    runner = _runner(tmp_path, builder, max_rounds=1, token_budget=1)
    cancelled = threading.Event()
    cancelled.set()

    report = runner.run(cancel_event=cancelled)

    assert report.stop_reason == "cancelled"
    runner.close()


def test_reentrant_run_is_rejected_and_every_created_task_is_closed(tmp_path: Path):
    class _ReentrantTask(_FakeTask):
        def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
            with pytest.raises(Exception, match="already running"):
                runner.run()
            return super().run(goal, cancel_event=cancel_event)

    created: list[_ReentrantTask] = []

    def builder(iteration: int, remaining: int, suffix: str, registry: object) -> _ReentrantTask:
        task = _ReentrantTask(
            _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))
        )
        created.append(task)
        return task

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=builder,
        goal="finish",
        budgets=_budgets(),
        trigger="test",
    )
    report = runner.run()
    assert report.status == "completed"
    assert created[0].closed == 1
    runner.close()


def test_audit_emits_lifecycle_events_without_private_loop_text(tmp_path: Path):
    sink = _AuditSink()
    builder = _Builder(
        [_outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))]
    )
    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=builder,
        goal="private goal",
        budgets=_budgets(),
        trigger="test",
        audit_sink=sink,
    )

    runner.run()

    types = [event.event_type for event in sink.events]
    assert {"loop.start", "loop.checkpoint", "loop.iteration", "loop.stop"} <= set(types)
    start = next(event for event in sink.events if event.event_type == "loop.start")
    iteration = next(event for event in sink.events if event.event_type == "loop.iteration")
    stop = next(event for event in sink.events if event.event_type == "loop.stop")
    assert {
        "schema",
        "loop_id",
        "trigger",
        "max_rounds",
        "token_budget",
        "wall_clock_seconds",
        "max_consecutive_failures",
    } <= start.parameters.keys()
    assert {
        "schema",
        "loop_id",
        "trigger",
        "revision",
        "iterations",
        "rounds_used",
        "tokens_used",
        "elapsed_seconds",
        "consecutive_failures",
        "completed_item_count",
        "open_question_count",
    } <= iteration.parameters.keys()
    assert iteration.result_status == "completed"
    assert {
        "schema",
        "loop_id",
        "trigger",
        "revision",
        "status",
        "stop_reason",
        "iterations",
        "rounds_used",
        "tokens_used",
        "elapsed_seconds",
        "consecutive_failures",
        "completed_item_count",
        "open_question_count",
    } <= stop.parameters.keys()
    assert stop.parameters["status"] == "completed"
    assert stop.parameters["stop_reason"] == "completed"
    forbidden_keys = {
        "goal",
        "path",
        "text",
        "raw_failure",
        "last_failure",
        "handoff",
        "completed_items",
        "open_questions",
    }
    assert all(forbidden_keys.isdisjoint(event.parameters) for event in sink.events)
    serialized = "\n".join(event.model_dump_json() for event in sink.events)
    assert "private goal" not in serialized
    assert "handoff" not in serialized
    runner.close()


@pytest.mark.parametrize(
    ("collaboration_mode", "collaboration_mode_source"),
    [("single", "default"), ("single", "explicit"), ("triad", "explicit")],
)
def test_loop_audits_route_with_loop_correlation(
    tmp_path: Path, collaboration_mode: str, collaboration_mode_source: str
):
    sink = _AuditSink()
    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_builder=(
            lambda *_args: (
                _FakeCollaborationRunner(
                    _collaboration_report(status="completed", stop_reason="completed")
                )
                if collaboration_mode != "single"
                else None
            )
        ),
        collaboration_mode=collaboration_mode,
        collaboration_mode_source=collaboration_mode_source,
        collaboration_id="b" * 32 if collaboration_mode != "single" else "",
        goal="private goal",
        budgets=_budgets(),
        trigger="test",
        audit_sink=sink,
        task_id="c" * 32,
    )

    route = next(event for event in sink.events if event.event_type == "collaboration.route")

    assert route.task_id == "c" * 32
    assert route.parameters == {
        "mode": collaboration_mode,
        "reason": collaboration_mode_source,
        "requested_mode": (
            "default" if collaboration_mode_source == "default" else collaboration_mode
        ),
        "override_required": False,
        "loop_id": runner._checkpoint.loop_id,
    }
    assert "private goal" not in repr(route)
    runner.close()


def test_loop_resume_reuses_checkpoint_collaboration_mode_source(tmp_path: Path):
    sink = _AuditSink()
    created = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        collaboration_mode="single",
        collaboration_mode_source="default",
        goal="private goal",
        budgets=_budgets(),
        trigger="test",
    )
    loop_id = created._checkpoint.loop_id
    created.close()

    resumed = LoopRunner.resume(
        allowed_root=str(tmp_path),
        task_builder=_Builder([]),
        loop_id=loop_id,
        trigger="test",
        audit_sink=sink,
    )

    route = next(event for event in sink.events if event.event_type == "collaboration.route")
    assert route.parameters["reason"] == "default"
    assert route.parameters["requested_mode"] == "default"
    resumed.close()


def test_runner_preserves_checkpoint_committed_by_its_fresh_task(tmp_path: Path):
    class _CheckpointingTask(_FakeTask):
        def __init__(self, registry: object) -> None:
            super().__init__(
                _outcome(completed=True, reason="completed", usage=TokenUsage(input_tokens=1))
            )
            self._registry = registry

        def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
            checkpoint = self._registry.get("Checkpoint")
            assert checkpoint is not None
            result = checkpoint.run(CheckpointArgs(completed_items=("durable work",)), None)
            assert result.success
            return super().run(goal, cancel_event=cancel_event)

    def builder(
        iteration: int, remaining: int, suffix: str, registry: object
    ) -> _CheckpointingTask:
        return _CheckpointingTask(registry)

    runner = LoopRunner.create(
        allowed_root=str(tmp_path),
        task_builder=builder,
        goal="finish",
        budgets=_budgets(),
        trigger="test",
    )

    report = runner.run()

    assert report.status == "completed"
    assert report.completed_item_count == 1
    runner.close()
