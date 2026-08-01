from __future__ import annotations

import ast
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]

RESTORED_MILESTONES = tuple(
    ROOT / "milestones" / f"milestone_{number:03d}.md"
    for number in (29, 30, 31, 32, 35, 36, 37, 38)
)
RESTORED_ARCHIVES = tuple(
    ROOT / "openspec" / "changes" / "archive" / name
    for name in (
        "2026-07-30-align-borrowing-roadmap-baseline",
        "2026-07-30-attention-state-projection",
        "2026-07-30-mcp-progressive-disclosure",
        "2026-07-30-prompt-memory-rewrite-governance",
        "2026-07-30-runtime-skill-exit-contract",
        "2026-07-30-structured-collaboration-handoff",
        "2026-07-31-align-http-trigger-next-steps",
        "2026-07-31-document-http-action-approval-trigger",
        "2026-07-31-retire-pypi-publication-goal",
        "2026-07-31-sync-borrowing-review-m34-baseline",
    )
)
RESTORED_SUPERPOWERS = tuple(
    ROOT / path
    for path in (
        "docs/superpowers/plans/2026-07-30-attention-state-projection.md",
        "docs/superpowers/plans/2026-07-30-mcp-progressive-disclosure.md",
        "docs/superpowers/plans/2026-07-30-prompt-memory-rewrite-governance.md",
        "docs/superpowers/plans/2026-07-30-runtime-skill-exit-contract.md",
        "docs/superpowers/plans/2026-07-30-structured-collaboration-handoff.md",
        "docs/superpowers/reports/2026-07-30-align-borrowing-roadmap-baseline-verify.md",
        "docs/superpowers/reports/2026-07-30-attention-state-projection-verify.md",
        "docs/superpowers/reports/2026-07-30-mcp-progressive-disclosure-verify.md",
        "docs/superpowers/reports/2026-07-30-prompt-memory-rewrite-governance-verify.md",
        "docs/superpowers/reports/2026-07-30-runtime-skill-exit-contract-verify.md",
        "docs/superpowers/reports/2026-07-30-structured-collaboration-handoff-verify.md",
        "docs/superpowers/reports/2026-07-31-align-http-trigger-next-steps-verify.md",
        "docs/superpowers/reports/2026-07-31-document-http-action-approval-trigger-verify.md",
        "docs/superpowers/reports/2026-07-31-retire-pypi-publication-goal-verify.md",
        "docs/superpowers/reports/2026-07-31-sync-borrowing-review-m34-baseline-verify.md",
        "docs/superpowers/specs/2026-07-30-attention-state-projection-design.md",
        "docs/superpowers/specs/2026-07-30-mcp-progressive-disclosure-design.md",
        "docs/superpowers/specs/2026-07-30-prompt-memory-rewrite-governance-design.md",
        "docs/superpowers/specs/2026-07-30-runtime-skill-exit-contract-design.md",
        "docs/superpowers/specs/2026-07-30-structured-collaboration-handoff-design.md",
    )
)
RESTORED_CAPABILITIES = (
    "agent-governance-gates",
    "attention-state-protocol",
    "runtime-skill-exit-contract",
    "structured-collaboration-handoff",
)
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
M34_SKILL_VERIFIER_DIGEST = "16b81f2b349a79cd8e55cbdb967df40504766d0a913eeb64bf3ffde75791673c"
M34_TOOL_VERIFIER_DIGEST = "131666f42abe0139c180d601c8b0608b9b9419e9848efaae9396a70b7eafba9b"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _verifier_bundle_digest(
    path: Path,
    required_functions: tuple[str, ...],
    required_assignments: tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    source = _read(path)
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assignments = {
        node.targets[0].id: node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    missing = [name for name in required_functions if name not in functions]
    missing.extend(name for name in required_assignments if name not in assignments)
    if missing:
        return "", missing
    nodes = [assignments[name] for name in required_assignments]
    nodes.extend(functions[name] for name in required_functions)
    selected_sources = [
        (ast.get_source_segment(source, node) or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        for node in nodes
    ]
    payload = "\n\n".join(selected_sources).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), []


def test_m29_m38_lifecycle_whitelist_exists() -> None:
    required = (
        *RESTORED_MILESTONES,
        *RESTORED_ARCHIVES,
        *RESTORED_SUPERPOWERS,
        ROOT / "docs" / "agent-governance-gates.md",
        ROOT / "tests" / "test_governance_docs.py",
        ROOT / "docs" / "reviews" / "2026-08-01-m45-m29-m38-artifact-reconciliation.md",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    assert not missing, f"missing lifecycle artifacts: {missing}"


def test_recovered_archives_are_verified_terminal_changes() -> None:
    for archive in RESTORED_ARCHIVES:
        state = _read(archive / ".comet.yaml")
        for field, expected in (
            ("phase", "archive"),
            ("verify_result", "pass"),
            ("archived", "true"),
        ):
            assert re.search(rf"(?m)^{field}:\s*{expected}\s*$", state), (
                f"{archive.name} missing exact {field}: {expected}"
            )
    assert not (ROOT / "openspec" / "changes" / "publish-v0-1-0").exists()


def test_recovered_milestone_links_and_reconciliation_notes_are_valid() -> None:
    for milestone in RESTORED_MILESTONES:
        text = _read(milestone)
        assert "M45 对账注记" in text, f"missing reconciliation note: {milestone.name}"
        for target in MARKDOWN_LINK.findall(text):
            if "://" in target or target.startswith("#"):
                continue
            resolved = (milestone.parent / target.split("#", 1)[0]).resolve()
            assert resolved.exists(), f"broken link in {milestone.name}: {target}"
    assert "repair-mcp-progressive-disclosure-baseline" in _read(RESTORED_MILESTONES[1])


def test_restored_capability_has_current_or_active_delta_source() -> None:
    active = ROOT / "openspec" / "changes" / "reconcile-m29-m38-artifacts" / "specs"
    for capability in RESTORED_CAPABILITIES:
        canonical = ROOT / "openspec" / "specs" / capability / "spec.md"
        delta = active / capability / "spec.md"
        assert canonical.exists() or delta.exists(), f"missing spec source: {capability}"


def test_canonical_specs_have_descriptive_purpose_and_no_delta_headers() -> None:
    for spec in (ROOT / "openspec" / "specs").glob("*/spec.md"):
        text = _read(spec)
        assert "## Purpose" in text, f"missing Purpose: {spec.parent.name}"
        purpose = text.split("## Purpose", 1)[1].split("## Requirements", 1)[0].strip()
        assert purpose and "TBD - created by archiving" not in purpose, (
            f"placeholder Purpose: {spec.parent.name}"
        )
        for heading in (
            "## ADDED Requirements",
            "## MODIFIED Requirements",
            "## REMOVED Requirements",
        ):
            assert heading not in text, f"delta heading in canonical spec: {spec.parent.name}"


def test_current_baseline_is_not_replaced_by_historical_sources() -> None:
    latest_name = _read(ROOT / "milestones" / "latest").strip()
    latest_number = int(re.search(r"(\d+)", latest_name).group(1))
    borrowing = _read(ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-借鉴清单.md")
    baseline_number = int(re.search(r"forgeagent_baseline: M(\d+)", borrowing).group(1))

    assert (ROOT / "milestones" / latest_name).exists()
    assert latest_number >= 45
    assert baseline_number == latest_number
    assert "manager-owned public discovery snapshot" in _read(
        ROOT / "openspec" / "specs" / "mcp-progressive-disclosure" / "spec.md"
    )
    assert (ROOT / "openspec" / "specs" / "http-action-approvals" / "spec.md").exists()


def test_m34_runtime_skill_contract_keeps_executable_verifiers() -> None:
    required_skill_tests = (
        "_governed_skill_with",
        "test_registry_accepts_512_utf8_byte_exit_text",
        "test_registry_accepts_governed_skill_and_reads_exit_conditions",
        "test_registry_rejects_invalid_governed_exit_contract",
        "test_registry_rejects_unsupported_format_version",
        "test_registry_rejects_duplicate_nested_exit_keys",
        "test_registry_isolates_recursive_yaml_alias",
        "test_registry_rejects_control_characters_in_exit_contract",
        "test_registry_keeps_legacy_skill_explicitly_version_one",
        "test_skill_definition_exit_conditions_are_immutable",
        "test_governed_exit_conditions_mask_sensitive_values",
        "test_project_governed_exit_change_reconfirms_effective_digest",
    )
    skill_digest, missing = _verifier_bundle_digest(
        ROOT / "tests" / "test_skills.py",
        required_skill_tests,
        ("_FULL_REVIEW_SKILL", "_GOVERNED_REVIEW_SKILL"),
    )
    assert not missing, f"missing M34 runtime Skill verifiers: {missing}"
    assert skill_digest == M34_SKILL_VERIFIER_DIGEST, "M34 Skill verifier bundle changed"

    tool_digest, missing = _verifier_bundle_digest(
        ROOT / "tests" / "test_tools.py",
        ("test_skill_tool_returns_governed_exit_conditions_section",),
    )
    assert not missing, f"missing M34 SkillTool verifiers: {missing}"
    assert tool_digest == M34_TOOL_VERIFIER_DIGEST, "M34 SkillTool verifier changed"


def test_m34_verifier_digest_detects_selected_source_mutation(tmp_path: Path) -> None:
    source = """\
def keep(value):
    return value + 1
"""
    path = tmp_path / "verifier.py"
    path.write_text(source, encoding="utf-8")

    original, missing = _verifier_bundle_digest(path, ("keep",))
    assert not missing

    path.write_text(source.replace("+ 1", "+ 2"), encoding="utf-8")
    mutated, missing = _verifier_bundle_digest(path, ("keep",))
    assert not missing
    assert mutated != original


def test_m34_verifier_digest_is_stable_across_supported_interpreters() -> None:
    interpreters = [
        shutil.which(f"python{version}")
        for version in ("3.11", "3.12", "3.14")
    ]
    if not all(interpreters):
        return

    probe = """
import importlib.util
import pathlib
import sys

module_path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("lifecycle", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
digest, missing = module._verifier_bundle_digest(
    module.ROOT / "tests" / "test_skills.py",
    (
        "_governed_skill_with",
        "test_registry_accepts_512_utf8_byte_exit_text",
        "test_registry_accepts_governed_skill_and_reads_exit_conditions",
        "test_registry_rejects_invalid_governed_exit_contract",
        "test_registry_rejects_unsupported_format_version",
        "test_registry_rejects_duplicate_nested_exit_keys",
        "test_registry_isolates_recursive_yaml_alias",
        "test_registry_rejects_control_characters_in_exit_contract",
        "test_registry_keeps_legacy_skill_explicitly_version_one",
        "test_skill_definition_exit_conditions_are_immutable",
        "test_governed_exit_conditions_mask_sensitive_values",
        "test_project_governed_exit_change_reconfirms_effective_digest",
    ),
    ("_FULL_REVIEW_SKILL", "_GOVERNED_REVIEW_SKILL"),
)
assert not missing, missing
print(digest)
"""
    digests = [
        subprocess.check_output(
            [interpreter, "-c", probe, str(Path(__file__))],
            text=True,
        ).strip()
        for interpreter in interpreters
    ]
    assert len(set(digests)) == 1
