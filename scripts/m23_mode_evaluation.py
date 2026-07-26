#!/usr/bin/env python3
"""Run the M23 Single/Duo/Triad evaluation protocol."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_SCHEMA = "forgeagent.m23.mode-evaluation/v1"
MODES = ("single", "duo", "triad")
Mode = Literal["single", "duo", "triad"]


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
    required_candidate_files: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[str, ...] = Field(min_length=1)
    checks: tuple[CheckSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_paths_and_ids(self) -> TaskSpec:
        for path in self.initial_files:
            _validate_relative_path(path)
        candidate_paths = {_validate_relative_path(path) for path in self.required_candidate_files}
        artifact_paths = {_validate_relative_path(path) for path in self.artifacts}
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


@dataclass(frozen=True)
class RunSpec:
    sequence: int
    task_id: str
    repeat: int
    mode: Mode


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_protocol(value: object) -> EvaluationProtocol:
    return EvaluationProtocol.model_validate(value)


def load_protocol(path: Path) -> tuple[EvaluationProtocol, str]:
    protocol = validate_protocol(json.loads(path.read_text(encoding="utf-8")))
    serialized = protocol.model_dump(mode="json", by_alias=True)
    return protocol, canonical_sha256(serialized)


def build_schedule(protocol: EvaluationProtocol) -> tuple[RunSpec, ...]:
    schedule: list[RunSpec] = []
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


def run_spec_hash(run_spec: RunSpec, protocol_sha256: str) -> str:
    return canonical_sha256(
        {
            "protocol_sha256": protocol_sha256,
            "run": {
                "sequence": run_spec.sequence,
                "task_id": run_spec.task_id,
                "repeat": run_spec.repeat,
                "mode": run_spec.mode,
            },
        }
    )


def main() -> int:
    protocol, digest = load_protocol(
        Path(__file__).parents[1] / "docs/evaluation/m23/protocol.json"
    )
    print(
        json.dumps(
            {"protocol_digest": digest, "runs": len(build_schedule(protocol))},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
