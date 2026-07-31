from pathlib import Path

ROOT = Path(__file__).parents[1]
BORROWING = ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-借鉴清单.md"
PROCESS = ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md"
PLAN = ROOT / "ACTION_PLAN.md"
M33_MILESTONE = ROOT / "milestones" / "milestone_033.md"
M34_MILESTONE = ROOT / "milestones" / "milestone_034.md"
CURRENT_MILESTONE = ROOT / "milestones" / "milestone_039.md"
M40_MILESTONE = ROOT / "milestones" / "milestone_040.md"
M41_MILESTONE = ROOT / "milestones" / "milestone_041.md"
M42_MILESTONE = ROOT / "milestones" / "milestone_042.md"
LATEST = ROOT / "milestones" / "latest"
RECEIPT_SPEC = ROOT / "openspec" / "specs" / "external-action-receipts" / "spec.md"
BORROWING_SPEC = ROOT / "openspec" / "specs" / "borrowing-review-baseline" / "spec.md"
CLI_BOUNDARY_SPEC = ROOT / "openspec" / "specs" / "cli-boundary-maintainability" / "spec.md"
M41_VERIFY_REPORT = (
    ROOT / "docs" / "superpowers" / "reports" / "2026-07-31-cli-boundary-extraction-verify.md"
)
M41_DOCUMENT_AUDIT = ROOT / "docs" / "reviews" / "2026-07-31-M41文档完成度审计.md"
M42_VERIFY_REPORT = (
    ROOT / "docs" / "superpowers" / "reports" / "2026-07-31-memory-metadata-migration-verify.md"
)
M42_ARCHIVE = ROOT / "openspec" / "changes" / "archive" / "2026-07-31-migrate-memory-metadata"
RETIRED_RELEASE_CHANGE = (
    ROOT
    / "openspec"
    / "changes"
    / "archive"
    / "2026-07-31-retired-pypi-publication-goal"
    / "publish-v0-1-0"
)
RETIRED_RELEASE_README = (
    ROOT
    / "openspec"
    / "changes"
    / "archive"
    / "2026-07-31-retired-pypi-publication-goal"
    / "README.md"
)
EXTERNAL_RECEIPT_ARCHIVE = (
    ROOT / "openspec" / "changes" / "archive" / "2026-07-30-external-action-receipts"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_borrowing_candidates_map_to_completed_evidence() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    expected = (
        "external-action-receipts",
        "M29",
        "M30",
        "M31",
        "M32",
        "已覆盖",
        "已完成",
    )
    for marker in expected:
        assert marker in borrowing, f"borrowing review missing: {marker}"
        assert marker in process, f"process review missing: {marker}"
    assert "不再表示待实施队列" in process
    assert "真实需求和独立 change" in process


def test_process_review_links_to_the_archived_receipt_change() -> None:
    process = _read(PROCESS)
    assert EXTERNAL_RECEIPT_ARCHIVE.is_dir()
    expected_link = "../../openspec/changes/archive/2026-07-30-external-action-receipts/"
    assert expected_link in process


def test_review_documents_track_m42_runtime_baseline() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    assert "forgeagent_baseline: M42" in borrowing
    assert "milestones/milestone_042.md" in borrowing
    assert "当前基线：ForgeAgent M42" in process
    assert "runtime-skill-exit-contract" in process
    assert "运行时 Skill 自动拒绝已由" in process
    assert "change 落地并归档" in process
    assert "M42 Memory 元数据迁移能力均已归档" in process
    assert "真实 readiness 为 `no_data`" in borrowing
    assert "未来新的 Rewrite/依赖变更" in process
    assert "M41 首次" in process
    assert "运行时依赖仍为 8" in process


def test_http_action_approval_binding_remains_conditional() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    assert "HTTP 远程动作审批绑定" in borrowing
    assert "当前 HTTP 仅 loopback" in borrowing
    assert "外部 HTTP 动作控制面" in process
    assert "当前 HTTP 仍是 loopback-only" in process
    assert "真实 verifier" in process


def test_next_step_summary_lists_all_conditional_items() -> None:
    borrowing = _read(BORROWING)
    expected = "未来新的 Rewrite/依赖变更与 HTTP 远程动作审批绑定"
    assert expected in borrowing
    assert "真实触发后另立 change" in borrowing


def test_m33_and_receipt_purpose_are_traceable() -> None:
    assert "M33" in _read(PLAN)
    assert "M34" in _read(PLAN)
    assert "M40" in _read(PLAN)
    assert "M41" in _read(PLAN)
    assert "M42" in _read(PLAN)
    assert _read(LATEST).strip() == "milestone_042.md"
    assert "Purpose: TBD" not in _read(RECEIPT_SPEC)
    assert "durable, bounded" in _read(RECEIPT_SPEC)
    assert "Purpose: TBD" not in _read(BORROWING_SPEC)
    assert "TBD - created by archiving change" not in _read(CLI_BOUNDARY_SPEC)
    assert "measurable, reversible boundaries" in _read(CLI_BOUNDARY_SPEC)
    milestone = _read(M33_MILESTONE)
    assert "external-action-receipts" in milestone
    assert "publish-v0-1-0" in milestone
    assert "M34" in _read(M34_MILESTONE)
    assert "M37" in _read(CURRENT_MILESTONE)
    assert "M38" in _read(CURRENT_MILESTONE)
    assert "M39" in _read(CURRENT_MILESTONE)
    assert "M40" in _read(M40_MILESTONE)
    assert "loop-handoff-contract" in _read(M40_MILESTONE)
    assert "M41 无未完成任务" in _read(M41_MILESTONE)
    assert "四处兼容/归属问题" in _read(M41_MILESTONE)
    assert "M42 无未完成任务" in _read(M42_MILESTONE)


def test_m42_memory_migration_completion_is_traceable() -> None:
    assert M42_ARCHIVE.is_dir()
    assert "archived: true" in _read(M42_ARCHIVE / ".comet.yaml")
    report = _read(M42_VERIFY_REPORT)
    assert "6/6 requirements、23/23 scenarios" in report
    assert "2635 passed, 10 skipped" in report
    assert "migration_skipped" in report
    milestone = _read(M42_MILESTONE)
    assert "memory_absent" in milestone
    assert "openspec/changes/archive/2026-07-31-migrate-memory-metadata" in milestone


def test_m41_documented_requirement_and_scenario_counts_match_the_spec() -> None:
    spec = _read(CLI_BOUNDARY_SPEC)
    assert spec.count("### Requirement:") == 4
    assert spec.count("#### Scenario:") == 9
    for document in (M41_VERIFY_REPORT, M41_DOCUMENT_AUDIT):
        content = _read(document)
        assert "4/4 requirements" in content
        assert "9/9 scenarios" in content


def test_removed_distribution_goal_is_retired_and_traceable() -> None:
    active_changes = ROOT / "openspec" / "changes"
    assert not (active_changes / "publish-v0-1-0").exists()
    assert RETIRED_RELEASE_CHANGE.is_dir()
    assert RETIRED_RELEASE_README.is_file()
    for name in ("proposal.md", "design.md", "tasks.md", "specs"):
        assert (RETIRED_RELEASE_CHANGE / name).exists()
    retirement = _read(RETIRED_RELEASE_README)
    for marker in ("撤销", "移除", "不提供恢复路径"):
        assert marker in retirement
    plan = _read(PROCESS)
    for marker in ("包索引发布", "正式 tag", "远程 push", "已撤销并归档"):
        assert marker in plan
