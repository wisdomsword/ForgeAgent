import stat
from datetime import UTC, datetime

import pytest

import forgeagent.memory as memory_module
from forgeagent.memory import MemoryManager
from forgeagent.protocol import MemoryCandidate

PRIVATE_VALUE = "migration-private-value"


def _write_v1(root, entries: dict[str, str]) -> bytes:
    raw = (
        "<!-- forgeagent-memory-v1 -->\n"
        + "".join(f"- {key}: {entries[key]}\n" for key in sorted(entries))
    ).encode()
    path = root / ".forgeagent" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _manifest(*keys: str, truth_source: str = "user_statement"):
    return {
        key: {
            "kind": "fact",
            "why_remember": "cross_task_fact",
            "source": "legacy_manifest",
            "writer": "unknown",
            "who_can_write": "host_only",
            "truth_source": truth_source,
            "visibility": "project",
            "written_at": "2026-07-30T00:00:00Z",
            "expires_at": None,
            "review_after": None,
            "revalidate_on": "conflict_or_explicit_review",
            "recovery": "project_memory_file",
            "delete_or_correct": "host_replace_delete_or_revalidate",
        }
        for key in keys
    }


@pytest.mark.parametrize(
    "manifest",
    [None, _manifest("extra"), {"editor": {"kind": "fact"}}],
)
def test_migrate_rejects_incomplete_or_mismatched_manifest_before_backup(tmp_path, manifest):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))

    result = manager.migrate_legacy(manifest)

    assert (result.status, result.entry_count) == ("rejected", 1)
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
    assert not (tmp_path / ".forgeagent" / "memory-backups").exists()
    assert PRIVATE_VALUE not in repr(result)
    assert str(tmp_path) not in repr(result)


def test_migrate_creates_private_backup_and_verified_semantic_v2(tmp_path):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(
        str(tmp_path),
        clock=lambda: datetime(2026, 7, 31, 0, 0, tzinfo=UTC),
    )

    result = manager.migrate_legacy(_manifest("editor"))

    assert (result.status, result.entry_count, result.reason) == (
        "migrated",
        1,
        "verified",
    )
    assert result.migration_id is not None and len(result.migration_id) == 32
    backup_dir = tmp_path / ".forgeagent" / "memory-backups"
    backup = backup_dir / f"{result.migration_id}.memory-v1.bak"
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert manager.verify_project().status == "verified"
    assert PRIVATE_VALUE in manager.render()


def test_unknown_truth_source_is_preserved_but_immediately_review_due(tmp_path):
    _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    now = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
    manager = MemoryManager(str(tmp_path), clock=lambda: now)

    result = manager.migrate_legacy(_manifest("editor", truth_source="unknown"))

    assert result.status == "migrated"
    assert PRIVATE_VALUE not in manager.render()
    assert (
        '"review_after":"2026-07-31T00:00:00Z"'
        in (tmp_path / ".forgeagent" / "MEMORY.md").read_text()
    )


@pytest.mark.parametrize("field", ["kind", "source"])
def test_manifest_requires_explicit_matching_kind_and_legacy_source(tmp_path, field):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manifest = _manifest("editor")
    if field == "kind":
        del manifest["editor"][field]
    else:
        manifest["editor"][field] = "host_api"

    result = MemoryManager(str(tmp_path)).migrate_legacy(manifest)

    assert (result.status, result.reason) == ("rejected", "manifest_invalid")
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original


def test_backup_directory_symlink_is_rejected(tmp_path):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    outside = tmp_path.parent / f"{tmp_path.name}-outside-backups"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_text("unchanged")
    (tmp_path / ".forgeagent" / "memory-backups").symlink_to(outside, target_is_directory=True)

    result = MemoryManager(str(tmp_path)).migrate_legacy(_manifest("editor"))

    assert (result.status, result.reason) == (
        "persistence_error",
        "backup_write_failed",
    )
    assert marker.read_text() == "unchanged"
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original


def test_existing_backup_name_is_not_overwritten(tmp_path, monkeypatch):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    backup_dir = tmp_path / ".forgeagent" / "memory-backups"
    backup_dir.mkdir(mode=0o700)
    migration_id = "a" * 32
    backup = backup_dir / f"{migration_id}.memory-v1.bak"
    backup.write_bytes(b"existing")
    monkeypatch.setattr(memory_module.secrets, "token_hex", lambda _size: migration_id)

    result = MemoryManager(str(tmp_path)).migrate_legacy(_manifest("editor"))

    assert (result.status, result.reason) == (
        "persistence_error",
        "backup_write_failed",
    )
    assert backup.read_bytes() == b"existing"
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original


@pytest.mark.parametrize(
    "raw",
    [
        b"<!-- forgeagent-memory-v1 -->\ninvalid\n",
        b"<!-- forgeagent-memory-v1 -->\n" + b"x" * (64 * 1024),
    ],
)
def test_oversize_or_noncanonical_v1_stops_before_backup(tmp_path, raw):
    path = tmp_path / ".forgeagent" / "MEMORY.md"
    path.parent.mkdir()
    path.write_bytes(raw)

    result = MemoryManager(str(tmp_path)).migrate_legacy(_manifest("editor"))

    assert result.status == "repair_required"
    assert path.read_bytes() == raw
    assert not (path.parent / "memory-backups").exists()


def test_post_write_verification_failure_restores_exact_v1_bytes(tmp_path, monkeypatch):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))
    real_verify = manager._verify_migration_snapshot
    calls = 0

    def fail_disk_verification(before, after, migration_id, migration_revision):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return real_verify(before, after, migration_id, migration_revision)

    monkeypatch.setattr(manager, "_verify_migration_snapshot", fail_disk_verification)

    result = manager.migrate_legacy(_manifest("editor"))

    assert (result.status, result.reason) == (
        "persistence_error",
        "verification_failed",
    )
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
    assert PRIVATE_VALUE not in repr(result)


def test_failed_restore_reports_unknown_without_claiming_success(tmp_path, monkeypatch):
    _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))
    real_write = manager._atomic_write_bytes
    writes = 0

    def corrupt_then_fail_restore(raw):
        nonlocal writes
        writes += 1
        if writes == 1:
            real_write(b"corrupt-after-replace\n")
            return
        raise OSError("private restore failure")

    monkeypatch.setattr(manager, "_atomic_write_bytes", corrupt_then_fail_restore)

    result = manager.migrate_legacy(_manifest("editor"))

    assert (result.status, result.reason) == (
        "recovery_failed",
        "restore_unconfirmed",
    )
    assert "private restore failure" not in repr(result)
    assert PRIVATE_VALUE not in repr(result)


def test_rollback_restores_unchanged_migration_but_rejects_later_revision(tmp_path):
    original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))
    migrated = manager.migrate_legacy(_manifest("editor"))
    assert migrated.migration_id is not None

    rolled_back = manager.rollback_migration(migrated.migration_id)

    assert (rolled_back.status, rolled_back.reason) == (
        "rolled_back",
        "verified_v1",
    )
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original

    migrated_again = manager.migrate_legacy(_manifest("editor"))
    assert migrated_again.migration_id is not None
    assert (
        manager.apply(
            MemoryCandidate(scope="project", kind="fact", key="language", content="python")
        ).status
        == "accepted"
    )
    current = (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes()

    conflict = manager.rollback_migration(migrated_again.migration_id)

    assert (conflict.status, conflict.reason) == (
        "rollback_conflict",
        "revision_changed",
    )
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == current
    assert "language: python" in manager.render()


def test_rollback_rejects_non_hex_or_mismatched_id(tmp_path):
    _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))
    migrated = manager.migrate_legacy(_manifest("editor"))
    assert migrated.migration_id is not None
    current = (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes()

    invalid = manager.rollback_migration("not-an-id")
    mismatched = manager.rollback_migration("f" * 32)

    assert (invalid.status, invalid.reason) == (
        "backup_unavailable",
        "invalid_migration_id",
    )
    assert (mismatched.status, mismatched.reason) == (
        "rollback_conflict",
        "migration_id_mismatch",
    )
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == current


@pytest.mark.parametrize("unsafe", ["missing", "symlink", "mode", "noncanonical"])
def test_rollback_rejects_unsafe_backup(tmp_path, unsafe):
    _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
    manager = MemoryManager(str(tmp_path))
    migrated = manager.migrate_legacy(_manifest("editor"))
    assert migrated.migration_id is not None
    current = (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes()
    backup = tmp_path / ".forgeagent" / "memory-backups" / f"{migrated.migration_id}.memory-v1.bak"
    if unsafe == "missing":
        backup.unlink()
    elif unsafe == "symlink":
        backup.unlink()
        backup.symlink_to(tmp_path / ".forgeagent" / "MEMORY.md")
    elif unsafe == "mode":
        backup.chmod(0o644)
    else:
        backup.write_bytes(b"<!-- forgeagent-memory-v1 -->\ninvalid\n")

    result = manager.rollback_migration(migrated.migration_id)

    assert result.status == "backup_unavailable"
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == current
    assert PRIVATE_VALUE not in repr(result)
    assert str(tmp_path) not in repr(result)


def test_rollback_has_no_force_override():
    import inspect

    parameters = inspect.signature(MemoryManager.rollback_migration).parameters

    assert "force" not in parameters
    assert set(parameters) == {"self", "migration_id", "task_id"}
