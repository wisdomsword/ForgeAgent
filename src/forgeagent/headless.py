"""Exact headless approval keys for non-interactive HTTP tasks."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from pydantic import BaseModel

from .audit import AuditEvent, AuditSink, emit_audit
from .protocol import FileWriteArgs, MCPArgs, WebFetchArgs

_GLOB_CHARACTERS = frozenset("*?[]{}")
_WEB_SCHEMES = {"http": 80, "https": 443}


def _invalid_allowlist_entry() -> ValueError:
    return ValueError("invalid headless allowlist entry")


def _validate_safe_text(value: str) -> None:
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or "#" in value
        or any(character in value for character in _GLOB_CHARACTERS)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _invalid_allowlist_entry()


def _validate_relative_key(key: str) -> str:
    _validate_safe_text(key)
    if key.startswith("/") or any(part in {"", ".", ".."} for part in key.split("/")):
        raise _invalid_allowlist_entry()
    return key


def _validate_mcp_segment(value: str) -> str:
    if not value or any(
        not character.isascii() or not (character.isalnum() or character in "-_.:")
        for character in value
    ):
        raise _invalid_allowlist_entry()
    return value


def _validate_mcp_key(key: str) -> str:
    try:
        prefix, server, tool = key.split("/")
    except ValueError:
        raise _invalid_allowlist_entry() from None
    if prefix != "mcp":
        raise _invalid_allowlist_entry()
    return f"mcp/{_validate_mcp_segment(server)}/{_validate_mcp_segment(tool)}"


def _validate_file_key(key: str) -> str:
    if not key.startswith("file/"):
        raise _invalid_allowlist_entry()
    return f"file/{_validate_relative_key(key.removeprefix('file/'))}"


def _canonical_web_host(host: str) -> str:
    try:
        canonical = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise _invalid_allowlist_entry() from None
    if not canonical or any(character.isspace() for character in canonical) or "@" in canonical:
        raise _invalid_allowlist_entry()
    return canonical


def _validate_web_key(key: str) -> str:
    _validate_safe_text(key)
    try:
        prefix, scheme, host, port_text, path = key.split("/", 4)
        port = int(port_text)
    except (TypeError, ValueError):
        raise _invalid_allowlist_entry() from None
    if prefix != "web" or scheme not in _WEB_SCHEMES or not 1 <= port <= 65535:
        raise _invalid_allowlist_entry()
    # split(..., 4) removes the slash before the URL path. An empty path represents
    # URL path "/"; non-empty paths must not contain traversal segments.
    decoded_parts = unquote(path).split("/")
    if any(part in {".", ".."} for part in decoded_parts):
        raise _invalid_allowlist_entry()
    return f"web/{scheme}/{_canonical_web_host(host)}/{port}/{path}"


def normalize_allowlist(entries: Iterable[str]) -> frozenset[str]:
    """Validate exact, portable operation keys; glob and path escape are forbidden."""
    if isinstance(entries, (str, bytes)):
        raise _invalid_allowlist_entry()
    normalized: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            raise _invalid_allowlist_entry()
        if entry.startswith("mcp/"):
            normalized.add(_validate_mcp_key(entry))
        elif entry.startswith("file/"):
            normalized.add(_validate_file_key(entry))
        elif entry.startswith("web/"):
            normalized.add(_validate_web_key(entry))
        else:
            raise _invalid_allowlist_entry()
    return frozenset(normalized)


def operation_key(args: BaseModel, root: Path) -> str:
    """Return the exact authorization key for one gated tool operation."""
    if isinstance(args, MCPArgs):
        try:
            return _validate_mcp_key(f"mcp/{args.server}/{args.tool}")
        except ValueError:
            raise ValueError("invalid MCP operation") from None
    if isinstance(args, FileWriteArgs):
        try:
            canonical_root = Path(root).resolve()
            candidate = Path(args.path)
            if not candidate.is_absolute():
                candidate = canonical_root / candidate
            relative = candidate.resolve().relative_to(canonical_root)
        except (OSError, RuntimeError, ValueError):
            raise ValueError("FileWrite path is outside project root") from None
        try:
            return _validate_file_key(f"file/{relative.as_posix()}")
        except ValueError:
            raise ValueError("FileWrite path is outside project root") from None
    if isinstance(args, WebFetchArgs):
        try:
            parts = urlsplit(args.url)
            scheme = parts.scheme.lower()
            if scheme not in _WEB_SCHEMES or not parts.hostname:
                raise ValueError
            if parts.username is not None or parts.password is not None:
                raise ValueError
            parsed_port = parts.port
            port = _WEB_SCHEMES[scheme] if parsed_port is None else parsed_port
            path = parts.path or "/"
            key = f"web/{scheme}/{parts.hostname}/{port}{path}"
            return _validate_web_key(key)
        except (UnicodeError, ValueError):
            raise ValueError("invalid WebFetch URL") from None
    raise ValueError("unsupported headless confirmation operation")


class HeadlessConfirmer:
    """Deterministic confirmer backed by an exact HTTP-only allowlist."""

    is_headless = True

    def __init__(
        self,
        allowlist: Iterable[str],
        *,
        audit: AuditSink | None,
        root: str | Path = ".",
    ) -> None:
        self._allowlist = normalize_allowlist(allowlist)
        self._audit = audit
        self._root = Path(root).resolve()

    def __call__(self, args: BaseModel) -> bool:
        return self.confirm_with_context(
            args,
            task_id=None,
            operation_id=uuid4().hex,
        )

    def confirm_with_context(
        self,
        args: BaseModel,
        *,
        task_id: str | None,
        operation_id: str,
        allowed_root: str | Path | None = None,
    ) -> bool:
        if (
            isinstance(args, FileWriteArgs)
            and allowed_root is not None
            and Path(allowed_root).resolve() != self._root
        ):
            key = "invalid"
            allowed = False
        else:
            try:
                key = operation_key(args, self._root)
            except ValueError:
                key = "invalid"
                allowed = False
            else:
                allowed = key in self._allowlist
        emit_audit(
            self._audit,
            AuditEvent(
                event_type="confirmation.decision",
                task_id=task_id,
                risk_level="high",
                operation_id=operation_id,
                parameters={"operation": key},
                result_status="preapproved" if allowed else "denied",
                duration_ms=0,
            ),
        )
        return allowed

    def allows_web_url(self, url: str) -> bool:
        """Return whether one effective WebFetch URL has an exact allowlist entry."""
        try:
            key = operation_key(WebFetchArgs(url=url), self._root)
        except ValueError:
            return False
        return key in self._allowlist
