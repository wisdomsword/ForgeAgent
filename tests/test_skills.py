"""User-level SKILL.md discovery and validation tests."""

from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from forgeagent.skills import SkillDefinition, SkillExitCondition, SkillRegistry

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

_GOVERNED_REVIEW_SKILL = """---
name: review-python
trigger: Use when reviewing Python.
format_version: 2
exit_conditions:
  success:
    condition: Review report exists and names each finding.
    verifier: reviewer checks the saved report and finding count.
  failure:
    condition: A required source file cannot be read.
    verifier: tool result records the read error.
  blocked:
    condition: Required approval is unavailable.
    verifier: approval gate records the missing approver.
  needs_input:
    condition: The task lacks a target branch.
    verifier: user response records the branch name.
  timeout_or_budget:
    condition: The loop reaches its configured round budget.
    verifier: loop checkpoint records the budget stop.
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


def _governed_skill_with(replacement: str) -> str:
    return _GOVERNED_REVIEW_SKILL.replace(
        "condition: Review report exists and names each finding.", replacement
    )


def test_registry_accepts_512_utf8_byte_exit_text(tmp_path):
    condition = ("界" * 170) + "ab"
    assert len(condition.encode("utf-8")) == 512
    document = _governed_skill_with(f"condition: {condition}")
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    assert registry._definitions["review-python"].exit_conditions["success"].condition == condition


def test_registry_accepts_governed_skill_and_reads_exit_conditions(tmp_path):
    _write_raw_skill(tmp_path / "home", "review-python", _GOVERNED_REVIEW_SKILL)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    definition = registry._definitions["review-python"]
    assert definition.format_version == 2
    assert "success" in definition.exit_conditions
    assert "## Exit Conditions" in registry.read("review-python")
    assert "round budget" in registry.read("review-python", "exit_conditions")


@pytest.mark.parametrize(
    "document",
    [
        _GOVERNED_REVIEW_SKILL.replace("  blocked:\n", "  # blocked omitted\n"),
        _GOVERNED_REVIEW_SKILL.replace(
            "condition: Review report exists and names each finding.",
            "condition: " + ("x" * 513),
        ),
        _governed_skill_with("condition: " + ("界" * 171)),
        _GOVERNED_REVIEW_SKILL.replace(
            "verifier: reviewer checks the saved report and finding count.",
            "verifier: " + ("界" * 171),
            1,
        ),
        _governed_skill_with('condition: ""'),
        _governed_skill_with("condition: 123"),
        _GOVERNED_REVIEW_SKILL.replace(
            "verifier: reviewer checks the saved report and finding count.",
            'verifier: ""',
            1,
        ),
        _GOVERNED_REVIEW_SKILL.replace(
            "verifier: reviewer checks the saved report and finding count.",
            "verifier: 123",
            1,
        ),
        _GOVERNED_REVIEW_SKILL.replace(
            "    verifier: reviewer checks the saved report and finding count.\n",
            "",
            1,
        ),
        _GOVERNED_REVIEW_SKILL.replace(
            "    condition: Review report exists and names each finding.\n",
            "",
            1,
        ),
        _GOVERNED_REVIEW_SKILL.replace(
            "    verifier: reviewer checks the saved report and finding count.\n",
            "    verifier: reviewer checks the saved report and finding count.\n"
            "    extra: unsupported\n",
            1,
        ),
        _GOVERNED_REVIEW_SKILL.replace(
            "  timeout_or_budget:\n",
            "  unexpected:\n"
            "    condition: Unexpected state exists.\n"
            "    verifier: test observes the unexpected state.\n"
            "  timeout_or_budget:\n",
            1,
        ),
        _governed_skill_with("condition: 100% complete"),
    ],
)
def test_registry_rejects_invalid_governed_exit_contract(tmp_path, document):
    diagnostics: list[str] = []
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == ["skill ignored: invalid exit contract (review-python)"]


def test_registry_rejects_unsupported_format_version(tmp_path):
    diagnostics: list[str] = []
    _write_raw_skill(
        tmp_path / "home",
        "review-python",
        _FULL_REVIEW_SKILL.replace(
            "trigger: Use when reviewing Python.\n",
            "trigger: Use when reviewing Python.\nformat_version: 3\n",
        ),
    )

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == ["skill ignored: invalid format version (review-python)"]


def test_registry_rejects_duplicate_nested_exit_keys(tmp_path):
    diagnostics: list[str] = []
    document = _GOVERNED_REVIEW_SKILL.replace(
        "    verifier: reviewer checks the saved report and finding count.\n",
        "    verifier: reviewer checks the saved report and finding count.\n"
        "    verifier: duplicate verifier.\n",
        1,
    )
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == ["skill ignored: invalid exit contract (review-python)"]


def test_registry_isolates_recursive_yaml_alias(tmp_path):
    diagnostics: list[str] = []
    document = _GOVERNED_REVIEW_SKILL.replace(
        (
            "  success:\n"
            "    condition: Review report exists and names each finding.\n"
            "    verifier: reviewer checks the saved report and finding count."
        ),
        (
            "  success: &success\n"
            "    condition: Review report exists and names each finding.\n"
            "    verifier: *success"
        ),
    )
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == ["skill ignored: invalid exit contract (review-python)"]


def test_registry_rejects_control_characters_in_exit_contract(tmp_path):
    diagnostics: list[str] = []
    document = _governed_skill_with('condition: "ok\\nINJECT"')
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.catalog_prompt() == ""
    assert diagnostics == ["skill ignored: invalid exit contract (review-python)"]


def test_registry_keeps_legacy_skill_explicitly_version_one(tmp_path):
    _write_raw_skill(tmp_path / "home", "review-python", _FULL_REVIEW_SKILL)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    definition = registry._definitions["review-python"]
    assert definition.format_version == 1
    assert definition.exit_conditions == {}
    assert registry.read("review-python") == _FULL_REVIEW_SKILL


def test_skill_definition_exit_conditions_are_immutable():
    definition = SkillDefinition(
        name="review-python",
        trigger="Review Python.",
        steps="Read.",
        failure_branches="Stop.",
        completion_criteria="Report.",
        source="user",
        format_version=2,
        exit_conditions={
            "success": SkillExitCondition("report exists", "test checks report"),
        },
    )

    with pytest.raises(TypeError):
        definition.exit_conditions["failure"] = SkillExitCondition("x", "y")


def test_governed_exit_conditions_mask_sensitive_values(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "secret-value")
    document = _GOVERNED_REVIEW_SKILL.replace(
        "condition: Review report exists and names each finding.",
        "condition: Review report uses secret-value as a redaction marker.",
    ).replace(
        "verifier: reviewer checks the saved report and finding count.",
        "verifier: reviewer checks secret-value is absent from the report.",
    )
    _write_raw_skill(tmp_path / "home", "review-python", document)

    registry = SkillRegistry.load(
        home=str(tmp_path / "home"),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    full = registry.read("review-python")
    exits = registry.read("review-python", "exit_conditions")
    assert "secret-value" not in full
    assert "secret-value" not in exits


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


def _standard_skill_document(
    *, name: str = "find-skills", description: str = "Helps users discover agent skills.", body: str
) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def test_registry_loads_standard_sdk_skill_in_compat_mode(tmp_path):
    body = "## Usage\n\n1. Search for a skill.\n\n2. Install it.\n"
    document = _standard_skill_document(
        description="Help discover agent skills on demand.", body=body
    )
    home = tmp_path / "home"
    _write_raw_skill(home, "find-skills", document)
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    skill = registry._definitions["find-skills"]
    assert skill.trigger == "Help discover agent skills on demand."
    assert skill.steps == body.strip()
    assert "no explicit failure branches" in skill.failure_branches
    assert "completes when its steps have been followed" in skill.completion_criteria
    assert skill.format_version == 1
    assert skill.source == "user"
    assert registry.read("find-skills", "steps") == body.strip()
    assert "find-skills — Help discover agent skills on demand." in registry.catalog_prompt()
    assert diagnostics == ["skill loaded in standard Skills SDK compatibility mode: find-skills"]


def test_registry_standard_skill_body_truncated_to_memory_bound(tmp_path):
    oversized_body = "## Usage\n\n" + ("x" * (32 * 1024)) + "\n"
    document = _standard_skill_document(description="Truncated skill.", body=oversized_body)
    home = tmp_path / "home"
    _write_raw_skill(home, "find-skills", document)

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    steps = registry._definitions["find-skills"].steps
    assert len(steps.encode("utf-8")) <= 32 * 1024
    assert steps.endswith("x")


def test_registry_bounds_oversized_skill_disk_read_before_parsing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _write_raw_skill(home, "find-skills", _standard_skill_document(body="x" * (300 * 1024)))
    _write_skill(home, "review-python", trigger="Review Python.")
    oversized = home / ".forgeagent" / "skills" / "find-skills" / "SKILL.md"
    oversized = oversized.resolve()
    original_open = Path.open
    requested_sizes = []

    def record_read_bound(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == oversized:
            original_read = handle.read

            def read(size=-1):
                requested_sizes.append(size)
                return original_read(size)

            monkeypatch.setattr(handle, "read", read)
        return handle

    monkeypatch.setattr(Path, "open", record_read_bound)

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    assert registry.read("find-skills") is None
    assert registry.read("review-python") is not None
    assert requested_sizes == [256 * 1024 + 1]


def test_registry_standard_skill_trigger_derived_bounded_and_single_line(tmp_path):
    long_description = " ".join(f"word{i}" for i in range(100))
    assert len(long_description) > 240
    document = _standard_skill_document(
        description=long_description, body="## Usage\n\n1. Do it.\n"
    )
    home = tmp_path / "home"
    _write_raw_skill(home, "find-skills", document)

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
    )

    trigger = registry._definitions["find-skills"].trigger
    assert len(trigger) <= 240
    assert "\n" not in trigger and "\r" not in trigger


@pytest.mark.parametrize(
    ("document", "name", "reason"),
    [
        (
            _standard_skill_document(description="No body here.", body="   \n"),
            "find-skills",
            "invalid format",
        ),
        (
            _standard_skill_document(description="   \n", body="## Usage\n\n1. Do it.\n"),
            "find-skills",
            "invalid format",
        ),
        ("---\nname: find-skills\n---\n\n## Usage\n", "find-skills", "invalid format"),
        (
            _standard_skill_document(description="Mismatch.", body="## Usage\n"),
            "wrong-name",
            "invalid name",
        ),
        (
            _standard_skill_document(
                description="Too large.", body="## Usage\n\n" + ("x" * (300 * 1024)) + "\n"
            ),
            "find-skills",
            "invalid format",
        ),
    ],
)
def test_registry_rejects_invalid_standard_skills(tmp_path, document, name, reason):
    home = tmp_path / "home"
    _write_raw_skill(home, name, document)
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.read(name) is None
    assert diagnostics == [f"skill ignored: {reason} ({name})"]


def test_registry_trigger_and_description_hybrid_rejected(tmp_path):
    document = _FULL_REVIEW_SKILL.replace(
        "trigger: Use when reviewing Python.\n",
        "trigger: Use when reviewing Python.\ndescription: Hybrid skill.\n",
    )
    home = tmp_path / "home"
    _write_raw_skill(home, "review-python", document)
    diagnostics: list[str] = []

    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(tmp_path / "root"),
        allow_project=False,
        diagnostic=diagnostics.append,
    )

    assert registry.read("review-python") is None
    assert diagnostics == ["skill ignored: invalid format (review-python)"]


def test_registry_standard_skill_raw_digest_binds_full_on_disk_content(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    trust_record_path = tmp_path / "skills-trust.json"
    # Place a unique marker beyond the 32KB truncation point so a change there alters the
    # raw on-disk content but not the truncated in-memory body.
    prefix = "## Usage\n\n"
    pad = (32 * 1024) - len(prefix) + 50
    document = _standard_skill_document(
        description="Binds full content.", body=prefix + ("x" * pad) + "MARKER_TAIL"
    )
    project_skill = root / ".forgeagent" / "skills" / "find-skills"
    project_skill.mkdir(parents=True)
    project_skill.joinpath("SKILL.md").write_text(document, encoding="utf-8")

    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        trust_record_path=str(trust_record_path),
    )
    # Flip the marker beyond the truncation point: the effective body is unchanged,
    # but the raw digest must change so the trust record is re-confirmed.
    mutated = document.replace("MARKER_TAIL", "MARKER_TAIL_y")
    project_skill.joinpath("SKILL.md").write_text(mutated, encoding="utf-8")
    prompts = []
    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: prompts.append(request) or True,
        trust_record_path=str(trust_record_path),
    )

    assert len(prompts) == 1


def test_registry_standard_skill_digest_stable_when_unchanged(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    _write_skill(home, "review-python", trigger="user trigger")
    document = _standard_skill_document(
        description="Stable digest.", body="## Usage\n\n1. Do it.\n"
    )
    project_skill = root / ".forgeagent" / "skills" / "find-skills"
    project_skill.mkdir(parents=True)
    project_skill.joinpath("SKILL.md").write_text(document, encoding="utf-8")
    approvals = []
    trust_record_path = tmp_path / "skills-trust.json"

    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: approvals.append(request) or True,
        trust_record_path=str(trust_record_path),
    )
    assert len(approvals) == 1

    # A second load with unchanged content must not re-prompt for trust.
    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: pytest.fail("unchanged compat skill must not re-prompt"),
        trust_record_path=str(trust_record_path),
    )
    assert registry.read("find-skills", "steps") == "## Usage\n\n1. Do it."
    assert "find-skills — Stable digest." in registry.catalog_prompt()


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


def test_project_governed_exit_change_reconfirms_effective_digest(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    trust_record_path = tmp_path / "skills-trust.json"
    _write_raw_skill(home, "review-python", _FULL_REVIEW_SKILL)
    _write_raw_skill(root, "review-python", _GOVERNED_REVIEW_SKILL)

    SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda _request: True,
        trust_record_path=str(trust_record_path),
    )
    changed = _GOVERNED_REVIEW_SKILL.replace(
        "verifier: reviewer checks the saved report and finding count.",
        "verifier: independent reviewer checks the saved report and finding count.",
        1,
    )
    _write_raw_skill(root, "review-python", changed)
    prompts: list[object] = []
    registry = SkillRegistry.load(
        home=str(home),
        allowed_root=str(root),
        confirmer=lambda request: prompts.append(request) or False,
        trust_record_path=str(trust_record_path),
    )

    assert prompts
    assert registry.catalog_prompt().endswith("review-python — Use when reviewing Python.")


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
