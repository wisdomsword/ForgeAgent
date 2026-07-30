"""Durable, bounded receipts for protected external actions."""

from __future__ import annotations

import json
import hashlib
import os
import re
import stat
import threading
import unicodedata
import weakref
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .audit import AuditEvent, AuditSink, emit_audit
from .secret_policy import mask_secrets, sensitive_env_values

RECEIPT_SCHEMA = "forgeagent.external-action-receipt.v1"
MAX_RECEIPT_BYTES = 256 * 1024
MAX_TASK_ID_CHARS = 128
MAX_LABEL_CHARS = 200
MAX_EVIDENCE_CHARS = 1000
MAX_PARENT_ACTION_ID_CHARS = 32
_ACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

ReceiptPhase = Literal["prepared", "dispatched", "confirmed", "unknown"]
ReceiptResolution = Literal["open", "confirmed", "abandoned", "retry_approved"]
DispatchCertainty = Literal["not_dispatched", "confirmed", "unknown"]


class ReceiptError(Exception):
    """A receipt cannot be safely created, loaded, or transitioned."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON value: {value}")


def _safe_text(value: Any, *, field: str, maximum: int, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if len(value) > maximum:
        raise ValueError(f"{field} is too long")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must not be blank")
    unsafe = {"Cc", "Cf", "Cs", "Zl", "Zp"}
    if any(unicodedata.category(character) in unsafe for character in value):
        raise ValueError(f"{field} contains unsafe characters")
    return value.strip() if not allow_empty else value


def _masked_text(value: Any, *, field: str, maximum: int, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    masked = mask_secrets(value, sensitive_env_values())
    escaped = "".join(
        character if unicodedata.category(character) not in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        else f"\\u{ord(character):04x}"
        for character in masked
    )
    return _safe_text(escaped, field=field, maximum=maximum, allow_empty=allow_empty)


def canonical_request_digest(arguments: object) -> str:
    """Hash only the canonical JSON representation of an arguments object."""
    try:
        payload = json.dumps(
            arguments,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("arguments must be JSON-serializable") from error
    return hashlib.sha256(payload).hexdigest()


class ExternalActionReceipt(BaseModel):
    """Strict immutable state for one externally visible action attempt."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema: Literal[RECEIPT_SCHEMA] = RECEIPT_SCHEMA
    action_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_action_id: str | None = None
    task_id: str
    loop_id: str | None = None
    action_type: Literal["mcp"] = "mcp"
    server_label: str
    tool_label: str
    request_digest: str
    phase: ReceiptPhase = "prepared"
    resolution: ReceiptResolution = "open"
    dispatch_certainty: DispatchCertainty | None = None
    remote_ok: bool | None = None
    evidence_ref: str = ""
    revision: int = 0
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @field_validator("action_id")
    @classmethod
    def _action_id(cls, value: str) -> str:
        if _ACTION_ID_RE.fullmatch(value) is None:
            raise ValueError("invalid action id")
        return value

    @field_validator("parent_action_id")
    @classmethod
    def _parent_action_id(cls, value: str | None) -> str | None:
        if value is not None and _ACTION_ID_RE.fullmatch(value) is None:
            raise ValueError("invalid parent action id")
        return value

    @field_validator("task_id")
    @classmethod
    def _task_id(cls, value: str) -> str:
        return _safe_text(value, field="task_id", maximum=MAX_TASK_ID_CHARS, allow_empty=False)

    @field_validator("loop_id")
    @classmethod
    def _loop_id(cls, value: str | None) -> str | None:
        if value is not None and _ACTION_ID_RE.fullmatch(value) is None:
            raise ValueError("invalid loop id")
        return value

    @field_validator("server_label", "tool_label")
    @classmethod
    def _labels(cls, value: str, info: Any) -> str:
        return _safe_text(value, field=info.field_name, maximum=MAX_LABEL_CHARS, allow_empty=False)

    @field_validator("request_digest")
    @classmethod
    def _request_digest(cls, value: str) -> str:
        if _DIGEST_RE.fullmatch(value) is None:
            raise ValueError("invalid request digest")
        return value

    @field_validator("evidence_ref")
    @classmethod
    def _evidence(cls, value: str) -> str:
        return _safe_text(value, field="evidence_ref", maximum=MAX_EVIDENCE_CHARS, allow_empty=True)

    @field_validator("revision")
    @classmethod
    def _revision(cls, value: int) -> int:
        if type(value) is not int or value < 0:
            raise ValueError("revision must be non-negative")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamp(cls, value: str, info: Any) -> str:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError(f"{info.field_name} must be UTC")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError(f"{info.field_name} must be an ISO timestamp") from error
        if parsed.tzinfo != UTC:
            raise ValueError(f"{info.field_name} must be UTC")
        return value

    @model_validator(mode="after")
    def _invariants(self) -> ExternalActionReceipt:
        if self.phase == "prepared" and self.dispatch_certainty is not None:
            raise ValueError("prepared receipt cannot have dispatch certainty")
        if self.phase == "dispatched" and self.dispatch_certainty is not None:
            raise ValueError("dispatched receipt cannot have dispatch certainty")
        if self.phase == "unknown" and self.dispatch_certainty != "unknown":
            raise ValueError("unknown receipt requires unknown certainty")
        if self.phase == "confirmed" and self.dispatch_certainty not in {"confirmed", "not_dispatched"}:
            raise ValueError("confirmed receipt requires certainty")
        if self.dispatch_certainty == "not_dispatched" and self.remote_ok is not False:
            raise ValueError("not-dispatched receipt must be remote failure")
        if self.dispatch_certainty == "unknown" and self.remote_ok is not None:
            raise ValueError("unknown receipt has no remote result")
        return self

    @classmethod
    def new_prepared(
        cls,
        *,
        task_id: str,
        action_type: Literal["mcp"] = "mcp",
        server_label: str,
        tool_label: str,
        request_digest: str,
        parent_action_id: str | None = None,
        loop_id: str | None = None,
        **extra: Any,
    ) -> ExternalActionReceipt:
        return cls(
            task_id=task_id,
            action_type=action_type,
            server_label=server_label,
            tool_label=tool_label,
            request_digest=request_digest,
            parent_action_id=parent_action_id,
            loop_id=loop_id,
            **extra,
        )


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


class ExternalActionReceiptStore:
    """Symlink-safe atomic JSON receipt store scoped to one allowed root."""

    def __init__(
        self,
        allowed_root: str,
        *,
        audit_sink: AuditSink | None = None,
        task_id: str | None = None,
        loop_id: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._audit_sink = audit_sink
        self._task_id = task_id
        self._loop_id = loop_id
        root = Path(allowed_root).expanduser()
        try:
            details = os.lstat(root)
        except OSError as error:
            raise ReceiptError("receipt root is unavailable") from error
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise ReceiptError("receipt root is unsafe")
        self._root = Path(os.path.realpath(root))
        self._directory = self._prepare_directory()
        self._directory_fd = self._open_directory()
        self._closed = False
        self._finalizer = weakref.finalize(self, os.close, self._directory_fd)

    def _safe_directory(self, path: Path, *, create: bool) -> Path:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            if not create:
                raise ReceiptError("receipt directory is unavailable")
            path.mkdir()
            details = os.lstat(path)
        except OSError as error:
            raise ReceiptError("receipt directory is unavailable") from error
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise ReceiptError("receipt directory is unsafe")
        resolved = Path(os.path.realpath(path))
        if not _is_within(self._root, resolved):
            raise ReceiptError("receipt directory is outside allowed root")
        return resolved

    def _prepare_directory(self) -> Path:
        current = self._root
        for part in (".forgeagent", "receipts"):
            current = self._safe_directory(current / part, create=True)
        return current

    def _open_directory(self) -> int:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if no_follow is None or directory is None:
            raise ReceiptError("receipt directory cannot be opened safely")
        try:
            descriptor = os.open(self._directory, os.O_RDONLY | no_follow | directory)
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                os.close(descriptor)
                raise ReceiptError("receipt directory is unsafe")
            return descriptor
        except ReceiptError:
            raise
        except OSError as error:
            raise ReceiptError("receipt directory cannot be opened safely") from error

    def _ensure_binding(self) -> None:
        if self._closed:
            raise ReceiptError("receipt store is closed")
        try:
            path_details = os.lstat(self._directory)
            fd_details = os.fstat(self._directory_fd)
        except OSError as error:
            raise ReceiptError("receipt directory is unavailable") from error
        if (
            stat.S_ISLNK(path_details.st_mode)
            or not stat.S_ISDIR(path_details.st_mode)
            or (path_details.st_dev, path_details.st_ino) != (fd_details.st_dev, fd_details.st_ino)
        ):
            raise ReceiptError("receipt directory is unsafe")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._finalizer()

    def _name(self, action_id: str) -> str:
        if not isinstance(action_id, str) or _ACTION_ID_RE.fullmatch(action_id) is None:
            raise ReceiptError("invalid action id")
        return f"{action_id}.json"

    @contextmanager
    def _receipt_lock(self, action_id: str) -> Iterator[None]:
        import fcntl

        self._ensure_binding()
        name = f".{action_id}.lock"
        descriptor = -1
        locked = False
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._directory_fd,
            )
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ReceiptError("receipt lock is unsafe")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            self._ensure_binding()
            yield
        except ReceiptError:
            raise
        except (OSError, TypeError) as error:
            raise ReceiptError("receipt lock failed") from error
        finally:
            if descriptor >= 0:
                if locked:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(descriptor)

    def _load_unlocked(self, action_id: str) -> ExternalActionReceipt:
        name = self._name(action_id)
        descriptor = -1
        try:
            self._ensure_binding()
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._directory_fd)
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_RECEIPT_BYTES:
                raise ReceiptError("receipt file is unsafe")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                raw = handle.read(MAX_RECEIPT_BYTES + 1)
            if len(raw.encode("utf-8")) > MAX_RECEIPT_BYTES:
                raise ReceiptError("receipt file is too large")
            parsed = json.loads(raw, parse_constant=_reject_json_constant)
            receipt = ExternalActionReceipt.model_validate(parsed)
        except ReceiptError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise ReceiptError("receipt file is invalid") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if receipt.action_id != action_id:
            raise ReceiptError("receipt file is invalid")
        return receipt

    def load(self, action_id: str) -> ExternalActionReceipt:
        with self._lock:
            return self._load_unlocked(action_id)

    def _write(self, receipt: ExternalActionReceipt) -> None:
        name = self._name(receipt.action_id)
        payload = (
            json.dumps(receipt.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
            + b"\n"
        )
        if len(payload) > MAX_RECEIPT_BYTES:
            raise ReceiptError("receipt is too large")
        temporary = f".receipt.{uuid4().hex}"
        descriptor = -1
        try:
            self._ensure_binding()
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._directory_fd,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, name, src_dir_fd=self._directory_fd, dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            self._ensure_binding()
        except ReceiptError:
            raise
        except (OSError, TypeError) as error:
            raise ReceiptError("receipt save failed") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=self._directory_fd)
            except (FileNotFoundError, OSError, TypeError):
                pass

    def _audit(self, receipt: ExternalActionReceipt, status: str) -> None:
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type="external_action.receipt",
                operation_id=receipt.action_id,
                task_id=receipt.task_id,
                risk_level="high",
                parameters={
                    "action_id": receipt.action_id,
                    "phase": receipt.phase,
                    "resolution": receipt.resolution,
                    "dispatch_certainty": receipt.dispatch_certainty,
                    "remote_ok": receipt.remote_ok,
                    "server_label": receipt.server_label,
                    "tool_label": receipt.tool_label,
                    "evidence_code": receipt.evidence_ref[:64],
                    "loop_id": receipt.loop_id,
                },
                result_status=status,
            ),
        )

    def create_prepared(
        self,
        *,
        task_id: str | None = None,
        loop_id: str | None = None,
        action_type: Literal["mcp"] = "mcp",
        server_label: str,
        tool_label: str,
        request_digest: str,
        parent_action_id: str | None = None,
    ) -> ExternalActionReceipt:
        effective_task_id = self._task_id if task_id is None else task_id
        if effective_task_id is None:
            raise ReceiptError("task id is required")
        try:
            receipt = ExternalActionReceipt.new_prepared(
                task_id=effective_task_id,
                loop_id=self._loop_id if loop_id is None else loop_id,
                action_type=action_type,
                server_label=_masked_text(server_label, field="server_label", maximum=MAX_LABEL_CHARS, allow_empty=False),
                tool_label=_masked_text(tool_label, field="tool_label", maximum=MAX_LABEL_CHARS, allow_empty=False),
                request_digest=request_digest,
                parent_action_id=parent_action_id,
            )
        except ValidationError as error:
            raise ReceiptError("invalid receipt") from error
        with self._lock, self._receipt_lock(receipt.action_id):
            try:
                os.stat(self._name(receipt.action_id), dir_fd=self._directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as error:
                raise ReceiptError("receipt file is invalid") from error
            else:
                raise ReceiptError("receipt already exists")
            self._write(receipt)
        self._audit(receipt, "created")
        return receipt

    def _transition(self, action_id: str, expected_revision: int, update: Mapping[str, object]) -> ExternalActionReceipt:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ReceiptError("invalid receipt revision")
        with self._lock, self._receipt_lock(action_id):
            current = self._load_unlocked(action_id)
            if current.revision != expected_revision:
                raise ReceiptError("receipt revision is stale")
            try:
                updated = ExternalActionReceipt.model_validate(
                    current.model_dump(mode="python") | dict(update) | {"revision": expected_revision + 1, "updated_at": _utc_now()}
                )
            except ValidationError as error:
                raise ReceiptError("invalid receipt transition") from error
            self._write(updated)
        self._audit(updated, "transitioned")
        return updated

    def mark_dispatched(self, action_id: str, expected_revision: int) -> ExternalActionReceipt:
        receipt = self.load(action_id)
        if receipt.phase != "prepared" or receipt.resolution != "open":
            raise ReceiptError("invalid receipt transition")
        return self._transition(action_id, expected_revision, {"phase": "dispatched"})

    def mark_confirmed(
        self,
        action_id: str,
        expected_revision: int,
        certainty: DispatchCertainty,
        remote_ok: bool,
        evidence: str,
    ) -> ExternalActionReceipt:
        current = self.load(action_id)
        if current.phase not in {"prepared", "dispatched"} or current.resolution != "open":
            raise ReceiptError("invalid receipt transition")
        if certainty not in {"confirmed", "not_dispatched"}:
            raise ReceiptError("invalid dispatch certainty")
        if certainty == "confirmed" and current.phase != "dispatched":
            raise ReceiptError("confirmed certainty requires dispatch")
        if certainty == "not_dispatched" and remote_ok is not False:
            raise ReceiptError("not-dispatched confirmation requires remote failure")
        if type(remote_ok) is not bool:
            raise ReceiptError("remote result must be boolean")
        try:
            safe_evidence = _masked_text(evidence, field="evidence_ref", maximum=MAX_EVIDENCE_CHARS, allow_empty=False)
        except ValueError as error:
            raise ReceiptError("invalid evidence") from error
        return self._transition(
            action_id,
            expected_revision,
            {"phase": "confirmed", "dispatch_certainty": certainty, "remote_ok": remote_ok, "evidence_ref": safe_evidence},
        )

    def mark_unknown(self, action_id: str, expected_revision: int, evidence: str) -> ExternalActionReceipt:
        current = self.load(action_id)
        if current.phase not in {"prepared", "dispatched"} or current.resolution != "open":
            raise ReceiptError("invalid receipt transition")
        try:
            safe_evidence = _masked_text(evidence, field="evidence_ref", maximum=MAX_EVIDENCE_CHARS, allow_empty=False)
        except ValueError as error:
            raise ReceiptError("invalid evidence") from error
        return self._transition(
            action_id,
            expected_revision,
            {"phase": "unknown", "dispatch_certainty": "unknown", "remote_ok": None, "evidence_ref": safe_evidence},
        )

    def list_pending(self, loop_id: str | None = None, task_id: str | None = None) -> tuple[ExternalActionReceipt, ...]:
        with self._lock:
            self._ensure_binding()
            try:
                names = sorted(os.listdir(self._directory_fd))
            except OSError as error:
                raise ReceiptError("receipt listing failed") from error
            records: list[ExternalActionReceipt] = []
            for name in names:
                if not name.endswith(".json"):
                    continue
                action_id = name[:-5]
                if _ACTION_ID_RE.fullmatch(action_id) is None:
                    raise ReceiptError("receipt file is invalid")
                receipt = self._load_unlocked(action_id)
                if receipt.resolution == "open" and (loop_id is None or receipt.loop_id == loop_id) and (task_id is None or receipt.task_id == task_id):
                    records.append(receipt)
            return tuple(records)

    def resolve(self, action_id: str, expected_revision: int, decision: ReceiptResolution, evidence: str = "") -> ExternalActionReceipt:
        if decision not in {"confirmed", "abandoned", "retry_approved"}:
            raise ReceiptError("invalid resolution")
        if decision == "confirmed":
            try:
                evidence = _masked_text(evidence, field="evidence_ref", maximum=MAX_EVIDENCE_CHARS, allow_empty=False)
            except ValueError as error:
                raise ReceiptError("confirmation evidence is required") from error
        elif evidence:
            try:
                evidence = _masked_text(evidence, field="evidence_ref", maximum=MAX_EVIDENCE_CHARS, allow_empty=False)
            except ValueError as error:
                raise ReceiptError("invalid evidence") from error
        current = self.load(action_id)
        if current.resolution != "open":
            raise ReceiptError("receipt is already resolved")
        return self._transition(action_id, expected_revision, {"resolution": decision, "evidence_ref": evidence or current.evidence_ref})
