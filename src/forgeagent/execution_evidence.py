"""Bounded, safe evidence for tools attempted during a ForgeAgent task.

This module is deliberately independent from task, loop, and collaboration runtime
objects.  It is the shared wire model used by those layers and therefore keeps all
public data small, deterministic, and free of host-local paths.
"""

from __future__ import annotations

import os
import re
import stat
import threading
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .secret_policy import mask_audit_data, sensitive_env_values

EvidenceStatus = Literal["succeeded", "failed", "artifact_persistence_failed"]
EvidenceRole = Literal["planner", "generator", "evaluator"]

MAX_INTERNAL_EVIDENCE_RECORDS = 128
MAX_PUBLIC_EVIDENCE_RECORDS = 32
MAX_EVIDENCE_LABEL_CHARS = 128
MAX_ARTIFACT_REFERENCE_CHARS = 512
MAX_PROGRAMS_PER_TASK = 100
MAX_PROGRAM_BYTES = 1024 * 1024
MAX_PROGRAM_TOTAL_BYTES = 8 * 1024 * 1024

_REFERENCE_RE = re.compile(
    r"^execution-artifacts/[0-9a-f]{32}/programs/[0-9]{4}-[a-z0-9-]{1,64}\.py$"
)
_PROGRAM_LABEL_RE = re.compile(r"[^a-z0-9]+")


class ProgramArtifactPersistenceError(Exception):
    """Stable public failure for program artifact persistence."""

    def __init__(self) -> None:
        super().__init__("program artifact persistence failed")


def _program_label(value: str) -> str:
    masked = mask_audit_data(value, sensitive_env_values())
    if not isinstance(masked, str):
        masked = "program"
    label = _PROGRAM_LABEL_RE.sub("-", masked.casefold()).strip("-")
    return (label or "program")[:64]


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


class ProgramArtifactStore:
    """Persist generated Python programs below one task-owned artifact root."""

    def __init__(self, project_root: str | Path, *, execution_id: str | None = None) -> None:
        try:
            self._project_root = Path(project_root).resolve(strict=True)
        except OSError as exc:
            raise ProgramArtifactPersistenceError from exc
        if not self._project_root.is_dir():
            raise ProgramArtifactPersistenceError
        try:
            self._execution_id = UUID(execution_id).hex if execution_id is not None else uuid4().hex
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("execution_id must be a UUID") from exc
        self._lock = threading.Lock()
        self._programs_fd: int | None = None
        self._directory_identities: tuple[tuple[int, int], ...] = ()
        self._count = 0
        self._total_bytes = 0

    @property
    def _programs_path(self) -> Path:
        return (
            self._project_root
            / ".forgeagent"
            / "execution-artifacts"
            / self._execution_id
            / "programs"
        )

    def _open_programs(self) -> int:
        if self._programs_fd is not None:
            return self._programs_fd
        fds: list[int] = []
        try:
            root_fd = os.open(
                self._project_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            fds = [root_fd]
            identities = [os.fstat(root_fd)]
            for index, part in enumerate(
                (".forgeagent", "execution-artifacts", self._execution_id, "programs")
            ):
                created = False
                try:
                    os.mkdir(part, 0o700, dir_fd=fds[-1])
                    created = True
                except FileExistsError:
                    pass
                fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fds[-1],
                )
                if created and index > 0:
                    os.fchmod(fd, 0o700)
                elif index > 0 and stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                    os.close(fd)
                    raise OSError("artifact directory is not private")
                fds.append(fd)
                identities.append(os.fstat(fd))
            for fd in fds[:-1]:
                os.close(fd)
            self._programs_fd = fds[-1]
            self._directory_identities = tuple((item.st_dev, item.st_ino) for item in identities)
            return self._programs_fd
        except (OSError, ValueError) as exc:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise ProgramArtifactPersistenceError from exc

    def _directories_unchanged(self, programs_fd: int) -> bool:
        fds: list[int] = []
        try:
            root_fd = os.open(
                self._project_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            fds = [root_fd]
            identities = [(item.st_dev, item.st_ino) for item in [os.fstat(root_fd)]]
            for index, part in enumerate(
                (".forgeagent", "execution-artifacts", self._execution_id, "programs")
            ):
                fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fds[-1],
                )
                fds.append(fd)
                info = os.fstat(fd)
                identities.append((info.st_dev, info.st_ino))
                if index > 0 and stat.S_IMODE(info.st_mode) != 0o700:
                    return False
            held = os.fstat(programs_fd)
            return tuple(identities) == self._directory_identities and identities[-1] == (
                held.st_dev,
                held.st_ino,
            )
        except OSError:
            return False
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def persist(self, *, block_name: str, language: str, code: str) -> ProgramArtifact:
        del language
        try:
            payload = code.encode("utf-8")
        except (UnicodeError, AttributeError) as exc:
            raise ProgramArtifactPersistenceError from exc
        with self._lock:
            if len(payload) > MAX_PROGRAM_BYTES:
                raise ProgramArtifactPersistenceError
            if (
                self._count >= MAX_PROGRAMS_PER_TASK
                or self._total_bytes + len(payload) > MAX_PROGRAM_TOTAL_BYTES
            ):
                raise ProgramArtifactPersistenceError
            programs_fd = self._open_programs()
            if not self._directories_unchanged(programs_fd):
                raise ProgramArtifactPersistenceError
            sequence = self._count + 1
            label = _program_label(block_name)
            final_name = f"{sequence:04d}-{label}.py"
            temp_name = f".tmp-{uuid4().hex}"
            temp_fd: int | None = None
            published = False
            try:
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=programs_fd,
                )
                view = memoryview(payload)
                while view:
                    written = os.write(temp_fd, view)
                    if written <= 0:
                        raise OSError("short write")
                    view = view[written:]
                os.fchmod(temp_fd, 0o600)
                os.fsync(temp_fd)
                temp_stat = os.fstat(temp_fd)
                if not stat.S_ISREG(temp_stat.st_mode) or temp_stat.st_size != len(payload):
                    raise OSError("invalid artifact")
                if not self._directories_unchanged(programs_fd):
                    raise OSError("directory changed")
                os.replace(temp_name, final_name, src_dir_fd=programs_fd, dst_dir_fd=programs_fd)
                published = True
                os.fsync(programs_fd)
                if not self._directories_unchanged(programs_fd):
                    raise OSError("directory changed")
                final_stat = os.stat(final_name, dir_fd=programs_fd, follow_symlinks=False)
                if (temp_stat.st_dev, temp_stat.st_ino) != (final_stat.st_dev, final_stat.st_ino):
                    raise OSError("published artifact mismatch")
                local_path = self._programs_path / final_name
                self._count += 1
                self._total_bytes += len(payload)
                return ProgramArtifact(
                    reference=f"execution-artifacts/{self._execution_id}/programs/{final_name}",
                    local_path=local_path,
                )
            except BaseException as exc:
                try:
                    os.unlink(temp_name, dir_fd=programs_fd)
                except OSError:
                    pass
                if published:
                    try:
                        os.unlink(final_name, dir_fd=programs_fd)
                    except OSError:
                        pass
                if isinstance(exc, KeyboardInterrupt | SystemExit):
                    raise
                if isinstance(exc, OSError | ValueError | UnicodeError):
                    raise ProgramArtifactPersistenceError from exc
                raise
            finally:
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except OSError:
                        pass

    def close(self) -> None:
        with self._lock:
            if self._programs_fd is not None:
                os.close(self._programs_fd)
                self._programs_fd = None


def resolve_local_artifact_path(project_root: str | Path, reference: str) -> Path | None:
    fds: list[int] = []
    file_fd: int | None = None
    try:
        parsed = ProgramArtifact(reference=reference)
        root = Path(project_root).resolve(strict=True)
        parts = (
            ".forgeagent",
            "execution-artifacts",
            parsed.reference.split("/")[1],
            "programs",
        )
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds = [root_fd]
        identities = [(os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino)]
        for part in parts:
            fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=fds[-1],
            )
            fds.append(fd)
            info = os.fstat(fd)
            identities.append((info.st_dev, info.st_ino))
        filename = parsed.reference.rsplit("/", 1)[1]
        file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fds[-1])
        file_info = os.fstat(file_fd)
        if not stat.S_ISREG(file_info.st_mode):
            return None
        check_fds = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        try:
            check_identities = [(os.fstat(check_fds[0]).st_dev, os.fstat(check_fds[0]).st_ino)]
            for part in parts:
                fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=check_fds[-1],
                )
                check_fds.append(fd)
                info = os.fstat(fd)
                check_identities.append((info.st_dev, info.st_ino))
            current_file = os.stat(filename, dir_fd=check_fds[-1], follow_symlinks=False)
            if tuple(check_identities) != tuple(identities) or (
                current_file.st_dev,
                current_file.st_ino,
            ) != (file_info.st_dev, file_info.st_ino):
                return None
        finally:
            for fd in check_fds:
                os.close(fd)
        return root / ".forgeagent" / "execution-artifacts" / parts[2] / "programs" / filename
    except (OSError, ValueError):
        return None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for fd in fds:
            os.close(fd)


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
