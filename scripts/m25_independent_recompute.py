#!/usr/bin/env python3
"""Independently recompute M25 denominators and additive totals from raw JSON."""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "forgeagent.m25.mode-evaluation/v1"
ENVIRONMENT_SCHEMA = "forgeagent.m25.mode-evaluation.environment/v1"
RAW_SCHEMA = "forgeagent.m25.mode-evaluation.run/v1"
SUMMARY_SCHEMA = "forgeagent.m25.mode-evaluation.summary/v1"
MODELS = ("claude-haiku-4-5", "gpt-5.4-mini")
MODES = ("single", "duo", "triad")
FAMILIES = ("baseline", "bugfix", "feature", "refactor")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens")
MODEL_SLUGS = {
    "claude-haiku-4-5": "claude-haiku-4-5",
    "gpt-5.4-mini": "gpt-5-4-mini",
}


def _load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular JSON file is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object is required: {path.name}")
    return value


def _sha256_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _protocol_sha256(protocol: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(protocol))
    normalized["generation"]["timeout_seconds"] = 120.0
    normalized["execution"]["check_timeout_seconds"] = 30.0
    for task in normalized["tasks"]:
        for check in task["checks"]:
            check["timeout_seconds"] = 30.0
    return _canonical_sha256(normalized)


def _fixed_protocol(protocol_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    protocol = _load_object(protocol_path)
    if (
        protocol.get("schema") != SCHEMA
        or tuple(protocol.get("model_ids", ())) != MODELS
        or protocol.get("repetitions") != 5
        or tuple(protocol.get("modes", ())) != MODES
        or tuple(tuple(order) for order in protocol.get("mode_orders", ()))
        != (
            ("single", "duo", "triad"),
            ("duo", "triad", "single"),
            ("triad", "single", "duo"),
        )
    ):
        raise ValueError("M25 protocol constants do not match")
    tasks = protocol.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 9:
        raise ValueError("M25 protocol must contain nine tasks")
    task_families: dict[str, str] = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("M25 task must be an object")
        task_id = task.get("id")
        family = task.get("family")
        if not isinstance(task_id, str) or family not in FAMILIES or task_id in task_families:
            raise ValueError("M25 task identity or family is invalid")
        task_families[task_id] = family
    if Counter(task_families.values()) != Counter(
        {"baseline": 3, "bugfix": 2, "feature": 2, "refactor": 2}
    ):
        raise ValueError("M25 family counts do not match")
    return protocol, task_families


def _schedule(
    protocol: dict[str, Any], task_families: dict[str, str]
) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    orders = protocol["mode_orders"]
    expected: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    sequence = 0
    for task_index, task in enumerate(protocol["tasks"]):
        task_id = task["id"]
        for repeat_index in range(5):
            models = list(enumerate(MODELS))
            if (task_index + repeat_index) % 2:
                models.reverse()
            for model_index, model_id in models:
                order = orders[(2 * task_index + model_index + repeat_index) % 3]
                for mode in order:
                    sequence += 1
                    combination = (task_id, model_id, repeat_index + 1, mode)
                    expected[combination] = {
                        "sequence": sequence,
                        "family": task_families[task_id],
                        "run_id": (
                            f"{sequence:03d}-{task_id}-{MODEL_SLUGS[model_id]}-"
                            f"r{repeat_index + 1}-{mode}"
                        ),
                    }
    if len(expected) != 270:
        raise ValueError("M25 schedule must contain 270 runs")
    return expected


def _empty_metrics() -> dict[str, Any]:
    return {
        "scheduled_runs": 0,
        "solved_runs": 0,
        "logical_model_calls": 0,
        "provider_attempts": 0,
        "usage_missing_calls": 0,
        "usage_rate_denominator_calls": 0,
        "tokens": {field: 0 for field in TOKEN_FIELDS},
    }


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"non-negative integer required for {label}")
    return value


def _add(metrics: dict[str, Any], record: dict[str, Any]) -> None:
    logical_calls = _integer(record.get("logical_model_calls"), "logical_model_calls")
    missing_calls = _integer(record.get("usage_missing_calls"), "usage_missing_calls")
    present_calls = _integer(record.get("usage_present_calls"), "usage_present_calls")
    if present_calls + missing_calls != logical_calls:
        raise ValueError("usage call counts do not equal logical calls")
    metrics["scheduled_runs"] += 1
    metrics["solved_runs"] += record.get("solved") is True
    metrics["logical_model_calls"] += logical_calls
    metrics["provider_attempts"] += _integer(record.get("provider_attempts"), "provider_attempts")
    metrics["usage_missing_calls"] += missing_calls
    metrics["usage_rate_denominator_calls"] += logical_calls
    tokens = record.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("tokens object is required")
    for field in TOKEN_FIELDS:
        value = tokens.get(field)
        if value is None:
            continue
        metrics["tokens"][field] += _integer(value, field)


def recompute(protocol_path: Path, output_dir: Path) -> dict[str, object]:
    protocol, task_families = _fixed_protocol(protocol_path)
    expected = _schedule(protocol, task_families)
    environment = _load_object(output_dir / "environment.json")
    routes = environment.get("model_routes")
    if environment.get("schema") != ENVIRONMENT_SCHEMA or not isinstance(routes, list):
        raise ValueError("M25 environment schema or routes are invalid")
    if len(routes) != 2 or tuple(route.get("model_id") for route in routes) != MODELS:
        raise ValueError("M25 environment model routes do not match")
    route_hashes = {}
    for route in routes:
        route_hash = route.get("provider_route_sha256")
        if not _sha256_string(route_hash):
            raise ValueError("M25 environment route hash is invalid")
        route_hashes[route["model_id"]] = route_hash
    protocol_sha256 = environment.get("protocol_sha256")
    if not _sha256_string(protocol_sha256) or protocol_sha256 != _protocol_sha256(protocol):
        raise ValueError("M25 environment protocol hash does not match protocol")
    environment_projection = dict(environment)
    environment_projection.pop("generated_at", None)
    environment_sha256_expected = _canonical_sha256(environment_projection)

    raw_dir = output_dir / "raw"
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ValueError("M25 raw directory is invalid")
    files = sorted(raw_dir.glob("*.json"))
    if len(files) != 270 or any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError("exactly 270 regular M25 raw files are required")

    models = {model: {mode: _empty_metrics() for mode in MODES} for model in MODELS}
    families = {
        family: {model: {mode: _empty_metrics() for mode in MODES} for model in MODELS}
        for family in FAMILIES
    }
    tasks = {
        task_id: {model: {mode: _empty_metrics() for mode in MODES} for model in MODELS}
        for task_id in task_families
    }
    seen = set()
    environment_sha256 = None
    for path in files:
        record = _load_object(path)
        combination = (
            record.get("task_id"),
            record.get("model_id"),
            record.get("repeat"),
            record.get("mode"),
        )
        spec = expected.get(combination)
        if spec is None or combination in seen:
            raise ValueError("M25 raw combination is missing, extra, or duplicate")
        seen.add(combination)
        model_id = combination[1]
        mode = combination[3]
        task_id = combination[0]
        if (
            record.get("schema") != RAW_SCHEMA
            or record.get("terminal") is not True
            or record.get("sequence") != spec["sequence"]
            or record.get("run_id") != spec["run_id"]
            or path.name != spec["run_id"] + ".json"
            or record.get("task_family") != spec["family"]
            or record.get("protocol_sha256") != protocol_sha256
            or record.get("provider_route_sha256") != route_hashes[model_id]
        ):
            raise ValueError("M25 raw identity does not match protocol or environment")
        expected_run_spec_sha256 = _canonical_sha256(
            {
                "protocol_sha256": protocol_sha256,
                "run": {
                    "sequence": spec["sequence"],
                    "task_id": task_id,
                    "task_family": spec["family"],
                    "model_id": model_id,
                    "repeat": combination[2],
                    "mode": mode,
                },
            }
        )
        if record.get("run_spec_sha256") != expected_run_spec_sha256:
            raise ValueError("M25 raw run-spec hash does not match")
        record_environment = record.get("environment_sha256")
        if (
            not _sha256_string(record_environment)
            or record_environment != environment_sha256_expected
        ):
            raise ValueError("M25 raw environment hash does not match environment")
        if environment_sha256 is None:
            environment_sha256 = record_environment
        elif environment_sha256 != record_environment:
            raise ValueError("M25 raw environment hashes are mixed")
        _add(models[model_id][mode], record)
        _add(families[spec["family"]][model_id][mode], record)
        _add(tasks[task_id][model_id][mode], record)
    if seen != expected.keys() or environment_sha256 is None:
        raise ValueError("complete M25 schedule is required")
    return {
        "runs": len(seen),
        "protocol_sha256": protocol_sha256,
        "environment_sha256": environment_sha256,
        "models": models,
        "families": families,
        "tasks": tasks,
    }


def _mismatch(path: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ValueError(f"independent recompute mismatch at {path}: {actual!r} != {expected!r}")


def _verify_bucket(path: str, projection: dict[str, Any], summary: dict[str, Any]) -> None:
    _mismatch(path + ".scheduled_runs", summary.get("scheduled_runs"), projection["scheduled_runs"])
    completion = summary.get("task_completion_rate")
    if not isinstance(completion, dict):
        raise ValueError(f"independent recompute mismatch at {path}.task_completion_rate")
    _mismatch(
        path + ".completion.numerator",
        completion.get("numerator"),
        projection["solved_runs"],
    )
    _mismatch(
        path + ".completion.denominator",
        completion.get("denominator"),
        projection["scheduled_runs"],
    )
    expected_completion = projection["solved_runs"] / projection["scheduled_runs"]
    if not math.isclose(completion.get("value"), expected_completion, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"independent recompute mismatch at {path}.completion.value")
    for field in ("logical_model_calls", "provider_attempts"):
        distribution = summary.get(field)
        if not isinstance(distribution, dict):
            raise ValueError(f"independent recompute mismatch at {path}.{field}")
        _mismatch(path + f".{field}.sum", distribution.get("sum"), projection[field])
    usage = summary.get("usage_missing_rate")
    if not isinstance(usage, dict):
        raise ValueError(f"independent recompute mismatch at {path}.usage_missing_rate")
    _mismatch(path + ".usage.numerator", usage.get("numerator"), projection["usage_missing_calls"])
    _mismatch(
        path + ".usage.denominator",
        usage.get("denominator"),
        projection["usage_rate_denominator_calls"],
    )
    denominator = projection["usage_rate_denominator_calls"]
    expected_usage = None if denominator == 0 else projection["usage_missing_calls"] / denominator
    actual_usage = usage.get("value")
    if expected_usage is None:
        _mismatch(path + ".usage.value", actual_usage, None)
    elif not isinstance(actual_usage, (int, float)) or not math.isclose(
        actual_usage, expected_usage, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError(f"independent recompute mismatch at {path}.usage.value")
    tokens = summary.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError(f"independent recompute mismatch at {path}.tokens")
    _mismatch(
        path + ".tokens.usage_missing_calls",
        tokens.get("usage_missing_calls"),
        projection["usage_missing_calls"],
    )
    for field in TOKEN_FIELDS:
        distribution = tokens.get(field)
        if not isinstance(distribution, dict):
            raise ValueError(f"independent recompute mismatch at {path}.tokens.{field}")
        actual = distribution.get("sum")
        _mismatch(
            path + f".tokens.{field}.sum",
            0 if actual is None else actual,
            projection["tokens"][field],
        )


def verify_summary(protocol_path: Path, output_dir: Path) -> None:
    projection = recompute(protocol_path, output_dir)
    summary = _load_object(output_dir / "summary.json")
    _mismatch("schema", summary.get("schema"), SUMMARY_SCHEMA)
    _mismatch("protocol_sha256", summary.get("protocol_sha256"), projection["protocol_sha256"])
    _mismatch(
        "environment_sha256",
        summary.get("environment_sha256"),
        projection["environment_sha256"],
    )
    completeness = summary.get("completeness")
    if not isinstance(completeness, dict):
        raise ValueError("independent recompute mismatch at completeness")
    _mismatch("completeness.expected_runs", completeness.get("expected_runs"), 270)
    _mismatch("completeness.observed_runs", completeness.get("observed_runs"), 270)
    _mismatch("completeness.complete", completeness.get("complete"), True)
    for model_id in MODELS:
        for mode in MODES:
            _verify_bucket(
                f"models.{model_id}.{mode}",
                projection["models"][model_id][mode],
                summary["models"][model_id]["modes"][mode],
            )
    for family in FAMILIES:
        for model_id in MODELS:
            for mode in MODES:
                _verify_bucket(
                    f"families.{family}.{model_id}.{mode}",
                    projection["families"][family][model_id][mode],
                    summary["families"][family]["models"][model_id]["modes"][mode],
                )
    for task_id, task_projection in projection["tasks"].items():
        for model_id in MODELS:
            for mode in MODES:
                _verify_bucket(
                    f"tasks.{task_id}.{model_id}.{mode}",
                    task_projection[model_id][mode],
                    summary["tasks"][task_id]["models"][model_id]["modes"][mode],
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    projection = recompute(arguments.protocol, arguments.output)
    verify_summary(arguments.protocol, arguments.output)
    print(f"INDEPENDENT_RECOMPUTE_OK runs={projection['runs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
