"""Small, deterministic runtime memory store for facts and preferences."""

from __future__ import annotations

import os
import re
import tempfile
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
    ) -> None:
        self._root = Path(allowed_root).resolve()
        self._path = self._root / ".forgeagent" / "MEMORY.md"
        self._audit_sink = audit_sink
        self._enabled = enabled
        self._session: dict[str, MemoryCandidate] = {}
        self._project: dict[str, MemoryCandidate] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def load(self) -> None:
        if not self._enabled or not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return
        loaded: dict[str, MemoryCandidate] = {}
        for line in lines:
            match = _LINE.fullmatch(line)
            if match is None:
                continue
            key, content = match.groups()
            candidate = MemoryCandidate(scope="project", kind="fact", key=key, content=content)
            if self._admission_reason(candidate) is None and len(loaded) < _MAX_ENTRIES:
                loaded[key] = candidate
        self._project = loaded

    def disable(self) -> None:
        if self._enabled:
            self._enabled = False
            self._session.clear()
            self._project.clear()
            self._audit("disabled", "", "", "memory_disabled")

    def apply(self, candidate: MemoryCandidate, task_id: str | None = None) -> MemoryResult:
        if not self._enabled:
            return self._result(candidate, "disabled", "memory_disabled", task_id)
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
            try:
                self._write_project(new_project)
            except OSError:
                return self._result(candidate, "persistence_error", "project_write_failed", task_id)
            self._project = new_project
        else:
            target[candidate.key] = candidate
        status: Literal["accepted", "replaced"] = "replaced" if replaced else "accepted"
        return self._result(candidate, status, "", task_id)

    def render(self) -> str:
        if not self._enabled:
            return ""
        sections: list[str] = []
        if self._session:
            sections.append(self._render_section("Session memory", self._session))
        if self._project:
            sections.append(self._render_section("Project memory", self._project))
        rendered = "\n\n".join(sections)
        encoded = rendered.encode("utf-8")
        if len(encoded) <= _MAX_RENDER_BYTES:
            return rendered
        return encoded[:_MAX_RENDER_BYTES].decode("utf-8", errors="ignore")

    def _render_section(self, title: str, entries: dict[str, MemoryCandidate]) -> str:
        lines = [f"## {title}"]
        for key in sorted(entries):
            value = mask_secrets(entries[key].content, sensitive_env_values())
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _write_project(self, entries: dict[str, MemoryCandidate]) -> None:
        directory = self._path.parent
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
            os.replace(temporary_name, self._path)
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

    def _result(
        self,
        candidate: MemoryCandidate,
        status: Literal["accepted", "replaced", "rejected", "persistence_error", "disabled"],
        reason: str,
        task_id: str | None,
    ) -> MemoryResult:
        self._audit(status, candidate.scope, candidate.key, reason, task_id)
        return MemoryResult(status, candidate.scope, candidate.kind, candidate.key, reason)

    def _audit(
        self,
        status: str,
        scope: str,
        key: str,
        reason: str,
        task_id: str | None = None,
    ) -> None:
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type=f"memory.{status}",
                task_id=task_id,
                parameters={"scope": scope, "key": key[:80], "reason": reason[:80]},
                result_status=status,
            ),
        )
