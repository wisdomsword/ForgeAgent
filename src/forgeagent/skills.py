"""Validated, immutable snapshots of local ``SKILL.md`` definitions."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import yaml

from forgeagent.secret_policy import mask_secrets, sensitive_env_values

if TYPE_CHECKING:
    from forgeagent.identity import IdentityConfirmer


_MAX_SKILL_BYTES = 32 * 1024
_MAX_CATALOG_BYTES = 16 * 1024
_MAX_CATALOG_ENTRIES = 64
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_HEADING_RE = re.compile(r"^## ([^\r\n]+)\s*$")
_SECTION_HEADINGS = ("Steps", "Failure Branches", "Completion Criteria")
_CATALOG_HEADER = (
    "## Available Skills",
    "",
    "Choose a skill when its trigger matches the task. Read it with the Skill tool before "
    "following it.",
)


@dataclass(frozen=True)
class SkillDefinition:
    """A validated local skill document with its trusted discovery source."""

    name: str
    trigger: str
    steps: str
    failure_branches: str
    completion_criteria: str
    source: Literal["user", "project"]


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
        """Load the user-level snapshot.

        Project skills require an identity confirmation flow and are intentionally deferred
        until that trust boundary is added.
        """
        del allowed_root, confirmer, allow_project, trust_record_path
        user = _discover(
            Path(home) / ".forgeagent" / "skills",
            source="user",
            diagnostic=diagnostic,
        )
        return cls(_bounded_catalog(user, diagnostic=diagnostic))

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
            continue
        skill_file = child / "SKILL.md"
        skill_real = _contained_regular_file(skill_file, root_real)
        if skill_real is None:
            continue
        try:
            if os.stat(skill_real).st_size > _MAX_SKILL_BYTES:
                raise ValueError("invalid format")
            document = Path(skill_real).read_text(encoding="utf-8")
            definition = _parse_document(document, source=source, expected_name=directory_name)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            _emit_ignored(diagnostic, "invalid format", directory_name)
            continue
        except ValueError as error:
            _emit_ignored(diagnostic, str(error), directory_name)
            continue
        definitions.setdefault(definition.name, definition)
    return definitions


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
        front_matter = yaml.safe_load(front_matter_text)
    except ValueError:
        raise
    except yaml.YAMLError as error:
        if _has_malformed_multiline_trigger(front_matter_text):
            raise ValueError("invalid trigger") from error
        raise ValueError("invalid format") from error
    if not isinstance(front_matter, dict) or set(front_matter) != {"name", "trigger"}:
        raise ValueError("invalid format")
    name = front_matter["name"]
    trigger = front_matter["trigger"]
    if not isinstance(name, str) or not _SKILL_NAME_RE.fullmatch(name) or name != expected_name:
        raise ValueError("invalid name")
    if not isinstance(trigger, str) or not trigger or "\n" in trigger or "\r" in trigger:
        raise ValueError("invalid trigger")

    sections = _parse_sections(match.group(2))
    secret_values = sensitive_env_values()
    return SkillDefinition(
        name=mask_secrets(name, secret_values),
        trigger=mask_secrets(trigger, secret_values),
        steps=mask_secrets(sections["Steps"], secret_values),
        failure_branches=mask_secrets(sections["Failure Branches"], secret_values),
        completion_criteria=mask_secrets(sections["Completion Criteria"], secret_values),
        source=source,
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
    return (
        f"---\nname: {skill.name}\ntrigger: {skill.trigger}\n---\n\n"
        f"## Steps\n\n{skill.steps}\n\n"
        f"## Failure Branches\n\n{skill.failure_branches}\n\n"
        f"## Completion Criteria\n\n{skill.completion_criteria}\n"
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
            if reason in {"invalid format", "invalid name", "invalid trigger"}
            else "invalid format"
        )
        diagnostic(f"skill ignored: {bounded_reason} ({bounded_name})")
