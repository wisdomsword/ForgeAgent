"""Bounded worker registry for local HTTP task execution."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from .attention import Attention, attention_for_reason
from .audit import AuditSink
from .collaboration import (
    CollaborationMode,
    CollaborationReport,
    ModeDecision,
    emit_collaboration_route,
    resolve_collaboration_mode,
)
from .execution_evidence import ExecutionEvidence, public_execution_evidence
from .external_actions import (
    ExternalActionReceipt,
    ExternalActionReceiptStore,
    ReceiptError,
    ReceiptResolution,
    public_receipt_evidence_code,
    public_receipt_label,
)
from .http_action_approvals import ApprovalUnavailableError, HttpActionApprovalStore
from .http_config import HttpServiceConfig
from .loop import LoopReport
from .step import Termination
from .task import TaskOutcome

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


class TaskReceiptNotFound(RuntimeError):
    """A receipt is unavailable under the requested retained task."""


class TaskReceiptConflict(RuntimeError):
    """A receipt is no longer open at the expected revision."""


class ReceiptServiceUnavailable(RuntimeError):
    """The receipt authority cannot complete a safe operation."""


@dataclass
class TaskRecord:
    """Private task state with a fixed, safe public projection."""

    task_id: str
    goal: str
    options: Mapping[str, object] = field(default_factory=dict, repr=False)
    approval_ids: tuple[str, ...] = field(default=(), repr=False)
    status: str = "queued"
    reason: str | None = None
    detail: str | None = None
    outcome: TaskOutcome | None = field(default=None, repr=False)
    loop_report: LoopReport | None = field(default=None, repr=False)
    collaboration_report: CollaborationReport | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    audit_degraded: bool = False
    future: Future[None] | None = field(default=None, repr=False)
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    ended_at: float | None = None

    def public_view(self, *, service_audit_degraded: bool = False) -> dict[str, object]:
        requested_mode = self.options.get("mode", "task")
        mode = requested_mode if requested_mode in {"loop", "duo", "triad"} else "task"
        outcome_status = self.outcome.status if self.outcome is not None else None
        report_reason = self.loop_report.stop_reason if self.loop_report is not None else None
        reason = (
            self.reason
            or report_reason
            or (outcome_status.reason if outcome_status is not None else None)
        )
        status, reason = _public_status_reason(self.status, reason, mode=mode)
        attention = _record_attention(
            self,
            status=status,
            reason=reason,
            mode=mode,
        )
        view: dict[str, object] = {
            "task_id": self.task_id,
            "mode": mode,
            "status": status,
            "reason": reason,
            "detail": _PUBLIC_DETAILS.get(reason),
            "round_count": len(self.outcome.rounds) if self.outcome is not None else 0,
            "usage": _usage_summary(self.outcome),
            "audit_degraded": self.audit_degraded or service_audit_degraded,
            "attention": attention.model_dump(mode="json"),
        }
        if mode in {"duo", "triad"}:
            report = self.collaboration_report
            view["phase"] = (
                report.phase
                if report is not None
                else ("planning" if mode == "triad" else "generator")
            )
            if report is not None and self.ended_at is not None:
                view.update(
                    round_count=report.rounds,
                    usage=report.usage.model_dump(mode="json"),
                    plan_item_count=report.plan_item_count,
                    passed_item_count=report.passed_item_count,
                    failed_item_count=report.failed_item_count,
                    generator_attempts=report.generator_attempts,
                    evaluator_attempts=report.evaluator_attempts,
                    rejections=report.rejections,
                    usage_available=report.usage_available,
                    evidence=list(report.evidence),
                )
        if self.loop_report is not None and self.ended_at is not None:
            report = self.loop_report
            view.update(
                loop_id=report.loop_id,
                iterations=report.iterations,
                rounds_used=report.rounds_used,
                tokens_used=report.tokens_used,
                elapsed_seconds=report.elapsed_seconds,
                consecutive_failures=report.consecutive_failures,
                completed_item_count=report.completed_item_count,
                open_question_count=report.open_question_count,
                usage_available=report.usage_available,
            )
        if mode == "task" and self.ended_at is not None:
            source = (
                self.outcome.execution_evidence
                if self.outcome is not None
                else ExecutionEvidence()
            )
            view["execution_evidence"] = public_execution_evidence(source).model_dump(mode="json")
        return view


class TaskRunner(Protocol):
    def run(
        self, goal: str, *, cancel_event: threading.Event | None = None
    ) -> TaskOutcome | LoopReport | CollaborationReport: ...

    def close(self) -> None: ...


TaskFactory = Callable[[TaskRecord], TaskRunner]


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
        approval_store: HttpActionApprovalStore | None = None,
        receipt_store: ExternalActionReceiptStore | None = None,
    ) -> None:
        self._factory = factory
        self._config = config
        self._clock = clock
        self._shared_mcp_manager = shared_mcp_manager
        self._audit_sink = audit_sink
        self._approval_store = approval_store
        self._receipt_store = receipt_store
        self._audit_degraded = False
        self._records: dict[str, TaskRecord] = {}
        self._active_resume_ids: dict[str, str] = {}
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

    def issue_action_approval(
        self,
        *,
        server: str,
        tool: str,
        request_digest: str,
        expires_in_seconds: int,
    ) -> dict[str, object]:
        if self._approval_store is None:
            raise ApprovalUnavailableError
        return self._approval_store.issue(
            server=server,
            tool=tool,
            request_digest=request_digest,
            expires_in_seconds=expires_in_seconds,
        ).public_view()

    def get_action_approval(self, approval_id: str) -> dict[str, object]:
        if self._approval_store is None:
            raise ApprovalUnavailableError
        return self._approval_store.get(approval_id).public_view()

    def revoke_action_approval(self, approval_id: str) -> dict[str, object]:
        if self._approval_store is None:
            raise ApprovalUnavailableError
        return self._approval_store.revoke(approval_id).public_view()

    def list_task_receipts(self, task_id: str) -> tuple[dict[str, object], ...]:
        task_error: TaskNotFound | None = None
        try:
            self._require_retained_task(task_id)
        except TaskNotFound as error:
            task_error = error
        if self._receipt_store is None:
            if task_error is not None:
                raise task_error
            raise ReceiptServiceUnavailable
        try:
            receipts = self._receipt_store.list_pending(task_id=task_id)
        except ReceiptError:
            if task_error is not None:
                raise task_error from None
            raise ReceiptServiceUnavailable from None
        if task_error is not None and not receipts:
            raise task_error
        return tuple(_receipt_public_view(receipt) for receipt in receipts)

    def resolve_task_receipt(
        self,
        task_id: str,
        action_id: str,
        *,
        expected_revision: int,
        decision: ReceiptResolution,
        evidence: str = "",
    ) -> dict[str, object]:
        task_error: TaskNotFound | None = None
        try:
            self._require_retained_task(task_id)
        except TaskNotFound as error:
            task_error = error
        if self._receipt_store is None:
            if task_error is not None:
                raise task_error
            raise ReceiptServiceUnavailable
        try:
            receipt = self._receipt_store.load(action_id)
        except ReceiptError as error:
            if task_error is not None:
                raise task_error from None
            if isinstance(error.__cause__, FileNotFoundError):
                raise TaskReceiptNotFound from None
            raise ReceiptServiceUnavailable from None
        if receipt.task_id != task_id:
            if task_error is not None:
                raise task_error
            raise TaskReceiptNotFound
        if receipt.resolution != "open" or receipt.revision != expected_revision:
            raise TaskReceiptConflict
        try:
            updated = self._receipt_store.resolve(
                action_id,
                expected_revision,
                decision,
                evidence,
            )
        except ReceiptError as error:
            if str(error) in {
                "receipt revision is stale",
                "receipt is already resolved",
                "invalid receipt transition",
            }:
                raise TaskReceiptConflict from None
            raise ReceiptServiceUnavailable from None
        return _receipt_public_view(updated)

    def submit(
        self,
        goal: str,
        options: Mapping[str, object],
        *,
        approval_ids: Iterable[str] = (),
    ) -> TaskRecord:
        record, _ = self._submit_internal(goal, options, approval_ids=approval_ids)
        return record

    def submit_view(
        self,
        goal: str,
        options: Mapping[str, object],
        *,
        approval_ids: Iterable[str] = (),
    ) -> dict[str, object]:
        """Create a task and return its initial public view in one lock scope."""
        _, view = self._submit_internal(goal, options, approval_ids=approval_ids)
        return view

    def _submit_internal(
        self,
        goal: str,
        options: Mapping[str, object],
        *,
        approval_ids: Iterable[str],
    ) -> tuple[TaskRecord, dict[str, object]]:
        if isinstance(approval_ids, (str, bytes)):
            raise ApprovalUnavailableError
        approval_snapshot = tuple(approval_ids)
        if any(not isinstance(approval_id, str) for approval_id in approval_snapshot):
            raise ApprovalUnavailableError
        option_snapshot: dict[str, object] = {}
        for key, value in options.items():
            if key == "has_bound_checks":
                raise TypeError("Task options must not set has_bound_checks.")
            if not isinstance(key, str) or type(value) not in _OPTION_SCALAR_TYPES:
                raise TypeError("Task options must use string keys and scalar values.")
            if type(value) is float and not math.isfinite(value):
                raise TypeError("Task options must use finite scalar values.")
            option_snapshot[key] = value
        requested = option_snapshot.get("mode")
        requested_mode: CollaborationMode | None = (
            None
            if requested is None
            else "single"
            if requested == "task"
            else requested
            if requested in {"duo", "triad"}
            else None
        )
        decision: ModeDecision | None = None
        if requested != "loop":
            decision = resolve_collaboration_mode(
                goal,
                requested_mode,
                allow_weaker_override=self._config.allow_weaker_override,
            )
        if requested is None and decision is not None:
            if decision.mode == "triad":
                option_snapshot["mode"] = "triad"

        with self._lock:
            if not self._accepting:
                raise ServiceClosedError
            self._purge_expired_locked()
            queued = sum(record.status == "queued" for record in self._records.values())
            if queued >= self._config.max_queue or len(self._records) >= self._config.max_records:
                raise ServiceCapacityError

            task_id = uuid4().hex
            if approval_snapshot:
                if self._approval_store is None:
                    raise ApprovalUnavailableError
                self._approval_store.bind_many(approval_snapshot, task_id)
            record = TaskRecord(
                task_id=task_id,
                goal=goal,
                options=MappingProxyType(option_snapshot),
                approval_ids=approval_snapshot,
                created_at=self._clock(),
            )
            self._records[record.task_id] = record
            if decision is not None:
                emit_collaboration_route(
                    self._audit_sink,
                    decision,
                    requested_mode,
                    task_id=record.task_id,
                )
            loop_id = _record_loop_id(record)
            if loop_id is not None and loop_id in self._active_resume_ids:
                record.status = "failed"
                record.reason = "internal_error"
                record.detail = "Task execution failed."
                record.ended_at = self._clock()
                self._release_approvals(record)
                return record, record.public_view(service_audit_degraded=self._audit_degraded)
            if loop_id is not None:
                self._active_resume_ids[loop_id] = record.task_id
            try:
                record.future = self._executor.submit(self._run_record, record)
            except BaseException:
                # A custom/external executor may enqueue the callable before raising.
                # Publish a terminal tombstone while holding the registry lock so a
                # late worker observes it and returns without constructing a Task.
                record.cancel_event.set()
                record.status = "cancelled"
                record.reason = "cancelled"
                try:
                    record.ended_at = self._clock()
                except BaseException:
                    record.ended_at = time.monotonic()
                del self._records[record.task_id]
                if loop_id is not None:
                    self._active_resume_ids.pop(loop_id, None)
                self._release_approvals(record)
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
                self._release_resume_id_locked(record)
                self._release_approvals(record)
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
                    self._release_resume_id_locked(record)
                    self._release_approvals(record)
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
            receipt_store = self._receipt_store
            self._receipt_store = None
        if receipt_store is not None:
            try:
                receipt_store.close()
            except Exception:
                _logger.error("shared receipt store close failed")
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

        task: TaskRunner | None = None
        outcome: TaskOutcome | None = None
        loop_report: LoopReport | None = None
        collaboration_report: CollaborationReport | None = None
        failed = False
        process_control_error: BaseException | None = None
        audit_degraded = False
        try:
            task = self._factory(record)
            result = task.run(record.goal, cancel_event=record.cancel_event)
            if isinstance(result, LoopReport):
                loop_report = result
            elif isinstance(result, CollaborationReport):
                collaboration_report = result
            else:
                outcome = result
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
            if (
                record.cancel_event.is_set()
                and (loop_report is None or loop_report.status == "active")
                and (collaboration_report is None or collaboration_report.status == "active")
            ):
                record.outcome = outcome
                self._set_cancelled_locked(record)
            elif failed or (
                outcome is None and loop_report is None and collaboration_report is None
            ):
                record.status = "failed"
                record.reason = "internal_error"
                record.detail = "Task execution failed."
                record.ended_at = self._clock()
            else:
                record.outcome = outcome
                record.loop_report = loop_report
                record.collaboration_report = collaboration_report
                if loop_report is not None:
                    record.status = loop_report.status
                    record.reason = loop_report.stop_reason
                elif collaboration_report is not None:
                    record.status = collaboration_report.status
                    record.reason = collaboration_report.stop_reason
                else:
                    assert outcome is not None
                    record.status = outcome.status.reason
                    record.reason = outcome.status.reason
                record.ended_at = self._clock()
            self._release_resume_id_locked(record)

        self._release_approvals(record)

        if process_control_error is not None:
            raise process_control_error

    def _close_task_resources(self, task: TaskRunner) -> bool:
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

    def _release_resume_id_locked(self, record: TaskRecord) -> None:
        resume_loop_id = _record_loop_id(record)
        if (
            resume_loop_id is not None
            and self._active_resume_ids.get(resume_loop_id) == record.task_id
        ):
            del self._active_resume_ids[resume_loop_id]

    def _release_approvals(self, record: TaskRecord) -> None:
        if not record.approval_ids or self._approval_store is None:
            return
        try:
            self._approval_store.release_task(record.task_id)
        except RuntimeError:
            _logger.error("task approval cleanup failed")

    def _get_record_locked(self, task_id: str) -> TaskRecord:
        self._purge_expired_locked()
        record = self._records.get(task_id)
        if record is None:
            raise TaskNotFound(task_id, expired=task_id in self._expired_ids)
        return record

    def _require_retained_task(self, task_id: str) -> None:
        with self._lock:
            self._get_record_locked(task_id)

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


def _audit_degraded(task: TaskRunner) -> bool:
    try:
        sink = getattr(task, "_audit_sink", None)
        return bool(getattr(sink, "degraded", False))
    except BaseException:
        return True


def _public_status_reason(
    status: str, reason: str | None, *, mode: str = "task"
) -> tuple[str, str | None]:
    if status in _PUBLIC_NONTERMINAL_STATES and reason is None:
        return status, None
    if status == "failed" and reason == "internal_error":
        return status, reason
    if mode in {"loop", "duo", "triad"} and status in {
        "completed",
        "stopped",
        "cancelled",
        "failed",
    }:
        return status, reason
    if status == reason and reason in _PUBLIC_TERMINAL_REASONS:
        return status, reason
    return "failed", "internal_error"


def _record_attention(
    record: TaskRecord, *, status: str, reason: str | None, mode: str
) -> Attention:
    """Project attention without exposing private task, loop, or collaboration text."""
    if record.outcome is not None and record.outcome.status.attention is not None:
        return record.outcome.status.attention
    if record.loop_report is not None and record.loop_report.attention is not None:
        return record.loop_report.attention
    if (
        mode in {"duo", "triad"}
        and record.collaboration_report is not None
        and record.collaboration_report.stop_reason == "needs_confirmation"
    ):
        return attention_for_reason("needs_info", "Confirm the generated plan before continuing.")
    if status in _PUBLIC_NONTERMINAL_STATES:
        return attention_for_reason(None)
    return attention_for_reason(reason)


def _record_loop_id(record: TaskRecord) -> str | None:
    if record.options.get("mode") != "loop":
        return None
    value = record.options.get("resume_loop_id")
    return value if isinstance(value, str) else record.task_id


def _receipt_public_view(receipt: ExternalActionReceipt) -> dict[str, object]:
    return {
        "action_id": receipt.action_id,
        "action_type": receipt.action_type,
        "server_label": public_receipt_label(receipt.server_label),
        "tool_label": public_receipt_label(receipt.tool_label),
        "request_digest": receipt.request_digest,
        "phase": receipt.phase,
        "resolution": receipt.resolution,
        "dispatch_certainty": receipt.dispatch_certainty,
        "remote_ok": receipt.remote_ok,
        "evidence_code": public_receipt_evidence_code(receipt.evidence_ref),
        "revision": receipt.revision,
    }


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
