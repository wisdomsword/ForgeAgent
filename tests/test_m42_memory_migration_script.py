import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "m42_memory_migration.py"


def _run(*args: str):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_v1(root) -> bytes:
    raw = b"<!-- forgeagent-memory-v1 -->\n- editor: private-value\n"
    path = root / ".forgeagent" / "MEMORY.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return raw


def _manifest() -> dict[str, dict[str, object]]:
    return {
        "editor": {
            "kind": "fact",
            "why_remember": "cross_task_fact",
            "source": "legacy_manifest",
            "writer": "unknown",
            "who_can_write": "host_only",
            "truth_source": "user_statement",
            "visibility": "project",
            "written_at": "2026-07-30T00:00:00Z",
            "expires_at": None,
            "review_after": None,
            "revalidate_on": "conflict_or_explicit_review",
            "recovery": "project_memory_file",
            "delete_or_correct": "host_replace_delete_or_revalidate",
        }
    }


def test_readiness_no_data_is_single_line_json_and_does_not_write(tmp_path):
    result = _run("readiness", "--root", str(tmp_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "entry_count": 0,
        "format_version": "none",
        "reason": "memory_absent",
        "status": "no_data",
    }
    assert result.stdout.count("\n") == 1
    assert not (tmp_path / ".forgeagent").exists()


def test_readiness_accepts_manifest_without_migrating_legacy_file(tmp_path):
    original = _write_v1(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = _run(
        "readiness",
        "--root",
        str(tmp_path),
        "--manifest",
        "manifest.json",
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "entry_count": 1,
        "format_version": "v1",
        "reason": "manifest_valid",
        "status": "legacy_ready",
    }
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
    assert not (tmp_path / ".forgeagent" / "memory-backups").exists()


def test_manifest_must_be_project_relative_regular_json(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-manifest.json"
    outside.write_text('{"private":"value"}', encoding="utf-8")

    result = _run(
        "migrate",
        "--root",
        str(tmp_path),
        "--manifest",
        str(outside),
    )

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "entry_count": 0,
        "reason": "manifest_path",
        "status": "rejected",
    }
    assert str(outside) not in result.stdout
    assert "private" not in result.stdout


def test_manifest_symlink_is_rejected_without_following_target(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text('{"private":"value"}', encoding="utf-8")
    (tmp_path / "manifest.json").symlink_to(outside)

    result = _run("migrate", "--root", str(tmp_path), "--manifest", "manifest.json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["reason"] == "manifest_path"
    assert "private" not in result.stdout


def test_invalid_or_oversize_manifest_has_fixed_reason(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"x" * (64 * 1024) + b"}")

    malformed = _run("migrate", "--root", str(tmp_path), "--manifest", "invalid.json")
    too_large = _run("migrate", "--root", str(tmp_path), "--manifest", "oversized.json")

    assert json.loads(malformed.stdout)["reason"] == "manifest_format"
    assert json.loads(too_large.stdout)["reason"] == "manifest_file"


def test_verify_reports_legacy_without_modifying_it(tmp_path):
    original = _write_v1(tmp_path)

    result = _run("verify", "--root", str(tmp_path))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert (payload["status"], payload["reason"]) == ("not_current", "legacy_format")
    assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original


def test_rollback_invalid_id_is_rejected(tmp_path):
    result = _run("rollback", "--root", str(tmp_path), "--migration-id", "invalid")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert (payload["status"], payload["reason"]) == (
        "backup_unavailable",
        "invalid_migration_id",
    )


def test_script_never_prints_runtime_exception(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("m42_memory_migration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class BrokenManager:
        def __init__(self, _root):
            pass

        def readiness(self):
            raise OSError("PRIVATE_RUNTIME_FAILURE")

    monkeypatch.setattr(module, "MemoryManager", BrokenManager)

    exit_code = module.main(["readiness", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out) == {
        "entry_count": 0,
        "reason": "operation_failed",
        "status": "persistence_error",
    }
    assert captured.err == ""
    assert "PRIVATE_RUNTIME_FAILURE" not in captured.out
    assert str(tmp_path) not in captured.out
