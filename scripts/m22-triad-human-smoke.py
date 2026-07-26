"""Validate the persisted state for the M22 Triad human smoke test."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SmokeModels:
    generator: str
    planner: str
    evaluator: str


@dataclass(frozen=True)
class SmokeConfig:
    workdir: Path
    forgeagent: Path
    python: Path
    models: SmokeModels


GOAL = (
    "在当前目录创建 calc.py 和 test_calc.py。calc.py 必须提供 "
    "moving_average(values, window)，window 小于等于 0 或大于数据长度时抛出 "
    "ValueError；命令行执行 python calc.py '[1,2,3,4]' 2 必须输出 JSON "
    "[1.5,2.5,3.5]；使用 pytest 覆盖正常和异常情况。"
)

RunCommand = Callable[..., subprocess.CompletedProcess[str]]

_COLLABORATION_ID = re.compile(r"^[0-9a-f]{32}$")
_PLAN_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = frozenset({"active", "completed", "stopped", "cancelled", "failed"})
_PHASES = frozenset(
    {
        "planning",
        "needs_confirmation",
        "generator",
        "evaluator",
        "completed",
        "stopped",
        "cancelled",
        "failed",
    }
)
_STOP_REASONS = frozenset(
    {
        "completed",
        "needs_confirmation",
        "rejection_limit",
        "cancelled",
        "state_failure",
        "unrecoverable_failure",
        "invalid_role_submission",
        "role_failed",
    }
)


def build_forgeagent_command(forgeagent: Path, models: SmokeModels) -> list[str]:
    """Build the fixed argv contract for the manual Triad run."""
    return [
        str(forgeagent),
        "--model",
        models.generator,
        "--tier",
        "restricted",
        "--no-identity",
        "--no-memory",
        "run",
        "--mode",
        "triad",
        "--planner-model",
        models.planner,
        "--evaluator-model",
        models.evaluator,
        "--max-rejections",
        "2",
        GOAL,
    ]


def load_collaboration_state(workdir: Path) -> dict[str, object]:
    """Load the one regular collaboration state file from a smoke workdir."""
    directory = workdir / ".forgeagent" / "collaborations"
    try:
        candidates = [
            path for path in directory.glob("*.json") if not path.is_symlink() and path.is_file()
        ]
    except OSError:
        raise ValueError("could not discover collaboration state") from None
    if len(candidates) != 1:
        raise ValueError("expected exactly one collaboration state")

    try:
        value = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("invalid collaboration state JSON") from None
    if not isinstance(value, dict):
        raise ValueError("invalid collaboration state JSON") from None
    return value


def collaboration_failures(state: dict[str, object]) -> list[str]:
    """Return validation failures for the raw state projection consumed by this smoke test."""
    failures: list[str] = []
    if not _is_string_matching(state.get("collaboration_id"), _COLLABORATION_ID):
        failures.append("invalid collaboration_id")
    if state.get("mode") != "triad":
        failures.append("mode is not triad")
    if state.get("status") != "completed":
        failures.append(f"status is not completed: {_stable_value(state.get('status'), _STATUSES)}")
    if state.get("phase") != "completed":
        failures.append(f"phase is not completed: {_stable_value(state.get('phase'), _PHASES)}")
    if state.get("stop_reason") != "completed":
        failures.append(
            "stop_reason is not completed: "
            f"{_stable_value(state.get('stop_reason'), _STOP_REASONS)}"
        )

    plan_ids = _plan_ids(state.get("plan"), failures)
    if not _is_string_matching(state.get("plan_digest"), _PLAN_DIGEST):
        failures.append("invalid plan_digest")
    _positive_attempt(state, "generator_attempts", failures)
    _positive_attempt(state, "evaluator_attempts", failures)
    _nonnegative_counter(state, "rejections", failures)
    _evaluation_ids(state.get("last_evaluation"), plan_ids, failures)
    return failures


def _is_string_matching(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _stable_value(value: object, allowed: frozenset[str]) -> str:
    return value if type(value) is str and value in allowed else "invalid"


def _plan_ids(value: object, failures: list[str]) -> list[str]:
    if type(value) is not list or not value:
        failures.append("plan must be a non-empty list")
        return []

    ids: list[str] = []
    for item in value:
        item_id = item.get("id") if type(item) is dict else None
        if type(item_id) is not str or not item_id:
            failures.append("plan item id must be a non-empty string")
            continue
        ids.append(item_id)
    if len(ids) != len(set(ids)):
        failures.append("plan item ids must be unique")
    return ids


def _positive_attempt(state: dict[str, object], name: str, failures: list[str]) -> None:
    value = state.get(name)
    if type(value) is not int or value <= 0:
        failures.append(f"{name} must be a positive integer")


def _nonnegative_counter(state: dict[str, object], name: str, failures: list[str]) -> None:
    value = state.get(name)
    if type(value) is not int or value < 0:
        failures.append(f"{name} must be a non-negative integer")


def _evaluation_ids(value: object, plan_ids: list[str], failures: list[str]) -> None:
    if type(value) is not list or not value:
        failures.append("last_evaluation must be a non-empty list")
        return

    evaluation_ids: list[str] = []
    for item in value:
        item_id = item.get("id") if type(item) is dict else None
        passed = item.get("passed") if type(item) is dict else None
        if type(item_id) is not str or not item_id:
            failures.append("last_evaluation item id must be a non-empty string")
        else:
            evaluation_ids.append(item_id)
        if type(passed) is not bool or passed is not True:
            failures.append("last_evaluation passed must be true")
    if evaluation_ids != plan_ids:
        failures.append("last_evaluation ids must match plan ids in order")


def artifact_failures(workdir: Path, python: Path, run: RunCommand) -> list[str]:
    """Validate the two generated files and their required CLI behavior."""
    failures = [
        f"missing regular file: {name}"
        for name in ("calc.py", "test_calc.py")
        if not _is_regular_file(workdir / name)
    ]
    if failures:
        return failures

    pytest_result = run(
        [str(python), "-m", "pytest", "-q"],
        cwd=workdir,
        check=False,
    )
    if pytest_result.returncode != 0:
        return [f"pytest failed with exit code {pytest_result.returncode}"]

    cli_result = run(
        [str(python), "calc.py", "[1,2,3,4]", "2"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if cli_result.returncode != 0:
        return [f"calc.py CLI failed with exit code {cli_result.returncode}"]
    if not isinstance(cli_result.stderr, str) or cli_result.stderr.strip():
        return ["calc.py CLI output validation failed"]
    if not isinstance(cli_result.stdout, str):
        return ["calc.py CLI output validation failed"]
    try:
        value = json.loads(cli_result.stdout)
    except (json.JSONDecodeError, RecursionError):
        return ["calc.py CLI output validation failed"]
    if value != [1.5, 2.5, 3.5]:
        return ["calc.py CLI output validation failed"]
    return []


def run_smoke(config: SmokeConfig, run: RunCommand = subprocess.run) -> int:
    """Run the manual Triad smoke test and print a stable, safe summary."""
    print(f"workdir: {config.workdir}")
    try:
        forgeagent_result = run(
            build_forgeagent_command(config.forgeagent, config.models),
            cwd=config.workdir,
            check=False,
        )
        failures: list[str] = []
        try:
            state = load_collaboration_state(config.workdir)
        except ValueError as error:
            state = None
            failures.append(f"state: {error}")

        if forgeagent_result.returncode != 0:
            failures.append(f"ForgeAgent failed with exit code {forgeagent_result.returncode}")
        if state is not None:
            failures.extend(collaboration_failures(state))
        if not failures:
            failures.extend(artifact_failures(config.workdir, config.python, run))
        if failures:
            _print_failure_summary(failures)
            return 1

        _print_success_summary(state)
        return 0
    except KeyboardInterrupt:
        print("M22 TRIAD HUMAN SMOKE: INTERRUPTED")
        return 130


def _is_regular_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _print_failure_summary(failures: list[str]) -> None:
    print("M22 TRIAD HUMAN SMOKE: FAIL")
    for failure in failures:
        print(f"failure: {failure}")


def _print_success_summary(state: dict[str, object]) -> None:
    print("M22 TRIAD HUMAN SMOKE: PASS")
    print(f"collaboration: {state['collaboration_id']}")
    print(f"generator_attempts: {state['generator_attempts']}")
    print(f"evaluator_attempts: {state['evaluator_attempts']}")
    print(f"rejections: {state['rejections']}")
