import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "m43_executor_rewrite_baseline.py"
EVIDENCE = ROOT / "docs" / "evaluation" / "m43" / "executor-rewrite-baseline.json"
BASELINE = ROOT / "docs" / "evaluation" / "m43" / "rewrite-dependency-baseline.md"

EXPECTED_METRICS = (
    "performance",
    "reliability",
    "maintenance_cost",
    "compatibility",
    "team_capability",
    "migration_rollback_risk",
)
GOVERNANCE_FIELDS = {
    "baseline",
    "threshold",
    "evidence",
    "migration",
    "rollback_trigger",
    "status",
}


def _load_module():
    assert SCRIPT.is_file(), "M43 measurement script must exist"
    spec = importlib.util.spec_from_file_location("m43_executor_rewrite_baseline", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metrics(*, bottleneck: bool = False, team_ready: bool = True):
    metrics = {}
    for name in EXPECTED_METRICS:
        status = (
            "ready"
            if name
            in {
                "compatibility",
                "team_capability",
                "migration_rollback_risk",
            }
            else "within_threshold"
        )
        metrics[name] = {
            "baseline": {},
            "threshold": {},
            "evidence": {},
            "migration": "fixed migration rule",
            "rollback_trigger": "fixed rollback rule",
            "status": status,
        }
    if bottleneck:
        metrics["performance"]["status"] = "confirmed_bottleneck"
    if not team_ready:
        metrics["team_capability"]["status"] = "not_ready"
    return metrics


def test_contract_constants_and_sample_summary():
    module = _load_module()

    assert module.REPORT_SCHEMA == "forgeagent.executor-rewrite-baseline.v1"
    assert module.METRIC_NAMES == EXPECTED_METRICS
    assert module.summarize_samples([1.0, 2.0, 3.0, 4.0]) == {
        "count": 4,
        "samples_ms": [1.0, 2.0, 3.0, 4.0],
        "median_ms": 2.5,
        "p95_ms": 4.0,
        "min_ms": 1.0,
        "max_ms": 4.0,
        "ops_per_second": 400.0,
    }
    with pytest.raises(ValueError, match="samples_required"):
        module.summarize_samples([])


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        (_metrics(), "keep_python"),
        (_metrics(bottleneck=True), "eligible_for_single_module_experiment"),
        (_metrics(bottleneck=True, team_ready=False), "insufficient_evidence"),
    ],
)
def test_readiness_verdicts(metrics, expected):
    module = _load_module()

    assert module.evaluate_readiness(metrics) == expected


def test_readiness_rejects_missing_or_failed_required_evidence():
    module = _load_module()
    missing = _metrics()
    missing["performance"].pop("rollback_trigger")
    failed = _metrics()
    failed["reliability"]["status"] = "failed"

    assert module.evaluate_readiness(missing) == "insufficient_evidence"
    assert module.evaluate_readiness(failed) == "insufficient_evidence"


@pytest.mark.parametrize("metric_name", ["performance", "compatibility"])
def test_readiness_rejects_unknown_metric_status(metric_name):
    module = _load_module()
    metrics = _metrics()
    metrics[metric_name]["status"] = "typo_status"

    assert module.evaluate_readiness(metrics) == "insufficient_evidence"


def test_readiness_does_not_depend_on_metric_mapping_order():
    module = _load_module()
    reordered = dict(reversed(list(_metrics().items())))

    assert module.evaluate_readiness(reordered) == "keep_python"


def test_build_report_has_six_complete_metrics_and_fixed_environment(monkeypatch):
    module = _load_module()
    metrics = _metrics()
    monkeypatch.setattr(module, "_collect_metrics", lambda **_kwargs: metrics)
    monkeypatch.setattr(
        module,
        "_environment_summary",
        lambda: {
            "python": "3.14.3",
            "platform": "darwin",
            "machine": "arm64",
            "commit": "a14630f",
        },
    )

    report = module.build_report(samples=3, reliability_runs=2)

    assert report["schema"] == module.REPORT_SCHEMA
    assert set(report) == {"schema", "generated_at", "environment", "metrics", "verdict"}
    assert report["environment"] == {
        "python": "3.14.3",
        "platform": "darwin",
        "machine": "arm64",
        "commit": "a14630f",
    }
    assert tuple(report["metrics"]) == EXPECTED_METRICS
    assert all(set(metric) == GOVERNANCE_FIELDS for metric in report["metrics"].values())
    assert report["verdict"] == "keep_python"


def test_container_unavailable_is_fixed_and_not_measured(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    result = module._measure_container(samples=1, reliability_runs=1)

    assert result == {
        "status": "not_available",
        "reason": "container_unavailable",
    }


def test_main_masks_runtime_exception_and_output_path(monkeypatch, tmp_path, capsys):
    module = _load_module()
    secret = "PRIVATE_MEASUREMENT_FAILURE"
    output = tmp_path / "private" / "evidence.json"

    def fail(**_kwargs):
        raise OSError(secret)

    monkeypatch.setattr(module, "build_report", fail)

    exit_code = module.main(["--output", str(output), "--samples", "1"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "reason": "measurement_failed",
        "status": "failed",
    }
    assert secret not in captured.out
    assert str(output) not in captured.out


def test_main_does_not_swallow_keyboard_interrupt(monkeypatch, tmp_path):
    module = _load_module()

    def interrupt(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "build_report", interrupt)

    with pytest.raises(KeyboardInterrupt):
        module.main(["--output", str(tmp_path / "evidence.json"), "--samples", "1"])


def test_reliability_observes_crash_and_timeout_without_replay():
    module = _load_module()

    metric = module._measure_reliability(1)

    assert metric["status"] == "within_threshold"
    assert metric["evidence"]["failed_block_replayed"] is False
    assert metric["evidence"]["crash_failed_block_replayed"] is False
    assert metric["evidence"]["timeout_failed_block_replayed"] is False


def test_team_capability_requires_profiling_rehearsal():
    module = _load_module()

    metric = module._measure_team_capability()

    assert metric["threshold"]["profiling_rehearsal_required"] is True


def test_write_report_is_atomic_when_replace_fails(monkeypatch, tmp_path):
    module = _load_module()
    output = tmp_path / "evidence.json"
    output.write_text("old evidence\n", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        module.write_report(output, {"schema": module.REPORT_SCHEMA})

    assert output.read_text(encoding="utf-8") == "old evidence\n"
    assert list(tmp_path.glob(".m43-evidence-*.tmp")) == []


def test_frozen_evidence_and_baseline_document_contract():
    payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    text = BASELINE.read_text(encoding="utf-8")

    assert payload["schema"] == "forgeagent.executor-rewrite-baseline.v1"
    assert set(payload["metrics"]) == set(EXPECTED_METRICS)
    assert all(set(metric) == GOVERNANCE_FIELDS for metric in payload["metrics"].values())
    assert payload["verdict"] in {
        "keep_python",
        "eligible_for_single_module_experiment",
        "insufficient_evidence",
    }
    for required in (
        "| metric | baseline | threshold | evidence | migration | rollback trigger |",
        "performance",
        "reliability",
        "maintenance cost",
        "compatibility",
        "team capability",
        "migration/rollback risk",
        "同机干净复测",
        "not_available",
        "不授权 Rust 重写",
        "不新增依赖",
        "scripts/m43_executor_rewrite_baseline.py",
    ):
        assert required in text, required
