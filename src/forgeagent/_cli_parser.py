"""Argument parsing and isolated evaluation-command helpers for the CLI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from rich.console import Console

from .client import ModelClient
from .collaboration import normalize_required_candidate_files
from .context import ContextConfig, load_context_config
from .model_registry import RegistryError
from .sandbox import RestrictedLimits, load_restricted_limits, resolve_restricted_limits

if TYPE_CHECKING:
    from .evaluation import EvaluationRecord, TrendAppendResult
    from .evaluator import EvaluationRequest, EvaluatorResult


DEFAULT_MODEL = "claude-sonnet-5"


def load_cli_context_config(
    raw_override: str | None,
    *,
    context_loader: Callable[..., ContextConfig] = load_context_config,
    json_loader: Callable[[str], object] = json.loads,
) -> ContextConfig:
    """Load context configuration while preserving the CLI's bounded errors."""
    try:
        if raw_override is None:
            return context_loader()
        override = json_loader(raw_override)
        if not isinstance(override, Mapping):
            raise ValueError("context configuration root must be a mapping")
        return context_loader(data=override)
    except RecursionError:
        raise RegistryError("Invalid context configuration: nesting is too deep") from None
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RegistryError(f"Invalid context configuration: {exc}") from exc


def load_required_candidate_files(
    raw: str | None,
    *,
    json_loader: Callable[[str], object] = json.loads,
    normalizer: Callable[[object], tuple[str, ...]] = normalize_required_candidate_files,
) -> tuple[str, ...]:
    if raw is None:
        return ()
    try:
        return normalizer(json_loader(raw))
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise RegistryError("Invalid candidate file configuration") from None


def load_cli_restricted_limits(
    *,
    timeout_seconds: float | None,
    cpu_seconds: int | None,
    memory_mb: int | None,
    limits_loader: Callable[[], RestrictedLimits] = load_restricted_limits,
) -> RestrictedLimits:
    """Load restricted limits and apply explicit CLI overrides."""
    try:
        return resolve_restricted_limits(
            limits_loader(),
            timeout_seconds=timeout_seconds,
            cpu_seconds=cpu_seconds,
            memory_mb=memory_mb,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RegistryError(f"Invalid restricted sandbox configuration: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgeagent", description="Lightweight code-as-action agent."
    )
    parser.add_argument(
        "--tier",
        choices=("trusted", "restricted", "container"),
        default="restricted",
        help="sandbox tier (default: restricted; container requires docker)",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="skip session and project memory loading, injection, and writes",
    )
    parser.add_argument(
        "--container-image",
        default=None,
        metavar="IMAGE",
        help="container tier image (default: python:3.11-slim)",
    )
    parser.add_argument(
        "--restricted-timeout-seconds",
        type=float,
        default=None,
        metavar="SECONDS",
        help="override restricted tier wall-clock limit",
    )
    parser.add_argument(
        "--restricted-cpu-seconds",
        type=int,
        default=None,
        metavar="SECONDS",
        help="override restricted tier CPU-time limit",
    )
    parser.add_argument(
        "--restricted-memory-mb",
        type=int,
        default=None,
        metavar="MB",
        help="override restricted tier address-space limit",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"model id (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="render responses live as they arrive (auto-disabled when not attached to a terminal)",
    )
    parser.add_argument(
        "--no-identity",
        action="store_true",
        help="skip SOUL/USER/AGENTS/MEMORY identity files; use the built-in default prompt only",
    )
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run a single goal and exit")
    run_p.add_argument("goal", help="the task goal")
    run_p.add_argument("--mode", choices=("single", "duo", "triad"), default=None)
    run_p.add_argument("--planner-model", default=None)
    run_p.add_argument("--evaluator-model", default=None)
    run_p.add_argument("--max-rejections", type=int, default=2)
    run_p.add_argument(
        "--interactive",
        action="store_true",
        help="allow mid-task Survey questions (prompts on the terminal)",
    )
    receipts_p = sub.add_parser("receipts", help="inspect and reconcile external action receipts")
    receipts_sub = receipts_p.add_subparsers(dest="receipts_command", required=True)
    list_p = receipts_sub.add_parser("list", help="list bounded receipt metadata")
    list_p.add_argument("--loop-id", default=None)
    list_p.add_argument("--task-id", default=None)
    resolve_p = receipts_sub.add_parser("resolve", help="resolve one receipt explicitly")
    resolve_p.add_argument("action_id")
    decision = resolve_p.add_mutually_exclusive_group(required=True)
    decision.add_argument("--confirmed", action="store_true")
    decision.add_argument("--abandon", action="store_true")
    decision.add_argument("--retry", action="store_true")
    resolve_p.add_argument("--revision", type=int, required=True)
    resolve_p.add_argument("--evidence", default="")
    run_p.add_argument(
        "--image",
        default=None,
        metavar="PATH",
        help="attach image(s) at PATH (a file, or a directory of images)",
    )
    loop_p = sub.add_parser("loop", help="run or resume one bounded durable Loop")
    loop_p.add_argument("goal", nargs="?", help="the frozen Loop goal for a new Loop")
    loop_p.add_argument("--token-budget", type=int, default=None, metavar="INT")
    loop_p.add_argument("--max-rounds", type=int, default=None, metavar="INT")
    loop_p.add_argument("--wall-clock-seconds", type=float, default=None, metavar="SECONDS")
    loop_p.add_argument("--max-consecutive-failures", type=int, default=None, metavar="INT")
    loop_p.add_argument("--resume", default=None, metavar="LOOP_ID", help="resume a durable Loop")
    loop_p.add_argument("--collaboration-mode", choices=("single", "duo", "triad"), default=None)
    loop_p.add_argument("--planner-model", default=None)
    loop_p.add_argument("--evaluator-model", default=None)
    loop_p.add_argument("--max-rejections", type=int, default=None)
    sub.add_parser("models", help="list available models and their aliases")
    smoke_p = sub.add_parser("smoke", help="run a live smoke check against real models")
    smoke_p.add_argument(
        "--include-fable",
        action="store_true",
        help="also run claude-fable-5 (opt-in: extra cost + refusal risk)",
    )
    smoke_p.add_argument(
        "--include-openai-compatible",
        action="store_true",
        help="also run gpt-5.4-mini/glm-5.2/deepseek-v4-flash (opt-in: separate API keys required)",
    )
    serve_p = sub.add_parser("serve", help="run the local authenticated HTTP task service")
    serve_p.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="server-owned HTTP service configuration",
    )
    serve_p.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    evaluate_p = sub.add_parser(
        "evaluate", help="evaluate declared artifacts with an isolated real-model session"
    )
    evaluate_p.add_argument("--model", dest="evaluate_model", required=True)
    evaluate_p.add_argument("--artifact-root", required=True, metavar="PATH")
    evaluate_p.add_argument("--task-description", required=True, metavar="TEXT")
    evaluate_p.add_argument("--expected-behavior", required=True, metavar="TEXT")
    evaluate_p.add_argument(
        "--artifact", dest="artifacts", action="append", required=True, metavar="PATH"
    )
    evaluate_p.add_argument("--golden-report", default=None, metavar="PATH")
    evaluate_p.add_argument("--audit-jsonl", default=None, metavar="PATH")
    evaluate_p.add_argument("--record-dir", default=None, metavar="ABSOLUTE_PATH")
    return parser


def load_strict_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value: {value}")
        ),
    )


def validate_artifact_manifest(root: Path, paths: list[str]):
    from .evaluator import validate_artifact_manifest as validate

    return validate(root, paths)


def run_evaluator(client: ModelClient, request: EvaluationRequest) -> EvaluatorResult:
    from .evaluator import run_evaluator as run

    return run(client, request)


def evaluation_record(
    golden_report_path: str | None, audit_jsonl_path: str | None
) -> EvaluationRecord:
    from .evaluation import EvaluationMetrics, EvaluationRecord, aggregate_metrics

    golden_report: Mapping[str, object] | None = None
    audit_events: list[Mapping[str, object]] = []
    if golden_report_path is not None:
        loaded = load_strict_json(Path(golden_report_path))
        if not isinstance(loaded, dict):
            raise ValueError("golden report must be a JSON object")
        golden_report = loaded
    if audit_jsonl_path is not None:
        for line in Path(audit_jsonl_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            loaded = json.loads(
                line,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON value: {value}")
                ),
            )
            if not isinstance(loaded, dict):
                raise ValueError("audit line must be a JSON object")
            audit_events.append(loaded)
    if golden_report is None:
        if audit_events:
            projected = aggregate_metrics({}, audit_events=audit_events)
            return EvaluationRecord(metrics=projected.metrics)
        return EvaluationRecord(metrics=EvaluationMetrics())
    return aggregate_metrics(golden_report, audit_events=audit_events)


def metric_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4g}"


def append_trend(record_dir: Path, record: EvaluationRecord) -> TrendAppendResult:
    from .evaluation import append_trend as append

    return append(record_dir, record)


def render_evaluation(
    console: Console,
    result: EvaluatorResult,
    record: EvaluationRecord,
    trend: TrendAppendResult | None,
    artifacts: list[str],
) -> None:
    from .evaluation import METRIC_NAMES

    console.print(f"evaluation status: {result.status}")
    console.print(f"artifacts: {', '.join(artifacts)}")
    for item in result.observed_evidence:
        console.print(f"observed: {item}")
    for item in result.unmet_expectations:
        console.print(f"unmet: {item}")
    for name in METRIC_NAMES:
        console.print(f"{name}: {metric_text(getattr(record.metrics, name))}")
    if trend is not None:
        for name in METRIC_NAMES:
            console.print(f"delta.{name}: {metric_text(trend.comparison.deltas[name])}")


def run_evaluate_command(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[str], ModelClient],
    console: Console,
    error_console: Console,
    validate_manifest: Callable,
    evaluate: Callable,
    make_record: Callable,
    append_record: Callable,
) -> int:
    try:
        client = client_factory(args.evaluate_model)
    except Exception:
        error_console.print("[red]evaluation preflight failed[/red]")
        return 2

    try:
        from .evaluator import EvaluationRequest, EvaluatorPreflightError

        try:
            artifact_root = Path(args.artifact_root)
            artifacts = validate_manifest(artifact_root, args.artifacts)
            record = make_record(args.golden_report, args.audit_jsonl)
            record_dir = Path(args.record_dir) if args.record_dir is not None else None
            if record_dir is not None and not record_dir.is_absolute():
                raise ValueError("record directory must be absolute")
        except (EvaluatorPreflightError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            error_console.print("[red]evaluation preflight failed[/red]")
            return 2

        request = EvaluationRequest(
            task_description=args.task_description,
            expected_behavior=args.expected_behavior,
            artifact_root=artifact_root,
            artifacts=artifacts,
        )
        result = evaluate(client, request)
        trend = None
        if record_dir is not None:
            try:
                record_dir.mkdir(parents=True, exist_ok=True)
                trend = append_record(record_dir, record)
            except (OSError, ValueError):
                error_console.print("[red]evaluation persistence failed[/red]")
                return 2

        render_evaluation(console, result, record, trend, args.artifacts)
        return 0 if result.status == "passed" else 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
