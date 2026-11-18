from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_memory_migration_runbook_covers_bounded_operations():
    text = (ROOT / "docs" / "memory-migration.md").read_text(encoding="utf-8")
    for required in (
        "readiness --root",
        "migrate --root",
        "verify --root",
        "rollback --root",
        "legacy_needs_metadata",
        "migration_required",
        "rollback_conflict",
        ".forgeagent/memory-backups/",
        "0600",
        "不推断",
        "不进入 prompt",
        "保留原始 `source`/`writer`",
        "truth_source=unknown",
    ):
        assert required in text, required


def test_memory_migration_is_linked_from_project_entry_points():
    assert (ROOT / "docs/memory-migration.md").is_file()
    for relative in ("README.md", "docs/threat-model.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "docs/memory-migration.md" in text, relative


def test_memory_migration_runbook_links_the_existing_governance_gate():
    text = (ROOT / "docs" / "memory-migration.md").read_text(encoding="utf-8")
    target = Path("docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md")
    assert target.as_posix() in text
    assert (ROOT / target).is_file()
