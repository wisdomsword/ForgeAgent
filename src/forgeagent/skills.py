"""Validated, immutable snapshots of local ``SKILL.md`` definitions."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import yaml

from forgeagent.identity import _escape_identity_confirmation, resolve_project_content_trust
from forgeagent.secret_policy import (
    _redact_absolute_paths,
    mask_secrets,
    sensitive_env_values,
)

if TYPE_CHECKING:
    from forgeagent.identity import IdentityConfirmer


_MAX_SKILL_BYTES = 32 * 1024
_MAX_CATALOG_BYTES = 16 * 1024
_MAX_CATALOG_ENTRIES = 64
_MAX_TRUST_SUMMARY_BYTES = 8 * 1024
_RAW_DIGEST_DOMAIN = b"forgeagent-skills-raw-content-digest-v1\x00"
_EFFECTIVE_DIGEST_DOMAIN = b"forgeagent-skills-effective-input-digest-v1\x00"
_TRUST_SUMMARY_TRUNCATION = "\n...[summary truncated; approval remains bound to the full digest]"
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_HEADING_RE = re.compile(r"^## ([^\r\n]+)\s*$")
_SECTION_HEADINGS = ("Steps", "Failure Branches", "Completion Criteria")
_EXIT_CLASS_NAMES = ("success", "failure", "blocked", "needs_input", "timeout_or_budget")
_MAX_EXIT_TEXT_BYTES = 512
# Standard Skills SDK skills (front matter ``name`` + ``description`` + free-form body) are
# accepted through a compatibility path. They may be larger on disk than a native skill, but
# the loaded definition's body is truncated to ``_MAX_SKILL_BYTES`` so the in-memory skill
# stays bounded. The trigger is derived from the description; the failure-branch and
# completion-criteria sections are synthesized, since a standard skill declares neither.
_MAX_COMPAT_SKILL_BYTES = 256 * 1024
_MAX_TRIGGER_CHARS = 240
_STANDARD_FAILURE_BRANCHES = (
    "The skill is a standard Skills SDK skill loaded in compatibility mode; it declares "
    "no explicit failure branches. Observe tool errors and the user's stated outcome."
)
_STANDARD_COMPLETION_CRITERIA = (
    "The skill completes when its steps have been followed and the user confirms the "
    "requested outcome is achieved."
)
_ABSOLUTE_EXIT_CLAIM_RE = re.compile(
    r"^(?:100\s*%|always|never|all|everything|全部|始终|永远|完美)"
    r"(?:\s+(?:complete|completed|succeeds?|done|完成|成功|通过))?$",
    re.IGNORECASE,
)
_CATALOG_HEADER = (
    "## Available Skills",
    "",
    "Choose a skill when its trigger matches the task. Read it with the Skill tool before "
    "following it.",
)


@dataclass(frozen=True)
class SkillExitCondition:
    """One bounded, observable exit condition and its responsible verifier."""

    condition: str
    verifier: str


@dataclass(frozen=True)
class SkillDefinition:
    """A validated local skill document with its trusted discovery source."""

    name: str
    trigger: str
    steps: str
    failure_branches: str
    completion_criteria: str
    source: Literal["user", "project"]
    format_version: int = 1
    exit_conditions: Mapping[str, SkillExitCondition] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "exit_conditions", MappingProxyType(dict(self.exit_conditions)))


class SkillRegistry:
    """An immutable, deterministic snapshot of validated local skills."""

    def __init__(self, definitions: Mapping[str, SkillDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def load(
        cls,
        *,
        home: str,
        allowed_root: str,
        confirmer: IdentityConfirmer | None = None,
        allow_project: bool = True,
        trust_record_path: str | None = None,
        diagnostic: Callable[[str], None] | None = None,
    ) -> SkillRegistry:
        """Load a user snapshot with an approved project-Skill overlay."""
        user = _discover(
            Path(home) / ".forgeagent" / "skills",
            source="user",
            diagnostic=diagnostic,
        )
        if not allow_project:
            return cls(_bounded_catalog(user, diagnostic=diagnostic))

        project_raw_documents: dict[str, bytes] = {}
        project = _discover(
            Path(allowed_root) / ".forgeagent" / "skills",
            source="project",
            diagnostic=diagnostic,
            raw_documents=project_raw_documents,
        )
        if not project:
            return cls(_bounded_catalog(user, diagnostic=diagnostic))

        record_path = trust_record_path or os.path.join(home, ".forgeagent", "skills-trust.json")
        if not resolve_project_content_trust(
            allowed_root=allowed_root,
            raw_content_digest=_content_digest(_RAW_DIGEST_DOMAIN, project_raw_documents),
            effective_input_digest=_content_digest(
                _EFFECTIVE_DIGEST_DOMAIN,
                {
                    name: _render_full_skill(definition).encode("utf-8")
                    for name, definition in project.items()
                },
            ),
            trust_record_path=record_path,
            confirmer=confirmer,
            summary=_project_trust_summary(project),
            diagnostic=diagnostic,
            diagnostic_prefix="skill",
        ):
            return cls(_bounded_catalog(user, diagnostic=diagnostic))

        return cls(_bounded_catalog({**user, **project}, diagnostic=diagnostic))

    def catalog_prompt(self) -> str:
        """Return the fixed, bounded catalog prompt for this snapshot."""
        if not self._definitions:
            return ""
        lines = [*_CATALOG_HEADER]
        lines.extend(f"- {skill.name} — {skill.trigger}" for skill in self._definitions.values())
        return "\n".join(lines)

    def read(self, name: str, section: str = "full") -> str | None:
        """Read a named skill or one of its validated sections."""
        skill = self._definitions.get(name)
        if skill is None:
            return None
        sections = {
            "steps": skill.steps,
            "failure_branches": skill.failure_branches,
            "completion_criteria": skill.completion_criteria,
        }
        if skill.format_version == 2:
            sections["exit_conditions"] = _render_exit_conditions(skill.exit_conditions)
        if section in sections:
            return sections[section]
        if section != "full":
            return None
        return _render_full_skill(skill)


def _discover(
    root: Path,
    *,
    source: Literal["user", "project"],
    diagnostic: Callable[[str], None] | None,
    raw_documents: dict[str, bytes] | None = None,
) -> dict[str, SkillDefinition]:
    root_real = _real_directory(root)
    if root_real is None:
        return {}

    definitions: dict[str, SkillDefinition] = {}
    try:
        directory_names = sorted(os.listdir(root_real))
    except OSError:
        return definitions

    for directory_name in directory_names:
        child = Path(root_real, directory_name)
        child_real = _contained_directory(child, root_real)
        if child_real is None:
            _emit_ignored(diagnostic, "invalid format", directory_name)
            continue
        skill_file = child / "SKILL.md"
        skill_real = _contained_regular_file(skill_file, root_real)
        if skill_real is None:
            _emit_ignored(diagnostic, "invalid format", directory_name)
            continue
        try:
            raw_document = Path(skill_real).read_bytes()
            document = raw_document.decode("utf-8")
            definition = _parse_document(
                document,
                source=source,
                expected_name=directory_name,
                raw_bytes=len(raw_document),
                diagnostic=diagnostic,
            )
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            _emit_ignored(diagnostic, "invalid format", directory_name)
            continue
        except RecursionError:
            _emit_ignored(diagnostic, "invalid exit contract", directory_name)
            continue
        except ValueError as error:
            _emit_ignored(diagnostic, str(error), directory_name)
            continue
        if definition.name not in definitions:
            definitions[definition.name] = definition
            if raw_documents is not None:
                raw_documents[definition.name] = raw_document
    return definitions


def _content_digest(domain: bytes, documents: Mapping[str, bytes]) -> str:
    hasher = hashlib.sha256()
    hasher.update(domain)
    for name in sorted(documents):
        encoded = name.encode("utf-8") + b"\x00" + documents[name]
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def _project_trust_summary(definitions: Mapping[str, SkillDefinition]) -> str:
    lines: list[str] = []
    for definition in definitions.values():
        safe_trigger = _escape_identity_confirmation(
            _redact_absolute_paths(definition.trigger), preserve_newlines=False
        )
        lines.append(f"{definition.name} — {safe_trigger}")
    summary = "\n".join(lines)
    if len(summary.encode("utf-8")) <= _MAX_TRUST_SUMMARY_BYTES:
        return summary
    available = _MAX_TRUST_SUMMARY_BYTES - len(_TRUST_SUMMARY_TRUNCATION.encode("utf-8"))
    truncated = summary.encode("utf-8")[:available].decode("utf-8", errors="ignore")
    return truncated + _TRUST_SUMMARY_TRUNCATION


def _real_directory(path: Path) -> str | None:
    """Return a directory's real path after checking both link and target metadata."""
    try:
        os.lstat(path)
        if not stat.S_ISDIR(os.stat(path).st_mode):
            return None
    except OSError:
        return None
    return os.path.realpath(path)


def _contained_directory(path: Path, root_real: str) -> str | None:
    try:
        os.lstat(path)
        path_real = os.path.realpath(path)
        if not _is_contained(path_real, root_real) or not stat.S_ISDIR(os.stat(path).st_mode):
            return None
    except OSError:
        return None
    return path_real


def _contained_regular_file(path: Path, root_real: str) -> str | None:
    try:
        os.lstat(path)
        path_real = os.path.realpath(path)
        if not _is_contained(path_real, root_real) or not stat.S_ISREG(os.stat(path).st_mode):
            return None
    except OSError:
        return None
    return path_real


def _is_contained(path_real: str, root_real: str) -> bool:
    try:
        return os.path.commonpath((path_real, root_real)) == root_real
    except ValueError:
        return False


def _parse_document(
    document: str,
    *,
    source: Literal["user", "project"],
    expected_name: str,
    raw_bytes: int | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> SkillDefinition:
    match = _FRONT_MATTER_RE.fullmatch(document)
    if match is None:
        raise ValueError("invalid format")
    front_matter_text = match.group(1)
    try:
        front_matter_node = yaml.compose(front_matter_text)
        if not isinstance(front_matter_node, yaml.MappingNode):
            raise ValueError("invalid format")
        keys = [
            key_node.value
            for key_node, _ in front_matter_node.value
            if isinstance(key_node, yaml.ScalarNode)
        ]
        if len(keys) != len(front_matter_node.value) or len(keys) != len(set(keys)):
            raise ValueError("invalid format")
        if _has_duplicate_mapping_key(front_matter_node):
            raise ValueError("invalid exit contract")
        front_matter = yaml.safe_load(front_matter_text)
    except ValueError:
        raise
    except yaml.YAMLError as error:
        if _has_malformed_multiline_trigger(front_matter_text):
            raise ValueError("invalid trigger") from error
        raise ValueError("invalid format") from error
    if not isinstance(front_matter, dict):
        raise ValueError("invalid format")
    format_version = front_matter.get("format_version", 1)
    if isinstance(format_version, bool) or not isinstance(format_version, int):
        raise ValueError("invalid format version")
    if format_version not in {1, 2}:
        raise ValueError("invalid format version")

    # A skill with no ``trigger`` but with a ``description`` is a standard Skills SDK
    # skill (``name`` + ``description`` + free-form body). It is accepted through the
    # compatibility path, which derives the trigger and synthesizes the sections that
    # the ForgeAgent-native format requires.
    is_standard = format_version == 1 and "trigger" not in front_matter
    if is_standard:
        return _parse_standard_document(
            match,
            front_matter,
            source=source,
            expected_name=expected_name,
            raw_bytes=raw_bytes,
            diagnostic=diagnostic,
        )

    # A native skill is bounded on disk. (A standard Skills SDK skill reaches the
    # compatibility path above instead, where the bound is ``_MAX_COMPAT_SKILL_BYTES``.)
    if raw_bytes is not None and raw_bytes > _MAX_SKILL_BYTES:
        raise ValueError("invalid format")

    expected_keys = (
        {"name", "trigger"}
        if format_version == 1
        else {
            "name",
            "trigger",
            "format_version",
            "exit_conditions",
        }
    )
    if set(front_matter) != expected_keys:
        raise ValueError("invalid exit contract" if format_version == 2 else "invalid format")
    name = front_matter["name"]
    trigger = front_matter["trigger"]
    if not isinstance(name, str) or not _SKILL_NAME_RE.fullmatch(name) or name != expected_name:
        raise ValueError("invalid name")
    if not isinstance(trigger, str) or not trigger or "\n" in trigger or "\r" in trigger:
        raise ValueError("invalid trigger")

    exit_conditions: Mapping[str, SkillExitCondition] = MappingProxyType({})
    if format_version == 2:
        exit_conditions = _parse_exit_conditions(front_matter["exit_conditions"])

    sections = _parse_sections(match.group(2))
    secret_values = sensitive_env_values()
    return SkillDefinition(
        name=mask_secrets(name, secret_values),
        trigger=mask_secrets(trigger, secret_values),
        steps=mask_secrets(sections["Steps"], secret_values),
        failure_branches=mask_secrets(sections["Failure Branches"], secret_values),
        completion_criteria=mask_secrets(sections["Completion Criteria"], secret_values),
        source=source,
        format_version=format_version,
        exit_conditions=MappingProxyType(
            {
                name: SkillExitCondition(
                    condition=mask_secrets(item.condition, secret_values),
                    verifier=mask_secrets(item.verifier, secret_values),
                )
                for name, item in exit_conditions.items()
            }
        ),
    )


def _parse_standard_document(
    match: re.Match[str],
    front_matter: dict,
    *,
    source: Literal["user", "project"],
    expected_name: str,
    raw_bytes: int | None,
    diagnostic: Callable[[str], None] | None,
) -> SkillDefinition:
    """Accept a standard Skills SDK skill (``name`` + ``description`` + free-form body).

    The trigger is derived from the description, the body becomes ``Steps``, and the
    failure-branch and completion-criteria sections are synthesized. All security bounds
    still apply: name format, symlink containment (enforced by the caller), secret
    masking, and a truncated, bounded in-memory body.
    """
    name = front_matter.get("name")
    description = front_matter.get("description")
    if not isinstance(name, str) or not _SKILL_NAME_RE.fullmatch(name) or name != expected_name:
        raise ValueError("invalid name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("invalid format")
    if raw_bytes is not None and raw_bytes > _MAX_COMPAT_SKILL_BYTES:
        raise ValueError("invalid format")

    body = match.group(2)
    steps = _bounded_body(body)
    if not steps:
        raise ValueError("invalid format")
    trigger = _derive_trigger(description)
    secret_values = sensitive_env_values()
    definition = SkillDefinition(
        name=mask_secrets(name, secret_values),
        trigger=mask_secrets(trigger, secret_values),
        steps=mask_secrets(steps, secret_values),
        failure_branches=_STANDARD_FAILURE_BRANCHES,
        completion_criteria=_STANDARD_COMPLETION_CRITERIA,
        source=source,
        format_version=1,
    )
    if diagnostic is not None:
        diagnostic(f"skill loaded in standard Skills SDK compatibility mode: {name}")
    return definition


def _derive_trigger(description: str) -> str:
    """Collapse a description into a single bounded line usable as a trigger."""
    collapsed = " ".join(description.split())
    if len(collapsed) <= _MAX_TRIGGER_CHARS:
        return collapsed
    truncated = collapsed[:_MAX_TRIGGER_CHARS]
    boundary = truncated.rfind(" ")
    return truncated[:boundary] if boundary > 0 else truncated


def _bounded_body(body: str) -> str:
    """Trim a standard skill body to the in-memory byte bound."""
    stripped = body.strip()
    if len(stripped.encode("utf-8")) <= _MAX_SKILL_BYTES:
        return stripped
    return stripped.encode("utf-8")[:_MAX_SKILL_BYTES].decode("utf-8", errors="ignore").rstrip()


def _parse_exit_conditions(value: object) -> Mapping[str, SkillExitCondition]:
    if not isinstance(value, dict) or set(value) != set(_EXIT_CLASS_NAMES):
        raise ValueError("invalid exit contract")
    parsed: dict[str, SkillExitCondition] = {}
    for name in _EXIT_CLASS_NAMES:
        item = value[name]
        if not isinstance(item, dict) or set(item) != {"condition", "verifier"}:
            raise ValueError("invalid exit contract")
        condition, verifier = item["condition"], item["verifier"]
        if not _valid_exit_text(condition) or not _valid_exit_text(verifier):
            raise ValueError("invalid exit contract")
        if _ABSOLUTE_EXIT_CLAIM_RE.fullmatch(condition.strip()):
            raise ValueError("invalid exit contract")
        parsed[name] = SkillExitCondition(condition=condition, verifier=verifier)
    return MappingProxyType(parsed)


def _has_duplicate_mapping_key(node: yaml.Node, visited: set[int] | None = None) -> bool:
    if visited is None:
        visited = set()
    node_id = id(node)
    if node_id in visited:
        return True
    visited.add(node_id)
    if isinstance(node, yaml.MappingNode):
        keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
        if len(keys) != len(node.value) or len(keys) != len(set(keys)):
            return True
        return any(_has_duplicate_mapping_key(value, visited) for _, value in node.value)
    if isinstance(node, yaml.SequenceNode):
        return any(_has_duplicate_mapping_key(item, visited) for item in node.value)
    return False


def _valid_exit_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(ord(character) < 0x20 for character in value)
        and len(value.encode("utf-8")) <= _MAX_EXIT_TEXT_BYTES
    )


def _has_malformed_multiline_trigger(front_matter: str) -> bool:
    lines = front_matter.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith("trigger:"):
            following = lines[index + 1]
            return (
                bool(following.strip())
                and not following.startswith((" ", "\t"))
                and ":" not in following
            )
    return False


def _parse_sections(body: str) -> dict[str, str]:
    lines = body.splitlines()
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := _HEADING_RE.fullmatch(line)) is not None
    ]
    if [heading for _, heading in headings] != list(_SECTION_HEADINGS):
        raise ValueError("invalid format")
    if any(line.strip() for line in lines[: headings[0][0]]):
        raise ValueError("invalid format")

    sections: dict[str, str] = {}
    for index, (start, heading) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start + 1 : end]).strip()
        if not content:
            raise ValueError("invalid format")
        sections[heading] = content
    return sections


def _bounded_catalog(
    definitions: Mapping[str, SkillDefinition],
    *,
    diagnostic: Callable[[str], None] | None,
) -> dict[str, SkillDefinition]:
    selected: dict[str, SkillDefinition] = {}
    catalog = "\n".join(_CATALOG_HEADER)
    truncated = False
    for name, skill in definitions.items():
        line = f"- {skill.name} — {skill.trigger}"
        candidate = f"{catalog}\n{line}"
        if len(selected) >= _MAX_CATALOG_ENTRIES or len(candidate.encode()) > _MAX_CATALOG_BYTES:
            truncated = True
            break
        selected[name] = skill
        catalog = candidate
    if truncated and diagnostic is not None:
        diagnostic("skill catalog truncated")
    return selected


def _render_full_skill(skill: SkillDefinition) -> str:
    rendered = (
        f"---\nname: {skill.name}\ntrigger: {skill.trigger}\n---\n\n"
        f"## Steps\n\n{skill.steps}\n\n"
        f"## Failure Branches\n\n{skill.failure_branches}\n\n"
        f"## Completion Criteria\n\n{skill.completion_criteria}\n"
    )
    if skill.format_version == 2:
        rendered = rendered.replace(
            "---\n\n",
            "format_version: 2\nexit_conditions:\n"
            + "".join(
                f"  {name}:\n    condition: {item.condition}\n    verifier: {item.verifier}\n"
                for name, item in skill.exit_conditions.items()
            )
            + "---\n\n",
            1,
        )
        rendered += (
            "\n## Exit Conditions\n\n" + _render_exit_conditions(skill.exit_conditions) + "\n"
        )
    return rendered


def _render_exit_conditions(conditions: Mapping[str, SkillExitCondition]) -> str:
    return "\n".join(
        f"### {name}\n- condition: {item.condition}\n- verifier: {item.verifier}"
        for name, item in conditions.items()
    )


def _emit_ignored(
    diagnostic: Callable[[str], None] | None,
    reason: str,
    directory_name: str,
) -> None:
    if diagnostic is not None:
        bounded_name = directory_name if _SKILL_NAME_RE.fullmatch(directory_name) else "unknown"
        bounded_reason = (
            reason
            if reason
            in {
                "invalid format",
                "invalid format version",
                "invalid exit contract",
                "invalid name",
                "invalid trigger",
            }
            else "invalid format"
        )
        diagnostic(f"skill ignored: {bounded_reason} ({bounded_name})")
