"""Small, deterministic runtime memory store for facts and preferences."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .audit import AuditEvent, AuditSink, emit_audit
from .protocol import MemoryCandidate
from .secret_policy import mask_secrets, sensitive_env_values

_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_LINE = re.compile(r"^- ([a-z0-9][a-z0-9._-]{0,79}): ([^\r\n]{1,512})$")
_MAX_ENTRIES = 64
_MAX_RENDER_BYTES = 32 * 1024
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+)?(?:secret|api\s*key|token)", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"execute\s+(?:a\s+)?command", re.IGNORECASE),
)


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
    ) -> None:
        self._root = Path(allowed_root).resolve()
        self._path = self._root / ".forgeagent" / "MEMORY.md"
        self._audit_sink = audit_sink
        self._diagnostic = diagnostic
        self._enabled = enabled
        self._allow_project = allow_project
        self._session: dict[str, MemoryCandidate] = {}
        self._project: dict[str, MemoryCandidate] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def load(self) -> None:
        if not self._enabled or not self._allow_project:
            self._project = {}
            return
        try:
            path = self._safe_storage_path()
        except OSError:
            self._diagnose("memory file ignored: unsafe path")
            self._project = {}
            return
        if path is None:
            self._project = {}
            return
        try:
            if path.stat().st_size > _MAX_RENDER_BYTES:
                self._diagnose("memory file ignored: memory_limit")
                self._project = {}
                return
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            self._diagnose("memory file ignored: unreadable")
            self._project = {}
            return
        loaded: dict[str, MemoryCandidate] = {}
        for line in lines:
            match = _LINE.fullmatch(line)
            if match is None:
                if line and not line.startswith("<!-- forgeagent-memory-v1 -->"):
                    self._diagnose("memory entry ignored: invalid format")
                continue
            key, content = match.groups()
            candidate = MemoryCandidate(scope="project", kind="fact", key=key, content=content)
            if self._admission_reason(candidate) is None and len(loaded) < _MAX_ENTRIES:
                loaded[key] = candidate
            elif len(loaded) >= _MAX_ENTRIES:
                self._diagnose("memory entry ignored: memory_limit")
            else:
                self._diagnose("memory entry ignored: invalid content")
        self._project = loaded

    def disable(self) -> None:
        if self._enabled:
            self._enabled = False
            self._session.clear()
            self._project.clear()
            self._audit("disabled", "", "", "", "memory_disabled")

    def clear_project(self) -> None:
        """Drop project entries when identity trust no longer permits them."""
        self._project.clear()

    def set_project_access(self, allowed: bool) -> None:
        self._allow_project = allowed
        if not allowed:
            self._project.clear()

    def apply(self, candidate: MemoryCandidate, task_id: str | None = None) -> MemoryResult:
        if not self._enabled:
            return self._result(candidate, "disabled", "memory_disabled", task_id)
        if candidate.scope == "project" and not self._allow_project:
            return self._result(candidate, "rejected", "project_memory_untrusted", task_id)
        reason = self._admission_reason(candidate)
        if reason is not None:
            return self._result(candidate, "rejected", reason, task_id)
        target = self._session if candidate.scope == "session" else self._project
        replaced = candidate.key in target
        if not replaced and len(target) >= _MAX_ENTRIES:
            return self._result(candidate, "rejected", "memory_limit", task_id)
        if candidate.scope == "project":
            new_project = dict(target)
            new_project[candidate.key] = candidate
            rendered_size = len(self._render_memory(self._session, new_project).encode("utf-8"))
            if rendered_size > _MAX_RENDER_BYTES:
                return self._result(candidate, "rejected", "memory_limit", task_id)
            try:
                self._write_project(new_project)
            except OSError:
                return self._result(candidate, "persistence_error", "project_write_failed", task_id)
            self._project = new_project
        else:
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
        return self._render_memory(self._session, self._project)

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

    def _write_project(self, entries: dict[str, MemoryCandidate]) -> None:
        path = self._safe_storage_path(for_write=True)
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        content = "<!-- forgeagent-memory-v1 -->\n" + "\n".join(
            f"- {key}: {entries[key].content}" for key in sorted(entries)
        ) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".MEMORY.", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

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

    def _audit(
        self,
        status: str,
        scope: str,
        kind: str,
        key: str,
        reason: str,
        task_id: str | None = None,
    ) -> None:
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type=f"memory.{status}",
                task_id=task_id,
                parameters={
                    "scope": scope,
                    "kind": kind,
                    "key": key[:80],
                    "reason": reason[:80],
                },
                result_status=status,
            ),
        )
