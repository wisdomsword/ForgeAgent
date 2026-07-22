"""Injectable, masked JSONL audit events for core execution boundaries."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .secret_policy import mask_audit_data, sensitive_env_values

_logger = logging.getLogger(__name__)
_MIN_LINE_BYTES = 3
_PRIVATE_FILE_MODE = 0o600
_PRIVATE_OPEN_FLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_private_descriptor(path: Path, flags: int) -> int:
    descriptor = os.open(path, flags | _PRIVATE_OPEN_FLAGS, _PRIVATE_FILE_MODE)
    try:
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AuditEvent(BaseModel):
    """Stable immutable event accepted by every audit sink."""

    model_config = ConfigDict(frozen=True)

    timestamp: str = Field(default_factory=_utc_now)
    event_type: str
    task_id: str | None = None
    risk_level: str = "low"
    operation_id: str = Field(default_factory=lambda: uuid4().hex)
    attempt: int | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    result_status: str = "unknown"
    duration_ms: int | None = None
    audit_degraded: bool = False


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> bool:
        """Persist one event, returning whether it was durably accepted."""
        ...


class JsonlAuditSink:
    """Thread-safe JSONL sink with bounded rotation and runtime fail-open behavior."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        retention_files: int = 5,
        secret_values: Iterable[str] | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("audit max_bytes must be positive")
        if retention_files < 1:
            raise ValueError("audit retention_files must be positive")
        if max_bytes < _MIN_LINE_BYTES:
            raise ValueError("audit max_bytes must fit one JSONL line")
        self._path = Path(path).expanduser()
        self._max_bytes = max_bytes
        self._retention_files = retention_files
        self._secret_values = (
            sensitive_env_values() if secret_values is None else set(secret_values)
        )
        self._lock = threading.Lock()
        self._degraded = False
        # Opening the destination is a startup check; every later recreation uses the
        # same descriptor-level private mode enforcement.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = _open_private_descriptor(
            self._path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        )
        os.close(descriptor)
        self._remove_stale_rotated_files()
        for candidate in (self._path, *(path for _, path in self._rotated_files())):
            self._compact_existing_file(candidate)

    @property
    def degraded(self) -> bool:
        with self._lock:
            return self._degraded

    def emit(self, event: AuditEvent) -> bool:
        with self._lock:
            try:
                payload = mask_audit_data(event.model_dump(mode="python"), self._secret_values)
                assert isinstance(payload, dict)
                payload["audit_degraded"] = bool(payload["audit_degraded"] or self._degraded)
                line = (
                    json.dumps(
                        payload,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
                if len(line.encode("utf-8")) > self._max_bytes:
                    line = self._oversize_line()
                self._rotate_if_needed(len(line.encode("utf-8")))
                self._append_line(line)
                return True
            except OSError:
                self._degraded = True
                _logger.error("audit append failed; audit is degraded")
                return False
            except Exception:
                self._degraded = True
                _logger.error("audit serialization failed; writing fixed fallback")
                try:
                    line = self._oversize_line(result_status="serialization_error")
                    self._rotate_if_needed(len(line.encode("utf-8")))
                    self._append_line(line)
                    return True
                except OSError:
                    return False

    def _oversize_line(self, *, result_status: str = "oversize") -> str:
        candidates = (
            f'{{"event_type":"audit.logging_error","result_status":"{result_status}"}}\n',
            '{"event_type":"audit.logging_error"}\n',
            "{}\n",
        )
        for candidate in candidates:
            if len(candidate.encode("utf-8")) <= self._max_bytes:
                return candidate
        return "\n"[: self._max_bytes]

    def _compact_existing_file(self, path: Path) -> None:
        """Drop malformed/oversized startup lines so retained files stay bounded."""
        if not path.exists():
            return
        descriptor = _open_private_descriptor(path, os.O_RDONLY)
        with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as handle:
            raw_lines = handle.read().splitlines()
        kept: list[str] = []
        total = 0
        for raw in reversed(raw_lines):
            candidate = raw + "\n"
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                continue
            size = len(candidate.encode("utf-8"))
            if size > self._max_bytes or total + size > self._max_bytes:
                continue
            kept.append(candidate)
            total += size
        descriptor = _open_private_descriptor(
            path,
            os.O_WRONLY | os.O_TRUNC | os.O_CREAT,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("".join(reversed(kept)))

    def _append_line(self, line: str) -> None:
        descriptor = _open_private_descriptor(
            self._path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        if self._path.stat().st_size + incoming_bytes <= self._max_bytes:
            return
        self._remove_stale_rotated_files()
        if self._retention_files == 1:
            self._path.unlink()
            return
        oldest = self._rotated_path(self._retention_files - 1)
        if oldest.exists():
            oldest.unlink()
        for index in range(self._retention_files - 2, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                os.replace(source, self._rotated_path(index + 1))
        os.replace(self._path, self._rotated_path(1))

    def _rotated_path(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")

    def _rotated_files(self) -> list[tuple[int, Path]]:
        prefix = f"{self._path.name}."
        rotated: list[tuple[int, Path]] = []
        for candidate in self._path.parent.iterdir():
            if not candidate.name.startswith(prefix):
                continue
            suffix = candidate.name[len(prefix) :]
            if suffix.isascii() and suffix.isdigit():
                rotated.append((int(suffix), candidate))
        return sorted(rotated)

    def _remove_stale_rotated_files(self) -> None:
        for index, candidate in self._rotated_files():
            if (
                index < 1
                or index >= self._retention_files
                or candidate != self._rotated_path(index)
            ):
                candidate.unlink()


def emit_audit(sink: AuditSink | None, event: AuditEvent) -> bool:
    """Keep an injected sink failure from changing task execution behavior."""
    if sink is None:
        return True
    try:
        return sink.emit(event)
    except Exception:  # pragma: no cover - defensive boundary for third-party sinks
        _logger.error("audit sink failed; audit is degraded")
        return False
