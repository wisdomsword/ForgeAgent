#!/usr/bin/env python3
"""Derive auditable M27 collaboration-routing evidence from frozen M25 runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import uuid
from pathlib import Path
from typing import Any


def _load_recompute_module():
    path = Path(__file__).with_name("m25_independent_recompute.py")
    spec = importlib.util.spec_from_file_location("m25_independent_recompute", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load M25 independent recompute")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M25 = _load_recompute_module()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _non_negative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"non-negative integer required for {field}")
    return value


def _non_negative_float(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"finite non-negative number required for {field}")
    return float(value)


def _validate_metric_fields(record: dict[str, Any]) -> None:
    for field in ("runtime_completed", "solved"):
        if type(record.get(field)) is not bool:
            raise ValueError(f"boolean required for {field}")
    reason = record.get("runtime_reason")
    if not isinstance(reason, str) or not reason:
        raise ValueError("non-empty string required for runtime_reason")
    for field in (
        "logical_model_calls",
        "provider_attempts",
        "usage_present_calls",
        "usage_missing_calls",
    ):
        _non_negative_integer(record.get(field), field)
    _non_negative_float(record.get("end_to_end_latency_seconds"), "end_to_end_latency_seconds")
    tokens = record.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("tokens object is required")
    for field in M25.TOKEN_FIELDS:
        value = tokens.get(field)
        if value is not None:
            _non_negative_integer(value, f"tokens.{field}")


def _empty_bucket() -> dict[str, Any]:
    return {
        "scheduled_runs": 0,
        "runtime_completed_runs": 0,
        "solved_runs": 0,
        "false_completions": 0,
        "termination_reasons": {},
        "logical_model_calls": {"sum": 0},
        "provider_attempts": {"sum": 0},
        "end_to_end_latency_seconds": {"sum": 0.0},
        "tokens": {"sum": {field: 0 for field in M25.TOKEN_FIELDS}},
    }


def _add(bucket: dict[str, Any], record: dict[str, Any]) -> None:
    bucket["scheduled_runs"] += 1
    completed = record["runtime_completed"]
    solved = record["solved"]
    bucket["runtime_completed_runs"] += completed
    bucket["solved_runs"] += solved
    bucket["false_completions"] += completed and not solved
    reason = record["runtime_reason"]
    bucket["termination_reasons"][reason] = bucket["termination_reasons"].get(reason, 0) + 1
    for field in ("logical_model_calls", "provider_attempts"):
        bucket[field]["sum"] += record[field]
    bucket["end_to_end_latency_seconds"]["sum"] += record["end_to_end_latency_seconds"]
    for field in M25.TOKEN_FIELDS:
        bucket["tokens"]["sum"][field] += record["tokens"].get(field) or 0


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else numerator / denominator,
    }


def _finish(bucket: dict[str, Any]) -> None:
    scheduled = bucket["scheduled_runs"]
    completed = bucket["runtime_completed_runs"]
    bucket["solved_rate"] = _rate(bucket["solved_runs"], scheduled)
    bucket["false_completion_rate_scheduled"] = _rate(bucket["false_completions"], scheduled)
    bucket["false_completion_rate_runtime_completed"] = _rate(
        bucket["false_completions"], completed
    )
    for field in ("logical_model_calls", "provider_attempts", "end_to_end_latency_seconds"):
        bucket[field]["mean"] = None if scheduled == 0 else bucket[field]["sum"] / scheduled
    bucket["tokens"]["mean"] = {
        field: None if scheduled == 0 else value / scheduled
        for field, value in bucket["tokens"]["sum"].items()
    }
    bucket["termination_reasons"] = dict(sorted(bucket["termination_reasons"].items()))


def _frozen_manifest(
    protocol_path: Path, run_dir: Path, raw_paths: list[Path]
) -> dict[str, object]:
    inputs = [("protocol.json", protocol_path)]
    inputs.extend(
        (name, run_dir / name) for name in ("environment.json", "summary.json", "report.md")
    )
    inputs.extend((f"raw/{path.name}", path) for path in raw_paths)
    files = [{"path": name, "sha256": _sha256(path)} for name, path in inputs]
    manifest = {"files": files}
    return {"files": files, "sha256": hashlib.sha256(_canonical_json(manifest)).hexdigest()}


def derive(protocol_path: Path, run_dir: Path) -> dict[str, object]:
    """Validate frozen M25 evidence and return an additive M27 routing projection."""
    protocol_path = protocol_path.resolve()
    run_dir = run_dir.resolve()
    M25.verify_summary(protocol_path, run_dir)
    projection = M25.recompute(protocol_path, run_dir)
    raw_paths = sorted((run_dir / "raw").glob("*.json"))

    models = {model: {mode: _empty_bucket() for mode in M25.MODES} for model in M25.MODELS}
    families = {family: {mode: _empty_bucket() for mode in M25.MODES} for family in M25.FAMILIES}
    for path in raw_paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError(f"JSON object is required: {path.name}")
        _validate_metric_fields(record)
        _add(models[record["model_id"]][record["mode"]], record)
        _add(families[record["task_family"]][record["mode"]], record)

    for modes in models.values():
        for bucket in modes.values():
            _finish(bucket)
    for modes in families.values():
        for bucket in modes.values():
            _finish(bucket)

    eligible = [
        family
        for family, modes in families.items()
        if modes["triad"]["solved_rate"]["value"] > modes["single"]["solved_rate"]["value"]
    ]
    restored = eligible.copy()
    reason = (
        "No task family has a strictly higher Triad solved rate than Single."
        if not restored
        else "Triad has a strictly higher solved rate than Single for: " + ", ".join(restored) + "."
    )
    return {
        "schema": "forgeagent.m27.collaboration-routing-analysis/v1",
        "source": {
            "milestone": "M25",
            "runs": projection["runs"],
            "protocol_sha256": projection["protocol_sha256"],
            "environment_sha256": projection["environment_sha256"],
            "frozen_manifest": _frozen_manifest(protocol_path, run_dir, raw_paths),
        },
        "models": models,
        "families": families,
        "quality_eligible_for_automatic_triad": eligible,
        "automatic_triad_restored_for": restored,
        "decision": {
            "default_mode": "single",
            "reason": reason,
            "triad_still_available_for": ["explicit_selection", "bound_checks"],
        },
    }


def _percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_report(analysis: dict[str, object]) -> str:
    """Render the immutable-input projection as a concise human-readable report."""
    source = analysis["source"]
    restored = analysis["automatic_triad_restored_for"]
    restored_description = (
        "M27 不恢复任何任务类别的自动 Triad：没有类别的 Triad solved rate 严格高于 Single。"
        if not restored
        else "M27 自动恢复以下任务类别的 Triad：" + ", ".join(restored) + "。"
    )
    lines = [
        "# M27 M25 协作路由派生分析",
        "",
        "## 结论",
        "",
        restored_description,
        "默认保持 Single；用户显式选择或可信宿主已绑定冻结检查时仍可使用 Triad。",
        "",
        "M25 早于 M26 冻结检查绑定。下列误完成和终止原因是历史结果，不能作为当前 "
        "evidence-bound Triad 质量的证明。",
        "",
        "## 冻结输入",
        "",
        f"- runs: {source['runs']}",
        f"- protocol SHA-256: `{source['protocol_sha256']}`",
        f"- environment SHA-256: `{source['environment_sha256']}`",
        f"- frozen manifest SHA-256: `{source['frozen_manifest']['sha256']}`",
        "",
        "## 任务类别比较",
        "",
        "| 类别 | Single solved | Triad solved | Single 延迟均值 (s) | Triad 延迟均值 (s) | "
        "Single 调用均值 | Triad 调用均值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, modes in analysis["families"].items():
        single = modes["single"]
        triad = modes["triad"]
        lines.append(
            "| {family} | {single_solved} | {triad_solved} | {single_latency:.3f} | "
            "{triad_latency:.3f} | {single_calls:.2f} | {triad_calls:.2f} |".format(
                family=family,
                single_solved=_percentage(single["solved_rate"]["value"]),
                triad_solved=_percentage(triad["solved_rate"]["value"]),
                single_latency=single["end_to_end_latency_seconds"]["mean"],
                triad_latency=triad["end_to_end_latency_seconds"]["mean"],
                single_calls=single["logical_model_calls"]["mean"],
                triad_calls=triad["logical_model_calls"]["mean"],
            )
        )
    lines.extend(
        [
            "",
            "## 误完成与终止原因",
            "",
            "误完成定义为 `runtime_completed == true && solved == false`。率同时以 scheduled runs "
            "和 runtime-completed runs 为分母；原因按 raw `runtime_reason` 原样分类。"
            "完整机器读数见 `analysis.json`。",
            "",
            "## 策略裁决",
            "",
            "quality eligible: "
            + (", ".join(analysis["quality_eligible_for_automatic_triad"]) or "none"),
            "automatic Triad restored: "
            + (", ".join(analysis["automatic_triad_restored_for"]) or "none"),
            "",
        ]
    )
    return "\n".join(lines)


def _ensure_output_outside_run(output_dir: Path, run_dir: Path) -> None:
    if output_dir.resolve().is_relative_to(run_dir.resolve()):
        raise ValueError("output directory must be outside the frozen run directory")


def write_outputs(output_dir: Path, analysis: dict[str, object]) -> None:
    outputs = {
        "analysis.json": _canonical_json(analysis),
        "report.md": render_report(analysis).encode(),
    }
    transaction_dir = output_dir / f".m27-routing-analysis-{uuid.uuid4().hex}"
    paths = {
        name: {
            "destination": output_dir / name,
            "staged": transaction_dir / f"{name}.staged",
            "old": transaction_dir / f"{name}.old",
            "failed_new": transaction_dir / f"{name}.failed-new",
        }
        for name in outputs
    }

    def cleanup_transaction() -> list[BaseException]:
        errors: list[BaseException] = []
        for file_paths in paths.values():
            for key in ("staged", "old", "failed_new"):
                try:
                    file_paths[key].unlink(missing_ok=True)
                except BaseException as error:
                    errors.append(error)
        try:
            transaction_dir.rmdir()
        except BaseException as error:
            errors.append(error)
        return errors

    output_dir.mkdir(parents=True, exist_ok=True)
    transaction_dir.mkdir()
    had_old = {name: False for name in outputs}
    publish_started = {name: False for name in outputs}
    try:
        for name, content in outputs.items():
            with paths[name]["staged"].open("xb") as handle:
                handle.write(content)

        for name, file_paths in paths.items():
            try:
                file_paths["destination"].lstat()
            except FileNotFoundError:
                pass
            else:
                had_old[name] = True
                file_paths["destination"].replace(file_paths["old"])
            publish_started[name] = True
            file_paths["staged"].replace(file_paths["destination"])
    except BaseException as transaction_error:
        if not isinstance(transaction_error, Exception):
            raise BaseExceptionGroup(
                "output publication was interrupted; transaction evidence was retained",
                [transaction_error],
            ) from transaction_error
        if any(
            had_old[name]
            and not publish_started[name]
            and isinstance(transaction_error, FileNotFoundError)
            for name in outputs
        ):
            raise BaseExceptionGroup(
                "output backup state was uncertain; transaction evidence was retained",
                [transaction_error],
            ) from transaction_error

        rollback_errors: list[BaseException] = []
        rollback_uncertain = False
        for name, file_paths in paths.items():
            restored_old = False
            try:
                file_paths["old"].replace(file_paths["destination"])
                restored_old = True
            except FileNotFoundError:
                if had_old[name]:
                    rollback_uncertain = True
                    rollback_errors.append(
                        RuntimeError(
                            f"rollback state uncertain for {file_paths['destination'].name}"
                        )
                    )
                    continue
            except BaseException as restore_error:
                rollback_uncertain = True
                rollback_errors.append(restore_error)
                continue

            if restored_old:
                continue

            try:
                file_paths["staged"].replace(file_paths["failed_new"])
            except FileNotFoundError:
                if publish_started[name]:
                    try:
                        file_paths["destination"].replace(file_paths["failed_new"])
                    except FileNotFoundError:
                        rollback_uncertain = True
                        rollback_errors.append(
                            RuntimeError(
                                f"rollback state uncertain for {file_paths['destination'].name}"
                            )
                        )
                    except BaseException as remove_new_error:
                        rollback_uncertain = True
                        rollback_errors.append(remove_new_error)
            except BaseException as probe_error:
                rollback_uncertain = True
                rollback_errors.append(probe_error)

        if rollback_uncertain:
            raise BaseExceptionGroup(
                "output publication failed and rollback was incomplete",
                [transaction_error, *rollback_errors],
            ) from transaction_error

        cleanup_errors = cleanup_transaction()
        if cleanup_errors:
            raise BaseExceptionGroup(
                "output publication failed and transaction cleanup was incomplete",
                [transaction_error, *cleanup_errors],
            ) from transaction_error
        raise
    else:
        cleanup_errors = cleanup_transaction()
        if cleanup_errors:
            raise BaseExceptionGroup("output publication cleanup failed", cleanup_errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    _ensure_output_outside_run(arguments.output_dir, arguments.run_dir)
    analysis = derive(arguments.protocol, arguments.run_dir)
    write_outputs(arguments.output_dir, analysis)
    restored = analysis["automatic_triad_restored_for"]
    print(
        "M27_ROUTING_ANALYSIS_OK "
        f"runs={analysis['source']['runs']} restored={','.join(restored) or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
