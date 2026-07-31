"""Bounded host-owned approvals for one HTTP-controlled MCP dispatch."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .audit import AuditEvent, AuditSink, emit_audit
from .headless import mcp_operation_key

APPROVAL_SCHEMA = "forgeagent.http-action-approval.v1"
MAX_APPROVAL_TTL_SECONDS = 3600

ApprovalStatus = Literal["issued", "bound", "consumed", "revoked", "expired"]
_TERMINAL_STATUSES = frozenset({"consumed", "revoked", "expired"})
_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_UNCHANGED = object()


class ApprovalError(RuntimeError):
    """An approval operation failed without exposing private state."""


class ApprovalNotFoundError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("approval is unavailable")


class ApprovalUnavailableError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("approval is unavailable")


class ApprovalCapacityError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("approval capacity is exhausted")


def _utc_timestamp(value: float) -> str:
    return (
        datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _valid_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("timestamp must be ISO-8601") from error
    if parsed.tzinfo != UTC:
        raise ValueError("timestamp must be UTC")
    return value


class HttpActionApproval(BaseModel):
    """Strict safe projection of one short-lived allow-once authority."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", populate_by_name=True)

    schema_version: Literal[APPROVAL_SCHEMA] = Field(APPROVAL_SCHEMA, alias="schema")
    approval_id: str = Field(default_factory=lambda: uuid4().hex)
    action_type: Literal["mcp"] = "mcp"
    scope: str
    request_digest: str
    mode: Literal["allow_once"] = "allow_once"
    status: ApprovalStatus = "issued"
    task_id: str | None = None
    issued_at: str
    expires_at: str

    @field_validator("approval_id")
    @classmethod
    def _approval_id(cls, value: str) -> str:
        if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
            raise ValueError("invalid approval id")
        return value

    @field_validator("scope")
    @classmethod
    def _scope(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid approval scope")
        try:
            prefix, server, tool = value.split("/")
            normalized = mcp_operation_key(server, tool)
        except ValueError:
            raise ValueError("invalid approval scope") from None
        if prefix != "mcp" or normalized != value:
            raise ValueError("invalid approval scope")
        return value

    @field_validator("request_digest")
    @classmethod
    def _request_digest(cls, value: str) -> str:
        if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
            raise ValueError("invalid request digest")
        return value

    @field_validator("task_id")
    @classmethod
    def _task_id(cls, value: str | None) -> str | None:
        if value is not None and _ID_RE.fullmatch(value) is None:
            raise ValueError("invalid task id")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        return _valid_timestamp(value)

    @model_validator(mode="after")
    def _status_binding(self) -> HttpActionApproval:
        if self.status == "issued" and self.task_id is not None:
            raise ValueError("issued approval cannot be task-bound")
        if self.status in {"bound", "consumed"} and self.task_id is None:
            raise ValueError("bound approval requires a task")
        return self

    def public_view(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)


class HttpActionApprovalStore:
    """Thread-safe bounded registry for process-local HTTP action authority."""

    def __init__(
        self,
        *,
        max_records: int,
        clock: Callable[[], float] = time.time,
        audit_sink: AuditSink | None = None,
    ) -> None:
        if type(max_records) is not int or max_records <= 0:
            raise ValueError("max_records must be positive")
        self._max_records = max_records
        self._clock = clock
        self._audit_sink = audit_sink
        self._records: dict[str, HttpActionApproval] = {}
        self._deadlines: dict[str, float] = {}
        self._lock = threading.RLock()

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApprovalUnavailableError
        result = float(value)
        if not math.isfinite(result):
            raise ApprovalUnavailableError
        return result

    def _audit(self, record: HttpActionApproval, result_status: str) -> None:
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type="action_approval.state",
                operation_id=record.approval_id,
                task_id=record.task_id,
                risk_level="high",
                parameters={
                    "approval_id": record.approval_id,
                    "action_type": record.action_type,
                    "scope": record.scope,
                    "request_digest": record.request_digest,
                    "status": record.status,
                },
                result_status=result_status,
            ),
        )

    def _replace(
        self,
        record: HttpActionApproval,
        *,
        status: ApprovalStatus,
        task_id: object = _UNCHANGED,
    ) -> HttpActionApproval:
        payload = record.model_dump(mode="python")
        payload["status"] = status
        if task_id is not _UNCHANGED:
            payload["task_id"] = task_id
        updated = HttpActionApproval.model_validate(payload)
        self._records[updated.approval_id] = updated
        return updated

    def _expire_locked(self, now: float) -> list[HttpActionApproval]:
        expired: list[HttpActionApproval] = []
        for approval_id, record in tuple(self._records.items()):
            if record.status in {"issued", "bound"} and now >= self._deadlines[approval_id]:
                expired.append(self._replace(record, status="expired"))
        return expired

    def issue(
        self,
        *,
        server: str,
        tool: str,
        request_digest: str,
        expires_in_seconds: int,
    ) -> HttpActionApproval:
        if (
            type(expires_in_seconds) is not int
            or not 1 <= expires_in_seconds <= MAX_APPROVAL_TTL_SECONDS
        ):
            raise ValueError("approval TTL is invalid")
        scope = mcp_operation_key(server, tool)
        if not isinstance(request_digest, str) or _DIGEST_RE.fullmatch(request_digest) is None:
            raise ValueError("request digest is invalid")
        now = self._now()
        with self._lock:
            expired = self._expire_locked(now)
            if len(self._records) >= self._max_records:
                terminal_id = next(
                    (
                        approval_id
                        for approval_id, record in self._records.items()
                        if record.status in _TERMINAL_STATUSES
                    ),
                    None,
                )
                if terminal_id is None:
                    raise ApprovalCapacityError
                del self._records[terminal_id]
                del self._deadlines[terminal_id]
            record = HttpActionApproval(
                scope=scope,
                request_digest=request_digest,
                issued_at=_utc_timestamp(now),
                expires_at=_utc_timestamp(now + expires_in_seconds),
            )
            self._records[record.approval_id] = record
            self._deadlines[record.approval_id] = now + expires_in_seconds
        for item in expired:
            self._audit(item, "expired")
        self._audit(record, "issued")
        return record

    def get(self, approval_id: str) -> HttpActionApproval:
        now = self._now()
        with self._lock:
            expired = self._expire_locked(now)
            record = self._records.get(approval_id)
            if record is None:
                raise ApprovalNotFoundError
        for item in expired:
            self._audit(item, "expired")
        return record

    def bind_many(
        self, approval_ids: Iterable[str], task_id: str
    ) -> tuple[HttpActionApproval, ...]:
        identifiers = tuple(approval_ids)
        if _ID_RE.fullmatch(task_id) is None or len(identifiers) != len(set(identifiers)):
            raise ApprovalUnavailableError
        now = self._now()
        with self._lock:
            expired = self._expire_locked(now)
            records = [self._records.get(approval_id) for approval_id in identifiers]
            if any(record is None or record.status != "issued" for record in records):
                raise ApprovalUnavailableError
            bound = tuple(
                self._replace(record, status="bound", task_id=task_id)
                for record in records
                if record is not None
            )
        for item in expired:
            self._audit(item, "expired")
        for item in bound:
            self._audit(item, "bound")
        return bound

    def consume(
        self,
        *,
        task_id: str,
        scope: str,
        request_digest: str,
    ) -> HttpActionApproval | None:
        now = self._now()
        consumed: HttpActionApproval | None = None
        with self._lock:
            expired = self._expire_locked(now)
            for record in self._records.values():
                if (
                    record.status == "bound"
                    and record.task_id == task_id
                    and record.scope == scope
                    and record.request_digest == request_digest
                ):
                    consumed = self._replace(record, status="consumed")
                    break
        for item in expired:
            self._audit(item, "expired")
        if consumed is not None:
            self._audit(consumed, "consumed")
        return consumed

    def revoke(self, approval_id: str) -> HttpActionApproval:
        now = self._now()
        with self._lock:
            expired = self._expire_locked(now)
            record = self._records.get(approval_id)
            if record is None:
                raise ApprovalNotFoundError
            if record.status in {"issued", "bound"}:
                record = self._replace(record, status="revoked")
        for item in expired:
            self._audit(item, "expired")
        self._audit(record, record.status)
        return record

    def release_task(self, task_id: str) -> None:
        released: list[HttpActionApproval] = []
        now = self._now()
        with self._lock:
            expired = self._expire_locked(now)
            for record in tuple(self._records.values()):
                if record.status == "bound" and record.task_id == task_id:
                    released.append(self._replace(record, status="revoked"))
        for item in expired:
            self._audit(item, "expired")
        for item in released:
            self._audit(item, "revoked")
