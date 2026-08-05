import re
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
M43_MILESTONE = ROOT / "milestones" / "milestone_043.md"
M44_MILESTONE = ROOT / "milestones" / "milestone_044.md"
M45_MILESTONE = ROOT / "milestones" / "milestone_045.md"
M46_MILESTONE = ROOT / "milestones" / "milestone_046.md"
M43_VERIFY_REPORT = (
    ROOT / "docs" / "superpowers" / "reports" / "2026-07-31-executor-rewrite-baseline-verify.md"
)
M43_ARCHIVE = (
    ROOT / "openspec" / "changes" / "archive" / "2026-07-31-measure-executor-rewrite-baseline"
)
M43_ACTIVE = ROOT / "openspec" / "changes" / "measure-executor-rewrite-baseline"
M43_BASELINE = ROOT / "docs" / "evaluation" / "m43" / "rewrite-dependency-baseline.md"
M43_EVIDENCE = ROOT / "docs" / "evaluation" / "m43" / "executor-rewrite-baseline.json"
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


def test_review_documents_track_latest_runtime_baseline() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    latest_name = _read(LATEST).strip()
    latest_number = int(latest_name.removeprefix("milestone_").removesuffix(".md"))
    borrowing_baseline = re.search(
        r"(?m)^forgeagent_baseline: M(?P<number>\d+).*milestones/(?P<path>milestone_\d+\.md)",
        borrowing,
    )
    process_baseline = re.search(
        r"(?m)^> 当前基线：ForgeAgent M(?P<number>\d+).*milestones/(?P<path>milestone_\d+\.md)",
        process,
    )
    assert borrowing_baseline is not None
    assert process_baseline is not None
    for baseline in (borrowing_baseline, process_baseline):
        assert int(baseline.group("number")) == latest_number
        assert baseline.group("path") == latest_name
    assert "- 状态: 已完成并归档" in _read(ROOT / "milestones" / latest_name)
    assert "runtime-skill-exit-contract" in process
    assert "运行时 Skill 自动拒绝已由" in process
    assert "change 落地并归档" in process
    assert "M42 Memory 元数据迁移能力均已归档" in process
    assert "真实 readiness 为 `no_data`" in borrowing
    assert "M43" in process
    assert "最终 verdict 为 `keep_python`" in process
    assert "单模块试验" in process
    assert "M41 首次" in process
    assert "运行时依赖仍为 8" in process
    assert "M45" in process
    assert "基线一致性" in process
    assert "M46" in process
    assert "文档入口" in process


def test_http_action_approval_binding_is_complete_but_remote_exposure_is_conditional() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    assert "HTTP 远程动作审批绑定" in borrowing
    assert "M44 已交付“HTTP 远程动作审批绑定”的 loopback 控制面范围" in borrowing
    assert "外部可达 HTTP 控制面" in process
    assert "当前 HTTP 仍是 loopback-only" in process
    assert "复用 M44 已交付的审批绑定" in process


def test_next_step_summary_lists_all_conditional_items() -> None:
    borrowing = _read(BORROWING)
    expected = "未来仅保留新的单模块 Rewrite/依赖试验与外部可达 HTTP 控制面扩展"
    assert expected in borrowing
    assert "真实触发后另立 change" in borrowing


def test_m33_and_receipt_purpose_are_traceable() -> None:
    assert "M33" in _read(PLAN)
    assert "M34" in _read(PLAN)
    assert "M40" in _read(PLAN)
    assert "M41" in _read(PLAN)
    assert "M42" in _read(PLAN)
    assert "M43" in _read(PLAN)
    assert "M44" in _read(PLAN)
    assert "M45" in _read(PLAN)
    assert "M46" in _read(PLAN)
    assert "M47" in _read(PLAN)
    assert "M48" in _read(PLAN)
    assert "M49" in _read(PLAN)
    assert _read(LATEST).strip() == "milestone_049.md"
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
    assert "M44 无未完成任务" in _read(M44_MILESTONE)
    assert "M45 范围内无未完成任务" in _read(M45_MILESTONE)
    assert "M46" in _read(M46_MILESTONE)
    assert "文档入口" in _read(M46_MILESTONE)


def test_m43_rewrite_baseline_completion_is_traceable() -> None:
    change = M43_ARCHIVE if M43_ARCHIVE.is_dir() else M43_ACTIVE
    assert change.is_dir()
    if change == M43_ARCHIVE:
        assert "archived: true" in _read(change / ".comet.yaml")
    baseline = _read(M43_BASELINE)
    assert "最终 verdict：`keep_python`" in baseline
    assert "不授权 Rust 重写" in baseline
    assert '"verdict": "keep_python"' in _read(M43_EVIDENCE)
    report = _read(M43_VERIFY_REPORT)
    assert "六项指标" in report
    assert "container" in report
    assert "not_available" in report
    milestone = _read(M43_MILESTONE)
    assert "最终 verdict" in milestone
    assert "openspec/changes/archive/2026-07-31-measure-executor-rewrite-baseline" in milestone


def test_m42_memory_migration_completion_is_traceable() -> None:
    assert M42_ARCHIVE.is_dir()
    assert "archived: true" in _read(M42_ARCHIVE / ".comet.yaml")
    report = _read(M42_VERIFY_REPORT)
    assert "6/6 requirements、23/23 scenarios" in report
    assert "2636 passed, 10 skipped" in report
    assert "migration_skipped" in report
    milestone = _read(M42_MILESTONE)
    assert "memory_absent" in milestone
    assert "openspec/changes/archive/2026-07-31-migrate-memory-metadata" in milestone


def test_current_cli_spec_and_m41_historical_counts_are_traceable() -> None:
    spec = _read(CLI_BOUNDARY_SPEC)
    assert spec.count("### Requirement:") == 4
    assert spec.count("#### Scenario:") == 10
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
