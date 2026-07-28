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
        if path.name == "report.md.staged" and Path(target).name == "report.md":
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


def test_write_outputs_keeps_unresolved_backup_when_rollback_restore_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    (output_dir / "unrelated.txt").write_text("keep", encoding="utf-8")
    existing = {
        "analysis.json": b"old analysis\n",
        "report.md": b"old report\n",
    }
    for name, content in existing.items():
        (output_dir / name).write_bytes(content)

    original_replace = Path.replace

    def fail_publication_and_analysis_restore(path: Path, target: Path) -> Path:
        if path.name == "report.md.staged" and target.name == "report.md":
            raise OSError("simulated publish failure")
        if path.name == "analysis.json.old" and target.name == "analysis.json":
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

    with pytest.raises(BaseExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    errors = [str(error) for error in raised.value.exceptions]
    assert "simulated publish failure" in errors
    assert "simulated restore failure" in errors
    transactions = list(output_dir.glob(".m27-routing-analysis-*"))
    assert len(transactions) == 1
    assert (transactions[0] / "analysis.json.old").read_bytes() == existing["analysis.json"]
    assert (output_dir / "analysis.json").read_bytes() != existing["analysis.json"]
    assert (output_dir / "report.md").read_bytes() == existing["report.md"]
    assert (output_dir / "unrelated.txt").read_text() == "keep"


def test_write_outputs_stops_after_restore_failure_and_preserves_evidence(
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
    restore_attempts = 0

    def fail_restore_and_interrupt_report_publish(path: Path, target: Path) -> Path:
        nonlocal restore_attempts
        if path.name == "report.md.staged" and target.name == "report.md":
            raise OSError("simulated publish failure")
        if path.name == "analysis.json.old" and target.name == "analysis.json":
            restore_attempts += 1
            raise OSError("simulated restore failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_restore_and_interrupt_report_publish)
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

    with pytest.raises(BaseExceptionGroup):
        module.write_outputs(output_dir, analysis)

    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert restore_attempts == 1
    assert (output_dir / "analysis.json").read_bytes() != existing["analysis.json"]
    assert (transaction / "analysis.json.old").read_bytes() == existing["analysis.json"]


def test_write_outputs_reports_rollback_probe_interrupt_and_keeps_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_replace = Path.replace

    def fail_publish_and_probe(path: Path, target: Path) -> Path:
        if path.name == "analysis.json.staged" and target.name == "analysis.json":
            raise OSError("simulated publish failure")
        if path.name == "analysis.json.staged" and target.name == "analysis.json.failed-new":
            raise KeyboardInterrupt("simulated rollback probe interrupt")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_publish_and_probe)
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
        "simulated rollback probe interrupt" in str(error) for error in raised.value.exceptions
    )
    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert (transaction / "analysis.json.staged").exists()


def test_write_outputs_cleans_known_transaction_after_stage_write_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_open = Path.open

    def interrupt_analysis_stage(path: Path, *args, **kwargs):
        if path.name == "analysis.json.staged":
            raise KeyboardInterrupt("simulated stage open interrupt")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupt_analysis_stage)
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

    assert any("simulated stage open interrupt" in str(error) for error in raised.value.exceptions)
    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert list(transaction.iterdir()) == []


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
        if path.name == "report.md.staged" and target.name == "report.md":
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

    with pytest.raises(BaseExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    assert any("simulated interrupt" in str(error) for error in raised.value.exceptions)
    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert (transaction / "analysis.json.old").read_bytes() == existing["analysis.json"]
    assert (transaction / "report.md.old").read_bytes() == existing["report.md"]
    assert (transaction / "report.md.staged").exists()


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
        if path.name == "analysis.json" and target.name == "analysis.json.old":
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

    with pytest.raises(BaseExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    assert any("simulated post-backup interrupt" in str(error) for error in raised.value.exceptions)
    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert (transaction / "analysis.json.old").read_bytes() == existing["analysis.json"]
    assert (transaction / "analysis.json.staged").exists()


def test_write_outputs_removes_new_only_publish_when_interrupt_follows_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    original_replace = Path.replace

    def interrupt_after_analysis_publish(path: Path, target: Path) -> Path:
        result = original_replace(path, target)
        if path.name == "analysis.json.staged" and target.name == "analysis.json":
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

    with pytest.raises(BaseExceptionGroup) as raised:
        module.write_outputs(output_dir, analysis)

    assert any(
        "simulated post-publish interrupt" in str(error) for error in raised.value.exceptions
    )
    transaction = next(output_dir.glob(".m27-routing-analysis-*"))
    assert (transaction / "report.md.staged").exists()
    assert (output_dir / "analysis.json").exists()


@pytest.mark.parametrize("stage", ["successful-publication"])
def test_write_outputs_exposes_persistent_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    module = load_analysis()
    output_dir = tmp_path / "derived"
    if stage == "successful-publication":
        output_dir.mkdir()
        (output_dir / "analysis.json").write_text("old analysis\n", encoding="utf-8")
    original_unlink = Path.unlink
    original_replace = Path.replace

    def fail_cleanup(path: Path, *args, **kwargs) -> None:
        if stage == "rollback-files" and path.name == "report.md.staged":
            raise OSError("simulated rollback cleanup failure")
        if stage == "successful-publication" and path.name == "analysis.json.old":
            raise OSError("simulated successful publication cleanup failure")
        original_unlink(path, *args, **kwargs)

    def fail_publication(path: Path, target: Path) -> Path:
        if (
            stage == "rollback-files"
            and path.name == "report.md.staged"
            and target.name == "report.md"
        ):
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
        if Path(target).name == "report.md" and Path(path).name == "report.md.staged":
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
    (output_dir / "unrelated.txt").write_text("keep", encoding="utf-8")
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
    assert (output_dir / "unrelated.txt").read_text(encoding="utf-8") == "keep"
