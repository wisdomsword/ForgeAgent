import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
CANONICAL = ROOT / "docs" / "agent-governance-gates.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _table_rows(text: str, heading: str) -> dict[str, list[str]]:
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] not in {"exit class", "field", "metric"}:
            rows[cells[0].strip("`")] = cells
    return rows


def test_canonical_governance_doc_declares_prompt_exit_contract() -> None:
    text = _read(CANONICAL)
    rows = _table_rows(text, "## 1. Prompt / Skill Exit Contract")
    for field in ("success", "failure", "blocked", "needs-input", "timeout-or-budget"):
        assert field in rows, f"missing Prompt/Skill exit field: {field}"
        assert len(rows[field]) == 3 and all(rows[field][1:]), (
            f"incomplete Prompt/Skill exit row: {field}"
        )
    for field in ("minimum_regression_set", "retire_stale_scaffolding"):
        assert field in text, f"missing Prompt/Skill upgrade field: {field}"
    assert "unbounded" in text.lower(), "missing bounded-exit guard"


def test_canonical_governance_doc_declares_memory_review() -> None:
    text = _read(CANONICAL)
    rows = _table_rows(text, "## 2. Memory Governance Review")
    for field in (
        "why_remember",
        "who_can_write",
        "truth_source",
        "expires_or_revalidate",
        "visibility_and_recovery",
        "delete_or_correct",
    ):
        assert field in rows, f"missing Memory governance field: {field}"


def test_canonical_governance_doc_declares_rewrite_gate() -> None:
    text = _read(CANONICAL)
    rows = _table_rows(text, "## 3. Rewrite / Dependency Gate")
    for metric in (
        "performance",
        "reliability",
        "maintenance cost",
        "compatibility",
        "team capability",
        "migration/rollback risk",
    ):
        assert metric in rows, f"missing Rewrite gate metric: {metric}"
        assert len(rows[metric]) == 6 and all(rows[metric][1:]), (
            f"incomplete Rewrite gate row: {metric}"
        )


def test_governance_references_and_distribution_boundary_are_traceable() -> None:
    canonical_ref = "agent-governance-gates.md"
    entry_points = (
        ROOT / "spec.md",
        ROOT / "MILESTONE_GUIDE.md",
        ROOT / "docs" / "reviews" / "2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md",
        ROOT / "docs" / "threat-model.md",
    )
    for path in entry_points:
        text = _read(path)
        assert canonical_ref in text, f"missing canonical governance reference: {path.name}"

    text = _read(CANONICAL)
    for guard in ("包索引发布", "正式 tag", "远程 push", "已从当前路线图移除"):
        assert guard in text, f"missing distribution-boundary guard: {guard}"
    assert not (ROOT / "openspec" / "changes" / "publish-v0-1-0").exists()


def test_governance_contract_test_is_offline_and_release_neutral() -> None:
    source = _read(Path(__file__))
    tree = ast.parse(source)
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported.intersection({"subprocess", "requests", "urllib", "socket"}), (
        "contract test must remain a pure local file test"
    )
    forbidden_calls = (
        "os." + "system",
        "os." + "popen",
        "sub" + "process.",
        "request" + "s.",
    )
    for forbidden_call in forbidden_calls:
        assert forbidden_call not in source, f"contract test must not invoke: {forbidden_call}"
