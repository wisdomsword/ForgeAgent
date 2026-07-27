from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m25_mode_evaluation import (
    M25_PROTOCOL_PATH,
    ROOT,
    _write_m25_batch,
    load_harness,
    make_complete_m25_records,
)

RECOMPUTE_PATH = ROOT / "scripts" / "m25_independent_recompute.py"


def load_recompute():
    spec = importlib.util.spec_from_file_location("m25_independent_recompute", RECOMPUTE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_complete_evidence(output: Path):
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    records = make_complete_m25_records(harness, protocol, digest)
    _, environment_sha = _write_m25_batch(harness, output, protocol, digest, records)
    bound = tuple(
        record.model_copy(update={"environment_sha256": environment_sha}) for record in records
    )
    summary = harness.aggregate_records(protocol, harness.build_schedule(protocol), bound)
    (output / "summary.json").write_bytes(harness.canonical_json(summary))
    return summary


def test_independent_recompute_matches_and_detects_changed_denominator(tmp_path) -> None:
    summary = write_complete_evidence(tmp_path / "evidence")
    output = tmp_path / "evidence"
    recompute = load_recompute()
    projection = recompute.recompute(M25_PROTOCOL_PATH, output)
    assert projection["runs"] == 270
    assert projection["models"]["claude-haiku-4-5"]["single"]["scheduled_runs"] == 45
    recompute.verify_summary(M25_PROTOCOL_PATH, output)

    summary["models"]["gpt-5.4-mini"]["modes"]["duo"]["scheduled_runs"] = 44
    (output / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="independent recompute mismatch"):
        recompute.verify_summary(M25_PROTOCOL_PATH, output)


def test_recompute_script_does_not_import_harness_aggregation() -> None:
    source = RECOMPUTE_PATH.read_text(encoding="utf-8")
    assert "m23_mode_evaluation" not in source
    assert "aggregate_records" not in source
    assert "render_report" not in source


def test_independent_recompute_rejects_run_spec_hash_tampering(tmp_path) -> None:
    output = tmp_path / "evidence"
    write_complete_evidence(output)
    first = sorted((output / "raw").glob("*.json"))[0]
    record = json.loads(first.read_text(encoding="utf-8"))
    record["run_spec_sha256"] = "0" * 64
    first.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="run-spec hash"):
        load_recompute().recompute(M25_PROTOCOL_PATH, output)


def test_independent_recompute_cli_reports_complete_run_count(tmp_path) -> None:
    output = tmp_path / "evidence"
    write_complete_evidence(output)
    result = subprocess.run(
        (
            sys.executable,
            str(RECOMPUTE_PATH),
            "--protocol",
            str(M25_PROTOCOL_PATH),
            "--output",
            str(output),
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "INDEPENDENT_RECOMPUTE_OK runs=270"
