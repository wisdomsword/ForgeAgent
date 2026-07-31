from pathlib import Path

ROOT = Path(__file__).parents[1]
BORROWING = ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-借鉴清单.md"
PROCESS = ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md"
PLAN = ROOT / "ACTION_PLAN.md"
M33_MILESTONE = ROOT / "milestones" / "milestone_033.md"
LATEST_MILESTONE = ROOT / "milestones" / "milestone_034.md"
CURRENT_MILESTONE = ROOT / "milestones" / "milestone_039.md"
M40_MILESTONE = ROOT / "milestones" / "milestone_040.md"
LATEST = ROOT / "milestones" / "latest"
RECEIPT_SPEC = ROOT / "openspec" / "specs" / "external-action-receipts" / "spec.md"
BORROWING_SPEC = ROOT / "openspec" / "specs" / "borrowing-review-baseline" / "spec.md"
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


def test_review_documents_track_m34_runtime_baseline() -> None:
    borrowing = _read(BORROWING)
    process = _read(PROCESS)
    assert "forgeagent_baseline: M34" in borrowing
    assert "milestones/milestone_034.md" in borrowing
    assert "当前基线：ForgeAgent M34" in process
    assert "runtime-skill-exit-contract" in process
    assert "运行时 Skill 自动拒绝已由独立" in process
    assert "既有 Memory 元数据迁移" in process
    assert "新的 Rewrite/依赖变更" in process


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
    assert "既有 Memory 元数据迁移、新 Rewrite/依赖变更，以及 HTTP 远程动作审批绑定" in borrowing
    assert "真实触发后另立 change" in borrowing


def test_m33_and_receipt_purpose_are_traceable() -> None:
    assert "M33" in _read(PLAN)
    assert "M34" in _read(PLAN)
    assert "M40" in _read(PLAN)
    assert _read(LATEST).strip() == "milestone_040.md"
    assert "Purpose: TBD" not in _read(RECEIPT_SPEC)
    assert "durable, bounded" in _read(RECEIPT_SPEC)
    assert "Purpose: TBD" not in _read(BORROWING_SPEC)
    milestone = _read(M33_MILESTONE)
    assert "external-action-receipts" in milestone
    assert "publish-v0-1-0" in milestone
    assert "M34" in _read(LATEST_MILESTONE)
    assert "M37" in _read(CURRENT_MILESTONE)
    assert "M38" in _read(CURRENT_MILESTONE)
    assert "M39" in _read(CURRENT_MILESTONE)
    assert "M40" in _read(M40_MILESTONE)
    assert "loop-handoff-contract" in _read(M40_MILESTONE)


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
