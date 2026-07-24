"""Durable, bounded checkpoints for task-level Loop execution."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .audit import AuditEvent, AuditSink, emit_audit
from .skills import SkillRegistry
from .tools import Tool, ToolContext, ToolOutcome, ToolRegistry, default_registry

LOOP_SCHEMA = "forgeagent.loop.v1"
DEFAULT_MAX_ROUNDS = 50
DEFAULT_WALL_CLOCK_SECONDS = 3600.0
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_ITEMS = 100
MAX_ITEM_CHARS = 500
MAX_HANDOFF_CHARS = 4000
MAX_FAILURE_CHARS = 2000
MAX_GOAL_CHARS = 4000

_LOOP_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_STOP_REASON_CHARS = 100


class LoopCheckpointError(Exception):
    """A checkpoint cannot be safely created, loaded, or committed."""


def _safe_text(value: Any, *, field: str, maximum: int, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if len(value) > maximum:
        raise ValueError(f"{field} is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains control characters")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must not be blank")
    return value.strip() if not allow_empty else value


def _positive_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return result


def _nonnegative_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a non-negative finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return result


def _items(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _safe_text(item, field=field, maximum=MAX_ITEM_CHARS, allow_empty=False)
        if text not in seen:
            seen.add(text)
            normalized.append(text)
    if len(normalized) > MAX_ITEMS:
        raise ValueError(f"{field} has too many items")
    return tuple(normalized)


class LoopBudgets(BaseModel):
    """Frozen execution limits persisted with each durable Loop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rounds: int = DEFAULT_MAX_ROUNDS
    token_budget: int
    wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES

    @field_validator("max_rounds", "token_budget", "max_consecutive_failures", mode="before")
    @classmethod
    def _validate_positive_integer(cls, value: Any, info: Any) -> int:
        return _positive_int(value, field=info.field_name)

    @field_validator("wall_clock_seconds", mode="before")
    @classmethod
    def _validate_wall_clock(cls, value: Any) -> float:
        return _positive_number(value, field="wall_clock_seconds")


with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "schema" in "LoopCheckpoint" shadows an attribute',
        category=UserWarning,
    )

    class LoopCheckpoint(BaseModel):
        """The complete, strictly validated durable Loop snapshot."""

        model_config = ConfigDict(frozen=True, extra="forbid")

        schema: Literal[LOOP_SCHEMA] = LOOP_SCHEMA
        loop_id: str
        goal: str
        budgets: LoopBudgets
        status: Literal["active", "completed", "stopped", "cancelled", "failed"] = "active"
        stop_reason: str | None = None
        revision: int = 0
        iterations: int = 0
        rounds_used: int = 0
        tokens_used: int = 0
        elapsed_seconds: float = 0.0
        consecutive_failures: int = 0
        usage_available: bool = True
        completed_items: tuple[str, ...] = ()
        open_questions: tuple[str, ...] = ()
        handoff: str = ""
        last_failure: str = ""

        @field_validator("loop_id")
        @classmethod
        def _validate_loop_id(cls, value: Any) -> str:
            if not isinstance(value, str) or _LOOP_ID_RE.fullmatch(value) is None:
                raise ValueError("invalid loop id")
            return value

        @field_validator("goal")
        @classmethod
        def _validate_goal(cls, value: Any) -> str:
            return _safe_text(value, field="goal", maximum=MAX_GOAL_CHARS, allow_empty=False)

        @field_validator("stop_reason")
        @classmethod
        def _validate_stop_reason(cls, value: Any) -> str | None:
            if value is None:
                return None
            return _safe_text(
                value, field="stop_reason", maximum=_MAX_STOP_REASON_CHARS, allow_empty=False
            )

        @field_validator(
            "revision",
            "iterations",
            "rounds_used",
            "tokens_used",
            "consecutive_failures",
            mode="before",
        )
        @classmethod
        def _validate_counter(cls, value: Any, info: Any) -> int:
            return _nonnegative_int(value, field=info.field_name)

        @field_validator("elapsed_seconds", mode="before")
        @classmethod
        def _validate_elapsed_seconds(cls, value: Any) -> float:
            return _nonnegative_number(value, field="elapsed_seconds")

        @field_validator("usage_available", mode="before")
        @classmethod
        def _validate_usage_available(cls, value: Any) -> bool:
            if type(value) is not bool:
                raise ValueError("usage_available must be a bool")
            return value

        @field_validator("completed_items", "open_questions", mode="before")
        @classmethod
        def _validate_items(cls, value: Any, info: Any) -> tuple[str, ...]:
            return _items(value, field=info.field_name)

        @field_validator("handoff")
        @classmethod
        def _validate_handoff(cls, value: Any) -> str:
            return _safe_text(value, field="handoff", maximum=MAX_HANDOFF_CHARS, allow_empty=True)

        @field_validator("last_failure")
        @classmethod
        def _validate_last_failure(cls, value: Any) -> str:
            return _safe_text(
                value, field="last_failure", maximum=MAX_FAILURE_CHARS, allow_empty=True
            )

        @model_validator(mode="after")
        def _validate_invariants(self) -> LoopCheckpoint:
            if self.status == "active":
                if self.stop_reason is not None:
                    raise ValueError("active checkpoints cannot have a stop reason")
            elif self.stop_reason is None:
                raise ValueError("terminal checkpoints require a stop reason")
            elif self.status == "completed" and self.stop_reason != "completed":
                raise ValueError("completed checkpoints require the completed stop reason")
            if self.rounds_used > self.budgets.max_rounds:
                raise ValueError("rounds_used exceeds max_rounds")
            if self.tokens_used > self.budgets.token_budget:
                raise ValueError("tokens_used exceeds token_budget")
            if self.consecutive_failures > self.budgets.max_consecutive_failures:
                raise ValueError("consecutive_failures exceeds its budget")
            return self


class LoopReport(BaseModel):
    """A deliberately safe public projection of a Loop checkpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    loop_id: str
    status: Literal["active", "completed", "stopped", "cancelled", "failed"]
    stop_reason: str | None
    iterations: int
    rounds_used: int
    tokens_used: int
    elapsed_seconds: float
    consecutive_failures: int
    completed_item_count: int
    open_question_count: int
    usage_available: bool

    @field_validator("loop_id")
    @classmethod
    def _validate_loop_id(cls, value: Any) -> str:
        if not isinstance(value, str) or _LOOP_ID_RE.fullmatch(value) is None:
            raise ValueError("invalid loop id")
        return value

    @field_validator(
        "iterations",
        "rounds_used",
        "tokens_used",
        "consecutive_failures",
        "completed_item_count",
        "open_question_count",
        mode="before",
    )
    @classmethod
    def _validate_counter(cls, value: Any, info: Any) -> int:
        return _nonnegative_int(value, field=info.field_name)

    @field_validator("elapsed_seconds", mode="before")
    @classmethod
    def _validate_elapsed_seconds(cls, value: Any) -> float:
        return _nonnegative_number(value, field="elapsed_seconds")

    @field_validator("usage_available", mode="before")
    @classmethod
    def _validate_usage_available(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("usage_available must be a bool")
        return value

    @classmethod
    def from_checkpoint(cls, checkpoint: LoopCheckpoint) -> LoopReport:
        return cls(
            loop_id=checkpoint.loop_id,
            status=checkpoint.status,
            stop_reason=checkpoint.stop_reason,
            iterations=checkpoint.iterations,
            rounds_used=checkpoint.rounds_used,
            tokens_used=checkpoint.tokens_used,
            elapsed_seconds=checkpoint.elapsed_seconds,
            consecutive_failures=checkpoint.consecutive_failures,
            completed_item_count=len(checkpoint.completed_items),
            open_question_count=len(checkpoint.open_questions),
            usage_available=checkpoint.usage_available,
        )


class CheckpointArgs(BaseModel):
    """Replacement state submitted by the Loop-only Checkpoint tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    completed_items: tuple[str, ...] = Field(default_factory=tuple)
    open_questions: tuple[str, ...] = Field(default_factory=tuple)
    handoff: str = ""

    @field_validator("completed_items", "open_questions", mode="before")
    @classmethod
    def _validate_items(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _items(value, field=info.field_name)

    @field_validator("handoff")
    @classmethod
    def _validate_handoff(cls, value: Any) -> str:
        return _safe_text(value, field="handoff", maximum=MAX_HANDOFF_CHARS, allow_empty=True)


class LoopCheckpointStore:
    """A symlink-safe, atomic JSON snapshot store under one allowed project root."""

    def __init__(
        self,
        allowed_root: str,
        *,
        audit_sink: AuditSink | None = None,
        task_id: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._audit_sink = audit_sink
        self._task_id = task_id
        self._root = self._safe_directory(Path(allowed_root), must_exist=True, root=None)
        self._loop_directory = self._prepare_loop_directory()

    @staticmethod
    def _safe_directory(path: Path, *, must_exist: bool, root: Path | None) -> Path:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            if must_exist:
                raise LoopCheckpointError("checkpoint root is unavailable") from None
            path.mkdir()
            details = os.lstat(path)
        except OSError:
            raise LoopCheckpointError("checkpoint root is unavailable") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise LoopCheckpointError("checkpoint root is unsafe")
        resolved = Path(os.path.realpath(path))
        if root is not None and not _is_within(root, resolved):
            raise LoopCheckpointError("checkpoint path is unsafe")
        return resolved

    def _prepare_loop_directory(self) -> Path:
        current = self._root
        for part in (".forgeagent", "loops"):
            candidate = current / part
            current = self._safe_directory(candidate, must_exist=False, root=self._root)
        return current

    def _path_for(self, loop_id: str) -> Path:
        if not isinstance(loop_id, str) or _LOOP_ID_RE.fullmatch(loop_id) is None:
            raise LoopCheckpointError("invalid checkpoint id")
        path = self._loop_directory / f"{loop_id}.json"
        if not _is_within(self._loop_directory, path):
            raise LoopCheckpointError("checkpoint path is unsafe")
        return path

    def _audit(self, checkpoint: LoopCheckpoint, result_status: str) -> None:
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type="loop.checkpoint",
                task_id=self._task_id,
                risk_level="low",
                parameters={
                    "schema": checkpoint.schema,
                    "revision": checkpoint.revision,
                    "iterations": checkpoint.iterations,
                    "rounds_used": checkpoint.rounds_used,
                    "tokens_used": checkpoint.tokens_used,
                    "completed_item_count": len(checkpoint.completed_items),
                    "open_question_count": len(checkpoint.open_questions),
                },
                result_status=result_status,
            ),
        )

    def create(
        self, goal: str, budgets: LoopBudgets, *, loop_id: str | None = None
    ) -> LoopCheckpoint:
        with self._lock:
            effective_id = uuid4().hex if loop_id is None else loop_id
            try:
                checkpoint = LoopCheckpoint(loop_id=effective_id, goal=goal, budgets=budgets)
            except ValidationError as error:
                raise LoopCheckpointError("invalid checkpoint") from error
            path = self._path_for(checkpoint.loop_id)
            if os.path.lexists(path):
                raise LoopCheckpointError("checkpoint already exists")
            self._write(path, checkpoint)
            self._audit(checkpoint, "created")
            return checkpoint

    def load(self, loop_id: str) -> LoopCheckpoint:
        with self._lock:
            path = self._path_for(loop_id)
            try:
                details = os.lstat(path)
                if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
                    raise LoopCheckpointError("checkpoint file is unsafe")
                if details.st_size > MAX_CHECKPOINT_BYTES:
                    raise LoopCheckpointError("checkpoint file is too large")
                with path.open("r", encoding="utf-8") as handle:
                    raw = handle.read(MAX_CHECKPOINT_BYTES + 1)
                if len(raw.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
                    raise LoopCheckpointError("checkpoint file is too large")
                parsed = json.loads(raw, parse_constant=_reject_json_constant)
                checkpoint = LoopCheckpoint.model_validate(parsed)
            except LoopCheckpointError:
                raise
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ) as error:
                raise LoopCheckpointError("checkpoint file is invalid") from error
            if checkpoint.loop_id != loop_id:
                raise LoopCheckpointError("checkpoint file is invalid")
            return checkpoint

    def save(self, checkpoint: LoopCheckpoint, *, expected_revision: int) -> LoopCheckpoint:
        if type(expected_revision) is not int or expected_revision < 0:
            raise LoopCheckpointError("invalid checkpoint revision")
        with self._lock:
            current = self.load(checkpoint.loop_id)
            if current.revision != expected_revision:
                raise LoopCheckpointError("checkpoint revision is stale")
            try:
                updated = LoopCheckpoint.model_validate(
                    checkpoint.model_dump(mode="python") | {"revision": expected_revision + 1}
                )
            except ValidationError as error:
                raise LoopCheckpointError("invalid checkpoint") from error
            self._write(self._path_for(updated.loop_id), updated)
            self._audit(updated, "saved")
            return updated

    def _write(self, path: Path, checkpoint: LoopCheckpoint) -> None:
        payload = (
            json.dumps(
                checkpoint.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        if len(payload) > MAX_CHECKPOINT_BYTES:
            raise LoopCheckpointError("checkpoint is too large")
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb", dir=self._loop_directory, prefix=".loop-checkpoint.", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
            _fsync_directory(self._loop_directory)
        except OSError as error:
            raise LoopCheckpointError("checkpoint save failed") from error
        finally:
            if temporary_name is not None and os.path.exists(temporary_name):
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass


class CheckpointTool(Tool):
    """Commit model-supplied progress before returning success to the Step loop."""

    name = "Checkpoint"
    args_model = CheckpointArgs
    risk_level = "low"

    def __init__(self, store: LoopCheckpointStore, checkpoint: LoopCheckpoint) -> None:
        self._store = store
        self._checkpoint = checkpoint

    def run(self, args: BaseModel, ctx: ToolContext | None) -> ToolOutcome:
        if not isinstance(args, CheckpointArgs):
            return ToolOutcome(
                tool=self.name, success=False, detail="Checkpoint rejected: invalid arguments"
            )
        try:
            # Revalidation also protects direct tool callers that bypass protocol parsing.
            validated = CheckpointArgs.model_validate(args.model_dump(mode="python"))
            previous = set(self._checkpoint.completed_items)
            if not previous.issubset(validated.completed_items):
                return ToolOutcome(
                    tool=self.name,
                    success=False,
                    detail="Checkpoint rejected: completed items cannot be removed",
                )
            candidate = self._checkpoint.model_copy(
                update={
                    "completed_items": validated.completed_items,
                    "open_questions": validated.open_questions,
                    "handoff": validated.handoff,
                }
            )
            saved = self._store.save(candidate, expected_revision=self._checkpoint.revision)
        except (LoopCheckpointError, ValidationError):
            return ToolOutcome(tool=self.name, success=False, detail="Checkpoint save failed")
        self._checkpoint = saved
        return ToolOutcome(
            tool=self.name,
            success=True,
            detail=(
                f"checkpoint saved revision={saved.revision} "
                f"completed={len(saved.completed_items)} "
                f"open_questions={len(saved.open_questions)}"
            ),
        )


def build_loop_registry(
    *,
    store: LoopCheckpointStore,
    checkpoint: LoopCheckpoint,
    with_mcp: bool = False,
    skills: SkillRegistry | None = None,
) -> ToolRegistry:
    """Build one fresh registry so ordinary Task registries never see Checkpoint."""
    registry = default_registry(with_mcp=with_mcp, skills=skills)
    registry.register(CheckpointTool(store, checkpoint))
    return registry


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync keeps a successful replace durable on POSIX."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
