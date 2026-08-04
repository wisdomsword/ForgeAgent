"""Bounded, safe evidence for tools attempted during a ForgeAgent task.

This module is deliberately independent from task, loop, and collaboration runtime
objects.  It is the shared wire model used by those layers and therefore keeps all
public data small, deterministic, and free of host-local paths.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .secret_policy import mask_audit_data, sensitive_env_values

EvidenceStatus = Literal["succeeded", "failed", "artifact_persistence_failed"]
EvidenceRole = Literal["planner", "generator", "evaluator"]

MAX_INTERNAL_EVIDENCE_RECORDS = 128
MAX_PUBLIC_EVIDENCE_RECORDS = 32
MAX_EVIDENCE_LABEL_CHARS = 128
MAX_ARTIFACT_REFERENCE_CHARS = 512

_REFERENCE_RE = re.compile(
    r"^execution-artifacts/[0-9a-f]{32}/programs/[0-9]{4}-[a-z0-9-]{1,64}\.py$"
)


def _safe_text(value: str, secret_values: Iterable[str] = ()) -> str:
    """Mask secrets and make control/format characters unambiguous."""
    masked = mask_audit_data(value, secret_values)
    if not isinstance(masked, str):
        raise TypeError("safe evidence labels must be strings")
    escaped: list[str] = []
    length = 0
    for character in masked:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if category == "Cc" or category == "Cf":
            if codepoint <= 0xFF:
                token = f"\\x{codepoint:02x}"
            elif codepoint <= 0xFFFF:
                token = f"\\u{codepoint:04x}"
            else:
                token = f"\\U{codepoint:08x}"
        else:
            token = character
        if length + len(token) > MAX_EVIDENCE_LABEL_CHARS:
            break
        escaped.append(token)
        length += len(token)
    return "".join(escaped)


class ProgramArtifact(BaseModel):
    """A safe public reference plus an optional host-local CLI-only path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str = Field(min_length=1, max_length=MAX_ARTIFACT_REFERENCE_CHARS)
    local_path: Path | None = Field(default=None, exclude=True, repr=False)

    @field_validator("reference")
    @classmethod
    def _canonical_reference(cls, value: str) -> str:
        if not _REFERENCE_RE.fullmatch(value):
            raise ValueError("artifact reference must be canonical")
        return value


class ToolExecutionRecord(BaseModel):
    """One dispatched tool attempt, stripped to fields safe for public projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(strict=True, ge=0)
    tool: str = Field(min_length=1, max_length=MAX_EVIDENCE_LABEL_CHARS)
    status: EvidenceStatus
    block: str | None = Field(default=None, max_length=MAX_EVIDENCE_LABEL_CHARS)
    artifact: ProgramArtifact | None = None
    iteration: int | None = Field(default=None, strict=True, ge=0)
    role: EvidenceRole | None = None
    attempt: int | None = Field(default=None, strict=True, ge=0)

    @field_validator("tool", "block", mode="before")
    @classmethod
    def _sanitize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("evidence labels must be strings")
        return _safe_text(value, sensitive_env_values())

    @model_validator(mode="after")
    def _validate_origin_and_artifact(self) -> ToolExecutionRecord:
        if (self.role is None) != (self.attempt is None):
            raise ValueError("role and attempt must be supplied together")
        if self.status == "artifact_persistence_failed" and self.artifact is not None:
            raise ValueError("persistence failure cannot include an artifact")
        return self


class ExecutionEvidence(BaseModel):
    """A bounded immutable evidence envelope suitable for durable state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[ToolExecutionRecord, ...] = ()
    truncated: bool = False
    omitted_count: int = Field(default=0, strict=True, ge=0)


class ExecutionEvidenceRecorder:
    """Thread-safe recorder retaining the first 128 attempts in order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_sequence = 1
        self._records: list[ToolExecutionRecord] = []
        self._omitted_count = 0

    def append(
        self,
        *,
        tool: str,
        success: bool,
        block_name: str | None,
        program_artifact: ProgramArtifact | None,
        status: EvidenceStatus | None,
    ) -> None:
        with self._lock:
            sequence = self._next_sequence
            self._next_sequence += 1
            resolved_status: EvidenceStatus = status or ("succeeded" if success else "failed")
            record = ToolExecutionRecord(
                sequence=sequence,
                tool=tool,
                status=resolved_status,
                block=block_name,
                artifact=program_artifact,
            )
            if len(self._records) < MAX_INTERNAL_EVIDENCE_RECORDS:
                self._records.append(record)
            else:
                self._omitted_count += 1

    def snapshot(self) -> ExecutionEvidence:
        with self._lock:
            return ExecutionEvidence(
                records=tuple(self._records),
                truncated=self._omitted_count > 0,
                omitted_count=self._omitted_count,
            )


def _project_record(
    record: ToolExecutionRecord,
    *,
    secret_values: Iterable[str],
    include_local_paths: bool,
) -> ToolExecutionRecord:
    artifact = record.artifact
    projected_artifact = None
    if artifact is not None:
        projected_artifact = ProgramArtifact(
            reference=artifact.reference,
            local_path=artifact.local_path if include_local_paths else None,
        )
    return ToolExecutionRecord(
        sequence=record.sequence,
        tool=_safe_text(record.tool, secret_values),
        status=record.status,
        block=_safe_text(record.block, secret_values) if record.block is not None else None,
        artifact=projected_artifact,
        iteration=record.iteration,
        role=record.role,
        attempt=record.attempt,
    )


def public_execution_evidence(
    evidence: ExecutionEvidence,
    *,
    secret_values: Iterable[str] = (),
    include_local_paths: bool = False,
) -> ExecutionEvidence:
    """Return a stable, bounded projection safe for CLI/HTTP output."""
    secrets = tuple(secret_values)
    projected = tuple(
        _project_record(
            record,
            secret_values=secrets,
            include_local_paths=include_local_paths,
        )
        for record in evidence.records
    )
    omitted = evidence.omitted_count + max(0, len(projected) - MAX_PUBLIC_EVIDENCE_RECORDS)
    return ExecutionEvidence(
        records=projected[:MAX_PUBLIC_EVIDENCE_RECORDS],
        truncated=evidence.truncated or omitted > 0,
        omitted_count=omitted,
    )


def _origin_key(record: ToolExecutionRecord) -> tuple[object, ...]:
    return (record.iteration, record.role, record.attempt, record.sequence)


def _cumulative_role_key(record: ToolExecutionRecord) -> tuple[object, ...] | None:
    if record.role is None or record.attempt is None:
        return None
    return (record.role, record.attempt, record.sequence)


def merge_execution_evidence(
    current: ExecutionEvidence,
    incoming: ExecutionEvidence,
    *,
    iteration: int | None = None,
    role: EvidenceRole | None = None,
    attempt: int | None = None,
    dedupe_cumulative_roles: bool = False,
) -> ExecutionEvidence:
    """Merge evidence in order, optionally adding a collaboration origin."""
    if (role is None) != (attempt is None):
        raise ValueError("role and attempt must be supplied together")

    existing_origin_keys = {_origin_key(record) for record in current.records}
    existing_cumulative_keys = {
        key for record in current.records if (key := _cumulative_role_key(record)) is not None
    }
    records = list(current.records)
    omitted = current.omitted_count + incoming.omitted_count
    for original in incoming.records:
        record = original
        if role is not None or iteration is not None:
            record = ToolExecutionRecord(
                sequence=record.sequence,
                tool=record.tool,
                status=record.status,
                block=record.block,
                artifact=record.artifact,
                iteration=iteration if iteration is not None else record.iteration,
                role=role if role is not None else record.role,
                attempt=attempt if attempt is not None else record.attempt,
            )
        if dedupe_cumulative_roles:
            cumulative_key = _cumulative_role_key(record)
            if cumulative_key is not None and cumulative_key in existing_cumulative_keys:
                continue
            if cumulative_key is not None:
                existing_cumulative_keys.add(cumulative_key)
        origin_key = _origin_key(record)
        if origin_key in existing_origin_keys:
            continue
        existing_origin_keys.add(origin_key)
        records.append(record)

    if len(records) > MAX_PUBLIC_EVIDENCE_RECORDS:
        omitted += len(records) - MAX_PUBLIC_EVIDENCE_RECORDS
        records = records[:MAX_PUBLIC_EVIDENCE_RECORDS]
    return ExecutionEvidence(
        records=tuple(records),
        truncated=current.truncated or incoming.truncated or omitted > 0,
        omitted_count=omitted,
    )
