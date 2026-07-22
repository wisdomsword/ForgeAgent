"""Bounded worker registry for local HTTP task execution."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from .http_config import HttpServiceConfig
from .secret_policy import mask_audit_data, sensitive_env_values
from .task import Task, TaskOutcome

_logger = logging.getLogger(__name__)
_DETAIL_MAX_CHARS = 1024
_DETAIL_MAX_BYTES = 2048
_TRUNCATION_MARKER = "... [truncated]"


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
    _secret_values: frozenset[str] = field(default_factory=frozenset, repr=False)

    def public_view(self) -> dict[str, object]:
        outcome_status = self.outcome.status if self.outcome is not None else None
        detail = (
            self.detail
            if self.detail is not None
            else (outcome_status.detail if outcome_status is not None else None)
        )
        return {
            "task_id": self.task_id,
            "status": self.status,
            "reason": self.reason
            or (outcome_status.reason if outcome_status is not None else None),
            "detail": _safe_detail(detail, self._secret_values),
            "round_count": len(self.outcome.rounds) if self.outcome is not None else 0,
            "usage": _usage_summary(self.outcome),
            "audit_degraded": self.audit_degraded,
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
    ) -> None:
        self._factory = factory
        self._config = config
        self._clock = clock
        self._shared_mcp_manager = shared_mcp_manager
        self._records: dict[str, TaskRecord] = {}
        self._expired_ids: set[str] = set()
        self._expired_order: deque[str] = deque()
        self._lock = threading.Lock()
        self._accepting = True
        self._shutdown_complete = False
        self._executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="forgeagent-task",
        )
        self._secret_values = frozenset({*sensitive_env_values(), config.token})

    @property
    def records(self) -> dict[str, TaskRecord]:
        """Return a shallow registry snapshot so callers cannot replace service state."""
        with self._lock:
            self._purge_expired_locked()
            return dict(self._records)

    def submit(self, goal: str, options: Mapping[str, object]) -> TaskRecord:
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
                options=MappingProxyType(dict(options)),
                created_at=self._clock(),
                _secret_values=self._secret_values,
            )
            self._records[record.task_id] = record
            try:
                record.future = self._executor.submit(self._run_record, record)
            except Exception:
                del self._records[record.task_id]
                raise
            return record

    def query(self, task_id: str) -> dict[str, object]:
        with self._lock:
            record = self._get_record_locked(task_id)
            return record.public_view()

    def cancel(self, task_id: str) -> dict[str, object]:
        with self._lock:
            record = self._get_record_locked(task_id)
            if record.ended_at is not None:
                return record.public_view()
            record.cancel_event.set()
            if record.status == "queued":
                self._set_cancelled_locked(record)
                if record.future is not None:
                    record.future.cancel()
            return record.public_view()

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
            if self._shutdown_complete:
                return
            self._accepting = False
            futures: list[Future[None]] = []
            for record in self._records.values():
                if record.status == "queued":
                    record.cancel_event.set()
                    self._set_cancelled_locked(record)
                    if record.future is not None:
                        record.future.cancel()
                if record.future is not None:
                    futures.append(record.future)
            self._shutdown_complete = True

        if futures:
            wait(futures, timeout=max(0.0, timeout))
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._shared_mcp_manager is not None:
            try:
                self._shared_mcp_manager.close()
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
        audit_degraded = False
        try:
            task = self._factory(record)
            outcome = task.run(record.goal, cancel_event=record.cancel_event)
        except Exception:
            failed = True
            _logger.error("task worker failed")
        finally:
            if task is not None:
                failed = not self._close_task_resources(task) or failed
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
    sink = getattr(task, "_audit_sink", None)
    try:
        return bool(getattr(sink, "degraded", False))
    except Exception:
        return True


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


def _safe_detail(detail: str | None, secret_values: frozenset[str]) -> str | None:
    if detail is None:
        return None
    projected = mask_audit_data(detail, secret_values)
    safe = projected if isinstance(projected, str) else "<unsupported-detail>"
    return _truncate_utf8(safe)


def _truncate_utf8(text: str) -> str:
    if len(text) <= _DETAIL_MAX_CHARS and len(text.encode("utf-8")) <= _DETAIL_MAX_BYTES:
        return text
    prefix = text[: _DETAIL_MAX_CHARS - len(_TRUNCATION_MARKER)]
    byte_budget = _DETAIL_MAX_BYTES - len(_TRUNCATION_MARKER.encode("utf-8"))
    prefix = prefix.encode("utf-8")[:byte_budget].decode("utf-8", errors="ignore")
    return prefix + _TRUNCATION_MARKER
