"""Runtime identity prompt composition."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .secret_policy import mask_secrets, sensitive_env_values

_PROMPTS_PACKAGE = "forgeagent.res.prompts"
_MAX_IDENTITY_FILE_BYTES = 32 * 1024
_MAX_EFFECTIVE_TOTAL_BYTES = 96 * 1024
_RAW_DIGEST_DOMAIN = b"forgeagent-identity-raw-content-digest-v1\x00"
_EFFECTIVE_DIGEST_DOMAIN = b"forgeagent-identity-effective-input-digest-v1\x00"
_PROJECT_ID_DOMAIN = b"forgeagent-identity-project-id-v1\x00"

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
    except _IdentityPathError as exc:
        raise IdentityConfigError(f"{filename} has an unsafe path") from exc
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
