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
        self._path = Path(path).expanduser()
        self._max_bytes = max_bytes
        self._retention_files = retention_files
        self._secret_values = (
            sensitive_env_values() if secret_values is None else set(secret_values)
        )
        self._lock = threading.Lock()
        self._degraded = False
        # Opening the configured destination is a startup check. Runtime writes do not
        # recreate a missing destination, so an unexpected path failure is observable.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.open("a", encoding="utf-8").close()

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
                self._rotate_if_needed(len(line.encode("utf-8")))
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                return True
            except OSError:
                self._degraded = True
                _logger.error("audit append failed; audit is degraded")
                return False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        if self._path.stat().st_size + incoming_bytes <= self._max_bytes:
            return
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


def emit_audit(sink: AuditSink | None, event: AuditEvent) -> bool:
    """Keep an injected sink failure from changing task execution behavior."""
    if sink is None:
        return True
    try:
        return sink.emit(event)
    except Exception:  # pragma: no cover - defensive boundary for third-party sinks
        _logger.error("audit sink failed; audit is degraded")
        return False
