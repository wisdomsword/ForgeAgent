"""Bounded worker registry for local HTTP task execution."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from .audit import AuditSink
from .http_config import HttpServiceConfig
from .step import Termination
from .task import Task, TaskOutcome

_logger = logging.getLogger(__name__)
_PUBLIC_DETAILS = {"internal_error": "Task execution failed."}
_OPTION_SCALAR_TYPES = {str, int, float, bool, type(None)}
_PUBLIC_NONTERMINAL_STATES = frozenset({"queued", "running"})
_PUBLIC_TERMINAL_REASONS = frozenset(
    {
        *(termination.value for termination in Termination),
        "client_error:network",
        "client_error:auth",
        "client_error:rate_limit",
        "client_error:invalid_request",
        "client_error:timeout",
        "client_error:unknown",
        "no_rounds",
        "unknown",
    }
)


class ServiceCapacityError(RuntimeError):
    """The service cannot retain or schedule another task."""

    kind = "capacity_exceeded"

    def __init__(self) -> None:
        super().__init__("Task service capacity is exhausted.")


class ServiceClosedError(RuntimeError):
    """The service no longer accepts submissions."""

    kind = "service_closed"

    def __init__(self) -> None:
        super().__init__("Task service is shutting down.")


class TaskNotFound(KeyError):
    """A task id is unknown or its retained result expired."""

    kind = "not_found"

    def __init__(self, task_id: str, *, expired: bool = False) -> None:
        super().__init__(task_id)
        self.task_id = task_id
        self.expired = expired


@dataclass
class TaskRecord:
    """Private task state with a fixed, safe public projection."""

    task_id: str
    goal: str
    options: Mapping[str, object] = field(default_factory=dict, repr=False)
    status: str = "queued"
    reason: str | None = None
    detail: str | None = None
    outcome: TaskOutcome | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    audit_degraded: bool = False
    future: Future[None] | None = field(default=None, repr=False)
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    ended_at: float | None = None

    def public_view(self, *, service_audit_degraded: bool = False) -> dict[str, object]:
        outcome_status = self.outcome.status if self.outcome is not None else None
        reason = self.reason or (outcome_status.reason if outcome_status is not None else None)
        status, reason = _public_status_reason(self.status, reason)
        return {
            "task_id": self.task_id,
            "status": status,
            "reason": reason,
            "detail": _PUBLIC_DETAILS.get(reason),
            "round_count": len(self.outcome.rounds) if self.outcome is not None else 0,
            "usage": _usage_summary(self.outcome),
            "audit_degraded": self.audit_degraded or service_audit_degraded,
        }


TaskFactory = Callable[[TaskRecord], Task]


class _Closeable(Protocol):
    def close(self) -> None: ...


class TaskService:
    """Own a bounded registry and isolate each task in an executor worker."""

    def __init__(
        self,
        *,
        factory: TaskFactory,
        config: HttpServiceConfig,
        clock: Callable[[], float] = time.monotonic,
        shared_mcp_manager: _Closeable | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._factory = factory
        self._config = config
        self._clock = clock
        self._shared_mcp_manager = shared_mcp_manager
        self._audit_sink = audit_sink
        self._audit_degraded = False
        self._records: dict[str, TaskRecord] = {}
        self._expired_ids: set[str] = set()
        self._expired_order: deque[str] = deque()
        self._lock = threading.Lock()
        self._accepting = True
        self._shutdown_started = False
        self._shutdown_complete = False
        self._shutdown_cleanup_thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="forgeagent-task",
        )

    @property
    def records(self) -> dict[str, dict[str, object]]:
        """Return public snapshots without exposing mutable registry records."""
        with self._lock:
            self._purge_expired_locked()
            return {
                task_id: record.public_view(service_audit_degraded=self._audit_degraded)
                for task_id, record in self._records.items()
            }

    @property
    def audit_degraded(self) -> bool:
        with self._lock:
            return self._audit_degraded

    def mark_audit_degraded(self) -> None:
        """Remember a service-level audit failure for all current and future views."""
        with self._lock:
            self._audit_degraded = True

    def submit(self, goal: str, options: Mapping[str, object]) -> TaskRecord:
        record, _ = self._submit_internal(goal, options)
        return record

    def submit_view(self, goal: str, options: Mapping[str, object]) -> dict[str, object]:
        """Create a task and return its initial public view in one lock scope."""
        _, view = self._submit_internal(goal, options)
        return view

    def _submit_internal(
        self, goal: str, options: Mapping[str, object]
    ) -> tuple[TaskRecord, dict[str, object]]:
        option_snapshot: dict[str, object] = {}
        for key, value in options.items():
            if not isinstance(key, str) or type(value) not in _OPTION_SCALAR_TYPES:
                raise TypeError("Task options must use string keys and scalar values.")
            if type(value) is float and not math.isfinite(value):
                raise TypeError("Task options must use finite scalar values.")
            option_snapshot[key] = value

        with self._lock:
            if not self._accepting:
                raise ServiceClosedError
            self._purge_expired_locked()
            queued = sum(record.status == "queued" for record in self._records.values())
            if queued >= self._config.max_queue or len(self._records) >= self._config.max_records:
                raise ServiceCapacityError

            record = TaskRecord(
                task_id=uuid4().hex,
                goal=goal,
                options=MappingProxyType(option_snapshot),
                created_at=self._clock(),
            )
            self._records[record.task_id] = record
            try:
                record.future = self._executor.submit(self._run_record, record)
            except Exception:
                del self._records[record.task_id]
                raise
            return record, record.public_view(service_audit_degraded=self._audit_degraded)

    def query(self, task_id: str) -> dict[str, object]:
        return self.snapshot(task_id)

    def snapshot(self, task_id: str) -> dict[str, object]:
        """Return one service-owned public snapshot while holding the registry lock."""
        with self._lock:
            record = self._get_record_locked(task_id)
            return record.public_view(service_audit_degraded=self._audit_degraded)

    def cancel(self, task_id: str) -> dict[str, object]:
        with self._lock:
            record = self._get_record_locked(task_id)
            if record.ended_at is not None:
                return record.public_view(service_audit_degraded=self._audit_degraded)
            record.cancel_event.set()
            if record.status == "queued":
                self._set_cancelled_locked(record)
                if record.future is not None:
                    record.future.cancel()
            return record.public_view(service_audit_degraded=self._audit_degraded)

    def wait(self, task_id: str, timeout: float | None = None) -> dict[str, object]:
        with self._lock:
            record = self._get_record_locked(task_id)
            future = record.future
        if future is not None:
            try:
                future.result(timeout=timeout)
            except CancelledError:
                pass
        return self.query(task_id)

    def shutdown(self, timeout: float) -> None:
        with self._lock:
            if self._shutdown_started:
                return
            self._accepting = False
            self._shutdown_started = True
            futures: list[Future[None]] = []
            for record in self._records.values():
                if record.ended_at is None:
                    record.cancel_event.set()
                if record.status == "queued":
                    self._set_cancelled_locked(record)
                    if record.future is not None:
                        record.future.cancel()
                if record.future is not None:
                    futures.append(record.future)

        self._executor.shutdown(wait=False, cancel_futures=True)
        _, pending = wait(futures, timeout=max(0.0, timeout)) if futures else (set(), set())
        if pending:
            cleanup_thread = threading.Thread(
                target=self._finish_shutdown,
                args=(futures,),
                name="forgeagent-task-cleanup",
                daemon=True,
            )
            with self._lock:
                self._shutdown_cleanup_thread = cleanup_thread
            try:
                cleanup_thread.start()
            except Exception:
                _logger.error("task cleanup thread failed to start; using future callbacks")
                with self._lock:
                    if self._shutdown_cleanup_thread is cleanup_thread:
                        self._shutdown_cleanup_thread = None
                self._finish_shutdown_with_callbacks(futures)
        else:
            self._close_shared_mcp_manager_once()

    def _finish_shutdown(self, futures: list[Future[None]]) -> None:
        wait(futures)
        with self._lock:
            if self._shutdown_cleanup_thread is threading.current_thread():
                self._shutdown_cleanup_thread = None
        self._close_shared_mcp_manager_once()

    def _finish_shutdown_with_callbacks(self, futures: list[Future[None]]) -> None:
        def close_when_drained(_future: Future[None]) -> None:
            if all(future.done() for future in futures):
                self._close_shared_mcp_manager_once()

        for future in futures:
            future.add_done_callback(close_when_drained)

    def _close_shared_mcp_manager_once(self) -> None:
        with self._lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True
            manager = self._shared_mcp_manager
            self._shared_mcp_manager = None
        if manager is not None:
            try:
                manager.close()
            except Exception:
                _logger.error("shared MCP manager close failed")

    def _run_record(self, record: TaskRecord) -> None:
        with self._lock:
            if record.ended_at is not None:
                return
            record.status = "running"
            record.started_at = self._clock()

        task: Task | None = None
        outcome: TaskOutcome | None = None
        failed = False
        process_control_error: BaseException | None = None
        audit_degraded = False
        try:
            task = self._factory(record)
            outcome = task.run(record.goal, cancel_event=record.cancel_event)
        except BaseException as error:
            failed = True
            process_control_error = error if not isinstance(error, Exception) else None
            _logger.error("task worker failed")
        finally:
            if task is not None:
                try:
                    failed = not self._close_task_resources(task) or failed
                except BaseException as error:
                    failed = True
                    if process_control_error is None:
                        process_control_error = error
                    _logger.error("task resource close failed")
                audit_degraded = _audit_degraded(task)

        with self._lock:
            if record.ended_at is not None:
                return
            record.audit_degraded = audit_degraded
            if record.cancel_event.is_set():
                self._set_cancelled_locked(record)
            elif failed or outcome is None:
                record.status = "failed"
                record.reason = "internal_error"
                record.detail = "Task execution failed."
                record.ended_at = self._clock()
            else:
                record.outcome = outcome
                record.status = outcome.status.reason
                record.reason = outcome.status.reason
                record.ended_at = self._clock()

        if process_control_error is not None:
            raise process_control_error

    def _close_task_resources(self, task: Task) -> bool:
        succeeded = True
        try:
            task.close()
        except Exception:
            succeeded = False
            _logger.error("task resource close failed")
        client = getattr(task, "_client", None)
        close_client = getattr(client, "close", None)
        if callable(close_client):
            try:
                close_client()
            except Exception:
                succeeded = False
                _logger.error("task client close failed")
        return succeeded

    def _set_cancelled_locked(self, record: TaskRecord) -> None:
        if record.ended_at is not None:
            return
        record.status = "cancelled"
        record.reason = "cancelled"
        record.ended_at = self._clock()

    def _get_record_locked(self, task_id: str) -> TaskRecord:
        self._purge_expired_locked()
        record = self._records.get(task_id)
        if record is None:
            raise TaskNotFound(task_id, expired=task_id in self._expired_ids)
        return record

    def _purge_expired_locked(self) -> None:
        now = self._clock()
        expired = [
            task_id
            for task_id, record in self._records.items()
            if record.ended_at is not None
            and now - record.ended_at >= self._config.terminal_ttl_seconds
        ]
        for task_id in expired:
            del self._records[task_id]
            self._remember_expired_locked(task_id)

    def _remember_expired_locked(self, task_id: str) -> None:
        while len(self._expired_order) >= self._config.max_records:
            oldest = self._expired_order.popleft()
            self._expired_ids.discard(oldest)
        self._expired_order.append(task_id)
        self._expired_ids.add(task_id)


def _audit_degraded(task: Task) -> bool:
    try:
        sink = getattr(task, "_audit_sink", None)
        return bool(getattr(sink, "degraded", False))
    except BaseException:
        return True


def _public_status_reason(status: str, reason: str | None) -> tuple[str, str | None]:
    if status in _PUBLIC_NONTERMINAL_STATES and reason is None:
        return status, None
    if status == "failed" and reason == "internal_error":
        return status, reason
    if status == reason and reason in _PUBLIC_TERMINAL_REASONS:
        return status, reason
    return "failed", "internal_error"


def _usage_summary(outcome: TaskOutcome | None) -> dict[str, int] | None:
    if outcome is None:
        return None
    total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }
    for round_result in outcome.rounds:
        if round_result.usage is None:
            continue
        for field_name in total:
            total[field_name] += getattr(round_result.usage, field_name)
    return total
