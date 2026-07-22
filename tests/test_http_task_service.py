"""Bounded task registry and worker lifecycle tests."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from types import SimpleNamespace

import pytest

from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_task_service import (
    ServiceCapacityError,
    ServiceClosedError,
    TaskNotFound,
    TaskRecord,
    TaskService,
)
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


def _outcome(
    reason: str = Termination.COMPLETED,
    *,
    detail: str | None = None,
    usage: TokenUsage | None = None,
) -> TaskOutcome:
    return TaskOutcome(
        status=TaskStatus(completed=reason == Termination.COMPLETED, reason=reason, detail=detail),
        rounds=[RoundResult(text="private model text", usage=usage)],
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
            "status",
            "reason",
            "detail",
            "round_count",
            "usage",
            "audit_degraded",
        }
    finally:
        service.shutdown(1.0)


def test_safe_projection_masks_and_bounds_terminal_detail_and_sums_usage():
    unsafe_detail = (
        "service-secret-token at /Users/admin/private/answer.txt " + "\N{SNOWMAN}" * 3000
    )

    def factory(_record: TaskRecord) -> _FakeTask:
        return _FakeTask(
            lambda _goal, _cancel: _outcome(
                Termination.NEEDS_INFO,
                detail=unsafe_detail,
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

        assert view["status"] == "needs_info"
        assert view["reason"] == "needs_info"
        assert "service-secret-token" not in str(view["detail"])
        assert "/Users/admin" not in str(view["detail"])
        assert len(str(view["detail"])) <= 1024
        assert len(str(view["detail"]).encode("utf-8")) <= 2048
        assert view["round_count"] == 1
        assert view["usage"] == {
            "input_tokens": 7,
            "output_tokens": 5,
            "cached_tokens": 3,
            "reasoning_tokens": 2,
        }
        assert view["audit_degraded"] is True
        assert "private model text" not in repr(view)
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
            return _outcome(Termination.COMPLETED)

        return _FakeTask(run)

    service = TaskService(factory=factory, config=CONFIG)
    try:
        record = service.submit("goal", {})
        assert started.wait(1.0)
        assert service.cancel(record.task_id)["status"] in {"running", "cancelled"}
        service.wait(record.task_id, timeout=1.0)
        assert service.query(record.task_id)["status"] == "cancelled"
        assert service.cancel(record.task_id)["status"] == "cancelled"
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
