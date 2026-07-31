#!/usr/bin/env python3
"""Measure executor rewrite readiness without changing runtime behavior."""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from forgeagent.executor import ContainerBackend, ExecResult, RestrictedBackend, TrustedBackend
from forgeagent.runtime import Runtime

REPORT_SCHEMA = "forgeagent.executor-rewrite-baseline.v1"
METRIC_NAMES = (
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
FEASIBILITY_METRICS = (
    "compatibility",
    "team_capability",
    "migration_rollback_risk",
)
CONTAINER_IMAGE = "python:3.11-slim"
ROOT = Path(__file__).resolve().parents[1]

_TRIVIAL_CODE = "value = 1 + 1"
_MIGRATION_RULE = (
    "Use a separate full Comet change for one internal module while retaining the Python path."
)
_ROLLBACK_RULE = (
    "Stop when compatibility, recovery, maintenance, or measured improvement fails its threshold."
)


def summarize_samples(samples_ms: list[float]) -> dict[str, object]:
    """Return deterministic nearest-rank timing aggregates."""
    if not samples_ms:
        raise ValueError("samples_required")
    ordered = sorted(float(value) for value in samples_ms)
    count = len(ordered)
    p95_index = max(0, math.ceil(0.95 * count) - 1)
    total_ms = sum(ordered)
    return {
        "count": count,
        "samples_ms": [round(value, 6) for value in samples_ms],
        "median_ms": round(median(ordered), 6),
        "p95_ms": round(ordered[p95_index], 6),
        "min_ms": round(ordered[0], 6),
        "max_ms": round(ordered[-1], 6),
        "ops_per_second": round(1000.0 * count / total_ms, 6),
    }


def evaluate_readiness(metrics: dict[str, dict[str, object]]) -> str:
    """Evaluate the evidence gate; eligibility only authorizes a later change."""
    if set(metrics) != set(METRIC_NAMES):
        return "insufficient_evidence"
    if any(set(metrics[name]) != GOVERNANCE_FIELDS for name in METRIC_NAMES):
        return "insufficient_evidence"
    statuses = {name: metrics[name]["status"] for name in METRIC_NAMES}
    if any(status == "failed" for status in statuses.values()):
        return "insufficient_evidence"
    if any(status == "threshold_crossed" for status in statuses.values()):
        return "insufficient_evidence"
    bottleneck = any(
        statuses[name] == "confirmed_bottleneck"
        for name in ("performance", "reliability", "maintenance_cost")
    )
    if not bottleneck:
        return "keep_python"
    if any(statuses[name] != "ready" for name in FEASIBILITY_METRICS):
        return "insufficient_evidence"
    return "eligible_for_single_module_experiment"


def _time_backend(backend, samples: int) -> dict[str, object]:
    warmup = backend.execute(_TRIVIAL_CODE, Runtime())
    if not warmup.success:
        return {"status": "failed", "reason": "backend_execution_failed"}
    elapsed_ms: list[float] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        result = backend.execute(_TRIVIAL_CODE, Runtime())
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        if not result.success:
            return {"status": "failed", "reason": "backend_execution_failed"}
    return {"status": "measured", "timing": summarize_samples(elapsed_ms)}


def _measure_trusted(samples: int) -> dict[str, object]:
    return _time_backend(TrustedBackend(secret_values=set()), samples)


def _measure_restricted(samples: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="forgeagent-m43-restricted-") as allowed_root:
        backend = RestrictedBackend(
            allowed_root=allowed_root,
            timeout_seconds=10.0,
            secret_values=set(),
        )
        return _time_backend(backend, samples)


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        info = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if info.returncode != 0:
            return False
        image = subprocess.run(
            ["docker", "image", "inspect", CONTAINER_IMAGE],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return image.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _measure_container(*, samples: int, reliability_runs: int) -> dict[str, object]:
    if not _docker_ready():
        return {"status": "not_available", "reason": "container_unavailable"}
    with tempfile.TemporaryDirectory(prefix="forgeagent-m43-container-") as allowed_root:
        backend: ContainerBackend | None = None
        try:
            backend = ContainerBackend(
                allowed_root=allowed_root,
                image=CONTAINER_IMAGE,
                timeout_seconds=20.0,
                secret_values=set(),
            )
            performance = _time_backend(backend, min(samples, 3))
            normal_successes = 0
            for _ in range(min(reliability_runs, 3)):
                normal_successes += int(backend.execute(_TRIVIAL_CODE, Runtime()).success)
            crashed = backend.execute("import os; os._exit(7)", Runtime())
            recovered = backend.execute("value = 2 + 2", Runtime())
            return {
                "status": "measured",
                "performance": performance,
                "reliability": {
                    "normal_successes": normal_successes,
                    "normal_runs": min(reliability_runs, 3),
                    "crash_structured_failure": not crashed.success,
                    "crash_recovery": recovered.success,
                },
            }
        except Exception:  # noqa: BLE001 - public evidence uses a fixed code
            return {"status": "failed", "reason": "container_measurement_failed"}
        finally:
            if backend is not None:
                backend.close()


def _measure_reliability(reliability_runs: int) -> dict[str, object]:
    trusted = TrustedBackend(secret_values=set())
    trusted_successes = sum(
        int(trusted.execute(_TRIVIAL_CODE, Runtime()).success) for _ in range(reliability_runs)
    )
    with tempfile.TemporaryDirectory(prefix="forgeagent-m43-reliability-") as allowed_root:
        restricted = RestrictedBackend(
            allowed_root=allowed_root,
            timeout_seconds=10.0,
            secret_values=set(),
        )
        restricted_successes = sum(
            int(restricted.execute(_TRIVIAL_CODE, Runtime()).success)
            for _ in range(reliability_runs)
        )
        crashed = restricted.execute("import os; os._exit(7)", Runtime())
        crash_recovered = restricted.execute("value = 2 + 2", Runtime())

        timeout_backend = RestrictedBackend(
            allowed_root=allowed_root,
            timeout_seconds=1.0,
            secret_values=set(),
        )
        timed_out = timeout_backend.execute("while True:\n    pass", Runtime())
        timeout_recovered = timeout_backend.execute("value = 3 + 3", Runtime())

    baseline = {
        "trusted": {
            "runs": reliability_runs,
            "successes": trusted_successes,
        },
        "restricted": {
            "runs": reliability_runs,
            "successes": restricted_successes,
            "crash_structured_failure": not crashed.success,
            "crash_recovery": crash_recovered.success,
            "timeout_structured_failure": not timed_out.success,
            "timeout_recovery": timeout_recovered.success,
        },
    }
    within_threshold = (
        trusted_successes == reliability_runs
        and restricted_successes == reliability_runs
        and all(
            baseline["restricted"][name]
            for name in (
                "crash_structured_failure",
                "crash_recovery",
                "timeout_structured_failure",
                "timeout_recovery",
            )
        )
    )
    return {
        "baseline": baseline,
        "threshold": {
            "normal_control_plane_failures": 0,
            "crash_recovery_required": True,
            "timeout_recovery_required": True,
            "confirmation": "same_method_reproduction_and_real_path_impact",
        },
        "evidence": {
            "kind": "real_subprocess_fault_injection",
            "failed_block_replayed": False,
        },
        "migration": _MIGRATION_RULE,
        "rollback_trigger": (
            "Any recovery failure or unconditional replay restores the Python path."
        ),
        "status": "within_threshold" if within_threshold else "threshold_crossed",
    }


def _file_stats(relative_path: str) -> dict[str, int]:
    path = ROOT / relative_path
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    tree = ast.parse(text)
    symbols = sum(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in tree.body
    )
    imports = sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
    return {
        "lines": len(text.splitlines()),
        "bytes": len(raw),
        "top_level_symbols": symbols,
        "top_level_imports": imports,
    }


def _measure_maintenance() -> dict[str, object]:
    files = {
        relative: _file_stats(relative)
        for relative in (
            "src/forgeagent/executor.py",
            "src/forgeagent/_sandbox_worker.py",
            "src/forgeagent/runtime.py",
        )
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependency_count = len(project["dependencies"])
    total_lines = sum(stats["lines"] for stats in files.values())
    crossed = total_lines > 1000 or dependency_count > 8
    return {
        "baseline": {
            "files": files,
            "total_lines": total_lines,
            "direct_runtime_dependencies": dependency_count,
        },
        "threshold": {
            "current_surface_lines_gt": 1000,
            "direct_runtime_dependencies_gt": 8,
            "future_candidate_module_lines_lte": 400,
            "future_runtime_dependencies_added": 0,
        },
        "evidence": {"kind": "stdlib_ast_tomllib"},
        "migration": "Keep one candidate module behind the existing internal backend boundary.",
        "rollback_trigger": (
            "A new dependency, FFI framework, generator, registry, or second protocol is required."
        ),
        "status": "threshold_crossed" if crossed else "within_threshold",
    }


def _measure_compatibility() -> dict[str, object]:
    expected_fields = ["success", "stdout", "stderr", "error", "dropped_state_keys"]
    actual_fields = list(ExecResult.model_fields)
    with tempfile.TemporaryDirectory(prefix="forgeagent-m43-compatibility-") as allowed_root:
        runtime = Runtime()
        backend = RestrictedBackend(
            allowed_root=allowed_root,
            timeout_seconds=10.0,
            secret_values=set(),
        )
        first = backend.execute("utils.set_state('n', 21)", runtime)
        second = backend.execute("print(utils.get_state('n') * 2)", runtime)
    roundtrip = first.success and second.success and second.stdout.strip() == "42"
    ready = actual_fields == expected_fields and roundtrip
    return {
        "baseline": {
            "executor_backends": ["TrustedBackend", "RestrictedBackend", "ContainerBackend"],
            "exec_result_fields": actual_fields,
            "restricted_json_state_roundtrip": roundtrip,
            "worker_protocol": "one_shot_json",
        },
        "threshold": {
            "exec_result_fields_exact": expected_fields,
            "state_roundtrip_required": True,
            "existing_contract_test_failures": 0,
            "public_interface_changes": 0,
        },
        "evidence": {
            "focused_tests": [
                "tests/test_executor.py",
                "tests/test_restricted_backend.py",
                "tests/test_container_backend.py",
                "tests/test_escape.py",
                "tests/test_policy_wiring.py",
            ]
        },
        "migration": "Preserve the current backend API and worker frame throughout any trial.",
        "rollback_trigger": (
            "Any ExecResult, state, sandbox, CLI, config, or HTTP contract changes."
        ),
        "status": "ready" if ready else "not_ready",
    }


def _measure_team_capability() -> dict[str, object]:
    return {
        "baseline": {
            "python_toolchain": True,
            "uv_pytest_ruff": True,
            "rustc_available": shutil.which("rustc") is not None,
            "cargo_available": shutil.which("cargo") is not None,
            "candidate_maintenance_rehearsal": "not_run",
        },
        "threshold": {
            "named_owner_required": True,
            "target_build_rehearsal_required": True,
            "debug_rehearsal_required": True,
            "package_integration_rehearsal_required": True,
            "rollback_rehearsal_required": True,
        },
        "evidence": {
            "tool_presence_is_not_capability": True,
            "rehearsal_status": "not_run",
        },
        "migration": "Name an owner and rehearse build, debug, packaging, profiling, and rollback.",
        "rollback_trigger": (
            "No maintainer can diagnose and revert the candidate on target platforms."
        ),
        "status": "not_ready",
    }


def _measure_migration_rollback() -> dict[str, object]:
    return {
        "baseline": {
            "runtime_changes": 0,
            "schema_changes": 0,
            "config_changes": 0,
            "data_migrations": 0,
            "legacy_python_path_present": True,
        },
        "threshold": {
            "single_internal_module": True,
            "legacy_python_path_required": True,
            "state_conversion_allowed": False,
            "unconditional_replay_allowed": False,
        },
        "evidence": {"kind": "design_and_base_ref_diff"},
        "migration": _MIGRATION_RULE,
        "rollback_trigger": (
            "Rollback needs data conversion, the legacy path is removed, or failure mutates state."
        ),
        "status": "ready",
    }


def _measure_performance(samples: int, container: dict[str, object]) -> dict[str, object]:
    trusted = _measure_trusted(samples)
    restricted = _measure_restricted(samples)
    required_failed = trusted["status"] != "measured" or restricted["status"] != "measured"
    crossed = False
    if not required_failed:
        trusted_timing = trusted["timing"]
        restricted_timing = restricted["timing"]
        crossed = (
            trusted_timing["median_ms"] > 1.0
            or restricted_timing["median_ms"] > 250.0
            or restricted_timing["ops_per_second"] < 4.0
        )
    status = "failed" if required_failed else "threshold_crossed" if crossed else "within_threshold"
    return {
        "baseline": {
            "trusted": trusted,
            "restricted": restricted,
            "container": container,
        },
        "threshold": {
            "trusted_median_ms_gt": 1.0,
            "restricted_median_ms_gt": 250.0,
            "restricted_ops_per_second_lt": 4.0,
            "confirmation": "clean_same_host_rerun_and_real_requirement",
            "container_is_diagnostic_only": True,
        },
        "evidence": {
            "clock": "perf_counter_ns",
            "workload": "trivial_assignment",
            "container_unavailable_is_not_passed": True,
        },
        "migration": _MIGRATION_RULE,
        "rollback_trigger": "The clean rerun misses the improvement target or regresses p95.",
        "status": status,
    }


def _collect_metrics(*, samples: int, reliability_runs: int) -> dict[str, dict[str, object]]:
    container = _measure_container(samples=samples, reliability_runs=reliability_runs)
    return {
        "performance": _measure_performance(samples, container),
        "reliability": _measure_reliability(reliability_runs),
        "maintenance_cost": _measure_maintenance(),
        "compatibility": _measure_compatibility(),
        "team_capability": _measure_team_capability(),
        "migration_rollback_risk": _measure_migration_rollback(),
    }


def _environment_summary() -> dict[str, str]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        commit_id = commit.stdout.strip() if commit.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        commit_id = "unknown"
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "machine": platform.machine() or "unknown",
        "commit": commit_id,
    }


def build_report(*, samples: int, reliability_runs: int) -> dict[str, object]:
    metrics = _collect_metrics(samples=samples, reliability_runs=reliability_runs)
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": _environment_summary(),
        "metrics": metrics,
        "verdict": evaluate_readiness(metrics),
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".m43-evidence-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _bounded_positive(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= 1000:
        raise argparse.ArgumentTypeError("value must be between 1 and 1000")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure executor rewrite readiness.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=_bounded_positive, default=15)
    parser.add_argument("--reliability-runs", type=_bounded_positive, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(samples=args.samples, reliability_runs=args.reliability_runs)
        write_report(args.output, report)
    except Exception:  # noqa: BLE001 - public CLI returns only a fixed failure shape
        print(json.dumps({"reason": "measurement_failed", "status": "failed"}))
        return 2
    print(json.dumps({"status": "written", "verdict": report["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
