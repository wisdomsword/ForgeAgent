"""Bounded task registry and worker lifecycle tests."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from types import SimpleNamespace

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.collaboration import CollaborationReport, CollaborationUsage
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_task_service import (
    ServiceCapacityError,
    ServiceClosedError,
    TaskNotFound,
    TaskRecord,
    TaskService,
    _usage_summary,
)
from forgeagent.loop import LOOP_SCHEMA, LoopReport
from forgeagent.models import TokenUsage
from forgeagent.step import RoundResult, Termination
from forgeagent.task import TaskOutcome, TaskStatus

CONFIG = HttpServiceConfig(
    token="service-secret-token",
    max_workers=2,
    max_queue=4,
    max_records=8,
    terminal_ttl_seconds=60.0,
)


class _AuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def _outcome(
    reason: str = Termination.COMPLETED,
    *,
    detail: str | None = None,
    text: str = "private model text",
    usage: TokenUsage | None = None,
) -> TaskOutcome:
    return TaskOutcome(
        status=TaskStatus(completed=reason == Termination.COMPLETED, reason=reason, detail=detail),
        rounds=[RoundResult(text=text, usage=usage)],
    )


class _FakeClient:
    def __init__(self, events: list[str] | None = None) -> None:
        self._events = events

    def close(self) -> None:
        if self._events is not None:
            self._events.append("client.close")


class _FakeTask:
    def __init__(
        self,
        run: Callable[[str, threading.Event], TaskOutcome],
        *,
        events: list[str] | None = None,
        audit_degraded: bool = False,
    ) -> None:
        self._run = run
        self._events = events
        self._client = _FakeClient(events)
        self._audit_sink = SimpleNamespace(degraded=audit_degraded)

    def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
        assert cancel_event is not None
        if self._events is not None:
            self._events.append("run")
        return self._run(goal, cancel_event)

    def close(self) -> None:
        if self._events is not None:
            self._events.append("task.close")


def _loop_report(
    loop_id: str = "a" * 32,
    *,
    status: str = "stopped",
    stop_reason: str | None = "max_rounds",
) -> LoopReport:
    return LoopReport(
        schema=LOOP_SCHEMA,
        loop_id=loop_id,
        status=status,
        stop_reason=stop_reason,
        iterations=3,
        rounds_used=7,
        tokens_used=101,
        elapsed_seconds=2.5,
        consecutive_failures=1,
        completed_item_count=2,
        open_question_count=1,
        usage_available=True,
    )


class _FakeLoopRunner:
    def __init__(
        self,
        report: LoopReport,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._report = report
        self._started = started
        self._release = release
        self._events = events
        self._audit_sink = None

    def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> LoopReport:
        assert cancel_event is not None
        if self._events is not None:
            self._events.append("run")
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            self._release.wait(1.0)
        return self._report

    def close(self) -> None:
        if self._events is not None:
            self._events.append("loop.close")


def _collaboration_report(**overrides: object) -> CollaborationReport:
    values: dict[str, object] = {
        "collaboration_id": "b" * 32,
        "mode": "triad",
        "status": "completed",
        "stop_reason": "completed",
        "phase": "completed",
        "plan_item_count": 2,
        "passed_item_count": 2,
        "failed_item_count": 0,
        "generator_attempts": 1,
        "evaluator_attempts": 1,
        "rejections": 0,
        "rounds": 3,
        "usage": CollaborationUsage(input_tokens=4, output_tokens=3),
        "usage_available": True,
        "evidence": (),
    }
    values.update(overrides)
    return CollaborationReport(**values)


def test_collaboration_record_projects_running_and_terminal_safe_fields():
    record = TaskRecord(task_id="a" * 32, goal="private goal", options={"mode": "triad"})

    running = record.public_view()
    assert running["mode"] == "triad"
    assert running["phase"] == "planning"
    assert "goal" not in running

    record.status = "completed"
    record.reason = "completed"
    record.collaboration_report = _collaboration_report()
    record.ended_at = 1.0
    terminal = record.public_view()
    assert terminal["plan_item_count"] == 2
    assert terminal["round_count"] == 3
    assert terminal["usage"]["input_tokens"] == 4
    assert "goal" not in terminal


def test_programming_submission_is_publicly_routed_to_single_before_worker_runs():
    started = threading.Event()
    release = threading.Event()

    def run(_goal, _cancel_event):
        started.set()
        release.wait(1.0)
        return _outcome()

    service = TaskService(
        factory=lambda _record: _FakeTask(run),
        config=CONFIG,
    )
    view = service.submit_view("Add a unit test", {})

    assert view["mode"] == "task"
    assert "phase" not in view
    release.set()
    service.wait(view["task_id"])
    service.shutdown(1.0)


def test_programming_submission_audits_safe_single_route_before_worker_runs():
    sink = _AuditSink()
    service = TaskService(factory=_instant_factory, config=CONFIG, audit_sink=sink)

    view = service.submit_view("Add PRIVATE_GOAL unit test", {})
    service.wait(view["task_id"])
    service.shutdown(1.0)

    route = next(event for event in sink.events if event.event_type == "collaboration.route")
    assert route.task_id == view["task_id"]
    assert route.result_status == "default"
    assert route.parameters == {
        "mode": "single",
        "reason": "default",
        "requested_mode": "default",
        "override_required": False,
    }
    assert "PRIVATE_GOAL" not in repr(route)


def test_client_bound_checks_option_cannot_select_triad_or_enter_worker_record():
    observed: list[Mapping[str, object]] = []

    def factory(record: TaskRecord) -> _FakeTask:
        observed.append(record.options)
        return _instant_factory(record)

    service = TaskService(factory=factory, config=CONFIG)
    try:
        with pytest.raises(TypeError, match="has_bound_checks"):
            service.submit("Add a unit test", {"has_bound_checks": True})
        assert observed == []
        assert service.records == {}
    finally:
        service.shutdown(1.0)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _instant_factory(record: TaskRecord) -> _FakeTask:
    return _FakeTask(lambda _goal, _cancel: _outcome())


def test_service_rejects_zero_queue_capacity_without_creating_record():
    created = False

    def factory(_record: TaskRecord) -> _FakeTask:
        nonlocal created
        created = True
        return _FakeTask(lambda _goal, _cancel: _outcome())

    service = TaskService(factory=factory, config=replace(CONFIG, max_queue=0))
    try:
        with pytest.raises(ServiceCapacityError) as raised:
            service.submit("goal", {})
        assert raised.value.kind == "capacity_exceeded"
        assert service.records == {}
        assert created is False
    finally:
        service.shutdown(1.0)


def test_submit_copies_options_and_factory_receives_private_record_data():
    observed: list[tuple[str, Mapping[str, object]]] = []

    def factory(record: TaskRecord) -> _FakeTask:
        observed.append((record.goal, record.options))
        return _FakeTask(lambda _goal, _cancel: _outcome())

    options: dict[str, object] = {"max_rounds": 2}
    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", options)
        options["max_rounds"] = 99
        service.wait(record.task_id, timeout=1.0)

        assert observed == [("goal", {"max_rounds": 2})]
        assert set(service.query(record.task_id)) == {
            "task_id",
            "mode",
            "status",
            "reason",
            "detail",
            "round_count",
            "usage",
            "audit_degraded",
        }
    finally:
        service.shutdown(1.0)


def test_ordinary_task_public_view_always_identifies_task_mode():
    service = TaskService(factory=_instant_factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        assert service.wait(record.task_id, timeout=1.0)["mode"] == "task"
    finally:
        service.shutdown(1.0)


def test_loop_public_view_is_bounded_and_omits_private_checkpoint_state():
    private_options = {
        "mode": "loop",
        "resume_loop_id": "a" * 32,
    }
    report = _loop_report()
    service = TaskService(
        factory=lambda _record: _FakeLoopRunner(report),
        config=CONFIG,
    )
    try:
        record = service.submit("", private_options)
        view = service.wait(record.task_id, timeout=1.0)

        assert view == {
            "task_id": record.task_id,
            "mode": "loop",
            "status": "stopped",
            "reason": "max_rounds",
            "detail": None,
            "round_count": 0,
            "usage": None,
            "audit_degraded": False,
            "loop_id": "a" * 32,
            "iterations": 3,
            "rounds_used": 7,
            "tokens_used": 101,
            "elapsed_seconds": 2.5,
            "consecutive_failures": 1,
            "completed_item_count": 2,
            "open_question_count": 1,
            "usage_available": True,
        }
        assert "goal" not in repr(view)
        assert "checkpoint" not in repr(view)
        assert "handoff" not in repr(view)
        assert "/" not in repr(view)
    finally:
        service.shutdown(1.0)


def test_running_loop_view_does_not_fabricate_terminal_report_counters():
    started = threading.Event()
    release = threading.Event()
    service = TaskService(
        factory=lambda _record: _FakeLoopRunner(_loop_report(), started=started, release=release),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "loop", "token_budget": 10})
        assert started.wait(1.0)
        view = service.query(record.task_id)
        assert view["mode"] == "loop"
        assert view["status"] == "running"
        assert "loop_id" not in view
        assert "iterations" not in view
    finally:
        release.set()
        service.shutdown(1.0)


def test_loop_runner_is_closed_once_without_assuming_a_private_client():
    events: list[str] = []
    service = TaskService(
        factory=lambda _record: _FakeLoopRunner(_loop_report(), events=events),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "loop", "token_budget": 10})
        service.wait(record.task_id, timeout=1.0)
        assert events == ["run", "loop.close"]
    finally:
        service.shutdown(1.0)


def test_same_loop_id_overlapping_resume_fails_closed_without_second_runner():
    started = threading.Event()
    release = threading.Event()
    constructed = 0

    def factory(_record: TaskRecord) -> _FakeLoopRunner:
        nonlocal constructed
        constructed += 1
        return _FakeLoopRunner(_loop_report(), started=started, release=release)

    service = TaskService(factory=factory, config=CONFIG)
    options = {"mode": "loop", "resume_loop_id": "a" * 32}
    try:
        first = service.submit("", options)
        assert started.wait(1.0)
        second = service.submit("", options)
        second_view = service.wait(second.task_id, timeout=1.0)
        assert second_view["status"] == "failed"
        assert second_view["reason"] == "internal_error"
        assert constructed == 1
    finally:
        release.set()
        service.wait(first.task_id, timeout=1.0)
        service.shutdown(1.0)


def test_answered_in_prose_projection_never_returns_model_or_file_content():
    private_content = "service-secret-token at /Users/admin/private/answer.txt"

    def factory(_record: TaskRecord) -> _FakeTask:
        return _FakeTask(
            lambda _goal, _cancel: _outcome(
                Termination.ANSWERED_IN_PROSE,
                detail=private_content,
                text=f"model answer copied from {private_content}",
                usage=TokenUsage(
                    input_tokens=7,
                    output_tokens=5,
                    cached_tokens=3,
                    reasoning_tokens=2,
                ),
            ),
            audit_degraded=True,
        )

    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        service.wait(record.task_id, timeout=1.0)
        view = service.query(record.task_id)

        assert view["status"] == "answered_in_prose"
        assert view["reason"] == "answered_in_prose"
        assert view["detail"] is None
        assert view["round_count"] == 1
        assert view["usage"] == {
            "input_tokens": 7,
            "output_tokens": 5,
            "cached_tokens": 3,
            "reasoning_tokens": 2,
        }
        assert view["audit_degraded"] is True
        assert "service-secret-token" not in repr(view)
        assert "/Users/admin/private/answer.txt" not in repr(view)
        assert "model answer" not in repr(view)
    finally:
        service.shutdown(1.0)


def test_usage_projection_excludes_internal_normalized_prompt_metrics():
    summary = _usage_summary(
        _outcome(
            usage=TokenUsage(
                input_tokens=7,
                output_tokens=5,
                cached_tokens=3,
                reasoning_tokens=2,
                total_prompt_tokens=10,
                cache_rate_unavailable=True,
            )
        )
    )

    assert summary == {
        "input_tokens": 7,
        "output_tokens": 5,
        "cached_tokens": 3,
        "reasoning_tokens": 2,
    }


def test_unknown_outcome_reason_projects_fixed_internal_error():
    private_reason = "service-secret-token from /Users/admin/private/result.txt"

    def factory(_record: TaskRecord) -> _FakeTask:
        return _FakeTask(lambda _goal, _cancel: _outcome(private_reason))

    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        service.wait(record.task_id, timeout=1.0)
        view = service.query(record.task_id)

        assert view["status"] == "failed"
        assert view["reason"] == "internal_error"
        assert view["detail"] == "Task execution failed."
        assert "service-secret-token" not in repr(view)
        assert "/Users/admin/private/result.txt" not in repr(view)
    finally:
        service.shutdown(1.0)


def test_submit_rejects_nested_mutable_options():
    service = TaskService(factory=_instant_factory, config=CONFIG)
    try:
        with pytest.raises(TypeError, match="scalar"):
            service.submit("goal", {"nested": {"mutable": True}})
        assert service.records == {}
    finally:
        service.shutdown(1.0)


@pytest.mark.parametrize("raised", [RuntimeError("submit failed"), KeyboardInterrupt()])
def test_executor_submit_failure_tombstones_queued_record_and_reraises(raised):
    created: list[str] = []

    def factory(record: TaskRecord) -> _FakeTask:
        created.append(record.task_id)
        return _FakeTask(lambda _goal, _cancel: _outcome())

    class EnqueueThenFail:
        def __init__(self) -> None:
            self.fn = None
            self.record = None

        def submit(self, fn, record):
            self.fn = fn
            self.record = record
            raise raised

        def shutdown(self, **_kwargs):
            return None

    service = TaskService(factory=factory, config=CONFIG)
    old_executor = service._executor
    old_executor.shutdown(wait=False, cancel_futures=True)
    executor = EnqueueThenFail()
    service._executor = executor
    try:
        with pytest.raises(type(raised)):
            service.submit("goal", {})
        assert service.records == {}
        assert executor.record is not None
        assert executor.record.cancel_event.is_set()
        assert executor.record.status == "cancelled"
        assert executor.record.ended_at is not None
        executor.fn(executor.record)
        assert created == []
    finally:
        service.shutdown(1.0)


def test_queued_cancel_is_terminal_without_constructing_task():
    first_started = threading.Event()
    release_first = threading.Event()
    factory_ids: list[str] = []

    def factory(record: TaskRecord) -> _FakeTask:
        factory_ids.append(record.task_id)
        return _FakeTask(
            lambda _goal, _cancel: (first_started.set(), release_first.wait(1.0), _outcome())[-1]
        )

    service = TaskService(factory=factory, config=replace(CONFIG, max_workers=1))
    try:
        first = service.submit("first", {})
        assert first_started.wait(1.0)
        queued = service.submit("queued", {})

        assert service.cancel(queued.task_id)["status"] == "cancelled"
        service.wait(queued.task_id, timeout=1.0)
        assert factory_ids == [first.task_id]

        release_first.set()
        service.wait(first.task_id, timeout=1.0)
    finally:
        release_first.set()
        service.shutdown(1.0)


def test_running_cancel_is_cooperative_and_terminal_is_not_overwritten():
    started = threading.Event()

    def factory(_record: TaskRecord) -> _FakeTask:
        def run(_goal: str, cancel_event: threading.Event) -> TaskOutcome:
            started.set()
            assert cancel_event.wait(1.0)
            return _outcome(
                Termination.COMPLETED,
                usage=TokenUsage(
                    input_tokens=7,
                    output_tokens=5,
                    cached_tokens=3,
                    reasoning_tokens=2,
                ),
            )

        return _FakeTask(run)

    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        assert started.wait(1.0)
        assert service.cancel(record.task_id)["status"] in {"running", "cancelled"}
        service.wait(record.task_id, timeout=1.0)
        view = service.query(record.task_id)
        assert view["status"] == "cancelled"
        assert view["round_count"] == 1
        assert view["usage"] == {
            "input_tokens": 7,
            "output_tokens": 5,
            "cached_tokens": 3,
            "reasoning_tokens": 2,
        }
        assert service.cancel(record.task_id)["status"] == "cancelled"
    finally:
        service.shutdown(1.0)


def test_cancel_during_loop_close_preserves_completed_report():
    close_started = threading.Event()
    release_close = threading.Event()

    class ClosingLoopRunner(_FakeLoopRunner):
        def close(self) -> None:
            close_started.set()
            assert release_close.wait(1.0)

    report = _loop_report(status="completed", stop_reason="completed")
    service = TaskService(
        factory=lambda _record: ClosingLoopRunner(report),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "loop", "token_budget": 10})
        assert close_started.wait(1.0)

        assert service.cancel(record.task_id)["status"] == "running"
        release_close.set()

        view = service.wait(record.task_id, timeout=1.0)
        assert view["status"] == "completed"
        assert view["reason"] == "completed"
        assert view["loop_id"] == report.loop_id
        assert view["iterations"] == report.iterations
        assert service.cancel(record.task_id) == view
    finally:
        release_close.set()
        service.shutdown(1.0)


@pytest.mark.parametrize(
    ("report_status", "report_reason"),
    [
        ("completed", "completed"),
        ("stopped", "needs_confirmation"),
        ("failed", "role_failed"),
    ],
)
def test_cancel_during_collaboration_close_preserves_terminal_report(
    report_status: str, report_reason: str
):
    close_started = threading.Event()
    release_close = threading.Event()
    report = _collaboration_report(
        status=report_status,
        stop_reason=report_reason,
        phase=report_status,
    )

    class ClosingCollaborationRunner:
        def run(
            self, goal: str, *, cancel_event: threading.Event | None = None
        ) -> CollaborationReport:
            assert cancel_event is not None
            return report

        def close(self) -> None:
            close_started.set()
            assert release_close.wait(1.0)

    service = TaskService(
        factory=lambda _record: ClosingCollaborationRunner(),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "triad"})
        assert close_started.wait(1.0)

        assert service.cancel(record.task_id)["status"] == "running"
        release_close.set()

        view = service.wait(record.task_id, timeout=1.0)
        assert view["status"] == report_status
        assert view["reason"] == report_reason
        assert view["plan_item_count"] == 2
        assert service.cancel(record.task_id) == view
    finally:
        release_close.set()
        service.shutdown(1.0)


def test_cancel_during_collaboration_close_cancels_active_report():
    close_started = threading.Event()
    release_close = threading.Event()
    report = _collaboration_report(status="active", stop_reason=None, phase="evaluator")

    class ClosingCollaborationRunner:
        def run(
            self, goal: str, *, cancel_event: threading.Event | None = None
        ) -> CollaborationReport:
            assert cancel_event is not None
            return report

        def close(self) -> None:
            close_started.set()
            assert release_close.wait(1.0)

    service = TaskService(
        factory=lambda _record: ClosingCollaborationRunner(),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "triad"})
        assert close_started.wait(1.0)

        assert service.cancel(record.task_id)["status"] == "running"
        release_close.set()

        view = service.wait(record.task_id, timeout=1.0)
        assert view["status"] == "cancelled"
        assert view["reason"] == "cancelled"
        assert service.cancel(record.task_id) == view
    finally:
        release_close.set()
        service.shutdown(1.0)


def test_cancelled_collaboration_report_remains_cancelled():
    report = _collaboration_report(status="cancelled", stop_reason="cancelled", phase="cancelled")

    class CancelledCollaborationRunner:
        def run(
            self, goal: str, *, cancel_event: threading.Event | None = None
        ) -> CollaborationReport:
            assert cancel_event is not None
            cancel_event.set()
            return report

        def close(self) -> None:
            pass

    service = TaskService(
        factory=lambda _record: CancelledCollaborationRunner(),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "triad"})
        view = service.wait(record.task_id, timeout=1.0)

        assert view["status"] == "cancelled"
        assert view["reason"] == "cancelled"
        assert service.cancel(record.task_id) == view
    finally:
        service.shutdown(1.0)


def test_cancelled_loop_report_remains_cancelled():
    report = _loop_report(status="cancelled", stop_reason="cancelled")
    service = TaskService(
        factory=lambda _record: _FakeLoopRunner(report),
        config=CONFIG,
    )
    try:
        record = service.submit("goal", {"mode": "loop", "token_budget": 10})
        view = service.wait(record.task_id, timeout=1.0)

        assert view["status"] == "cancelled"
        assert view["reason"] == "cancelled"
        assert service.cancel(record.task_id) == view
    finally:
        service.shutdown(1.0)


def test_worker_failure_is_safe_and_does_not_affect_another_task():
    def factory(record: TaskRecord) -> _FakeTask:
        if record.goal == "broken":
            return _FakeTask(lambda _goal, _cancel: (_ for _ in ()).throw(ValueError("secret")))
        return _FakeTask(lambda _goal, _cancel: _outcome())

    service = TaskService(factory=factory, config=CONFIG)
    try:
        broken = service.submit("broken", {})
        healthy = service.submit("healthy", {})
        service.wait(broken.task_id, timeout=1.0)
        service.wait(healthy.task_id, timeout=1.0)

        assert service.query(broken.task_id) == {
            "task_id": broken.task_id,
            "mode": "task",
            "status": "failed",
            "reason": "internal_error",
            "detail": "Task execution failed.",
            "round_count": 0,
            "usage": None,
            "audit_degraded": False,
        }
        assert service.query(healthy.task_id)["status"] == "completed"
    finally:
        service.shutdown(1.0)


def test_worker_base_exception_terminalizes_record_before_propagating():
    def factory(_record: TaskRecord) -> _FakeTask:
        return _FakeTask(lambda _goal, _cancel: (_ for _ in ()).throw(KeyboardInterrupt("stop")))

    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        assert record.future is not None
        with pytest.raises(KeyboardInterrupt, match="stop"):
            record.future.result(timeout=1.0)
        assert service.query(record.task_id)["status"] == "failed"
        assert service.query(record.task_id)["reason"] == "internal_error"
    finally:
        service.shutdown(1.0)


def test_audit_degraded_base_exception_does_not_prevent_terminal_publication():
    class AuditAttributeFailureTask:
        _client = _FakeClient()

        @property
        def _audit_sink(self):
            raise KeyboardInterrupt("audit attribute failed")

        def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
            assert cancel_event is not None
            return _outcome()

        def close(self) -> None:
            pass

    service = TaskService(factory=lambda _record: AuditAttributeFailureTask(), config=CONFIG)
    try:
        record = service.submit("goal", {})
        service.wait(record.task_id, timeout=1.0)

        view = service.query(record.task_id)
        assert view["status"] == "completed"
        assert view["reason"] == "completed"
        assert view["audit_degraded"] is True
    finally:
        service.shutdown(1.0)


def test_terminal_records_expire_before_capacity_is_reused():
    clock = _Clock()
    service = TaskService(
        factory=_instant_factory,
        config=replace(CONFIG, max_records=1, terminal_ttl_seconds=5.0),
        clock=clock,
    )
    try:
        first = service.submit("first", {})
        service.wait(first.task_id, timeout=1.0)
        with pytest.raises(ServiceCapacityError):
            service.submit("too-soon", {})

        clock.now += 6.0
        second = service.submit("second", {})
        with pytest.raises(TaskNotFound) as raised:
            service.query(first.task_id)
        assert raised.value.expired is True
        service.wait(second.task_id, timeout=1.0)

        with pytest.raises(TaskNotFound) as unknown:
            service.query("never-existed")
        assert unknown.value.expired is False
    finally:
        service.shutdown(1.0)


def test_worker_closes_task_then_client_and_shutdown_closes_shared_manager():
    events: list[str] = []

    class Manager:
        def close(self) -> None:
            events.append("manager.close")

    def factory(_record: TaskRecord) -> _FakeTask:
        return _FakeTask(lambda _goal, _cancel: _outcome(), events=events)

    service = TaskService(factory=factory, config=CONFIG, shared_mcp_manager=Manager())
    record = service.submit("goal", {})
    service.wait(record.task_id, timeout=1.0)
    service.shutdown(1.0)

    assert events == ["run", "task.close", "client.close", "manager.close"]
    service.shutdown(1.0)
    assert events.count("manager.close") == 1
    with pytest.raises(ServiceClosedError) as raised:
        service.submit("late", {})
    assert raised.value.kind == "service_closed"


def test_shutdown_cancels_queued_tasks_without_constructing_them():
    first_started = threading.Event()
    release_first = threading.Event()
    factory_ids: list[str] = []

    def factory(record: TaskRecord) -> _FakeTask:
        factory_ids.append(record.task_id)
        return _FakeTask(
            lambda _goal, _cancel: (first_started.set(), release_first.wait(1.0), _outcome())[-1]
        )

    service = TaskService(factory=factory, config=replace(CONFIG, max_workers=1))
    first = service.submit("first", {})
    assert first_started.wait(1.0)
    queued = service.submit("queued", {})

    service.shutdown(0.0)
    assert service.query(queued.task_id)["status"] == "cancelled"
    assert factory_ids == [first.task_id]

    release_first.set()
    service.wait(first.task_id, timeout=1.0)


def test_shutdown_defers_shared_manager_close_until_active_worker_exits():
    started = threading.Event()
    release = threading.Event()
    manager_closed = threading.Event()
    close_calls = 0

    class Manager:
        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            manager_closed.set()

    def factory(_record: TaskRecord) -> _FakeTask:
        def run(_goal: str, cancel_event: threading.Event) -> TaskOutcome:
            started.set()
            release.wait()
            assert cancel_event.is_set()
            return _outcome()

        return _FakeTask(run)

    service = TaskService(factory=factory, config=CONFIG, shared_mcp_manager=Manager())
    record = service.submit("goal", {})
    assert started.wait(1.0)

    service.shutdown(0.0)
    assert manager_closed.is_set() is False
    assert close_calls == 0

    release.set()
    service.wait(record.task_id, timeout=1.0)
    assert manager_closed.wait(1.0)
    assert close_calls == 1
    assert service._shutdown_cleanup_thread is None

    service.shutdown(0.0)
    assert close_calls == 1


def test_shutdown_thread_start_failure_falls_back_to_future_callback(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    manager_closed = threading.Event()
    close_calls = 0

    class Manager:
        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            manager_closed.set()

    def factory(_record: TaskRecord) -> _FakeTask:
        def run(_goal: str, cancel_event: threading.Event) -> TaskOutcome:
            started.set()
            release.wait()
            assert cancel_event.is_set()
            return _outcome()

        return _FakeTask(run)

    service = TaskService(factory=factory, config=CONFIG, shared_mcp_manager=Manager())
    record = service.submit("goal", {})
    assert started.wait(1.0)

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    service.shutdown(0.0)
    assert manager_closed.is_set() is False
    assert service._shutdown_cleanup_thread is None

    release.set()
    service.wait(record.task_id, timeout=1.0)
    assert manager_closed.wait(1.0)
    assert close_calls == 1

    service.shutdown(0.0)
    assert close_calls == 1
