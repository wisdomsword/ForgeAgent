"""Run the bounded M26 completion-evidence evaluation."""

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import forgeagent
from forgeagent.check_runner import CheckDefinition
from forgeagent.cli import build_real_client
from forgeagent.client import MockClient, ModelClient
from forgeagent.collaboration import (
    CollaborationRunner,
    headless_plan_confirmer,
)
from forgeagent.model_registry import Registry, RegistryError, load_registry, resolve_model
from forgeagent.models import AssistantMessage, GenerationParams, TokenUsage
from forgeagent.task import Task, TaskOutcome

SCHEMA = "forgeagent.m26.completion-evidence/v1"
EVIDENCE_SCHEMA = "forgeagent.m26.completion-evidence-run/v1"
DEFAULT_EVALUATION_ROOT = Path(__file__).parents[1] / "docs" / "evaluation"
DEFAULT_PROTOCOL = DEFAULT_EVALUATION_ROOT / "m26" / "protocol.json"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_RUNTIME_PATHS = (
    "src/forgeagent/check_runner.py",
    "src/forgeagent/collaboration.py",
)
_ENVIRONMENT_KEYS = {
    "schema",
    "generated_at",
    "git_commit",
    "tracked_dirty",
    "package_version",
    "harness_sha256",
    "runtime_sha256",
    "execution",
    "real_execution",
    "fallback_reason",
    "requested_model_id",
    "provider_route_sha256",
    "python",
    "platform",
    "protocol_sha256",
}
_SUMMARY_KEYS = {
    "schema",
    "execution",
    "fallback_reason",
    "run_count",
    "completed_runs",
    "protocol_sha256",
    "environment_sha256",
    "raw_sha256",
}
_RAW_KEYS = {
    "schema",
    "sequence",
    "mode",
    "scenario",
    "status",
    "stop_reason",
    "generator_attempts",
    "evaluator_attempts",
    "failed_submit_before_check",
    "check_before_successful_submit",
    "tool_events",
    "execution",
    "protocol_sha256",
    "environment_sha256",
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GenerationSpec(_FrozenModel):
    max_output_tokens: int = Field(ge=1)
    temperature: float
    thinking: Literal["on", "off", "auto"]
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None
    timeout_seconds: float = Field(gt=0)


class FixtureSpec(_FrozenModel):
    goal: str = Field(min_length=1)
    files: dict[str, str]
    required_candidate_files: tuple[str, ...]


class CheckSpec(_FrozenModel):
    id: str
    command: tuple[str, ...]
    timeout_seconds: float = Field(gt=0)


class RunSpec(_FrozenModel):
    mode: Literal["duo", "triad"]
    scenario: Literal["skip-check-first", "all-pass"]


class Protocol(_FrozenModel):
    schema_: Literal[SCHEMA] = Field(alias="schema")
    model_id: str
    generation: GenerationSpec
    fixture: FixtureSpec
    check: CheckSpec
    runs: tuple[RunSpec, ...]


class _RecordingTask:
    def __init__(
        self,
        role: str,
        task: Task,
        client: ModelClient,
        outcomes: list[tuple[str, TaskOutcome]],
    ) -> None:
        self._role = role
        self._task = task
        self._client = client
        self._outcomes = outcomes

    def run(self, goal: str, *, cancel_event=None) -> TaskOutcome:
        outcome = self._task.run(goal, cancel_event=cancel_event)
        self._outcomes.append((self._role, outcome))
        return outcome

    def close(self) -> None:
        try:
            self._task.close()
        finally:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()


class _RoleBuilder:
    def __init__(
        self,
        *,
        root: Path,
        params: GenerationParams,
        client_factory: Callable[[str, int], ModelClient],
    ) -> None:
        self._root = root
        self._params = params
        self._client_factory = client_factory
        self.outcomes: list[tuple[str, TaskOutcome]] = []

    def __call__(self, role, attempt, registry, system_prompt):
        client = self._client_factory(role, attempt)
        task = Task(
            client,
            tier="restricted",
            allowed_root=str(self._root),
            system_prompt=system_prompt,
            max_rounds=4,
            params=self._params,
            tool_registry=registry,
        )
        return _RecordingTask(role, task, client, self.outcomes)


def load_protocol(path: Path) -> Protocol:
    protocol = Protocol.model_validate_json(path.read_bytes())
    expected = (
        ("duo", "skip-check-first"),
        ("duo", "all-pass"),
        ("triad", "skip-check-first"),
        ("triad", "all-pass"),
    )
    if tuple((run.mode, run.scenario) for run in protocol.runs) != expected:
        raise ValueError("protocol must contain the fixed four-run matrix")
    if protocol.check.command[:1] != ("{python}",):
        raise ValueError("check command must use {python}")
    for fixture_path in (*protocol.fixture.files, *protocol.fixture.required_candidate_files):
        _validate_fixture_path(fixture_path)
    if set(protocol.fixture.required_candidate_files) - set(protocol.fixture.files):
        raise ValueError("required candidate files must be supplied by the fixture")
    return protocol


def build_schedule(protocol: Protocol) -> tuple[RunSpec, ...]:
    return protocol.runs


def _validate_fixture_path(value: str) -> tuple[str, ...]:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.name in {"", ".", ".."}
    ):
        raise ValueError("fixture path must be a safe relative path")
    return path.parts


def _write_fixture_files(root: Path, files: Mapping[str, str]) -> None:
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for relative, content in files.items():
            parts = _validate_fixture_path(relative)
            parent_fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    os.close(parent_fd)
                    parent_fd = next_fd
                descriptor = os.open(
                    parts[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    with os.fdopen(descriptor, "wb", closefd=False) as stream:
                        stream.write(content.encode("utf-8"))
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise ValueError("fixture path is unsafe") from exc
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


def validate_output_dir(output: Path, *, evaluation_root: Path) -> Path:
    root = Path(os.path.abspath(evaluation_root))
    runs_root = root / "m26" / "runs"
    candidate = Path(os.path.abspath(output))
    if candidate.parent != runs_root or _RUN_ID.fullmatch(candidate.name) is None:
        raise ValueError("output must be one run directory under the M26 runs root")
    for path in (root, root / "m26", runs_root, candidate):
        if path.exists() and path.is_symlink():
            raise ValueError("output path must not contain a symlink")
    if runs_root.resolve(strict=False) != runs_root or candidate.resolve(strict=False) != candidate:
        raise ValueError("output path must not contain a symlink")
    runs_root.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(exist_ok=True)
    return candidate


def protected_evidence_hashes(evaluation_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for milestone in ("m23", "m25"):
        root = evaluation_root / milestone
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                hashes[f"{milestone}/{path.relative_to(root).as_posix()}"] = _sha256(
                    path.read_bytes()
                )
    return hashes


def _assistant(markers: Sequence[Mapping[str, object]]) -> AssistantMessage:
    content = "\n".join(
        f"<!-- ToolCall: {json.dumps(marker, separators=(',', ':'), sort_keys=True)} -->"
        for marker in markers
    )
    return AssistantMessage(
        content=content,
        usage=TokenUsage(input_tokens=1, output_tokens=1, total_prompt_tokens=1),
        stop_reason="end_turn",
    )


def _evaluation_marker() -> dict[str, object]:
    return {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "goal",
                    "passed": True,
                    "observed": "host check passed",
                    "expected": "fixture pytest passes",
                    "location": "test_increment.py",
                }
            ]
        },
    }


def _controlled_scripts(mode: str, scenario: str) -> dict[tuple[str, int], list[AssistantMessage]]:
    check = {"name": "RunCheck", "arguments": {"check_id": "fixture-pytest"}}
    submit = _evaluation_marker()
    evaluator = (
        [_assistant([submit]), _assistant([check, submit])]
        if scenario == "skip-check-first"
        else [_assistant([check, submit])]
    )
    scripts = {
        ("generator", 1): [_assistant([{"name": "SubmitCandidate", "arguments": {}}])],
        ("evaluator", 1): evaluator,
    }
    if mode == "triad":
        scripts[("planner", 1)] = [
            _assistant(
                [
                    {
                        "name": "SubmitPlan",
                        "arguments": {
                            "items": [
                                {
                                    "id": "goal",
                                    "behavior": "the supplied increment fixture remains valid",
                                    "acceptance": "fixture pytest passes",
                                }
                            ]
                        },
                    }
                ]
            )
        ]
    return scripts


def _params(spec: GenerationSpec) -> GenerationParams:
    return GenerationParams(**spec.model_dump(mode="python"))


def _check_definition(protocol: Protocol) -> CheckDefinition:
    argv = tuple(sys.executable if item == "{python}" else item for item in protocol.check.command)
    return CheckDefinition(
        id=protocol.check.id,
        argv=argv,
        timeout_seconds=protocol.check.timeout_seconds,
    )


def _tool_events(outcomes: Sequence[tuple[str, TaskOutcome]]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for role, outcome in outcomes:
        if role != "evaluator":
            continue
        for round_result in outcome.rounds:
            for item in round_result.outcomes:
                if item.tool in {"RunCheck", "SubmitEvaluation"}:
                    events.append({"tool": item.tool, "success": item.success})
    return events


def _sequence_evidence(events: Sequence[Mapping[str, object]]) -> tuple[bool, bool]:
    failed_submit = next(
        (
            index
            for index, item in enumerate(events)
            if item == {"tool": "SubmitEvaluation", "success": False}
        ),
        None,
    )
    passed_check = next(
        (
            index
            for index, item in enumerate(events)
            if item == {"tool": "RunCheck", "success": True}
        ),
        None,
    )
    passed_submit = next(
        (
            index
            for index, item in enumerate(events)
            if item == {"tool": "SubmitEvaluation", "success": True}
        ),
        None,
    )
    return (
        failed_submit is not None and passed_check is not None and failed_submit < passed_check,
        passed_check is not None and passed_submit is not None and passed_check < passed_submit,
    )


def _run_one(
    protocol: Protocol,
    spec: RunSpec,
    *,
    client_factory: Callable[[str, int], ModelClient],
    fixture_root: Path,
) -> dict[str, object]:
    _write_fixture_files(fixture_root, protocol.fixture.files)
    builder = _RoleBuilder(
        root=fixture_root, params=_params(protocol.generation), client_factory=client_factory
    )
    runner = CollaborationRunner.create(
        mode=spec.mode,
        goal=protocol.fixture.goal,
        allowed_root=str(fixture_root),
        role_task_builder=builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
        evaluator_checks={protocol.check.id: _check_definition(protocol)},
        required_candidate_files=protocol.fixture.required_candidate_files,
        task_data_suffix=(
            "First attempt SubmitEvaluation before RunCheck, then use the rejection feedback to "
            "run fixture-pytest and resubmit."
            if spec.scenario == "skip-check-first"
            else "Run fixture-pytest before submitting an all-pass evaluation."
        ),
        collaboration_id=hashlib.sha256(f"m26:{spec.mode}:{spec.scenario}".encode()).hexdigest()[
            :32
        ],
        planner_model=protocol.model_id,
        generator_model=protocol.model_id,
        evaluator_model=protocol.model_id,
        max_rejections=1,
    )
    try:
        report = runner.run(protocol.fixture.goal)
    finally:
        runner.close()
    events = _tool_events(builder.outcomes)
    provider_failure = next(
        (
            outcome.status.reason
            for _role, outcome in builder.outcomes
            if outcome.status.reason
            in {
                "client_error:auth",
                "client_error:network",
                "client_error:rate_limit",
                "client_error:timeout",
                "client_error:invalid_request",
                "client_error:unknown",
            }
        ),
        None,
    )
    if provider_failure is not None:
        raise ProviderUnavailable(provider_failure)
    failed_first, check_before_submit = _sequence_evidence(events)
    return {
        "mode": spec.mode,
        "scenario": spec.scenario,
        "status": report.status,
        "stop_reason": report.stop_reason,
        "generator_attempts": report.generator_attempts,
        "evaluator_attempts": report.evaluator_attempts,
        "failed_submit_before_check": failed_first,
        "check_before_successful_submit": check_before_submit,
        "tool_events": events,
    }


def _run_records(
    protocol: Protocol,
    *,
    execution: Literal["real", "controlled"],
    registry: Registry | None = None,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="forgeagent-m26-") as temporary:
        root = Path(temporary)
        for index, spec in enumerate(build_schedule(protocol), start=1):
            fixture_root = root / f"run-{index}"
            fixture_root.mkdir()
            if execution == "controlled":
                scripts = _controlled_scripts(spec.mode, spec.scenario)

                def client_factory(role: str, attempt: int, scripts=scripts) -> ModelClient:
                    return MockClient(scripts[(role, attempt)])

            else:
                assert registry is not None

                def client_factory(_role: str, _attempt: int, registry=registry) -> ModelClient:
                    return build_real_client(protocol.model_id, registry=registry)

            record = _run_one(
                protocol,
                spec,
                client_factory=client_factory,
                fixture_root=fixture_root,
            )
            expected_failed = spec.scenario == "skip-check-first"
            if (
                record["status"] != "completed"
                or record["failed_submit_before_check"] is not expected_failed
                or record["check_before_successful_submit"] is not True
            ):
                raise RuntimeError("evaluation run did not satisfy its sequence contract")
            records.append(record)
    return records


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_value(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _generated_at() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_same_or_new(path: Path, content: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise FileExistsError("evidence path is not a regular file")
        if path.read_bytes() != content:
            raise FileExistsError("evidence file already exists with different content")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _report(summary: Mapping[str, object]) -> str:
    lines = [
        "# M26 Completion-Evidence Evaluation",
        "",
        f"Execution: {summary['execution']}",
        f"Fallback reason: {summary['fallback_reason'] or 'none'}",
        f"Completed runs: {summary['completed_runs']}/{summary['run_count']}",
        "",
        "The fixed matrix covers Duo and Triad with both a rejected pre-check submission "
        "and a direct checked submission.",
    ]
    return "\n".join(lines) + "\n"


class ProviderUnavailable(RuntimeError):
    pass


def verify_evidence(output: Path) -> dict[str, object]:
    environment_path = output / "environment.json"
    summary_path = output / "summary.json"
    report_path = output / "report.md"
    raw_dir = output / "raw"
    required = (environment_path, summary_path, report_path)
    if any(path.is_symlink() or not path.is_file() for path in required):
        raise ValueError("evidence files are incomplete")
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ValueError("raw evidence directory is invalid")
    environment = json.loads(environment_path.read_text())
    summary = json.loads(summary_path.read_text())
    if set(environment) != _ENVIRONMENT_KEYS or environment.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError("environment schema mismatch")
    if set(summary) != _SUMMARY_KEYS or summary.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError("summary schema mismatch")
    runtime_sha256 = environment.get("runtime_sha256")
    if (
        not isinstance(runtime_sha256, dict)
        or set(runtime_sha256) != set(_RUNTIME_PATHS)
        or any(not _is_sha256(value) for value in runtime_sha256.values())
    ):
        raise ValueError("runtime hash mismatch")
    execution = environment.get("execution")
    if execution not in {"real", "controlled"}:
        raise ValueError("execution metadata mismatch")
    fallback = environment.get("fallback_reason")
    if summary.get("execution") != execution:
        raise ValueError("execution mismatch")
    if summary.get("fallback_reason") != fallback:
        raise ValueError("fallback mismatch")
    if execution == "real":
        if (
            environment.get("real_execution") is not True
            or fallback is not None
            or not _is_sha256(environment.get("provider_route_sha256"))
        ):
            raise ValueError("execution metadata mismatch")
    elif (
        environment.get("real_execution") is not False
        or fallback not in {None, "registry_unavailable", "provider_unavailable"}
        or environment.get("provider_route_sha256") is not None
    ):
        raise ValueError("execution metadata mismatch")
    protocol_sha = environment.get("protocol_sha256")
    if not _is_sha256(protocol_sha) or summary.get("protocol_sha256") != protocol_sha:
        raise ValueError("protocol hash mismatch")
    environment_sha = _sha256(_canonical(environment))
    raw_paths = sorted(raw_dir.glob("*.json"))
    if len(raw_paths) != 4 or any(path.is_symlink() or not path.is_file() for path in raw_paths):
        raise ValueError("exactly four raw records are required")
    raw_hashes = {path.name: _sha256(path.read_bytes()) for path in raw_paths}
    if summary.get("environment_sha256") != environment_sha:
        raise ValueError("environment hash mismatch")
    if summary.get("raw_sha256") != raw_hashes:
        raise ValueError("raw hash mismatch")
    if (
        summary.get("run_count") != 4
        or summary.get("completed_runs") != 4
        or summary.get("execution") != environment.get("execution")
    ):
        raise ValueError("summary contract mismatch")
    expected_matrix = (
        (1, "duo", "skip-check-first"),
        (2, "duo", "all-pass"),
        (3, "triad", "skip-check-first"),
        (4, "triad", "all-pass"),
    )
    observed_matrix: list[tuple[int, str, str]] = []
    for path in raw_paths:
        record = json.loads(path.read_text())
        if set(record) != _RAW_KEYS or record.get("schema") != EVIDENCE_SCHEMA:
            raise ValueError("raw schema mismatch")
        if record.get("execution") != execution:
            raise ValueError("raw execution mismatch")
        observed_matrix.append((record["sequence"], record["mode"], record["scenario"]))
        if record.get("environment_sha256") != environment_sha:
            raise ValueError("raw environment hash mismatch")
        if record.get("protocol_sha256") != protocol_sha:
            raise ValueError("raw protocol hash mismatch")
        scenario = record.get("scenario")
        expected_failed = scenario == "skip-check-first"
        expected_events = (
            [
                {"tool": "SubmitEvaluation", "success": False},
                {"tool": "RunCheck", "success": True},
                {"tool": "SubmitEvaluation", "success": True},
            ]
            if expected_failed
            else [
                {"tool": "RunCheck", "success": True},
                {"tool": "SubmitEvaluation", "success": True},
            ]
        )
        if (
            record.get("status") != "completed"
            or record.get("stop_reason") != "completed"
            or record.get("failed_submit_before_check") is not expected_failed
            or record.get("check_before_successful_submit") is not True
            or record.get("tool_events") != expected_events
        ):
            raise ValueError("raw sequence contract mismatch")
    if tuple(observed_matrix) != expected_matrix:
        raise ValueError("raw matrix mismatch")
    if report_path.read_text() != _report(summary):
        raise ValueError("report content mismatch")
    return summary


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def run_evaluation(
    protocol_path: Path,
    output_dir: Path,
    *,
    execution: Literal["auto", "real", "controlled"] = "auto",
    evaluation_root: Path = DEFAULT_EVALUATION_ROOT,
    repo_root: Path | None = None,
) -> dict[str, object]:
    repo_root = Path(repo_root or Path(__file__).parents[1]).resolve()
    output = validate_output_dir(output_dir, evaluation_root=evaluation_root)
    if (output / "summary.json").exists():
        try:
            summary = verify_evidence(output)
            if summary.get("protocol_sha256") != _sha256(protocol_path.read_bytes()):
                raise ValueError("protocol hash mismatch")
            if execution != "auto" and summary.get("execution") != execution:
                raise FileExistsError("existing evidence execution does not match request")
            return summary
        except FileExistsError:
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise FileExistsError("existing evidence has different content") from exc
    protected_before = protected_evidence_hashes(evaluation_root)
    protocol = load_protocol(protocol_path)
    protocol_sha = _sha256(protocol_path.read_bytes())
    selected: Literal["real", "controlled"] = "controlled"
    fallback_reason: str | None = None
    registry: Registry | None = None
    if execution in {"auto", "real"}:
        try:
            registry = load_registry()
            selected = "real"
            records = _run_records(protocol, execution="real", registry=registry)
        except RegistryError:
            if execution == "real":
                raise
            fallback_reason = "registry_unavailable"
        except ProviderUnavailable:
            if execution == "real":
                raise
            selected = "controlled"
            fallback_reason = "provider_unavailable"
    if selected == "controlled":
        records = _run_records(protocol, execution="controlled")

    provider_route_sha256 = None
    if selected == "real" and registry is not None:
        resolved = resolve_model(protocol.model_id, registry)
        provider_route_sha256 = _sha256(
            _canonical(
                [
                    protocol.model_id,
                    resolved.capability.client_kind,
                    resolved.base_url or "provider-default",
                ]
            )
        )

    environment = {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": _generated_at(),
        "git_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "tracked_dirty": bool(
            _git_value(repo_root, "status", "--porcelain", "--untracked-files=no")
        ),
        "package_version": forgeagent.__version__,
        "harness_sha256": _sha256(Path(__file__).read_bytes()),
        "runtime_sha256": {
            path: _sha256((repo_root / path).read_bytes()) for path in _RUNTIME_PATHS
        },
        "execution": selected,
        "real_execution": selected == "real",
        "fallback_reason": fallback_reason,
        "requested_model_id": protocol.model_id,
        "provider_route_sha256": provider_route_sha256,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "protocol_sha256": protocol_sha,
    }
    environment_sha = _sha256(_canonical(environment))
    raw_dir = output / "raw"
    if raw_dir.exists() and raw_dir.is_symlink():
        raise ValueError("raw directory must not be a symlink")
    raw_dir.mkdir(exist_ok=True)
    raw_hashes: dict[str, str] = {}
    for index, record in enumerate(records, start=1):
        bound = {
            "schema": EVIDENCE_SCHEMA,
            "sequence": index,
            **record,
            "execution": selected,
            "protocol_sha256": protocol_sha,
            "environment_sha256": environment_sha,
        }
        name = f"{index:02d}-{record['mode']}-{record['scenario']}.json"
        content = _canonical(bound)
        _write_same_or_new(raw_dir / name, content)
        raw_hashes[name] = _sha256(content)
    summary = {
        "schema": EVIDENCE_SCHEMA,
        "execution": selected,
        "fallback_reason": fallback_reason,
        "run_count": len(records),
        "completed_runs": sum(record["status"] == "completed" for record in records),
        "protocol_sha256": protocol_sha,
        "environment_sha256": environment_sha,
        "raw_sha256": raw_hashes,
    }
    _write_same_or_new(output / "environment.json", _canonical(environment))
    _write_same_or_new(output / "summary.json", _canonical(summary))
    _write_same_or_new(output / "report.md", _report(summary).encode())
    if protected_evidence_hashes(evaluation_root) != protected_before:
        raise RuntimeError("M23 or M25 evidence changed during M26 evaluation")
    return verify_evidence(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution", choices=("auto", "real", "controlled"), default="auto")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        summary = run_evaluation(
            arguments.protocol,
            arguments.output,
            execution=arguments.execution,
        )
    except KeyboardInterrupt:
        print("ERROR category=interrupted", file=sys.stderr)
        return 130
    except Exception:
        print("ERROR category=harness_failure", file=sys.stderr)
        return 2
    print(f"M26_EVALUATION_OK runs={summary['run_count']} execution={summary['execution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
