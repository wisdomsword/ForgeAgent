#!/usr/bin/env python3
"""Run the M23 Single/Duo/Triad evaluation protocol."""

from __future__ import annotations

import argparse
import hashlib
import importlib.resources
import json
import os
import platform
import re
import stat
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

import forgeagent
from forgeagent.audit import AuditEvent
from forgeagent.check_runner import CheckDefinition, run_check
from forgeagent.cli import build_real_client
from forgeagent.client import ClientError
from forgeagent.collaboration import CollaborationRunner, headless_plan_confirmer
from forgeagent.identity import ApprovedIdentity
from forgeagent.model_registry import RegistryError, load_registry, resolve_model
from forgeagent.models import GenerationParams
from forgeagent.task import Task

PROTOCOL_SCHEMA = "forgeagent.m23.mode-evaluation/v2"
MODES = ("single", "duo", "triad")
Mode = Literal["single", "duo", "triad"]
SHA256_PATTERN = r"^[0-9a-f]{64}$"
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationSettings(StrictModel):
    max_output_tokens: Literal[4096]
    temperature: Literal[0.0]
    thinking: Literal["off"]
    effort: Literal[None]
    timeout_seconds: Literal[120.0]


class ExecutionSettings(StrictModel):
    tier: Literal["restricted"]
    max_rounds: Literal[10]
    max_rejections: Literal[2]
    identity: Literal[False]
    memory: Literal[False]
    skills: Literal[False]
    mcp: Literal[False]
    plan_policy: Literal["preauthorize"]
    check_timeout_seconds: Literal[30.0]


def _validate_relative_path(value: str) -> str:
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError("relative path must be non-empty and contain no controls")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or str(path) != value
    ):
        raise ValueError("relative path must be normalized POSIX syntax")
    return value


class CheckSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    command: tuple[str, ...] = Field(min_length=2)
    timeout_seconds: Literal[30.0]

    @model_validator(mode="after")
    def validate_command(self) -> CheckSpec:
        if self.command[0] != "{python}":
            raise ValueError("check command must start with {python}")
        if any(not part or "\x00" in part for part in self.command):
            raise ValueError("check command arguments must be non-empty and NUL-free")
        return self


class TaskSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    goal: str = Field(min_length=1, max_length=4000)
    initial_files: dict[str, str]
    immutable_files: tuple[str, ...] = Field(min_length=1)
    required_candidate_files: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[str, ...] = Field(min_length=1)
    checks: tuple[CheckSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_paths_and_ids(self) -> TaskSpec:
        for path in self.initial_files:
            _validate_relative_path(path)
        immutable_paths = {_validate_relative_path(path) for path in self.immutable_files}
        candidate_paths = {_validate_relative_path(path) for path in self.required_candidate_files}
        artifact_paths = {_validate_relative_path(path) for path in self.artifacts}
        if len(immutable_paths) != len(self.immutable_files):
            raise ValueError("immutable file paths must be unique")
        if not immutable_paths <= set(self.initial_files):
            raise ValueError("immutable files must reference initial files")
        if len(candidate_paths) != len(self.required_candidate_files):
            raise ValueError("required candidate paths must be unique")
        if len(artifact_paths) != len(self.artifacts):
            raise ValueError("artifact paths must be unique")
        if not candidate_paths <= artifact_paths:
            raise ValueError("required candidate paths must be included in artifacts")
        check_ids = [check.id for check in self.checks]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("check ids must be unique within a task")
        return self


class EvaluationProtocol(StrictModel):
    schema_: Literal[PROTOCOL_SCHEMA] = Field(alias="schema")
    model_id: Literal["claude-haiku-4-5"]
    generation: GenerationSettings
    execution: ExecutionSettings
    modes: tuple[Mode, ...]
    repetitions: int
    mode_orders: tuple[tuple[Mode, ...], ...]
    tasks: tuple[TaskSpec, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_frozen_design(self) -> EvaluationProtocol:
        if self.modes != MODES:
            raise ValueError(f"modes must be exactly {MODES}")
        if self.repetitions < 3:
            raise ValueError("repetitions must be at least 3")
        if self.repetitions != 3:
            raise ValueError("repetitions must be exactly 3")
        expected_orders = (
            ("single", "duo", "triad"),
            ("duo", "triad", "single"),
            ("triad", "single", "duo"),
        )
        if len(self.mode_orders) != self.repetitions:
            raise ValueError("mode_orders must contain one order per repetition")
        expected_modes = set(MODES)
        if any(
            len(order) != len(MODES) or set(order) != expected_modes for order in self.mode_orders
        ):
            raise ValueError("each mode_orders entry must contain each mode exactly once")
        if self.mode_orders != expected_orders:
            raise ValueError("mode_orders must use the fixed balanced rotation")
        task_ids = [task.id for task in self.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("task ids must be unique")
        if len(self.tasks) != 3:
            raise ValueError("protocol must define exactly 3 tasks")
        return self


M25_PROTOCOL_SCHEMA = "forgeagent.m25.mode-evaluation/v1"
TaskFamily = Literal["baseline", "bugfix", "feature", "refactor"]


def _model_slug(model_id: str) -> str:
    slug = "-".join(
        part
        for part in re.sub(r"[^a-z0-9]+", "-", model_id.lower()).split("-")
        if part
    )
    if not slug:
        raise ValueError("model id has no safe slug")
    return slug


class M25TaskSpec(TaskSpec):
    family: TaskFamily


class M25EvaluationProtocol(StrictModel):
    schema_: Literal[M25_PROTOCOL_SCHEMA] = Field(alias="schema")
    model_ids: tuple[
        Literal["claude-haiku-4-5"], Literal["gpt-5.4-mini"]
    ]
    generation: GenerationSettings
    execution: ExecutionSettings
    modes: tuple[Mode, ...]
    repetitions: Literal[5]
    mode_orders: tuple[tuple[Mode, ...], ...]
    tasks: tuple[M25TaskSpec, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_frozen_design(self) -> M25EvaluationProtocol:
        expected_orders = (
            ("single", "duo", "triad"),
            ("duo", "triad", "single"),
            ("triad", "single", "duo"),
        )
        if self.modes != MODES or self.mode_orders != expected_orders:
            raise ValueError("M25 modes and mode_orders must use the fixed Latin rotation")
        task_ids = [task.id for task in self.tasks]
        if len(set(task_ids)) != 9:
            raise ValueError("M25 task ids must be unique")
        expected_families = {"baseline": 3, "bugfix": 2, "feature": 2, "refactor": 2}
        observed = {
            family: sum(task.family == family for task in self.tasks)
            for family in expected_families
        }
        if observed != expected_families:
            raise ValueError("M25 task families must be 3/2/2/2")
        slugs = [_model_slug(model_id) for model_id in self.model_ids]
        if len(set(slugs)) != len(slugs):
            raise ValueError("M25 model slugs must be unique")
        return self


@dataclass(frozen=True)
class RunSpec:
    sequence: int
    task_id: str
    repeat: int
    mode: Mode


@dataclass(frozen=True)
class M25RunSpec:
    sequence: int
    task_id: str
    task_family: TaskFamily
    model_id: str
    repeat: int
    mode: Mode


class TokenTotals(StrictModel):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


class AuditMetrics(StrictModel):
    tokens: TokenTotals
    logical_model_calls: int = Field(ge=0)
    provider_attempts: int = Field(ge=0)
    usage_present_calls: int = Field(ge=0)
    usage_missing_calls: int = Field(ge=0)
    usage_missing_rate: float | None = Field(default=None, ge=0.0, le=1.0)


@dataclass(frozen=True)
class ModeResult:
    runtime_completed: bool
    runtime_status: str
    runtime_reason: str | None
    first_acceptance_passed: bool | None
    rejection_count: int | None
    correction_count: int | None


class CollectingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


class EnvironmentManifest(StrictModel):
    schema_: Literal["forgeagent.m23.mode-evaluation.environment/v1"] = Field(
        "forgeagent.m23.mode-evaluation.environment/v1", alias="schema"
    )
    generated_at: str
    git_commit: str
    tracked_dirty: bool
    python_version: str
    python_executable_name: str
    platform: str
    package_version: str
    model_id: str
    provider_route_sha256: str = Field(pattern=SHA256_PATTERN)
    builtin_models_sha256: str = Field(pattern=SHA256_PATTERN)
    builtin_config_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    generation: GenerationSettings
    execution: ExecutionSettings


class M25ModelRoute(StrictModel):
    model_id: str
    client_kind: str
    provider_route_sha256: str = Field(pattern=SHA256_PATTERN)


class M25EnvironmentManifest(StrictModel):
    schema_: Literal["forgeagent.m25.mode-evaluation.environment/v1"] = Field(
        "forgeagent.m25.mode-evaluation.environment/v1", alias="schema"
    )
    generated_at: str
    git_commit: str
    tracked_dirty: Literal[False]
    python_version: str
    python_executable_name: str
    platform: str
    package_version: str
    model_routes: tuple[M25ModelRoute, M25ModelRoute]
    builtin_models_sha256: str = Field(pattern=SHA256_PATTERN)
    builtin_config_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    generation: GenerationSettings
    execution: ExecutionSettings


@dataclass(frozen=True)
class PreflightContext:
    registry: object
    environment: Environment
    environment_sha256: str


class CheckRecord(StrictModel):
    id: str
    status: Literal["passed", "failed", "timeout", "cancelled", "copy_error", "start_error"]
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    stdout_sha256: str = Field(pattern=SHA256_PATTERN)
    stderr_sha256: str = Field(pattern=SHA256_PATTERN)


class ArtifactResult(StrictModel):
    path: str
    status: Literal["ok", "missing", "not_regular", "symlink", "io_error"]
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_status_fields(self) -> ArtifactResult:
        if self.status == "ok" and (self.size is None or self.sha256 is None):
            raise ValueError("ok artifact requires size and sha256")
        if self.status != "ok" and (self.size is not None or self.sha256 is not None):
            raise ValueError("non-ok artifact must not include size or sha256")
        return self


class RawRecord(StrictModel):
    schema_: Literal["forgeagent.m23.mode-evaluation.run/v1"] = Field(
        "forgeagent.m23.mode-evaluation.run/v1", alias="schema"
    )
    run_id: str
    sequence: int = Field(ge=1)
    task_id: str
    mode: Mode
    repeat: int = Field(ge=1)
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    environment_sha256: str = Field(pattern=SHA256_PATTERN)
    run_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    started_at: str
    finished_at: str
    runtime_completed: bool
    runtime_status: str
    runtime_reason: str | None
    checks: tuple[CheckRecord, ...]
    artifacts: tuple[ArtifactResult, ...]
    solved: bool
    first_acceptance_passed: bool | None
    rejection_count: int | None = Field(default=None, ge=0)
    correction_count: int | None = Field(default=None, ge=0)
    tokens: TokenTotals
    logical_model_calls: int = Field(ge=0)
    provider_attempts: int = Field(ge=0)
    usage_present_calls: int = Field(ge=0)
    usage_missing_calls: int = Field(ge=0)
    usage_missing_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    end_to_end_latency_seconds: float = Field(ge=0.0)
    error_category: (
        Literal[
            "configuration_error",
            "client_error",
            "check_error",
            "io_error",
            "internal_error",
        ]
        | None
    )

    @model_validator(mode="after")
    def validate_applicability(self) -> RawRecord:
        acceptance = (
            self.first_acceptance_passed,
            self.rejection_count,
            self.correction_count,
        )
        if self.mode == "single" and any(value is not None for value in acceptance):
            raise ValueError("single acceptance-loop fields must be null")
        if self.mode != "single" and any(value is None for value in acceptance):
            raise ValueError("collaboration acceptance-loop fields must be present")
        if self.usage_present_calls + self.usage_missing_calls != self.logical_model_calls:
            raise ValueError("usage call counts must equal logical model calls")
        return self


class M25RawRecord(RawRecord):
    schema_: Literal["forgeagent.m25.mode-evaluation.run/v1"] = Field(
        "forgeagent.m25.mode-evaluation.run/v1", alias="schema"
    )
    terminal: Literal[True] = True
    task_family: TaskFamily
    model_id: str
    provider_route_sha256: str = Field(pattern=SHA256_PATTERN)


Protocol = EvaluationProtocol | M25EvaluationProtocol
RunSpecification = RunSpec | M25RunSpec
Environment = EnvironmentManifest | M25EnvironmentManifest
RunRecord = RawRecord | M25RawRecord


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_protocol(value: object) -> Protocol:
    if not isinstance(value, dict) or not isinstance(value.get("schema"), str):
        raise ValueError("protocol schema is required")
    schema = value["schema"]
    if schema == PROTOCOL_SCHEMA:
        return EvaluationProtocol.model_validate(value)
    if schema == M25_PROTOCOL_SCHEMA:
        return M25EvaluationProtocol.model_validate(value)
    raise ValueError(f"unsupported protocol schema: {schema}")


def protocol_model_ids(protocol: Protocol) -> tuple[str, ...]:
    return (protocol.model_id,) if isinstance(protocol, EvaluationProtocol) else protocol.model_ids


def run_model_id(protocol: Protocol, run_spec: RunSpecification) -> str:
    return protocol.model_id if isinstance(run_spec, RunSpec) else run_spec.model_id


def run_task_family(run_spec: RunSpecification) -> TaskFamily | None:
    return None if isinstance(run_spec, RunSpec) else run_spec.task_family


def protocol_namespace(protocol: Protocol) -> Literal["m23", "m25"]:
    return "m23" if isinstance(protocol, EvaluationProtocol) else "m25"


def route_hash_for_model(environment: Environment, model_id: str) -> str:
    if isinstance(environment, EnvironmentManifest):
        if model_id != environment.model_id:
            raise ValueError("model route is not present in environment")
        return environment.provider_route_sha256
    matches = [
        route.provider_route_sha256
        for route in environment.model_routes
        if route.model_id == model_id
    ]
    if len(matches) != 1:
        raise ValueError("model route is not uniquely present in environment")
    return matches[0]


def load_protocol(path: Path) -> tuple[Protocol, str]:
    protocol = validate_protocol(json.loads(path.read_text(encoding="utf-8")))
    serialized = protocol.model_dump(mode="json", by_alias=True)
    return protocol, canonical_sha256(serialized)


def build_schedule(protocol: Protocol) -> tuple[RunSpecification, ...]:
    if isinstance(protocol, EvaluationProtocol):
        schedule: list[RunSpecification] = []
        for task in protocol.tasks:
            for repetition, order in enumerate(protocol.mode_orders, start=1):
                for mode in order:
                    schedule.append(
                        RunSpec(
                            sequence=len(schedule) + 1,
                            task_id=task.id,
                            repeat=repetition,
                            mode=mode,
                        )
                    )
        return tuple(schedule)

    schedule = []
    for task_index, task in enumerate(protocol.tasks):
        for repeat_index in range(protocol.repetitions):
            stable_models = list(enumerate(protocol.model_ids))
            if (task_index + repeat_index) % 2:
                stable_models.reverse()
            for model_index, model_id in stable_models:
                order = protocol.mode_orders[
                    (2 * task_index + model_index + repeat_index) % 3
                ]
                for mode in order:
                    schedule.append(
                        M25RunSpec(
                            sequence=len(schedule) + 1,
                            task_id=task.id,
                            task_family=task.family,
                            model_id=model_id,
                            repeat=repeat_index + 1,
                            mode=mode,
                        )
                    )
    return tuple(schedule)


def _run_id_for_spec(run_spec: RunSpecification) -> str:
    if isinstance(run_spec, RunSpec):
        return (
            f"{run_spec.sequence:02d}-{run_spec.task_id}-"
            f"r{run_spec.repeat}-{run_spec.mode}"
        )
    return (
        f"{run_spec.sequence:03d}-{run_spec.task_id}-{_model_slug(run_spec.model_id)}-"
        f"r{run_spec.repeat}-{run_spec.mode}"
    )


def run_id_for(protocol: Protocol, run_spec: RunSpecification) -> str:
    return _run_id_for_spec(run_spec)


def run_spec_hash(run_spec: RunSpecification, protocol_sha256: str) -> str:
    if isinstance(run_spec, RunSpec):
        run = {
            "sequence": run_spec.sequence,
            "task_id": run_spec.task_id,
            "repeat": run_spec.repeat,
            "mode": run_spec.mode,
        }
    else:
        run = {
            "sequence": run_spec.sequence,
            "task_id": run_spec.task_id,
            "task_family": run_spec.task_family,
            "model_id": run_spec.model_id,
            "repeat": run_spec.repeat,
            "mode": run_spec.mode,
        }
    return canonical_sha256({"protocol_sha256": protocol_sha256, "run": run})


def project_audit_metrics(events: Sequence[AuditEvent]) -> AuditMetrics:
    outcomes = [event for event in events if event.event_type == "llm.outcome"]
    provider_attempts = sum(
        event.event_type == "llm.provider_attempt" and event.result_status == "started"
        for event in events
    )
    totals = {field: 0 for field in TOKEN_FIELDS}
    usage_present_calls = 0
    for event in outcomes:
        usage = event.parameters.get("usage")
        if not isinstance(usage, dict) or not all(
            type(usage.get(field)) is int and usage[field] >= 0 for field in TOKEN_FIELDS
        ):
            continue
        usage_present_calls += 1
        for field in TOKEN_FIELDS:
            totals[field] += usage[field]

    logical_model_calls = len(outcomes)
    usage_missing_calls = logical_model_calls - usage_present_calls
    if logical_model_calls == 0:
        token_values: dict[str, int | None] = totals
        usage_missing_rate = None
    elif usage_present_calls == 0:
        token_values = dict.fromkeys(TOKEN_FIELDS)
        usage_missing_rate = 1.0
    else:
        token_values = totals
        usage_missing_rate = usage_missing_calls / logical_model_calls
    return AuditMetrics(
        tokens=TokenTotals(**token_values),
        logical_model_calls=logical_model_calls,
        provider_attempts=provider_attempts,
        usage_present_calls=usage_present_calls,
        usage_missing_calls=usage_missing_calls,
        usage_missing_rate=usage_missing_rate,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resource_sha256(filename: str) -> str:
    content = importlib.resources.files("forgeagent.res").joinpath(filename).read_bytes()
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


def environment_manifest(
    protocol: Protocol,
    protocol_sha256: str,
    *,
    repo_root: Path,
    model_routes: Mapping[str, tuple[str, str]] | None = None,
    provider_route_sha256: str | None = None,
) -> Environment:
    git_commit = _git_value(repo_root, "rev-parse", "HEAD")
    tracked_dirty = bool(
        _git_value(repo_root, "status", "--porcelain", "--untracked-files=no")
    )
    common = dict(
        generated_at=_utc_now(),
        git_commit=git_commit,
        python_version=sys.version,
        python_executable_name=Path(sys.executable).name,
        platform="/".join((platform.system(), platform.release(), platform.machine())),
        package_version=forgeagent.__version__,
        builtin_models_sha256=_resource_sha256("models.yaml"),
        builtin_config_sha256=_resource_sha256("config.yaml"),
        protocol_sha256=protocol_sha256,
        generation=protocol.generation,
        execution=protocol.execution,
    )
    if isinstance(protocol, EvaluationProtocol):
        if provider_route_sha256 is None:
            raise ValueError("M23 provider route hash is required")
        return EnvironmentManifest(
            **common,
            tracked_dirty=tracked_dirty,
            model_id=protocol.model_id,
            provider_route_sha256=provider_route_sha256,
        )

    if tracked_dirty:
        raise ValueError("M25 requires tracked source to be clean")
    if model_routes is None or set(model_routes) != set(protocol.model_ids):
        raise ValueError("M25 model routes must match the fixed models")
    return M25EnvironmentManifest(
        **common,
        tracked_dirty=False,
        model_routes=tuple(
            M25ModelRoute(
                model_id=model_id,
                client_kind=model_routes[model_id][0],
                provider_route_sha256=model_routes[model_id][1],
            )
            for model_id in protocol.model_ids
        ),
    )


def environment_sha256(manifest: Environment) -> str:
    value = manifest.model_dump(mode="json", by_alias=True)
    del value["generated_at"]
    return canonical_sha256(value)


def prepare_workspace(task: TaskSpec, root: Path) -> None:
    if not root.is_dir():
        raise ValueError("workspace must be an existing directory")
    if root.is_symlink():
        raise ValueError("workspace must not be a symlink")
    if any(root.iterdir()):
        raise ValueError("workspace must be empty")
    resolved_root = root.resolve()
    for relative_path, content in task.initial_files.items():
        destination = root / relative_path
        if not destination.resolve().is_relative_to(resolved_root):
            raise ValueError("fixture path escapes workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = destination.parent
        while current != root:
            if current.is_symlink():
                raise ValueError("fixture parent must not be a symlink")
            current = current.parent
        destination.write_text(content, encoding="utf-8")


def _text_projection(value: str) -> tuple[int, str]:
    encoded = value.encode("utf-8")
    return len(encoded), hashlib.sha256(encoded).hexdigest()


def run_checks(task: TaskSpec, workspace: Path) -> tuple[CheckRecord, ...]:
    records: list[CheckRecord] = []
    for check in task.checks:
        definition = CheckDefinition(
            id=check.id,
            argv=(sys.executable, *check.command[1:]),
            timeout_seconds=check.timeout_seconds,
        )
        result = run_check(definition, allowed_root=workspace)
        stdout_bytes, stdout_sha256 = _text_projection(result.stdout)
        stderr_bytes, stderr_sha256 = _text_projection(result.stderr)
        records.append(
            CheckRecord(
                id=check.id,
                status=result.status,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                stdout_bytes=stdout_bytes,
                stderr_bytes=stderr_bytes,
                stdout_sha256=stdout_sha256,
                stderr_sha256=stderr_sha256,
            )
        )
    empty_bytes, empty_sha256 = _text_projection("")
    fixtures_unchanged = True
    for relative_path in task.immutable_files:
        path = workspace / relative_path
        try:
            metadata = path.lstat()
            fixtures_unchanged = (
                fixtures_unchanged
                and stat.S_ISREG(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and path.read_bytes() == task.initial_files[relative_path].encode("utf-8")
            )
        except OSError:
            fixtures_unchanged = False
    records.append(
        CheckRecord(
            id="fixture-integrity",
            status="passed" if fixtures_unchanged else "failed",
            exit_code=0 if fixtures_unchanged else 1,
            stdout_bytes=empty_bytes,
            stderr_bytes=empty_bytes,
            stdout_sha256=empty_sha256,
            stderr_sha256=empty_sha256,
        )
    )
    return tuple(records)


def hash_artifacts(task: TaskSpec, workspace: Path) -> tuple[ArtifactResult, ...]:
    records: list[ArtifactResult] = []
    for relative_path in task.artifacts:
        path = workspace / relative_path
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                records.append(ArtifactResult(path=relative_path, status="symlink"))
            elif not stat.S_ISREG(metadata.st_mode):
                records.append(ArtifactResult(path=relative_path, status="not_regular"))
            else:
                content = path.read_bytes()
                records.append(
                    ArtifactResult(
                        path=relative_path,
                        status="ok",
                        size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                    )
                )
        except FileNotFoundError:
            records.append(ArtifactResult(path=relative_path, status="missing"))
        except OSError:
            records.append(ArtifactResult(path=relative_path, status="io_error"))
    return tuple(records)


def build_raw_record(
    *,
    run_spec: RunSpecification,
    mode_result: ModeResult,
    checks: tuple[CheckRecord, ...],
    artifacts: tuple[ArtifactResult, ...],
    audit_metrics: AuditMetrics,
    protocol_sha256: str,
    environment_sha256: str,
    provider_route_sha256: str | None = None,
    started_at: str,
    finished_at: str,
    end_to_end_latency_seconds: float,
    error_category: str | None = None,
) -> RunRecord:
    values = dict(
        run_id=_run_id_for_spec(run_spec),
        sequence=run_spec.sequence,
        task_id=run_spec.task_id,
        mode=run_spec.mode,
        repeat=run_spec.repeat,
        protocol_sha256=protocol_sha256,
        environment_sha256=environment_sha256,
        run_spec_sha256=run_spec_hash(run_spec, protocol_sha256),
        started_at=started_at,
        finished_at=finished_at,
        runtime_completed=mode_result.runtime_completed,
        runtime_status=mode_result.runtime_status,
        runtime_reason=mode_result.runtime_reason,
        checks=checks,
        artifacts=artifacts,
        solved=mode_result.runtime_completed
        and bool(checks)
        and all(check.status == "passed" for check in checks),
        first_acceptance_passed=mode_result.first_acceptance_passed,
        rejection_count=mode_result.rejection_count,
        correction_count=mode_result.correction_count,
        tokens=audit_metrics.tokens,
        logical_model_calls=audit_metrics.logical_model_calls,
        provider_attempts=audit_metrics.provider_attempts,
        usage_present_calls=audit_metrics.usage_present_calls,
        usage_missing_calls=audit_metrics.usage_missing_calls,
        usage_missing_rate=audit_metrics.usage_missing_rate,
        end_to_end_latency_seconds=end_to_end_latency_seconds,
        error_category=error_category,
    )
    if isinstance(run_spec, RunSpec):
        return RawRecord(**values)
    if provider_route_sha256 is None:
        raise ValueError("M25 raw record requires a provider route hash")
    return M25RawRecord(
        **values,
        terminal=True,
        task_family=run_spec.task_family,
        model_id=run_spec.model_id,
        provider_route_sha256=provider_route_sha256,
    )


def write_raw_record(path: Path, record: RunRecord) -> None:
    content = canonical_json(record.model_dump(mode="json", by_alias=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError("raw record already exists with different content")
        return
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _generation_params(protocol: Protocol) -> GenerationParams:
    return GenerationParams(**protocol.generation.model_dump(mode="python"))


def _close_client(client: object) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()


def run_single(
    protocol: Protocol,
    task_spec: TaskSpec,
    run_spec: RunSpecification,
    workspace: Path,
    registry: object,
    audit_sink: CollectingAuditSink,
) -> ModeResult:
    model_id = run_model_id(protocol, run_spec)
    namespace = protocol_namespace(protocol)
    sequence = f"{run_spec.sequence:02d}" if namespace == "m23" else f"{run_spec.sequence:03d}"
    client = build_real_client(model_id, registry=registry)
    task: Task | None = None
    try:
        task = Task(
            client,
            tier="restricted",
            allowed_root=str(workspace),
            identity=ApprovedIdentity(soul=None, user=None, project_agents=None, memory=None),
            max_rounds=protocol.execution.max_rounds,
            params=_generation_params(protocol),
            confirmer=lambda _request: True,
            audit_sink=audit_sink,
            task_id=f"{namespace}-{sequence}-single",
        )
        outcome = task.run(task_spec.goal)
        return ModeResult(
            runtime_completed=outcome.status.completed,
            runtime_status="completed" if outcome.status.completed else "failed",
            runtime_reason=outcome.status.reason,
            first_acceptance_passed=None,
            rejection_count=None,
            correction_count=None,
        )
    finally:
        try:
            if task is not None:
                task.close()
        finally:
            _close_client(client)


class _OwnedRoleTask:
    def __init__(self, task: Task, client: object) -> None:
        self._task = task
        self._client = client
        self._closed = False

    def run(self, goal: str, *, cancel_event=None):
        return self._task.run(goal, cancel_event=cancel_event)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._task.close()
        finally:
            _close_client(self._client)


def run_collaboration(
    protocol: Protocol,
    task_spec: TaskSpec,
    run_spec: RunSpecification,
    workspace: Path,
    registry: object,
    audit_sink: CollectingAuditSink,
) -> ModeResult:
    if run_spec.mode not in {"duo", "triad"}:
        raise ValueError("collaboration run requires duo or triad mode")

    model_id = run_model_id(protocol, run_spec)
    namespace = protocol_namespace(protocol)
    sequence = f"{run_spec.sequence:02d}" if namespace == "m23" else f"{run_spec.sequence:03d}"

    def role_task_builder(role, attempt, tool_registry, system_prompt):
        client = build_real_client(model_id, registry=registry)
        try:
            task = Task(
                client,
                tier="restricted",
                allowed_root=str(workspace),
                system_prompt=system_prompt,
                identity=ApprovedIdentity(soul=None, user=None, project_agents=None, memory=None),
                max_rounds=protocol.execution.max_rounds,
                params=_generation_params(protocol),
                confirmer=lambda _request: True,
                audit_sink=audit_sink,
                task_id=(f"{namespace}-{sequence}-{run_spec.mode}-{role}-{attempt}"),
                tool_registry=tool_registry,
            )
        except BaseException:
            _close_client(client)
            raise
        return _OwnedRoleTask(task, client)

    collaboration_identity = {
            "scope": "m23-collaboration",
            "sequence": run_spec.sequence,
            "task_id": run_spec.task_id,
            "repeat": run_spec.repeat,
            "mode": run_spec.mode,
    }
    if namespace == "m25":
        collaboration_identity["scope"] = "m25-collaboration"
        collaboration_identity["model_id"] = model_id
    collaboration_id = canonical_sha256(collaboration_identity)[:32]
    runner = CollaborationRunner.create(
        mode=run_spec.mode,
        goal=task_spec.goal,
        allowed_root=str(workspace),
        role_task_builder=role_task_builder,
        plan_confirmer=(
            headless_plan_confirmer("preauthorize") if run_spec.mode == "triad" else None
        ),
        required_candidate_files=task_spec.required_candidate_files,
        execution_tier="restricted",
        collaboration_id=collaboration_id,
        planner_model=model_id,
        generator_model=model_id,
        evaluator_model=model_id,
        evaluator_tier="restricted",
        max_rejections=protocol.execution.max_rejections,
        audit_sink=audit_sink,
        task_id=f"{namespace}-{sequence}-{run_spec.mode}",
        loop_id=None,
    )
    try:
        report = runner.run(task_spec.goal)
        return ModeResult(
            runtime_completed=report.status == "completed",
            runtime_status=str(report.status),
            runtime_reason=report.stop_reason,
            first_acceptance_passed=(
                report.status == "completed"
                and report.generator_attempts == 1
                and report.evaluator_attempts == 1
                and report.rejections == 0
            ),
            rejection_count=report.rejections,
            correction_count=max(0, report.generator_attempts - 1),
        )
    finally:
        runner.close()


def _error_category(error: Exception) -> str:
    if isinstance(error, (RegistryError, ValueError)):
        return "configuration_error"
    if isinstance(error, ClientError):
        return "client_error"
    if isinstance(error, OSError):
        return "io_error"
    return "internal_error"


def execute_run(
    protocol: Protocol,
    protocol_sha256: str,
    environment_sha256_value: str,
    task_spec: TaskSpec,
    run_spec: RunSpecification,
    workspace: Path,
    registry: object,
    environment: Environment | None = None,
) -> RunRecord:
    started_at = _utc_now()
    started = time.monotonic()
    audit_sink = CollectingAuditSink()
    error_category: str | None = None
    try:
        if run_spec.mode == "single":
            mode_result = run_single(protocol, task_spec, run_spec, workspace, registry, audit_sink)
        else:
            mode_result = run_collaboration(
                protocol, task_spec, run_spec, workspace, registry, audit_sink
            )
    except KeyboardInterrupt:
        raise
    except Exception as error:
        error_category = _error_category(error)
        mode_result = ModeResult(
            runtime_completed=False,
            runtime_status="failed",
            runtime_reason=error_category,
            first_acceptance_passed=None if run_spec.mode == "single" else False,
            rejection_count=None if run_spec.mode == "single" else 0,
            correction_count=None if run_spec.mode == "single" else 0,
        )

    try:
        checks = run_checks(task_spec, workspace)
    except KeyboardInterrupt:
        raise
    except Exception:
        checks = ()
        if error_category is None:
            error_category = "check_error"

    try:
        artifacts = hash_artifacts(task_spec, workspace)
    except KeyboardInterrupt:
        raise
    except Exception:
        artifacts = ()
        if error_category is None:
            error_category = "io_error"

    finished_at = _utc_now()
    provider_route_sha256 = None
    if isinstance(run_spec, M25RunSpec):
        if not isinstance(environment, M25EnvironmentManifest):
            raise ValueError("M25 execution requires its environment manifest")
        provider_route_sha256 = route_hash_for_model(environment, run_spec.model_id)
    return build_raw_record(
        run_spec=run_spec,
        mode_result=mode_result,
        checks=checks,
        artifacts=artifacts,
        audit_metrics=project_audit_metrics(audit_sink.events),
        protocol_sha256=protocol_sha256,
        environment_sha256=environment_sha256_value,
        provider_route_sha256=provider_route_sha256,
        started_at=started_at,
        finished_at=finished_at,
        end_to_end_latency_seconds=max(0.0, time.monotonic() - started),
        error_category=error_category,
    )


def read_raw_records(
    raw_dir: Path,
    protocol: EvaluationProtocol,
    protocol_sha256: str,
    environment_sha256_value: str,
) -> tuple[RawRecord, ...]:
    files = sorted(raw_dir.glob("*.json"))
    records: list[RawRecord] = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("raw records must be regular non-symlink files")
        records.append(RawRecord.model_validate_json(path.read_bytes()))
    schedule = build_schedule(protocol)
    validated = _validate_complete_records(protocol, schedule, records)
    if any(record.protocol_sha256 != protocol_sha256 for record in validated):
        raise ValueError("raw record protocol hash mismatch")
    if any(record.environment_sha256 != environment_sha256_value for record in validated):
        raise ValueError("raw record environment hash mismatch")
    return validated


def _validate_complete_records(
    protocol: EvaluationProtocol,
    schedule: Sequence[RunSpec],
    records: Sequence[RawRecord],
) -> tuple[RawRecord, ...]:
    expected_count = len(schedule)
    combinations = [(record.task_id, record.repeat, record.mode) for record in records]
    if len(set(combinations)) != len(combinations):
        raise ValueError("duplicate raw record combination")
    if len(records) != expected_count:
        raise ValueError(f"complete {expected_count} raw records are required")

    protocol_sha256 = canonical_sha256(protocol.model_dump(mode="json", by_alias=True))
    if any(record.protocol_sha256 != protocol_sha256 for record in records):
        raise ValueError("protocol hash mismatch across raw records")
    environment_hashes = {record.environment_sha256 for record in records}
    if len(environment_hashes) != 1:
        raise ValueError("environment hash mismatch across raw records")

    records_by_combination = {
        (record.task_id, record.repeat, record.mode): record for record in records
    }
    expected_combinations = {(spec.task_id, spec.repeat, spec.mode): spec for spec in schedule}
    if records_by_combination.keys() != expected_combinations.keys():
        raise ValueError("complete 27 schedule does not match raw records")
    for combination, spec in expected_combinations.items():
        record = records_by_combination[combination]
        expected_run_id = f"{spec.sequence:02d}-{spec.task_id}-r{spec.repeat}-{spec.mode}"
        if record.run_id != expected_run_id:
            raise ValueError("raw record run id does not match schedule")
        if record.sequence != spec.sequence:
            raise ValueError("raw record sequence does not match schedule")
        if record.run_spec_sha256 != run_spec_hash(spec, protocol_sha256):
            raise ValueError("raw record run-spec hash mismatch")
    return tuple(sorted(records, key=lambda record: record.sequence))


def distribution(values: Sequence[int | float]) -> dict[str, int | float | None]:
    if not values:
        return {key: None for key in ("sum", "mean", "median", "min", "max")}
    return {
        "sum": sum(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else numerator / denominator,
    }


def _aggregate_group(records: Sequence[RawRecord], mode: Mode) -> dict[str, object]:
    logical_call_total = sum(record.logical_model_calls for record in records)
    missing_call_total = sum(record.usage_missing_calls for record in records)

    def known_token_values(field: str) -> list[int]:
        return [value for record in records if (value := getattr(record.tokens, field)) is not None]

    applicable = mode != "single"
    return {
        "scheduled_runs": len(records),
        "task_completion_rate": _rate(sum(record.solved for record in records), len(records)),
        "first_acceptance_rate": (
            _rate(
                sum(record.first_acceptance_passed is True for record in records),
                len(records),
            )
            if applicable
            else None
        ),
        "rejections": (
            distribution(
                [record.rejection_count for record in records if record.rejection_count is not None]
            )
            if applicable
            else None
        ),
        "corrections": (
            distribution(
                [
                    record.correction_count
                    for record in records
                    if record.correction_count is not None
                ]
            )
            if applicable
            else None
        ),
        "tokens": {field: distribution(known_token_values(field)) for field in TOKEN_FIELDS}
        | {"usage_missing_calls": missing_call_total},
        "logical_model_calls": distribution([record.logical_model_calls for record in records]),
        "provider_attempts": distribution([record.provider_attempts for record in records]),
        "end_to_end_latency_seconds": distribution(
            [record.end_to_end_latency_seconds for record in records]
        ),
        "usage_missing_rate": _rate(missing_call_total, logical_call_total),
    }


def aggregate_records(
    protocol: EvaluationProtocol,
    schedule: Sequence[RunSpec],
    records: Sequence[RawRecord],
) -> dict[str, object]:
    validated = _validate_complete_records(protocol, schedule, records)
    protocol_sha256 = validated[0].protocol_sha256
    environment_sha256_value = validated[0].environment_sha256
    modes = {
        mode: _aggregate_group([record for record in validated if record.mode == mode], mode)
        for mode in MODES
    }
    tasks = {
        task.id: {
            mode: _aggregate_group(
                [
                    record
                    for record in validated
                    if record.task_id == task.id and record.mode == mode
                ],
                mode,
            )
            for mode in MODES
        }
        for task in protocol.tasks
    }
    return {
        "schema": "forgeagent.m23.mode-evaluation.summary/v1",
        "protocol_sha256": protocol_sha256,
        "environment_sha256": environment_sha256_value,
        "generated_at": _utc_now(),
        "completeness": {
            "expected_runs": len(schedule),
            "observed_runs": len(validated),
            "complete": True,
        },
        "modes": modes,
        "tasks": tasks,
        "failures": [record.run_id for record in validated if not record.solved],
        "usage_missing_runs": [
            record.run_id for record in validated if record.usage_missing_calls > 0
        ],
        "limitations": [
            "Three fixed tasks and three repetitions per mode form a small sample.",
            "Provider-side model weights cannot be independently pinned or verified.",
            "Results are descriptive and do not establish comparative product conclusions.",
        ],
    }


def _format_rate(value: object) -> str:
    if value is None:
        return "N/A"
    assert isinstance(value, dict)
    ratio = value["value"]
    rendered = "N/A" if ratio is None else f"{ratio:.3f}"
    return f"{value['numerator']}/{value['denominator']} ({rendered})"


def render_report(
    protocol: EvaluationProtocol,
    environment: Mapping[str, object],
    summary: Mapping[str, object],
) -> str:
    mode_lines = []
    modes = summary["modes"]
    assert isinstance(modes, dict)
    for mode in MODES:
        metrics = modes[mode]
        mode_lines.extend(
            (
                f"### {mode.title()}",
                f"- Task completion: {_format_rate(metrics['task_completion_rate'])}",
                f"- First acceptance: {_format_rate(metrics['first_acceptance_rate'])}",
                f"- Rejections: {json.dumps(metrics['rejections'], sort_keys=True)}"
                if metrics["rejections"] is not None
                else "- Rejections: N/A",
                f"- Corrections: {json.dumps(metrics['corrections'], sort_keys=True)}"
                if metrics["corrections"] is not None
                else "- Corrections: N/A",
                f"- Model calls: {json.dumps(metrics['logical_model_calls'], sort_keys=True)}",
                f"- Provider attempts: {json.dumps(metrics['provider_attempts'], sort_keys=True)}",
                f"- Tokens: {json.dumps(metrics['tokens'], sort_keys=True)}",
                "- End-to-end latency: "
                + json.dumps(metrics["end_to_end_latency_seconds"], sort_keys=True),
                f"- Usage missing rate: {_format_rate(metrics['usage_missing_rate'])}",
                "",
            )
        )
    failures = summary["failures"]
    missing = summary["usage_missing_runs"]
    task_lines = [f"- `{task.id}`: 3 runs per mode" for task in protocol.tasks]
    return "\n".join(
        [
            "# M23 Single/Duo/Triad Quality-Cost Evaluation",
            "",
            "## Protocol",
            f"- Model ID: `{protocol.model_id}`",
            f"- Repetitions: {protocol.repetitions}",
            f"- Protocol SHA-256: `{summary['protocol_sha256']}`",
            "",
            "## Environment",
            f"- Environment schema: `{environment.get('schema', 'unknown')}`",
            f"- Environment SHA-256: `{summary['environment_sha256']}`",
            "",
            "## Evidence Completeness",
            "- Runs: "
            f"{summary['completeness']['observed_runs']}/"
            f"{summary['completeness']['expected_runs']}",
            "",
            "## Metrics By Mode",
            *mode_lines,
            "## Metrics By Task",
            *task_lines,
            "",
            "## Failures And Usage Gaps",
            f"- Failed runs: {json.dumps(failures)}",
            f"- Usage-missing runs: {json.dumps(missing)}",
            "",
            "## Limitations",
            "- 固定任务且每种模式仅重复三次，属于小样本描述性证据。",
            "- 服务端模型权重版本无法由本地独立验证。",
            "",
            "这些结果来自固定协议下的小样本描述性评估；"
            "本报告不自动宣称 Triad 优于 Single，也不据此作产品决策。",
            "",
        ]
    )


def _atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_aggregate_outputs(output_dir: Path, summary: Mapping[str, object], report: str) -> None:
    _atomic_replace(output_dir / "summary.json", canonical_json(summary))
    _atomic_replace(output_dir / "report.md", report.encode("utf-8"))


def _validate_output_path(output_dir: Path, allowed_output_root: Path) -> Path:
    allowed_root = allowed_output_root.resolve(strict=True)
    if not allowed_root.is_dir():
        raise ValueError("allowed output root must be an existing directory")
    output = Path(os.path.abspath(output_dir))
    if not output.is_relative_to(allowed_root):
        raise ValueError("output directory is outside the allowed root")
    current = output
    while current != allowed_root:
        if current.exists() and current.is_symlink():
            raise ValueError("output path must not contain a symlink")
        current = current.parent
    resolved_output = output.resolve(strict=False)
    if not resolved_output.is_relative_to(allowed_root):
        raise ValueError("output directory resolves outside the allowed root")
    output.mkdir(parents=True, exist_ok=True)
    return output


def preflight(
    protocol: Protocol,
    protocol_sha256: str,
    output_dir: Path,
    *,
    allowed_output_root: Path,
    registry_loader=load_registry,
    client_builder=build_real_client,
) -> PreflightContext:
    output = _validate_output_path(output_dir, allowed_output_root)
    registry = registry_loader()
    model_routes: dict[str, tuple[str, str]] = {}
    for model_id in protocol_model_ids(protocol):
        client = client_builder(model_id, registry=registry)
        try:
            capability = client.capability
            if capability.model_id != model_id:
                raise ValueError("model capability id mismatch")
            if capability.max_output_tokens < protocol.generation.max_output_tokens:
                raise ValueError("model capability output limit mismatch")
            resolved = resolve_model(model_id, registry)
            client_kind = resolved.capability.client_kind
            route_sha256 = canonical_sha256(
                [
                    model_id,
                    client_kind,
                    resolved.base_url or "provider-default",
                ]
            )
            model_routes[model_id] = (client_kind, route_sha256)
        finally:
            _close_client(client)

    manifest = environment_manifest(
        protocol,
        protocol_sha256,
        repo_root=Path(__file__).parents[1],
        model_routes=model_routes if isinstance(protocol, M25EvaluationProtocol) else None,
        provider_route_sha256=(
            model_routes[protocol.model_id][1]
            if isinstance(protocol, EvaluationProtocol)
            else None
        ),
    )
    digest = environment_sha256(manifest)
    environment_path = output / "environment.json"
    if environment_path.exists():
        if environment_path.is_symlink() or not environment_path.is_file():
            raise ValueError("environment manifest must be a regular file")
        environment_type = (
            EnvironmentManifest
            if isinstance(protocol, EvaluationProtocol)
            else M25EnvironmentManifest
        )
        existing = environment_type.model_validate_json(environment_path.read_bytes())
        if environment_sha256(existing) != digest:
            raise ValueError("existing environment manifest does not match preflight")
        manifest = existing
    else:
        _atomic_replace(
            environment_path,
            canonical_json(manifest.model_dump(mode="json", by_alias=True)),
        )
    return PreflightContext(
        registry=registry,
        environment=manifest,
        environment_sha256=digest,
    )


def pending_run_specs(
    output_dir: Path,
    schedule: Sequence[RunSpecification],
    protocol_sha256: str,
    environment_sha256_value: str,
    *,
    environment: Environment | None = None,
) -> tuple[RunSpecification, ...]:
    raw_dir = output_dir / "raw"
    if raw_dir.is_symlink():
        raise ValueError("raw directory must not be a symlink")
    raw_dir.mkdir(parents=True, exist_ok=True)
    is_m25 = bool(schedule) and isinstance(schedule[0], M25RunSpec)
    if is_m25 and not isinstance(environment, M25EnvironmentManifest):
        raise ValueError("M25 resume requires its environment manifest")
    expected_paths = {_run_id_for_spec(spec) + ".json": spec for spec in schedule}
    existing_paths = {path.name: path for path in raw_dir.glob("*.json")}
    if existing_paths.keys() - expected_paths.keys():
        raise ValueError("raw directory contains an unexpected run record")

    pending: list[RunSpecification] = []
    for filename, spec in expected_paths.items():
        path = existing_paths.get(filename)
        if path is None:
            pending.append(spec)
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("raw record must be a regular file")
        try:
            record_type = M25RawRecord if isinstance(spec, M25RunSpec) else RawRecord
            record = record_type.model_validate_json(path.read_bytes())
        except Exception as error:
            raise ValueError("existing raw record is invalid") from error
        if (
            record.run_id != path.stem
            or record.sequence != spec.sequence
            or record.task_id != spec.task_id
            or record.repeat != spec.repeat
            or record.mode != spec.mode
            or record.run_spec_sha256 != run_spec_hash(spec, protocol_sha256)
        ):
            raise ValueError("existing raw record run id or run spec mismatch")
        if isinstance(spec, M25RunSpec):
            assert isinstance(record, M25RawRecord)
            assert isinstance(environment, M25EnvironmentManifest)
            if (
                record.task_family != spec.task_family
                or record.model_id != spec.model_id
                or record.provider_route_sha256
                != route_hash_for_model(environment, spec.model_id)
            ):
                raise ValueError("existing raw record M25 identity mismatch")
        if record.protocol_sha256 != protocol_sha256:
            raise ValueError("existing raw record protocol mismatch")
        if record.environment_sha256 != environment_sha256_value:
            raise ValueError("existing raw record environment mismatch")
    return tuple(pending)


def aggregate_command(
    protocol_path: Path,
    output_dir: Path,
    *,
    allowed_output_root: Path | None = None,
) -> int:
    protocol, protocol_sha256 = load_protocol(protocol_path)
    namespace = protocol_namespace(protocol)
    default_root = Path(__file__).parents[1] / f"docs/evaluation/{namespace}/runs"
    output = _validate_output_path(output_dir, allowed_output_root or default_root)
    environment_path = output / "environment.json"
    if environment_path.is_symlink() or not environment_path.is_file():
        raise ValueError("environment manifest is missing or invalid")
    environment_type = (
        EnvironmentManifest if isinstance(protocol, EvaluationProtocol) else M25EnvironmentManifest
    )
    environment = environment_type.model_validate_json(environment_path.read_bytes())
    environment_matches = (
        environment.protocol_sha256 == protocol_sha256
        and environment.generation == protocol.generation
        and environment.execution == protocol.execution
    )
    if isinstance(protocol, EvaluationProtocol):
        environment_matches = environment_matches and environment.model_id == protocol.model_id
    else:
        environment_matches = environment_matches and tuple(
            route.model_id for route in environment.model_routes
        ) == protocol.model_ids
    if not environment_matches:
        raise ValueError("environment manifest does not match protocol")
    environment_sha256_value = environment_sha256(environment)
    records = read_raw_records(
        output / "raw",
        protocol,
        protocol_sha256,
        environment_sha256_value,
    )
    summary = aggregate_records(protocol, build_schedule(protocol), records)
    report = render_report(
        protocol,
        environment.model_dump(mode="json", by_alias=True),
        summary,
    )
    write_aggregate_outputs(output, summary, report)
    return 0


def run_command(
    protocol_path: Path,
    output_dir: Path,
    *,
    allowed_output_root: Path | None = None,
) -> int:
    protocol, protocol_sha256 = load_protocol(protocol_path)
    namespace = protocol_namespace(protocol)
    default_root = Path(__file__).parents[1] / f"docs/evaluation/{namespace}/runs"
    context = preflight(
        protocol,
        protocol_sha256,
        output_dir,
        allowed_output_root=allowed_output_root or default_root,
    )
    schedule = build_schedule(protocol)
    if isinstance(protocol, EvaluationProtocol):
        pending = pending_run_specs(
            output_dir,
            schedule,
            protocol_sha256,
            context.environment_sha256,
        )
    else:
        pending = pending_run_specs(
            output_dir,
            schedule,
            protocol_sha256,
            context.environment_sha256,
            environment=context.environment,
        )
    task_by_id = {task.id: task for task in protocol.tasks}
    pending_sequences = {spec.sequence for spec in pending}
    for spec in schedule:
        if spec.sequence not in pending_sequences:
            print(f"SKIP sequence={spec.sequence}")
            continue
        print(f"RUN sequence={spec.sequence} task={spec.task_id} mode={spec.mode}")
        with tempfile.TemporaryDirectory(prefix=f"forgeagent-{namespace}-", dir="/tmp") as root:
            workspace = Path(root)
            task_spec = task_by_id[spec.task_id]
            prepare_workspace(task_spec, workspace)
            execution_arguments = (
                protocol,
                protocol_sha256,
                context.environment_sha256,
                task_spec,
                spec,
                workspace,
                context.registry,
            )
            record = (
                execute_run(*execution_arguments)
                if isinstance(protocol, EvaluationProtocol)
                else execute_run(*execution_arguments, context.environment)
            )
            write_raw_record(output_dir / "raw" / f"{record.run_id}.json", record)
        print(f"DONE sequence={spec.sequence} solved={str(record.solved).lower()}")
    return aggregate_command(
        protocol_path,
        output_dir,
        allowed_output_root=allowed_output_root or default_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "aggregate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--protocol", type=Path, required=True)
        subparser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "run":
            return run_command(arguments.protocol, arguments.output)
        return aggregate_command(arguments.protocol, arguments.output)
    except KeyboardInterrupt:
        print("ERROR category=interrupted", file=sys.stderr)
        return 130
    except Exception:
        print("ERROR category=harness_failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
