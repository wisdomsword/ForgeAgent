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
