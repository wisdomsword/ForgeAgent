"""Runtime identity prompt composition."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

from .secret_policy import mask_secrets, sensitive_env_values

_PROMPTS_PACKAGE = "forgeagent.res.prompts"
_MAX_IDENTITY_FILE_BYTES = 32 * 1024
_MAX_EFFECTIVE_TOTAL_BYTES = 96 * 1024
_RAW_DIGEST_DOMAIN = b"forgeagent-identity-raw-content-digest-v1\x00"
_EFFECTIVE_DIGEST_DOMAIN = b"forgeagent-identity-effective-input-digest-v1\x00"
_PROJECT_ID_DOMAIN = b"forgeagent-identity-project-id-v1\x00"
_TRUST_RECORD_VERSION = 1
_TRUST_SECTION_PREVIEW_CHARS = 2048

IdentityDiagnostic = Callable[[str], None]


class _IdentityPathError(Exception):
    """An identity path exists or resolves in an unsafe shape."""


class IdentityConfigError(Exception):
    """A user-level identity file is invalid or cannot be safely read."""


def _encode_length_prefixed(label: bytes, payload: bytes | None) -> bytes:
    if payload is None:
        return label + b"\x00"
    return label + b"\x01" + len(payload).to_bytes(8, "big") + payload


def _raw_content_digest(agents_bytes: bytes | None, memory_bytes: bytes | None) -> str:
    hasher = hashlib.sha256()
    hasher.update(_RAW_DIGEST_DOMAIN)
    hasher.update(_encode_length_prefixed(b"AGENTS", agents_bytes))
    hasher.update(_encode_length_prefixed(b"MEMORY", memory_bytes))
    return hasher.hexdigest()


def _effective_input_digest(masked_agents: str | None, masked_memory: str | None) -> str:
    hasher = hashlib.sha256()
    hasher.update(_EFFECTIVE_DIGEST_DOMAIN)
    agents_bytes = masked_agents.encode("utf-8") if masked_agents is not None else None
    memory_bytes = masked_memory.encode("utf-8") if masked_memory is not None else None
    hasher.update(_encode_length_prefixed(b"AGENTS", agents_bytes))
    hasher.update(_encode_length_prefixed(b"MEMORY", memory_bytes))
    return hasher.hexdigest()


def canonical_project_id_digest(allowed_root: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(_PROJECT_ID_DOMAIN)
    hasher.update(os.fsencode(os.path.realpath(allowed_root)))
    return hasher.hexdigest()


def _mask(text: str) -> str:
    return mask_secrets(text, sensitive_env_values())


def _resolve_identity_file(directory: str, filename: str, *, containment_root: str) -> Path | None:
    """Resolve one fixed identity filename without crossing `containment_root`."""
    root = os.path.realpath(containment_root)
    base = os.path.realpath(directory)
    try:
        base_common = os.path.commonpath((root, base))
    except ValueError as exc:
        raise _IdentityPathError("identity directory is outside its allowed root") from exc
    if os.path.normcase(base_common) != os.path.normcase(root):
        raise _IdentityPathError("identity directory is outside its allowed root")

    candidate = os.path.join(base, filename)
    resolved = os.path.realpath(candidate)
    try:
        common = os.path.commonpath((base, resolved))
    except ValueError as exc:
        raise _IdentityPathError(f"{filename} is outside the identity directory") from exc
    if os.path.normcase(common) != os.path.normcase(base):
        raise _IdentityPathError(f"{filename} is outside the identity directory")
    try:
        file_stat = os.lstat(resolved)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _IdentityPathError(f"{filename} path metadata is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise _IdentityPathError(f"{filename} is not a regular file")
    return Path(resolved)


@dataclass(frozen=True)
class IdentitySnapshot:
    """Raw identity content and digests used by later trust decisions."""

    soul: str | None
    user: str | None
    agents: str | None
    memory: str | None
    raw_content_digest: str
    effective_input_digest: str


@dataclass(frozen=True)
class ApprovedIdentity:
    """Identity content approved to reach the model."""

    soul: str | None
    user: str | None
    project_agents: str | None
    memory: str | None


class _UnusableTrustRecordError(Exception):
    """A trust record exists but cannot be safely reused or updated."""


def default_trust_record_path(home: str | None = None) -> str:
    effective_home = str(Path.home()) if home is None else home
    return os.path.join(effective_home, ".forgeagent", "identity-trust.json")


def _load_trust_record(path: str) -> dict | None:
    """Read a fully validated v1 trust record, distinguishing absent from unusable."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw_text = handle.read()
    except FileNotFoundError:
        if os.path.lexists(path):
            raise _UnusableTrustRecordError("trust record path is unusable") from None
        return None
    except (OSError, UnicodeError) as exc:
        raise _UnusableTrustRecordError(type(exc).__name__) from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise _UnusableTrustRecordError("invalid JSON") from exc
    if not isinstance(raw, dict):
        raise _UnusableTrustRecordError("top-level value is not an object")
    if set(raw) != {"version", "projects"}:
        raise _UnusableTrustRecordError("unknown top-level field")
    if (
        not isinstance(raw.get("version"), int)
        or isinstance(raw.get("version"), bool)
        or raw["version"] != _TRUST_RECORD_VERSION
    ):
        raise _UnusableTrustRecordError("unknown version")
    if not isinstance(raw.get("projects"), dict):
        raise _UnusableTrustRecordError("'projects' field is not an object")
    for project_id, entry in raw["projects"].items():
        if not isinstance(project_id, str) or not isinstance(entry, dict):
            raise _UnusableTrustRecordError("invalid project entry")
        if set(entry) != {
            "raw_content_digest",
            "effective_input_digest",
            "approved_at",
        }:
            raise _UnusableTrustRecordError("unknown project entry field")
        if not isinstance(entry.get("raw_content_digest"), str):
            raise _UnusableTrustRecordError("invalid raw_content_digest")
        if not isinstance(entry.get("effective_input_digest"), str):
            raise _UnusableTrustRecordError("invalid effective_input_digest")
        if not isinstance(entry.get("approved_at"), str):
            raise _UnusableTrustRecordError("invalid approved_at")
    return raw


def _atomic_write_trust_record(path: str, record: dict) -> None:
    """Write a trust record through a sibling temporary file and atomic replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, prefix=".identity-trust.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(record, temporary, indent=2, sort_keys=True)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _record_approval(
    path: str, project_id: str, raw_content_digest: str, effective_input_digest: str
) -> bool:
    """Merge one approval; return false when read/write persistence is unavailable."""
    try:
        existing = _load_trust_record(path)
        record = existing if existing is not None else {"version": 1, "projects": {}}
        record["projects"][project_id] = {
            "raw_content_digest": raw_content_digest,
            "effective_input_digest": effective_input_digest,
            "approved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _atomic_write_trust_record(path, record)
    except (_UnusableTrustRecordError, OSError):
        return False
    return True


class IdentityTrustRequest(BaseModel):
    project_label: str
    summary: str


IdentityConfirmer = Callable[[IdentityTrustRequest], bool]


def _escape_identity_confirmation(value: str, *, preserve_newlines: bool) -> str:
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if preserve_newlines and character == "\n":
            escaped.append(character)
        elif (
            codepoint < 32
            or 127 <= codepoint <= 159
            or character in {"\u2028", "\u2029"}
            or unicodedata.category(character) in {"Cf", "Cs"}
        ):
            escaped.append(
                f"\\x{codepoint:02x}"
                if codepoint <= 0xFF
                else (f"\\u{codepoint:04x}" if codepoint <= 0xFFFF else f"\\U{codepoint:08x}")
            )
        else:
            escaped.append(character)
    return "".join(escaped)


def _project_label(allowed_root: str) -> str:
    resolved = Path(os.path.realpath(allowed_root))
    parts = resolved.parts[-2:] if len(resolved.parts) >= 2 else resolved.parts
    label = os.path.join("...", *parts) if len(resolved.parts) >= 2 else str(resolved)
    return _escape_identity_confirmation(
        mask_secrets(label, sensitive_env_values()), preserve_newlines=False
    )


def _identity_section_preview(filename: str, value: str) -> str:
    escaped = _escape_identity_confirmation(value, preserve_newlines=True)
    if len(escaped) > _TRUST_SECTION_PREVIEW_CHARS:
        escaped = (
            escaped[:_TRUST_SECTION_PREVIEW_CHARS]
            + "\n...[preview truncated; approval remains bound to the full digest]"
        )
    return f"{filename} ({len(value)} chars):\n{escaped}"


def _trust_request_summary(agents: str | None, memory: str | None) -> str:
    sections: list[str] = []
    if agents is not None:
        sections.append(_identity_section_preview("AGENTS.md", agents))
    if memory is not None:
        sections.append(_identity_section_preview("MEMORY.md", memory))
    return "\n\n".join(sections)


def resolve_project_trust(
    snapshot: IdentitySnapshot,
    allowed_root: str,
    home: str | None,
    confirmer: IdentityConfirmer | None,
    *,
    trust_record_path: str | None = None,
    diagnostic: IdentityDiagnostic | None = None,
) -> ApprovedIdentity:
    """Apply project identity confirmation and return the model-facing snapshot."""
    if snapshot.agents is None and snapshot.memory is None:
        return ApprovedIdentity(snapshot.soul, snapshot.user, None, None)

    record_path = trust_record_path or default_trust_record_path(home)
    project_id = canonical_project_id_digest(allowed_root)
    record_was_unusable = False
    try:
        record = _load_trust_record(record_path)
    except _UnusableTrustRecordError as exc:
        record = None
        record_was_unusable = True
        _emit_identity_diagnostic(
            diagnostic, f"identity trust record ignored: {type(exc).__name__}"
        )

    existing_entry = record["projects"].get(project_id) if record is not None else None
    digests_match = (
        existing_entry is not None
        and existing_entry.get("raw_content_digest") == snapshot.raw_content_digest
        and existing_entry.get("effective_input_digest") == snapshot.effective_input_digest
    )
    if digests_match:
        return ApprovedIdentity(snapshot.soul, snapshot.user, snapshot.agents, snapshot.memory)

    stripped = ApprovedIdentity(snapshot.soul, snapshot.user, None, None)
    if confirmer is None or not confirmer(
        IdentityTrustRequest(
            project_label=_project_label(allowed_root),
            summary=_trust_request_summary(snapshot.agents, snapshot.memory),
        )
    ):
        return stripped

    if not record_was_unusable:
        persisted = _record_approval(
            record_path, project_id, snapshot.raw_content_digest, snapshot.effective_input_digest
        )
        if not persisted:
            _emit_identity_diagnostic(
                diagnostic, "identity trust approval is memory-only: persistence failed"
            )
    return ApprovedIdentity(snapshot.soul, snapshot.user, snapshot.agents, snapshot.memory)


def _read_resolved_bytes(resolved: Path, filename: str) -> bytes:
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise IdentityConfigError(
            f"{filename} exists but could not be read ({type(exc).__name__})"
        ) from None


def _read_user_level_file(home: str, filename: str) -> str | None:
    forgeagent_dir = os.path.join(home, ".forgeagent")
    try:
        resolved = _resolve_identity_file(forgeagent_dir, filename, containment_root=home)
    except _IdentityPathError:
        # Raise after leaving the handler so the internal path exception (and any
        # metadata OSError it wraps) is not retained as the public error context.
        resolved = None
        unsafe_path = True
    else:
        unsafe_path = False
    if unsafe_path:
        raise IdentityConfigError(f"{filename} has an unsafe path")
    if resolved is None:
        return None
    raw_bytes = _read_resolved_bytes(resolved, filename)
    if len(raw_bytes) > _MAX_IDENTITY_FILE_BYTES:
        raise IdentityConfigError(
            f"{filename} is {len(raw_bytes)} bytes, exceeding the "
            f"{_MAX_IDENTITY_FILE_BYTES}-byte per-file limit"
        )
    return raw_bytes.decode("utf-8", errors="replace")


def _read_project_level_file(allowed_root: str, filename: str) -> bytes | None:
    forgeagent_dir = os.path.join(allowed_root, ".forgeagent")
    resolved = _resolve_identity_file(forgeagent_dir, filename, containment_root=allowed_root)
    if resolved is None:
        return None
    return _read_resolved_bytes(resolved, filename)


def _emit_identity_diagnostic(diagnostic: IdentityDiagnostic | None, message: str) -> None:
    if diagnostic is not None:
        masked = _mask(message)
        diagnostic(
            "".join(
                f"\\x{ord(character):02x}"
                if ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
                else character
                for character in masked
            )
        )


def load_identity(
    home: str | None = None,
    allowed_root: str | None = None,
    *,
    diagnostic: IdentityDiagnostic | None = None,
) -> IdentitySnapshot:
    """Read and mask runtime identity files using call-time path defaults."""
    effective_home = str(Path.home()) if home is None else home
    effective_root = str(Path.cwd()) if allowed_root is None else allowed_root

    soul = _read_user_level_file(effective_home, "SOUL.md")
    user = _read_user_level_file(effective_home, "USER.md")

    try:
        agents_bytes = _read_project_level_file(effective_root, "AGENTS.md")
        memory_bytes = _read_project_level_file(effective_root, "MEMORY.md")
    except _IdentityPathError as exc:
        _emit_identity_diagnostic(
            diagnostic,
            f"project identity snapshot rejected: {type(exc).__name__}",
        )
        agents_bytes = None
        memory_bytes = None

    if agents_bytes is not None and len(agents_bytes) > _MAX_IDENTITY_FILE_BYTES:
        _emit_identity_diagnostic(
            diagnostic,
            f"AGENTS.md stripped: {len(agents_bytes)} bytes exceeds {_MAX_IDENTITY_FILE_BYTES}",
        )
        agents_bytes = None
    if memory_bytes is not None and len(memory_bytes) > _MAX_IDENTITY_FILE_BYTES:
        _emit_identity_diagnostic(
            diagnostic,
            f"MEMORY.md stripped: {len(memory_bytes)} bytes exceeds {_MAX_IDENTITY_FILE_BYTES}",
        )
        memory_bytes = None

    masked_soul = _mask(soul) if soul is not None else None
    masked_user = _mask(user) if user is not None else None
    masked_agents = (
        _mask(agents_bytes.decode("utf-8", errors="replace")) if agents_bytes is not None else None
    )
    masked_memory = (
        _mask(memory_bytes.decode("utf-8", errors="replace")) if memory_bytes is not None else None
    )

    fixed_total = sum(
        len(value.encode("utf-8")) for value in (masked_soul, masked_user) if value is not None
    )
    project_sizes = {
        "agents": len(masked_agents.encode("utf-8")) if masked_agents is not None else 0,
        "memory": len(masked_memory.encode("utf-8")) if masked_memory is not None else 0,
    }
    if fixed_total > _MAX_EFFECTIVE_TOTAL_BYTES:
        raise IdentityConfigError(
            f"combined masked SOUL+USER content is {fixed_total} bytes, exceeding the "
            f"{_MAX_EFFECTIVE_TOTAL_BYTES}-byte combined limit"
        )
    for name in sorted(project_sizes, key=lambda item: project_sizes[item], reverse=True):
        if fixed_total + sum(project_sizes.values()) <= _MAX_EFFECTIVE_TOTAL_BYTES:
            break
        project_sizes[name] = 0
        if name == "agents":
            _emit_identity_diagnostic(
                diagnostic,
                "AGENTS.md stripped: masked identity total exceeds 98304 bytes",
            )
            agents_bytes = None
            masked_agents = None
        else:
            _emit_identity_diagnostic(
                diagnostic,
                "MEMORY.md stripped: masked identity total exceeds 98304 bytes",
            )
            memory_bytes = None
            masked_memory = None

    return IdentitySnapshot(
        soul=masked_soul,
        user=masked_user,
        agents=masked_agents,
        memory=masked_memory,
        raw_content_digest=_raw_content_digest(agents_bytes, memory_bytes),
        effective_input_digest=_effective_input_digest(masked_agents, masked_memory),
    )


def _read_prompt_resource(filename: str) -> str:
    return resources.files(_PROMPTS_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def compose_system_prompt(identity: ApprovedIdentity) -> str:
    """Render the bundled system prompt for an approved identity."""
    protocol = _read_prompt_resource("protocol.md")
    soul = identity.soul if identity.soul is not None else _read_prompt_resource("default_soul.md")
    template_source = _read_prompt_resource("system.j2")
    environment = Environment(
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    template = environment.from_string(template_source)
    return template.render(
        soul=soul,
        protocol=protocol,
        user=identity.user,
        project_agents=identity.project_agents,
        memory=identity.memory,
    )
