"""User-level SKILL.md discovery and validation tests."""

from __future__ import annotations

import json
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
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "SKILL.md").write_text(document, encoding="utf-8")


def _write_skill(home, name: str, *, trigger: str) -> None:
    _write_raw_skill(home, name, _skill_document(name=name, trigger=trigger))


def _write_project_skill(root, name: str, *, trigger: str) -> None:
    _write_skill(root, name, trigger=trigger)


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


def test_project_skills_override_only_after_approval_and_reuse_double_digest(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    _write_project_skill(root, "review-python", trigger="project trigger")
    approvals = []
    trust_record_path = tmp_path / "skills-trust.json"

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: approvals.append(request) or True,
        trust_record_path=str(trust_record_path),
    )

    assert registry.catalog_prompt().endswith("review-python — project trigger")
    assert len(approvals) == 1
    unchanged = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: pytest.fail("unchanged project skills must not prompt"),
        trust_record_path=str(trust_record_path),
    )
    assert unchanged.read("review-python") == registry.read("review-python")
    record = json.loads(trust_record_path.read_text(encoding="utf-8"))
    assert record["version"] == 1 and len(record["projects"]) == 1


def test_project_skill_reconfirmation_detects_raw_and_effective_digest_changes(
    tmp_path, monkeypatch
):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    trust_record_path = tmp_path / "skills-trust.json"
    monkeypatch.setenv("PROJECT_TOKEN", "first-secret")
    _write_project_skill(root, "review-python", trigger="Use first-secret.")

    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        trust_record_path=str(trust_record_path),
    )
    monkeypatch.setenv("PROJECT_TOKEN", "second-secret")
    _write_project_skill(root, "review-python", trigger="Use second-secret.")
    raw_changed = []
    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: raw_changed.append(request) or False,
        trust_record_path=str(trust_record_path),
    )
    assert raw_changed and registry.catalog_prompt().endswith("review-python — user trigger")

    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        trust_record_path=str(trust_record_path),
    )
    monkeypatch.delenv("PROJECT_TOKEN")
    effective_changed = []
    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: effective_changed.append(request) or False,
        trust_record_path=str(trust_record_path),
    )
    assert effective_changed and registry.catalog_prompt().endswith("review-python — user trigger")


def test_unapproved_or_unwritable_project_skill_keeps_user_definition(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    _write_project_skill(root, "review-python", trigger="project trigger")

    registry = SkillRegistry.load(home=str(home), allowed_root=str(root), confirmer=None)
    assert registry.catalog_prompt().endswith("review-python — user trigger")

    import forgeagent.identity as identity_module

    monkeypatch.setattr(
        identity_module,
        "_atomic_write_trust_record",
        lambda *_args: (_ for _ in ()).throw(PermissionError("no")),
    )
    diagnostics = []
    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        diagnostic=diagnostics.append,
    )
    assert registry.catalog_prompt().endswith("review-python — project trigger")
    assert diagnostics == ["skill trust record unavailable"]


def test_unusable_project_skill_record_is_never_overwritten_after_approval(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    _write_project_skill(root, "review-python", trigger="project trigger")
    trust_record_path = tmp_path / "skills-trust.json"
    original = "{corrupted"
    trust_record_path.write_text(original, encoding="utf-8")
    diagnostics = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        trust_record_path=str(trust_record_path),
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt().endswith("review-python — project trigger")
    assert trust_record_path.read_text(encoding="utf-8") == original
    assert diagnostics == ["skill trust record ignored: _UnusableTrustRecordError"]


def test_trusted_project_snapshot_overlays_complete_mapping_and_bounds_masked_summary(
    tmp_path, monkeypatch
):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user review")
    _write_skill(home, "user-only", trigger="user only")
    monkeypatch.setenv("PROJECT_TOKEN", "summary-secret")
    for index in range(3):
        name = "review-python" if index == 0 else f"project-{index}"
        _write_project_skill(root, name, trigger=f"summary-secret {'x' * 4090}")
    approvals = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: approvals.append(request) or True,
    )

    assert registry.read("user-only") is not None
    assert registry.catalog_prompt().count("review-python") == 1
    assert "project-1" in registry.catalog_prompt() and "project-2" in registry.catalog_prompt()
    assert len(approvals) == 1
    summary = approvals[0].summary
    assert "summary-secret" not in summary
    assert len(summary.encode()) <= 8 * 1024
    assert "summary truncated" in summary


def test_project_skill_trust_summary_redacts_paths_and_escapes_controls(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    document = _FULL_REVIEW_SKILL.replace(
        "trigger: Use when reviewing Python.",
        'trigger: "Use /private/review-secret \\x1b[31m safely."',
    )
    _write_raw_skill(root, "review-python", document)
    summaries = []

    for index in range(2):
        SkillRegistry.load(
            home=str(home),
            allowed_root=str(root),
            confirmer=lambda request: summaries.append(request.summary) or True,
            trust_record_path=str(tmp_path / f"skills-trust-{index}.json"),
        )

    assert summaries == [summaries[0], summaries[0]]
    assert "/private/review-secret" not in summaries[0]
    assert "\x1b" not in summaries[0]
    assert "Use <redacted-path>" in summaries[0]
    assert r"\x1b[31m safely." in summaries[0]
    assert len(summaries[0].encode()) <= 8 * 1024
