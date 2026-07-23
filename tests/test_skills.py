"""User-level SKILL.md discovery and validation tests."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError

import pytest

from forgeagent.skills import SkillDefinition, SkillRegistry

_FULL_REVIEW_SKILL = """---
name: review-python
trigger: Use when reviewing Python.
---

## Steps

1. Read the changed code.

## Failure Branches

- Ask for the missing context.

## Completion Criteria

- Report the findings.
"""


def _skill_document(
    *, name: str = "review-python", trigger: str = "Use when reviewing Python."
) -> str:
    return _FULL_REVIEW_SKILL.replace("name: review-python", f"name: {name}").replace(
        "trigger: Use when reviewing Python.", f"trigger: {trigger}"
    )


def _missing_front_matter() -> str:
    front_matter = "---\nname: review-python\ntrigger: Use when reviewing Python.\n---\n\n"
    return _FULL_REVIEW_SKILL.removeprefix(front_matter)


def _unknown_front_matter_key() -> str:
    return _FULL_REVIEW_SKILL.replace(
        "trigger: Use when reviewing Python.\n",
        "trigger: Use when reviewing Python.\nextra: no\n",
    )


def _duplicate_front_matter_key() -> str:
    return _FULL_REVIEW_SKILL.replace(
        "trigger: Use when reviewing Python.\n",
        "trigger: Use when reviewing Python.\ntrigger: Repeated metadata.\n",
    )


def _out_of_order_sections() -> str:
    steps_then_failure = (
        "## Steps\n\n"
        "1. Read the changed code.\n\n"
        "## Failure Branches\n\n"
        "- Ask for the missing context."
    )
    failure_then_steps = (
        "## Failure Branches\n\n"
        "- Ask for the missing context.\n\n"
        "## Steps\n\n"
        "1. Read the changed code."
    )
    return _FULL_REVIEW_SKILL.replace(
        steps_then_failure,
        failure_then_steps,
    )


def _empty_failure_branches() -> str:
    return _FULL_REVIEW_SKILL.replace("- Ask for the missing context.\n", "")


def _write_raw_skill(home, directory_name: str, document: str) -> None:
    destination = home / ".forgeagent" / "skills" / directory_name
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text(document, encoding="utf-8")


def _write_skill(home, name: str, *, trigger: str) -> None:
    _write_raw_skill(home, name, _skill_document(name=name, trigger=trigger))


def _skill_document_with_raw_size(size: int) -> str:
    padding = size - len(_FULL_REVIEW_SKILL.encode())
    assert padding >= 0
    return _FULL_REVIEW_SKILL.replace(
        "- Report the findings.\n",
        f"- Report the findings.{'x' * padding}\n",
    )


def test_registry_accepts_only_the_fixed_five_part_document(tmp_path):
    home, root = tmp_path / "home", tmp_path / "project"
    _write_skill(home, "review-python", trigger="Use when reviewing Python.")

    registry = SkillRegistry.load(home=str(home), allowed_root=str(root), allow_project=False)

    assert registry.read("review-python") == _FULL_REVIEW_SKILL
    assert "review-python" in registry.catalog_prompt()
    definition = registry._definitions["review-python"]
    assert isinstance(definition, SkillDefinition)
    with pytest.raises(FrozenInstanceError):
        definition.name = "changed"


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        (_missing_front_matter(), "invalid format"),
        (_unknown_front_matter_key(), "invalid format"),
        (_duplicate_front_matter_key(), "invalid format"),
        (_out_of_order_sections(), "invalid format"),
        (_empty_failure_branches(), "invalid format"),
        (_skill_document(name="wrong-name"), "invalid name"),
        (_skill_document(trigger="line one\nline two"), "invalid trigger"),
    ],
)
def test_registry_ignores_invalid_document_with_bounded_diagnostic(tmp_path, document, reason):
    diagnostics: list[str] = []
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == [f"skill ignored: {reason} (review-python)"]


def test_registry_rejects_user_symlink_escape_with_bounded_diagnostic(tmp_path, monkeypatch):
    home, root, outside = tmp_path / "home", tmp_path / "root", tmp_path / "outside"
    _write_skill(home, "review-python", trigger="Use $TOKEN before release.")
    _write_skill(outside, "escaped", trigger="do not disclose")
    user_skills = home / ".forgeagent" / "skills"
    os.symlink(
        outside / ".forgeagent" / "skills" / "escaped",
        user_skills / "escaped",
    )
    monkeypatch.setenv("TOKEN", "secret-value")
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert "secret-value" not in registry.catalog_prompt()
    assert registry.read("escaped") is None
    assert diagnostics == ["skill ignored: invalid format (escaped)"]


@pytest.mark.parametrize(
    ("raw_size", "accepted"),
    [
        (32 * 1024, True),
        (32 * 1024 + 1, False),
    ],
)
def test_registry_enforces_raw_skill_file_size_boundary(tmp_path, raw_size, accepted):
    home = tmp_path / "home"
    _write_raw_skill(
        home,
        "review-python",
        _skill_document_with_raw_size(raw_size),
    )
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert (registry.read("review-python") is not None) is accepted
    expected = [] if accepted else ["skill ignored: invalid format (review-python)"]
    assert diagnostics == expected


def test_catalog_uses_sorted_prefix_when_count_or_bytes_exceed_limit(tmp_path):
    home = tmp_path / "home"
    for index in range(65):
        _write_skill(home, f"skill-{index:02d}", trigger="x" * 240)
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    names = [line.split(" — ")[0][2:] for line in registry.catalog_prompt().splitlines()[3:]]
    assert names == sorted(names)
    assert len(names) <= 64
    assert len(registry.catalog_prompt().encode()) <= 16 * 1024
    assert diagnostics.count("skill catalog truncated") == 1
