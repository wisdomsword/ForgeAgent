from __future__ import annotations

import re
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
        for expected in ("phase: archive", "verify_result: pass", "archived: true"):
            assert expected in state, f"{archive.name} missing {expected}"
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
        for heading in ("## ADDED Requirements", "## MODIFIED Requirements", "## REMOVED Requirements"):
            assert heading not in text, f"delta heading in canonical spec: {spec.parent.name}"


def test_current_baseline_is_not_replaced_by_historical_sources() -> None:
    latest_name = _read(ROOT / "milestones" / "latest").strip()
    latest_number = int(re.search(r"(\d+)", latest_name).group(1))
    borrowing = _read(
        ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-借鉴清单.md"
    )
    baseline_number = int(re.search(r"forgeagent_baseline: M(\d+)", borrowing).group(1))

    assert (ROOT / "milestones" / latest_name).exists()
    assert latest_number >= 44
    assert baseline_number >= 44
    assert "manager-owned public discovery snapshot" in _read(
        ROOT / "openspec" / "specs" / "mcp-progressive-disclosure" / "spec.md"
    )
    assert (ROOT / "openspec" / "specs" / "http-action-approvals" / "spec.md").exists()
