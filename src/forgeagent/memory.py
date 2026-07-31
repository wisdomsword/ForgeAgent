"""Small, deterministic runtime memory store for facts and preferences."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias

from .audit import AuditEvent, AuditSink, emit_audit
from .protocol import MemoryCandidate
from .secret_policy import mask_secrets, sensitive_env_values

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_LINE = re.compile(r"^- ([a-z0-9][a-z0-9._-]{0,79}): ([^\r\n]{1,512})$")
_MAX_ENTRIES = 64
_MAX_RENDER_BYTES = 32 * 1024
_MAX_STORAGE_BYTES = 64 * 1024
_V1_HEADER = "<!-- forgeagent-memory-v1 -->"
_V2_HEADER_PREFIX = "<!-- forgeagent-memory-v2: "
_META_PREFIX = "<!-- forgeagent-memory-meta: "
_COMMENT_SUFFIX = " -->"
_OPAQUE_ID = re.compile(r"^[0-9a-f]{32}$")
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_KINDS = frozenset({"fact", "preference", "decision"})
_WHY = frozenset({"cross_task_fact", "cross_task_preference", "cross_task_decision"})
_SOURCES = frozenset({"host_api", "model_candidate", "user_command", "legacy_manifest"})
_WRITERS = frozenset({"host_api", "task_host", "interactive_host", "unknown"})
_TRUTH_SOURCES = frozenset(
    {"host_assertion", "model_output_unverified", "user_statement", "unknown"}
)
_REVALIDATE_ON = frozenset({"conflict_or_explicit_review", "source_change", "explicit_review"})
_WHY_BY_KIND = {
    "fact": "cross_task_fact",
    "preference": "cross_task_preference",
    "decision": "cross_task_decision",
}
_SOURCE_PROJECTION = {
    "host_api": ("host_api", "host_assertion"),
    "model_candidate": ("task_host", "model_output_unverified"),
    "user_command": ("interactive_host", "user_statement"),
}
_GOVERNANCE_FIELDS = frozenset(
    {
        "why_remember",
        "source",
        "writer",
        "who_can_write",
        "truth_source",
        "visibility",
        "written_at",
        "expires_at",
        "review_after",
        "revalidate_on",
        "recovery",
        "delete_or_correct",
    }
)
_METADATA_FIELDS = _GOVERNANCE_FIELDS | {"kind"}
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+)?(?:secret|api\s*key|token)", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"execute\s+(?:a\s+)?command", re.IGNORECASE),
)

MemoryWriteSource: TypeAlias = Literal["host_api", "model_candidate", "user_command"]
MemoryFormat: TypeAlias = Literal["none", "v1", "v2", "invalid"]


def _parse_timestamp(value: str) -> datetime:
    if _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError("invalid timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class MemoryGovernance:
    why_remember: str
    source: str
    writer: str
    who_can_write: str
    truth_source: str
    visibility: str
    written_at: str
    expires_at: str | None
    review_after: str | None
    revalidate_on: str
    recovery: str
    delete_or_correct: str


@dataclass(frozen=True)
class ProjectMemoryRecord:
    candidate: MemoryCandidate
    governance: MemoryGovernance | None


@dataclass(frozen=True)
class MemoryFileHeader:
    revision: str
    migration_id: str | None = None
    migration_revision: str | None = None


@dataclass(frozen=True)
class MemoryReadiness:
    status: Literal[
        "no_data",
        "legacy_needs_metadata",
        "legacy_ready",
        "current",
        "repair_required",
        "unsafe",
    ]
    format_version: Literal["none", "v1", "v2", "unknown"]
    entry_count: int
    reason: str


@dataclass(frozen=True)
class MemoryOperationResult:
    status: Literal[
        "migrated",
        "not_required",
        "rejected",
        "persistence_error",
        "recovery_failed",
        "verified",
        "not_current",
        "repair_required",
        "unsafe",
        "rolled_back",
        "rollback_conflict",
        "backup_unavailable",
    ]
    entry_count: int
    reason: str
    migration_id: str | None = None


@dataclass(frozen=True)
class _ProjectSnapshot:
    format_version: MemoryFormat
    entries: dict[str, ProjectMemoryRecord]
    header: MemoryFileHeader | None
    raw: bytes | None
    reason: str = ""


@dataclass(frozen=True)
class MemoryResult:
    status: Literal["accepted", "replaced", "rejected", "persistence_error", "disabled"]
    scope: str
    kind: str
    key: str
    reason: str = ""


class MemoryManager:
    """Own session facts and a bounded, atomically persisted project fact file."""

    def __init__(
        self,
        allowed_root: str,
        *,
        audit_sink: AuditSink | None = None,
        enabled: bool = True,
        allow_project: bool = True,
        diagnostic: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(allowed_root).resolve()
        self._path = self._root / ".forgeagent" / "MEMORY.md"
        self._audit_sink = audit_sink
        self._diagnostic = diagnostic
        self._enabled = enabled
        self._allow_project = allow_project
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session: dict[str, MemoryCandidate] = {}
        self._project: dict[str, MemoryCandidate] = {}
        self._project_records: dict[str, ProjectMemoryRecord] = {}
        self._project_format: MemoryFormat = "none"
        self._header: MemoryFileHeader | None = None
        self._lifecycle_notices: set[tuple[str, str, str]] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def readiness(self, manifest: Mapping[str, object] | None = None) -> MemoryReadiness:
        """Inspect project Memory without creating files or exposing stored values."""
        try:
            snapshot = self._read_snapshot(canonical_v1=True)
        except OSError:
            return MemoryReadiness("unsafe", "unknown", 0, "storage_path")
        if snapshot.format_version == "none":
            return MemoryReadiness("no_data", "none", 0, "memory_absent")
        if snapshot.format_version == "invalid":
            return MemoryReadiness(
                "repair_required",
                "unknown",
                len(snapshot.entries),
                snapshot.reason or "invalid_format",
            )
        if snapshot.format_version == "v2":
            return MemoryReadiness("current", "v2", len(snapshot.entries), "valid_v2")
        records, reason = self._validate_manifest(snapshot, manifest)
        if records is None:
            return MemoryReadiness("legacy_needs_metadata", "v1", len(snapshot.entries), reason)
        return MemoryReadiness("legacy_ready", "v1", len(records), "manifest_valid")

    def load(self) -> None:
        if not self._enabled or not self._allow_project:
            self._project = {}
            self._project_records = {}
            self._project_format = "none"
            self._header = None
            return
        try:
            snapshot = self._read_snapshot(diagnose=True)
        except OSError:
            self._diagnose("memory file ignored: unsafe path")
            self._project = {}
            self._project_records = {}
            self._project_format = "invalid"
            self._header = None
            return
        if snapshot.format_version == "none":
            self._project = {}
            self._project_records = {}
            self._project_format = "none"
            self._header = None
            return
        if snapshot.format_version == "invalid":
            self._diagnose(f"memory file ignored: {snapshot.reason or 'invalid_format'}")
            self._project = {}
            self._project_records = {}
            self._project_format = "invalid"
            self._header = None
            return
        self._install_snapshot(snapshot)

    def disable(self) -> None:
        if self._enabled:
            self._enabled = False
            self._session.clear()
            self._project.clear()
            self._audit("disabled", "", "", "", "memory_disabled")

    def clear_project(self) -> None:
        """Drop project entries when identity trust no longer permits them."""
        self._project.clear()
        self._project_records.clear()

    def set_project_access(self, allowed: bool) -> None:
        self._allow_project = allowed
        if not allowed:
            self._project.clear()
            self._project_records.clear()

    def copy_session_from(self, source: MemoryManager) -> None:
        """Preserve session-scoped facts while replacing project-backed state."""
        if self._enabled and source._enabled:
            self._session = dict(source._session)

    def apply(
        self,
        candidate: MemoryCandidate,
        task_id: str | None = None,
        *,
        source: MemoryWriteSource = "host_api",
    ) -> MemoryResult:
        if not self._enabled:
            return self._result(candidate, "disabled", "memory_disabled", task_id)
        if candidate.scope == "project" and not self._allow_project:
            return self._result(candidate, "rejected", "project_memory_untrusted", task_id)
        reason = self._admission_reason(candidate)
        if reason is not None:
            return self._result(candidate, "rejected", reason, task_id)
        if source not in _SOURCE_PROJECTION:
            return self._result(candidate, "rejected", "invalid_source", task_id)
        if candidate.scope == "project":
            try:
                governance = self._governance_for_write(candidate, source)
            except (TypeError, ValueError):
                return self._result(candidate, "persistence_error", "invalid_clock", task_id)
            try:
                with self._project_lock():
                    snapshot = self._read_snapshot(canonical_v1=True)
                    if snapshot.format_version == "v1":
                        return self._result(candidate, "rejected", "migration_required", task_id)
                    if snapshot.format_version == "invalid":
                        return self._result(
                            candidate, "persistence_error", "project_read_failed", task_id
                        )
                    records = dict(snapshot.entries)
                    replaced = candidate.key in records
                    if not replaced and len(records) >= _MAX_ENTRIES:
                        return self._result(candidate, "rejected", "memory_limit", task_id)
                    records[candidate.key] = ProjectMemoryRecord(candidate, governance)
                    new_project = {key: record.candidate for key, record in records.items()}
                    rendered_size = len(
                        self._render_memory(self._session, new_project).encode("utf-8")
                    )
                    if rendered_size > _MAX_RENDER_BYTES:
                        return self._result(candidate, "rejected", "memory_limit", task_id)
                    previous_header = snapshot.header
                    header = MemoryFileHeader(
                        revision=secrets.token_hex(16),
                        migration_id=(
                            previous_header.migration_id if previous_header is not None else None
                        ),
                        migration_revision=(
                            previous_header.migration_revision
                            if previous_header is not None
                            else None
                        ),
                    )
                    try:
                        raw = self._serialize_v2(records, header)
                    except ValueError:
                        return self._result(candidate, "rejected", "memory_limit", task_id)
                    self._atomic_write_bytes(raw)
                    persisted = self._read_snapshot(canonical_v1=True)
                    if (
                        persisted.format_version != "v2"
                        or persisted.header != header
                        or set(persisted.entries) != set(records)
                    ):
                        raise OSError("project memory write verification failed")
            except OSError:
                return self._result(candidate, "persistence_error", "project_write_failed", task_id)
            self._install_snapshot(persisted)
            status: Literal["accepted", "replaced"] = "replaced" if replaced else "accepted"
            return self._result(candidate, status, "", task_id)

        target = self._session
        replaced = candidate.key in target
        if not replaced and len(target) >= _MAX_ENTRIES:
            return self._result(candidate, "rejected", "memory_limit", task_id)
        new_session = dict(target)
        new_session[candidate.key] = candidate
        rendered_size = len(self._render_memory(new_session, self._project).encode("utf-8"))
        if rendered_size > _MAX_RENDER_BYTES:
            return self._result(candidate, "rejected", "memory_limit", task_id)
        self._session = new_session
        status: Literal["accepted", "replaced"] = "replaced" if replaced else "accepted"
        return self._result(candidate, status, "", task_id)

    def render(self) -> str:
        if not self._enabled:
            return ""
        try:
            project = self._active_project(emit_notices=True)
        except (TypeError, ValueError):
            revision = self._header.revision if self._header is not None else "legacy"
            notice = (revision, "", "invalid_time")
            if notice not in self._lifecycle_notices:
                self._lifecycle_notices.add(notice)
                self._diagnose("memory record inactive: invalid_time")
                self._audit("invalid_time", "project", "", "", "invalid_time")
            project = {}
        return self._render_memory(self._session, project)

    def correct_project(
        self,
        candidate: MemoryCandidate,
        governance: MemoryGovernance,
        *,
        task_id: str | None = None,
    ) -> MemoryResult:
        if not self._enabled:
            return self._result(candidate, "disabled", "memory_disabled", task_id)
        if not self._allow_project:
            return self._result(candidate, "rejected", "project_memory_untrusted", task_id)
        if candidate.scope != "project":
            return self._result(candidate, "rejected", "invalid_scope", task_id)
        reason = self._admission_reason(candidate)
        if reason is not None:
            return self._result(candidate, "rejected", reason, task_id)
        try:
            validated = self._parse_governance(asdict(governance))
        except (TypeError, ValueError):
            return self._result(candidate, "rejected", "invalid_metadata", task_id)

        def replace_record(
            records: dict[str, ProjectMemoryRecord],
            _current: ProjectMemoryRecord,
        ) -> None:
            records[candidate.key] = ProjectMemoryRecord(candidate, validated)

        return self._mutate_current_v2(
            candidate.key,
            success_status="replaced",
            event_status="replaced",
            task_id=task_id,
            mutate=replace_record,
        )

    def delete_project(self, key: str, *, task_id: str | None = None) -> MemoryResult:
        if not _KEY.fullmatch(key):
            return self._key_result(key, "rejected", "invalid_key", task_id=task_id)

        def delete_record(
            records: dict[str, ProjectMemoryRecord],
            _current: ProjectMemoryRecord,
        ) -> None:
            del records[key]

        return self._mutate_current_v2(
            key,
            success_status="accepted",
            event_status="deleted",
            task_id=task_id,
            mutate=delete_record,
        )

    def revalidate_project(
        self,
        key: str,
        *,
        review_after: str | None,
        expires_at: str | None,
        truth_source: str,
        task_id: str | None = None,
    ) -> MemoryResult:
        if not _KEY.fullmatch(key):
            return self._key_result(key, "rejected", "invalid_key", task_id=task_id)
        if truth_source not in {
            "host_assertion",
            "model_output_unverified",
            "user_statement",
        }:
            return self._key_result(key, "rejected", "invalid_truth_source", task_id=task_id)
        try:
            for value in (review_after, expires_at):
                if value is not None:
                    _parse_timestamp(value)
        except (TypeError, ValueError):
            return self._key_result(key, "rejected", "invalid_timestamp", task_id=task_id)

        def revalidate_record(
            records: dict[str, ProjectMemoryRecord],
            current: ProjectMemoryRecord,
        ) -> None:
            if current.governance is None:
                raise ValueError("missing governance")
            records[key] = ProjectMemoryRecord(
                current.candidate,
                replace(
                    current.governance,
                    review_after=review_after,
                    expires_at=expires_at,
                    truth_source=truth_source,
                ),
            )

        return self._mutate_current_v2(
            key,
            success_status="accepted",
            event_status="revalidated",
            task_id=task_id,
            mutate=revalidate_record,
        )

    def _render_memory(
        self,
        session: dict[str, MemoryCandidate],
        project: dict[str, MemoryCandidate],
    ) -> str:
        sections: list[str] = []
        if session:
            sections.append(self._render_section("Session memory", session))
        if project:
            sections.append(self._render_section("Project memory", project))
        rendered = "\n\n".join(sections)
        return rendered

    def _render_section(self, title: str, entries: dict[str, MemoryCandidate]) -> str:
        lines = [f"## {title}"]
        for key in sorted(entries):
            value = mask_secrets(entries[key].content, sensitive_env_values())
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _atomic_write_bytes(self, content: bytes) -> None:
        path = self._safe_storage_path(for_write=True)
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        path = self._safe_storage_path(for_write=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".MEMORY.", suffix=".tmp", dir=directory
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _parse_project_lines(
        self, lines: list[str], *, diagnose: bool
    ) -> dict[str, MemoryCandidate]:
        loaded: dict[str, MemoryCandidate] = {}
        for line in lines:
            match = _LINE.fullmatch(line)
            if match is None:
                if diagnose and line and not line.startswith("<!-- forgeagent-memory-v1 -->"):
                    self._diagnose("memory entry ignored: invalid format")
                continue
            key, content = match.groups()
            candidate = MemoryCandidate(scope="project", kind="fact", key=key, content=content)
            if self._admission_reason(candidate) is None and len(loaded) < _MAX_ENTRIES:
                loaded[key] = candidate
            elif diagnose and len(loaded) >= _MAX_ENTRIES:
                self._diagnose("memory entry ignored: memory_limit")
            elif diagnose:
                self._diagnose("memory entry ignored: invalid content")
        return loaded

    def _read_snapshot(
        self,
        *,
        canonical_v1: bool = False,
        diagnose: bool = False,
    ) -> _ProjectSnapshot:
        path = self._safe_storage_path()
        if path is None:
            return _ProjectSnapshot("none", {}, None, None)
        try:
            if path.stat().st_size > _MAX_STORAGE_BYTES:
                return _ProjectSnapshot("invalid", {}, None, None, "memory_limit")
            raw = path.read_bytes()
        except OSError:
            raise
        try:
            first_line = raw.decode("utf-8").splitlines()[0]
        except (UnicodeError, IndexError):
            return _ProjectSnapshot("invalid", {}, None, raw, "unreadable")
        if first_line == _V1_HEADER:
            return self._parse_v1(raw, canonical=canonical_v1, diagnose=diagnose)
        if first_line.startswith(_V2_HEADER_PREFIX):
            return self._parse_v2(raw)
        return _ProjectSnapshot("invalid", {}, None, raw, "invalid_header")

    def _parse_v1(
        self,
        raw: bytes,
        *,
        canonical: bool,
        diagnose: bool = False,
    ) -> _ProjectSnapshot:
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeError:
            return _ProjectSnapshot("invalid", {}, None, raw, "unreadable")
        if not lines or lines[0] != _V1_HEADER:
            return _ProjectSnapshot("invalid", {}, None, raw, "invalid_header")
        loaded: dict[str, ProjectMemoryRecord] = {}
        for line in lines[1:]:
            match = _LINE.fullmatch(line)
            if match is None:
                if not line:
                    continue
                if canonical:
                    return _ProjectSnapshot("invalid", loaded, None, raw, "invalid_format")
                if diagnose:
                    self._diagnose("memory entry ignored: invalid format")
                continue
            key, content = match.groups()
            if key in loaded:
                if canonical:
                    return _ProjectSnapshot("invalid", loaded, None, raw, "duplicate_key")
                loaded.pop(key)
            candidate = MemoryCandidate(scope="project", kind="fact", key=key, content=content)
            reason = self._admission_reason(candidate)
            if reason is not None:
                if canonical:
                    return _ProjectSnapshot("invalid", loaded, None, raw, "invalid_content")
                if diagnose:
                    self._diagnose("memory entry ignored: invalid content")
                continue
            if len(loaded) >= _MAX_ENTRIES:
                if canonical:
                    return _ProjectSnapshot("invalid", loaded, None, raw, "memory_limit")
                if diagnose:
                    self._diagnose("memory entry ignored: memory_limit")
                continue
            loaded[key] = ProjectMemoryRecord(candidate, None)
        return _ProjectSnapshot("v1", loaded, None, raw)

    def _parse_v2(self, raw: bytes) -> _ProjectSnapshot:
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeError:
            return _ProjectSnapshot("invalid", {}, None, raw, "unreadable")
        if not lines:
            return _ProjectSnapshot("invalid", {}, None, raw, "invalid_header")
        try:
            header_value = self._comment_json(lines[0], _V2_HEADER_PREFIX)
            if set(header_value) != {"revision", "migration_id", "migration_revision"}:
                raise ValueError("invalid header fields")
            revision = header_value["revision"]
            migration_id = header_value["migration_id"]
            migration_revision = header_value["migration_revision"]
            if not isinstance(revision, str) or _OPAQUE_ID.fullmatch(revision) is None:
                raise ValueError("invalid revision")
            if (migration_id is None) != (migration_revision is None):
                raise ValueError("incomplete migration header")
            for value in (migration_id, migration_revision):
                if value is not None and (
                    not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None
                ):
                    raise ValueError("invalid migration header")
            header = MemoryFileHeader(revision, migration_id, migration_revision)
        except (TypeError, ValueError):
            return _ProjectSnapshot("invalid", {}, None, raw, "invalid_header")

        body = lines[1:]
        if len(body) % 2:
            return _ProjectSnapshot("invalid", {}, header, raw, "unpaired_record")
        loaded: dict[str, ProjectMemoryRecord] = {}
        for index in range(0, len(body), 2):
            try:
                metadata = self._comment_json(body[index], _META_PREFIX)
                if set(metadata) != _METADATA_FIELDS:
                    raise ValueError("invalid metadata fields")
                kind = metadata["kind"]
                if not isinstance(kind, str) or kind not in _KINDS:
                    raise ValueError("invalid kind")
                governance = self._parse_governance(
                    {key: value for key, value in metadata.items() if key != "kind"}
                )
                if governance.why_remember != _WHY_BY_KIND[kind]:
                    raise ValueError("kind and purpose disagree")
            except (TypeError, ValueError):
                return _ProjectSnapshot("invalid", loaded, header, raw, "invalid_metadata")
            match = _LINE.fullmatch(body[index + 1])
            if match is None:
                return _ProjectSnapshot("invalid", loaded, header, raw, "invalid_format")
            key, content = match.groups()
            if key in loaded:
                return _ProjectSnapshot("invalid", loaded, header, raw, "duplicate_key")
            candidate = MemoryCandidate(scope="project", kind=kind, key=key, content=content)
            if self._admission_reason(candidate) is not None:
                return _ProjectSnapshot("invalid", loaded, header, raw, "invalid_content")
            if len(loaded) >= _MAX_ENTRIES:
                return _ProjectSnapshot("invalid", loaded, header, raw, "memory_limit")
            loaded[key] = ProjectMemoryRecord(candidate, governance)
        return _ProjectSnapshot("v2", loaded, header, raw)

    @staticmethod
    def _comment_json(line: str, prefix: str) -> dict[str, object]:
        if not line.startswith(prefix) or not line.endswith(_COMMENT_SUFFIX):
            raise ValueError("invalid comment")
        value = json.loads(line[len(prefix) : -len(_COMMENT_SUFFIX)])
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("comment must contain an object")
        return value

    @staticmethod
    def _parse_governance(value: Mapping[str, object]) -> MemoryGovernance:
        if set(value) != _GOVERNANCE_FIELDS:
            raise ValueError("invalid governance fields")
        string_fields = (
            "why_remember",
            "source",
            "writer",
            "who_can_write",
            "truth_source",
            "visibility",
            "written_at",
            "revalidate_on",
            "recovery",
            "delete_or_correct",
        )
        if any(not isinstance(value[field], str) for field in string_fields):
            raise ValueError("governance strings required")
        why_remember = str(value["why_remember"])
        source = str(value["source"])
        writer = str(value["writer"])
        truth_source = str(value["truth_source"])
        if why_remember not in _WHY or source not in _SOURCES:
            raise ValueError("invalid governance classification")
        if writer not in _WRITERS or truth_source not in _TRUTH_SOURCES:
            raise ValueError("invalid provenance")
        expected_projection = {
            "host_api": ("host_api", "host_assertion"),
            "model_candidate": ("task_host", "model_output_unverified"),
            "user_command": ("interactive_host", "user_statement"),
        }.get(source)
        if expected_projection is not None and (writer, truth_source) != expected_projection:
            raise ValueError("source projection mismatch")
        if value["who_can_write"] != "host_only" or value["visibility"] != "project":
            raise ValueError("invalid ownership")
        if value["revalidate_on"] not in _REVALIDATE_ON:
            raise ValueError("invalid revalidation policy")
        if value["recovery"] != "project_memory_file":
            raise ValueError("invalid recovery policy")
        if value["delete_or_correct"] != "host_replace_delete_or_revalidate":
            raise ValueError("invalid correction policy")
        written_at = str(value["written_at"])
        _parse_timestamp(written_at)
        dates: dict[str, str | None] = {}
        for field in ("expires_at", "review_after"):
            date_value = value[field]
            if date_value is not None and not isinstance(date_value, str):
                raise ValueError("invalid lifecycle date")
            if isinstance(date_value, str):
                _parse_timestamp(date_value)
            dates[field] = date_value
        if (
            source == "legacy_manifest"
            and truth_source == "unknown"
            and dates["review_after"] is None
        ):
            raise ValueError("unknown legacy truth requires review")
        return MemoryGovernance(
            why_remember=why_remember,
            source=source,
            writer=writer,
            who_can_write="host_only",
            truth_source=truth_source,
            visibility="project",
            written_at=written_at,
            expires_at=dates["expires_at"],
            review_after=dates["review_after"],
            revalidate_on=str(value["revalidate_on"]),
            recovery="project_memory_file",
            delete_or_correct="host_replace_delete_or_revalidate",
        )

    def _validate_manifest(
        self,
        snapshot: _ProjectSnapshot,
        manifest: Mapping[str, object] | None,
    ) -> tuple[dict[str, ProjectMemoryRecord] | None, str]:
        if manifest is None:
            return None, "manifest_required"
        if set(manifest) != set(snapshot.entries):
            return None, "manifest_key_mismatch"
        records: dict[str, ProjectMemoryRecord] = {}
        try:
            for key, raw_metadata in manifest.items():
                if not isinstance(raw_metadata, Mapping) or set(raw_metadata) != _METADATA_FIELDS:
                    raise ValueError("invalid manifest record")
                kind = raw_metadata["kind"]
                if not isinstance(kind, str) or kind not in _KINDS:
                    raise ValueError("invalid kind")
                governance = self._parse_governance(
                    {field: value for field, value in raw_metadata.items() if field != "kind"}
                )
                if governance.source != "legacy_manifest":
                    raise ValueError("invalid legacy source")
                if governance.why_remember != _WHY_BY_KIND[kind]:
                    raise ValueError("kind and purpose disagree")
                source_candidate = snapshot.entries[key].candidate
                candidate = MemoryCandidate(
                    scope="project",
                    kind=kind,
                    key=key,
                    content=source_candidate.content,
                )
                if self._admission_reason(candidate) is not None:
                    raise ValueError("invalid content")
                records[key] = ProjectMemoryRecord(candidate, governance)
        except (KeyError, TypeError, ValueError):
            return None, "manifest_invalid"
        return records, "manifest_valid"

    def _serialize_v2(
        self,
        entries: Mapping[str, ProjectMemoryRecord],
        header: MemoryFileHeader,
    ) -> bytes:
        header_payload = json.dumps(
            asdict(header), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        lines = [f"{_V2_HEADER_PREFIX}{header_payload}{_COMMENT_SUFFIX}"]
        for key in sorted(entries):
            record = entries[key]
            if record.governance is None:
                raise ValueError("v2 records require governance")
            metadata = {"kind": record.candidate.kind, **asdict(record.governance)}
            metadata_payload = json.dumps(
                metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            lines.append(f"{_META_PREFIX}{metadata_payload}{_COMMENT_SUFFIX}")
            lines.append(f"- {key}: {record.candidate.content}")
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        if len(raw) > _MAX_STORAGE_BYTES:
            raise ValueError("memory file exceeds storage limit")
        parsed = self._parse_v2(raw)
        if parsed.format_version != "v2" or set(parsed.entries) != set(entries):
            raise ValueError("serialized memory did not round trip")
        return raw

    def _install_snapshot(self, snapshot: _ProjectSnapshot) -> None:
        self._project_records = dict(snapshot.entries)
        self._project = {key: record.candidate for key, record in snapshot.entries.items()}
        self._project_format = snapshot.format_version
        self._header = snapshot.header
        self._lifecycle_notices.clear()

    def _inactive_reason(self, record: ProjectMemoryRecord) -> str | None:
        governance = record.governance
        if governance is None:
            return None
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return an aware datetime")
        now = now.astimezone(UTC)
        if governance.expires_at is not None and now >= _parse_timestamp(governance.expires_at):
            return "expired"
        if governance.review_after is not None and now >= _parse_timestamp(governance.review_after):
            return "review_due"
        return None

    def _active_project(self, *, emit_notices: bool) -> dict[str, MemoryCandidate]:
        active: dict[str, MemoryCandidate] = {}
        revision = self._header.revision if self._header is not None else "legacy"
        for key, record in self._project_records.items():
            reason = self._inactive_reason(record)
            if reason is None:
                active[key] = record.candidate
                continue
            if not emit_notices:
                continue
            notice = (revision, key, reason)
            if notice not in self._lifecycle_notices:
                self._lifecycle_notices.add(notice)
                self._diagnose(f"memory record inactive: {reason}")
                self._audit(reason, "project", record.candidate.kind, key, reason)
        return active

    def _mutate_current_v2(
        self,
        key: str,
        *,
        success_status: Literal["accepted", "replaced"],
        event_status: str,
        task_id: str | None,
        mutate: Callable[[dict[str, ProjectMemoryRecord], ProjectMemoryRecord], None],
    ) -> MemoryResult:
        if not self._enabled:
            return self._key_result(key, "disabled", "memory_disabled", task_id=task_id)
        if not self._allow_project:
            return self._key_result(key, "rejected", "project_memory_untrusted", task_id=task_id)
        try:
            with self._project_lock():
                snapshot = self._read_snapshot(canonical_v1=True)
                if snapshot.format_version == "v1":
                    return self._key_result(key, "rejected", "migration_required", task_id=task_id)
                if snapshot.format_version == "none":
                    return self._key_result(key, "rejected", "not_found", task_id=task_id)
                if snapshot.format_version != "v2" or snapshot.header is None:
                    return self._key_result(
                        key,
                        "persistence_error",
                        "project_read_failed",
                        task_id=task_id,
                    )
                current = snapshot.entries.get(key)
                if current is None:
                    return self._key_result(key, "rejected", "not_found", task_id=task_id)
                records = dict(snapshot.entries)
                try:
                    mutate(records, current)
                except ValueError:
                    return self._key_result(key, "rejected", "invalid_metadata", task_id=task_id)
                try:
                    active = self._active_candidates(records)
                except (TypeError, ValueError):
                    return self._key_result(
                        key,
                        "persistence_error",
                        "invalid_clock",
                        task_id=task_id,
                    )
                if (
                    len(self._render_memory(self._session, active).encode("utf-8"))
                    > _MAX_RENDER_BYTES
                ):
                    return self._key_result(key, "rejected", "memory_limit", task_id=task_id)
                header = replace(snapshot.header, revision=secrets.token_hex(16))
                try:
                    raw = self._serialize_v2(records, header)
                except ValueError:
                    return self._key_result(key, "rejected", "memory_limit", task_id=task_id)
                self._atomic_write_bytes(raw)
                persisted = self._read_snapshot(canonical_v1=True)
                if (
                    persisted.format_version != "v2"
                    or persisted.header != header
                    or persisted.entries != records
                ):
                    raise OSError("project memory write verification failed")
        except OSError:
            return self._key_result(
                key, "persistence_error", "project_write_failed", task_id=task_id
            )
        self._install_snapshot(persisted)
        record = current if event_status == "deleted" else persisted.entries[key]
        return self._key_result(
            key,
            success_status,
            "",
            kind=record.candidate.kind,
            task_id=task_id,
            event_status=event_status,
            revision=header.revision,
        )

    def _active_candidates(
        self, records: Mapping[str, ProjectMemoryRecord]
    ) -> dict[str, MemoryCandidate]:
        return {
            key: record.candidate
            for key, record in records.items()
            if self._inactive_reason(record) is None
        }

    def _governance_for_write(
        self,
        candidate: MemoryCandidate,
        source: MemoryWriteSource,
    ) -> MemoryGovernance:
        projection = _SOURCE_PROJECTION.get(source)
        if projection is None:
            raise ValueError("invalid memory write source")
        writer, truth_source = projection
        return MemoryGovernance(
            why_remember=_WHY_BY_KIND[candidate.kind],
            source=source,
            writer=writer,
            who_can_write="host_only",
            truth_source=truth_source,
            visibility="project",
            written_at=_format_timestamp(self._clock()),
            expires_at=None,
            review_after=None,
            revalidate_on="conflict_or_explicit_review",
            recovery="project_memory_file",
            delete_or_correct="host_replace_delete_or_revalidate",
        )

    @contextmanager
    def _project_lock(self) -> Iterator[None]:
        if fcntl is None:
            raise OSError("project memory locking is unavailable")
        path = self._safe_storage_path(for_write=True)
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        path = self._safe_storage_path(for_write=True)
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise OSError("safe memory lock is unavailable")
        descriptor = os.open(
            path.parent / ".MEMORY.lock",
            os.O_RDWR | os.O_CREAT | no_follow | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        locked = False
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("memory lock is not regular")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            yield
        finally:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)

    def _admission_reason(self, candidate: MemoryCandidate) -> str | None:
        if not _KEY.fullmatch(candidate.key):
            return "invalid_key"
        if candidate.kind == "procedure":
            return "procedure_requires_Skill"
        if len(candidate.content.encode("utf-8")) > 512:
            return "content_too_long"
        if any(ord(char) < 32 or ord(char) == 127 for char in candidate.content):
            return "control_character"
        if mask_secrets(candidate.content, sensitive_env_values()) != candidate.content:
            return "secret_detected"
        if any(pattern.search(candidate.content) for pattern in _INJECTION_PATTERNS):
            return "prompt_injection"
        return None

    def _safe_storage_path(self, *, for_write: bool = False) -> Path | None:
        directory = self._path.parent
        if os.path.lexists(directory) and stat.S_ISLNK(os.lstat(directory).st_mode):
            raise OSError("memory directory cannot be a symlink")
        if directory.exists() and not directory.is_dir():
            raise OSError("memory directory is not a directory")
        resolved_directory = Path(os.path.realpath(directory))
        try:
            if os.path.commonpath((str(self._root), str(resolved_directory))) != str(self._root):
                raise OSError("memory directory is outside project root")
        except ValueError as exc:
            raise OSError("memory directory is outside project root") from exc
        candidate = directory / self._path.name
        if candidate.exists() or os.path.lexists(candidate):
            if stat.S_ISLNK(os.lstat(candidate).st_mode):
                raise OSError("memory file cannot be a symlink")
            if not candidate.is_file():
                raise OSError("memory file is not regular")
            resolved = Path(os.path.realpath(candidate))
            try:
                if os.path.commonpath((str(self._root), str(resolved))) != str(self._root):
                    raise OSError("memory file is outside project root")
            except ValueError as exc:
                raise OSError("memory file is outside project root") from exc
            return resolved
        if for_write:
            return resolved_directory / self._path.name
        return None

    def _diagnose(self, message: str) -> None:
        if self._diagnostic is not None:
            self._diagnostic(message)

    def _result(
        self,
        candidate: MemoryCandidate,
        status: Literal["accepted", "replaced", "rejected", "persistence_error", "disabled"],
        reason: str,
        task_id: str | None,
    ) -> MemoryResult:
        self._audit(status, candidate.scope, candidate.kind, candidate.key, reason, task_id)
        return MemoryResult(status, candidate.scope, candidate.kind, candidate.key, reason)

    def _key_result(
        self,
        key: str,
        status: Literal["accepted", "replaced", "rejected", "persistence_error", "disabled"],
        reason: str,
        *,
        kind: str = "",
        task_id: str | None = None,
        event_status: str | None = None,
        revision: str | None = None,
    ) -> MemoryResult:
        self._audit(
            event_status or status,
            "project",
            kind,
            key,
            reason,
            task_id,
            revision=revision,
        )
        return MemoryResult(status, "project", kind, key[:80], reason)

    def _audit(
        self,
        status: str,
        scope: str,
        kind: str,
        key: str,
        reason: str,
        task_id: str | None = None,
        *,
        revision: str | None = None,
    ) -> None:
        parameters = {
            "scope": scope,
            "kind": kind,
            "key": key[:80],
            "reason": reason[:80],
        }
        if revision is not None:
            parameters["revision"] = revision
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type=f"memory.{status}",
                task_id=task_id,
                parameters=parameters,
                result_status=status,
            ),
        )
