"""Bounded durable Loop execution tests."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.loop import (
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
) -> TaskOutcome:
    return TaskOutcome(
        status=TaskStatus(completed=completed, reason=reason, detail=detail),
        rounds=[RoundResult(text="", usage=usage) for _ in range(rounds)],
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
    serialized = "\n".join(event.model_dump_json() for event in sink.events)
    assert "private goal" not in serialized
    assert "handoff" not in serialized
    runner.close()


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
