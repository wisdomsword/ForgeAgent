from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m25_independent_recompute import write_complete_evidence
from tests.test_m25_mode_evaluation import M25_PROTOCOL_PATH, ROOT, load_harness

SCRIPT = ROOT / "scripts" / "m27_m25_routing_analysis.py"


def load_analysis():
    spec = importlib.util.spec_from_file_location("m27_m25_routing_analysis", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_false_completion_evidence(output: Path) -> dict[str, object]:
    write_complete_evidence(output)
    raw_path = sorted((output / "raw").glob("*.json"))[0]
    record = json.loads(raw_path.read_text(encoding="utf-8"))
    record["runtime_completed"] = True
    record["runtime_status"] = "completed"
    record["runtime_reason"] = "completed"
    record["checks"][0]["status"] = "failed"
    record["solved"] = False
    raw_path.write_text(json.dumps(record), encoding="utf-8")

    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    environment = harness.M25EnvironmentManifest.model_validate_json(
        (output / "environment.json").read_bytes()
    )
    records = harness.read_raw_records(
        output / "raw",
        protocol,
        digest,
        harness.environment_sha256(environment),
        environment=environment,
    )
    summary = harness.aggregate_records(protocol, harness.build_schedule(protocol), records)
    (output / "summary.json").write_bytes(harness.canonical_json(summary))
    (output / "report.md").write_text("frozen report\n", encoding="utf-8")
    return record


def test_derive_reports_false_completion_costs_and_quality_gate(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    record = write_false_completion_evidence(evidence)

    analysis = load_analysis().derive(M25_PROTOCOL_PATH, evidence)

    bucket = analysis["models"]["claude-haiku-4-5"]["single"]
    assert bucket["false_completions"] == 1
    assert bucket["false_completion_rate_scheduled"] == {
        "numerator": 1,
        "denominator": 45,
        "value": 1 / 45,
    }
    assert bucket["false_completion_rate_runtime_completed"]["numerator"] == 1
    assert bucket["termination_reasons"][record["runtime_reason"]] >= 1

    family_bucket = analysis["families"]["baseline"]["single"]
    assert family_bucket["scheduled_runs"] == 30
    for metric in (
        "logical_model_calls",
        "provider_attempts",
        "end_to_end_latency_seconds",
        "tokens",
    ):
        assert set(family_bucket[metric]) == {"sum", "mean"}
    eligible = analysis["quality_eligible_for_automatic_triad"]
    assert eligible
    assert analysis["automatic_triad_restored_for"] == eligible
    assert analysis["decision"]["reason"] == (
        "Triad has a strictly higher solved rate than Single for: " + ", ".join(eligible) + "."
    )
    report = load_analysis().render_report(analysis)
    assert "M25 早于 M26" in report
    assert "automatic Triad restored: " + ", ".join(eligible) in report


def test_derive_rejects_raw_identity_and_summary_tampering(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    write_false_completion_evidence(evidence)
    first = sorted((evidence / "raw").glob("*.json"))[0]
    tampered = json.loads(first.read_text(encoding="utf-8"))
    tampered["run_spec_sha256"] = "0" * 64
    first.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="run-spec hash"):
        load_analysis().derive(M25_PROTOCOL_PATH, evidence)

    summary_evidence = tmp_path / "summary-evidence"
    write_false_completion_evidence(summary_evidence)
    summary = json.loads((summary_evidence / "summary.json").read_text(encoding="utf-8"))
    summary["models"]["claude-haiku-4-5"]["modes"]["single"]["scheduled_runs"] = 44
    (summary_evidence / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="independent recompute mismatch"):
        load_analysis().derive(M25_PROTOCOL_PATH, summary_evidence)


def test_cli_rejects_output_inside_frozen_run_without_artifacts(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    write_false_completion_evidence(evidence)
    result = subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--protocol",
            str(M25_PROTOCOL_PATH),
            "--run-dir",
            str(evidence),
            "--output-dir",
            str(evidence / "derived"),
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (evidence / "derived").exists()


def test_write_outputs_removes_partial_publication_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    original_replace = Path.replace

    def fail_report_publication(path: Path, target: Path) -> Path:
        if Path(target).name == "report.md":
            raise OSError("simulated publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_report_publication)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }
    with pytest.raises(OSError, match="simulated publish failure"):
        module.write_outputs(tmp_path / "derived", analysis)
    assert not (tmp_path / "derived" / "analysis.json").exists()
    assert not (tmp_path / "derived" / "report.md").exists()


def test_write_outputs_preserves_existing_outputs_when_backup_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def fail_report_backup(path: Path, target: Path) -> Path:
        if path.name == "report.md" and target.name.startswith(".backup-report.md."):
            raise OSError("simulated backup failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_report_backup)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(OSError, match="simulated backup failure"):
        module.write_outputs(output_dir, analysis)

    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_preserves_existing_outputs_when_backup_reservation_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_named_temporary_file = module.tempfile.NamedTemporaryFile
    reservations = 0

    def fail_first_backup_reservation(*args, **kwargs):
        nonlocal reservations
        prefix = kwargs.get("prefix", "")
        if prefix.startswith(".backup-"):
            reservations += 1
            if reservations == 1:
                raise KeyboardInterrupt("simulated reservation open interrupt")
        return original_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", fail_first_backup_reservation)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(KeyboardInterrupt, match="simulated reservation open interrupt"):
        module.write_outputs(output_dir, analysis)

    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_keeps_unresolved_backup_when_rollback_restore_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def fail_publication_and_analysis_restore(path: Path, target: Path) -> Path:
        if path.name.startswith(".report.md.") and target.name == "report.md":
            raise OSError("simulated publish failure")
        if path.name.startswith(".backup-analysis.json.") and target.name == "analysis.json":
            raise OSError("simulated restore failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_publication_and_analysis_restore)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(ExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    errors = [str(error) for error in raised.value.exceptions]
    assert errors == ["simulated publish failure", "simulated restore failure"]
    unresolved = list(output_dir.glob(".backup-analysis.json.*"))
    assert len(unresolved) == 1
    assert unresolved[0].read_bytes() == existing["analysis.json"]
    assert not (output_dir / "analysis.json").exists()
    assert (output_dir / "report.md").read_bytes() == existing["report.md"]
    assert not list(output_dir.glob(".analysis.json.*"))
    assert not list(output_dir.glob(".report.md.*"))
    assert not list(output_dir.glob(".backup-report.md.*"))


def test_write_outputs_keeps_restored_old_content_when_restore_interrupts_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def fail_publish_then_interrupt_after_restore(path: Path, target: Path) -> Path:
        if path.name.startswith(".report.md.") and target.name == "report.md":
            raise OSError("simulated publish failure")
        if path.name.startswith(".backup-analysis.json.") and target.name == "analysis.json":
            original_replace(path, target)
            raise KeyboardInterrupt("simulated post-restore interrupt")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_publish_then_interrupt_after_restore)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(BaseExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    assert any(
        "simulated post-restore interrupt" in str(error) for error in raised.value.exceptions
    )
    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_cleans_backup_reservation_when_unlink_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_unlink = Path.unlink
    failed = False

    def fail_first_backup_reservation_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal failed
        if not failed and path.name.startswith(".backup-analysis.json."):
            failed = True
            raise OSError("simulated reservation unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_backup_reservation_unlink)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(OSError, match="simulated reservation unlink failure"):
        module.write_outputs(output_dir, analysis)

    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_cleans_temp_when_named_temp_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_named_temporary_file = module.tempfile.NamedTemporaryFile

    class FailingWriteFile:
        def __init__(self, *args, **kwargs) -> None:
            self._file = original_named_temporary_file(*args, **kwargs)
            self.name = self._file.name
            self.closed = False

        def __enter__(self):
            self._file.__enter__()
            return self

        def write(self, _content: bytes) -> None:
            raise OSError("simulated write failure")

        def __exit__(self, *args) -> None:
            self._file.__exit__(*args)
            self.closed = self._file.closed

    files: list[FailingWriteFile] = []

    def failing_named_temporary_file(*args, **kwargs):
        file = FailingWriteFile(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", failing_named_temporary_file)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(OSError, match="simulated write failure"):
        module.write_outputs(output_dir, analysis)

    assert list(output_dir.iterdir()) == []
    assert len(files) == 1
    assert files[0].closed is True


def test_write_outputs_cleans_temp_when_named_temp_close_fails_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_named_temporary_file = module.tempfile.NamedTemporaryFile

    class FailingCloseFile:
        def __init__(self, *args, **kwargs) -> None:
            self._file = original_named_temporary_file(*args, **kwargs)
            self.name = self._file.name
            self.exit_calls = 0

        def __enter__(self):
            self._file.__enter__()
            return self

        def write(self, content: bytes) -> int:
            return self._file.write(content)

        def __exit__(self, *args) -> None:
            self.exit_calls += 1
            self._file.__exit__(*args)
            raise OSError("simulated close failure")

    files: list[FailingCloseFile] = []

    def failing_named_temporary_file(*args, **kwargs):
        file = FailingCloseFile(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", failing_named_temporary_file)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(OSError, match="simulated close failure"):
        module.write_outputs(output_dir, analysis)

    assert list(output_dir.iterdir()) == []
    assert len(files) == 1
    assert files[0].exit_calls == 1


def test_write_outputs_rolls_back_keyboard_interrupt_during_second_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def interrupt_report_publication(path: Path, target: Path) -> Path:
        if path.name.startswith(".report.md.") and target.name == "report.md":
            raise KeyboardInterrupt("simulated interrupt")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_report_publication)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(KeyboardInterrupt, match="simulated interrupt"):
        module.write_outputs(output_dir, analysis)

    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_recovers_when_backup_move_interrupts_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def interrupt_after_backup_move(path: Path, target: Path) -> Path:
        result = original_replace(path, target)
        if path.name == "analysis.json" and target.name.startswith(".backup-analysis.json."):
            raise KeyboardInterrupt("simulated post-backup interrupt")
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_backup_move)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(KeyboardInterrupt, match="simulated post-backup interrupt"):
        module.write_outputs(output_dir, analysis)

    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == existing


def test_write_outputs_removes_new_only_publish_when_interrupt_follows_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_replace = Path.replace

    def interrupt_after_analysis_publish(path: Path, target: Path) -> Path:
        result = original_replace(path, target)
        if path.name.startswith(".analysis.json.") and target.name == "analysis.json":
            raise KeyboardInterrupt("simulated post-publish interrupt")
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_analysis_publish)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(KeyboardInterrupt, match="simulated post-publish interrupt"):
        module.write_outputs(output_dir, analysis)

    assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize("stage", ["temporary", "reservation", "successful-publication"])
def test_write_outputs_exposes_persistent_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    if stage in ("reservation", "successful-publication"):
        output_dir.mkdir()
        (output_dir / "analysis.json").write_text("old analysis\n", encoding="utf-8")
    original_unlink = Path.unlink
    original_replace = Path.replace
    backup_unlinks = 0

    def fail_cleanup(path: Path, *args, **kwargs) -> None:
        nonlocal backup_unlinks
        if stage == "temporary" and path.name.startswith(".analysis.json."):
            raise OSError("simulated persistent temp cleanup failure")
        if stage == "reservation" and path.name.startswith(".backup-analysis.json."):
            raise OSError("simulated persistent reservation cleanup failure")
        if stage == "successful-publication" and path.name.startswith(".backup-analysis.json."):
            backup_unlinks += 1
            if backup_unlinks > 1:
                raise OSError("simulated successful publication cleanup failure")
        original_unlink(path, *args, **kwargs)

    def fail_publication(path: Path, target: Path) -> Path:
        if stage == "temporary" and path.name.startswith(".analysis.json."):
            raise OSError("simulated publication failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    monkeypatch.setattr(Path, "replace", fail_publication)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(BaseException) as raised:
        module.write_outputs(output_dir, analysis)

    if isinstance(raised.value, BaseExceptionGroup):
        messages = [str(error) for error in raised.value.exceptions]
    else:
        messages = [str(raised.value)]
    assert any("cleanup failure" in message for message in messages)


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (
            {"analysis.json": b"old analysis\n", "report.md": b"old report\n"},
            {"analysis.json": b"old analysis\n", "report.md": b"old report\n"},
        ),
        ({"analysis.json": b"old analysis\n"}, {"analysis.json": b"old analysis\n"}),
        ({"report.md": b"old report\n"}, {"report.md": b"old report\n"}),
    ],
)
def test_write_outputs_restores_preexisting_pair_when_second_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: dict[str, bytes],
    expected: dict[str, bytes],
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def fail_only_new_report(path: Path, target: Path) -> Path:
        if Path(target).name == "report.md" and Path(path).name.startswith(".report.md."):
            raise OSError("simulated second publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_only_new_report)
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    with pytest.raises(OSError, match="simulated second publish failure"):
        module.write_outputs(output_dir, analysis)

    published = {
        path.name: path.read_bytes()
        for path in output_dir.iterdir()
        if not path.name.startswith(".")
    }
    assert published == expected


def test_write_outputs_replaces_preexisting_pair_on_success(tmp_path: Path) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    (output_dir / "analysis.json").write_text("old analysis\n", encoding="utf-8")
    (output_dir / "report.md").write_text("old report\n", encoding="utf-8")
    analysis = {
        "source": {
            "runs": 0,
            "protocol_sha256": "test",
            "environment_sha256": "test",
            "frozen_manifest": {"sha256": "test"},
        },
        "families": {},
        "quality_eligible_for_automatic_triad": [],
        "automatic_triad_restored_for": [],
    }

    module.write_outputs(output_dir, analysis)

    assert (
        json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))["source"]["runs"]
        == 0
    )
    assert (
        (output_dir / "report.md")
        .read_text(encoding="utf-8")
        .startswith("# M27 M25 协作路由派生分析\n")
    )
