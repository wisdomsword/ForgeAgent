"""Threat-boundary tests for durable collaboration snapshots."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

import pytest

import forgeagent.collaboration as collaboration_module
from forgeagent.collaboration import (
    MAX_GOAL_CHARS,
    MAX_STATE_BYTES,
    AcceptanceItem,
    CollaborationError,
    CollaborationState,
    CollaborationStore,
    CollaborationUsage,
    EvaluationItem,
    plan_digest,
)
from forgeagent.execution_evidence import ExecutionEvidence, ToolExecutionRecord


def test_store_creates_loads_and_atomically_saves_private_state(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="b" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / ("b" * 32 + ".json")

    assert store.load(created.collaboration_id) == created
    assert created.status == "active"
    assert created.phase == "generator"
    assert "inspectable artifact" in created.plan[0].behavior.casefold()
    assert path.stat().st_mode & 0o777 == 0o600
    saved = store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)
    assert saved.revision == 1
    assert json.loads(path.read_text())["revision"] == 1


def test_store_loads_v1_state_without_execution_evidence_and_round_trips_prefix(
    tmp_path: Path,
):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="b" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / ("b" * 32 + ".json")
    payload = json.loads(path.read_text())
    payload.pop("execution_evidence", None)
    path.write_text(json.dumps(payload))

    loaded = store.load(created.collaboration_id)
    assert loaded.execution_evidence == ExecutionEvidence()
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool="Exec",
                status="succeeded",
                role="generator",
                attempt=1,
            ),
        ),
        omitted_count=3,
        truncated=True,
    )
    saved = store.save(
        loaded.model_copy(update={"execution_evidence": evidence}),
        expected_revision=loaded.revision,
    )
    assert store.load(saved.collaboration_id).execution_evidence == evidence


def test_store_strips_legacy_model_controlled_block_on_load(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="d" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / ("d" * 32 + ".json")
    payload = json.loads(path.read_text())
    payload["execution_evidence"] = {
        "records": [
            {
                "sequence": 1,
                "tool": "Exec",
                "status": "succeeded",
                "block": "/private/legacy.py RAW_ARG_MARKER PROMPT_MARKER NON_ENV_SECRET_MARKER",
                "role": "generator",
                "attempt": 1,
            }
        ],
        "truncated": False,
        "omitted_count": 0,
    }
    path.write_text(json.dumps(payload))

    loaded = store.load(created.collaboration_id)
    saved = store.save(loaded.model_copy(update={"rounds": 1}), expected_revision=0)

    assert loaded.execution_evidence.records[0].block is None
    assert saved.execution_evidence.records[0].block is None
    assert "block" not in json.loads(path.read_text())["execution_evidence"]["records"][0]


def test_store_rejects_execution_evidence_prefix_rewrite_and_omitted_regression(
    tmp_path: Path,
):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool="Exec",
                status="succeeded",
                role="generator",
                attempt=1,
            ),
        ),
        omitted_count=2,
        truncated=True,
    )
    saved = store.save(
        created.model_copy(update={"execution_evidence": evidence}),
        expected_revision=created.revision,
    )

    rewritten = ToolExecutionRecord(
        sequence=1,
        tool="FileRead",
        status="succeeded",
        role="generator",
        attempt=1,
    )
    with pytest.raises(CollaborationError):
        store.save(
            saved.model_copy(
                update={
                    "execution_evidence": ExecutionEvidence(
                        records=(rewritten,), omitted_count=2, truncated=True
                    )
                }
            ),
            expected_revision=saved.revision,
        )
    with pytest.raises(CollaborationError):
        store.save(
            saved.model_copy(
                update={
                    "execution_evidence": ExecutionEvidence(
                        records=evidence.records, omitted_count=1, truncated=True
                    )
                }
            ),
            expected_revision=saved.revision,
        )


def test_store_create_is_total_for_valid_goals_and_accepts_only_configuration(
    tmp_path: Path,
):
    store = CollaborationStore(str(tmp_path))
    created = store.create(
        "x" * MAX_GOAL_CHARS,
        "duo",
        collaboration_id="0" * 32,
        planner_model="planner",
        generator_model="generator",
        evaluator_model="evaluator",
        evaluator_tier="container",
        max_rejections=3,
        usage_available=False,
    )

    assert created.phase == "generator"
    assert created.plan_digest == plan_digest(created.plan)
    assert created.generator_model == "generator"
    assert created.max_rejections == 3
    assert created.usage_available is False

    lifecycle_values = {
        "phase": "evaluator",
        "status": "completed",
        "plan": created.plan,
        "plan_digest": created.plan_digest,
        "revision": 1,
        "rounds": 1,
        "last_evaluation": (),
    }
    for name, value in lifecycle_values.items():
        with pytest.raises(TypeError):
            store.create("another", "duo", **{name: value})


def test_store_rejects_stale_corrupt_oversized_and_unknown_schema(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    saved = store.save(created, expected_revision=0)
    with pytest.raises(CollaborationError):
        store.save(created, expected_revision=0)

    path = tmp_path / ".forgeagent" / "collaborations" / ("d" * 32 + ".json")
    path.write_bytes(b'{"schema":"unknown"}')
    with pytest.raises(CollaborationError):
        store.load("d" * 32)
    path.write_bytes(b"x" * (MAX_STATE_BYTES + 1))
    with pytest.raises(CollaborationError):
        store.load("d" * 32)
    assert saved.revision == 1


def test_overlapping_saves_from_distinct_stores_commit_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first = CollaborationStore(str(tmp_path))
    created = first.create("Build an artifact", "duo", collaboration_id="9" * 32)
    second = CollaborationStore(str(tmp_path))
    barrier = threading.Barrier(2)
    original_flock = collaboration_module.fcntl.flock

    def overlap_before_lock(descriptor: int, operation: int):
        if operation == collaboration_module.fcntl.LOCK_EX:
            barrier.wait(timeout=2)
        return original_flock(descriptor, operation)

    monkeypatch.setattr(collaboration_module.fcntl, "flock", overlap_before_lock)

    results: list[object] = []

    def save(store: CollaborationStore, rounds: int) -> None:
        try:
            results.append(
                store.save(created.model_copy(update={"rounds": rounds}), expected_revision=0)
            )
        except CollaborationError as error:
            results.append(error)

    threads = [
        threading.Thread(target=save, args=(first, 1)),
        threading.Thread(target=save, args=(second, 2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert sum(isinstance(result, CollaborationState) for result in results) == 1
    assert sum(isinstance(result, CollaborationError) for result in results) == 1
    assert first.load(created.collaboration_id).revision == 1


def test_overlapping_store_initialization_reuses_safe_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    barrier = threading.Barrier(2)
    target = tmp_path / ".forgeagent"
    original_mkdir = Path.mkdir

    def overlapping_mkdir(path: Path, *args, **kwargs):
        if path == target:
            barrier.wait(timeout=2)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", overlapping_mkdir)
    results: list[object] = []

    def initialize() -> None:
        try:
            results.append(CollaborationStore(str(tmp_path)))
        except Exception as error:
            results.append(error)

    threads = [threading.Thread(target=initialize) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert all(isinstance(result, CollaborationStore) for result in results)
    for result in results:
        result.close()


def test_overlapping_creates_from_distinct_stores_commit_once(tmp_path: Path):
    both_writing = threading.Event()
    write_count = 0
    count_lock = threading.Lock()

    class CoordinatedStore(CollaborationStore):
        def _write(self, name: str, state: CollaborationState) -> None:
            nonlocal write_count
            with count_lock:
                write_count += 1
                if write_count == 2:
                    both_writing.set()
            both_writing.wait(timeout=0.5)
            super()._write(name, state)

    stores = (CoordinatedStore(str(tmp_path)), CoordinatedStore(str(tmp_path)))
    start = threading.Barrier(2)
    results: list[object] = []

    def create(store: CollaborationStore) -> None:
        start.wait(timeout=2)
        try:
            results.append(store.create("Build an artifact", "duo", collaboration_id="a" * 32))
        except CollaborationError as error:
            results.append(error)

    threads = [threading.Thread(target=create, args=(store,)) for store in stores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert sum(isinstance(result, CollaborationState) for result in results) == 1
    assert sum(isinstance(result, CollaborationError) for result in results) == 1


def test_store_rejects_symlink_collaboration_lock(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="8" * 32)
    lock_path = tmp_path / ".forgeagent" / "collaborations" / f".{created.collaboration_id}.lock"
    outside = tmp_path / "outside-lock"
    outside.write_text("unchanged", encoding="utf-8")
    lock_path.unlink()
    lock_path.symlink_to(outside)

    with pytest.raises(CollaborationError):
        store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)

    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert store.load(created.collaboration_id).revision == 0


@pytest.mark.skipif(collaboration_module.fcntl is None, reason="flock is POSIX-only")
def test_collaboration_lock_failure_preserves_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="6" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / f"{created.collaboration_id}.json"
    before = path.read_bytes()

    def fail_lock(*args: object, **kwargs: object) -> None:
        raise OSError("lock unavailable")

    monkeypatch.setattr(collaboration_module.fcntl, "flock", fail_lock)

    with pytest.raises(CollaborationError):
        store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)

    assert path.read_bytes() == before


def test_collaboration_create_fails_closed_without_platform_locking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    monkeypatch.setattr(collaboration_module, "fcntl", None)

    with pytest.raises(CollaborationError):
        store.create("Build an artifact", "duo", collaboration_id="5" * 32)

    assert not (tmp_path / ".forgeagent" / "collaborations" / ("5" * 32 + ".json")).exists()


def test_store_rejects_symlink_and_directory_replacement(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    store = CollaborationStore(str(root))
    created = store.create("Build an artifact", "duo", collaboration_id="e" * 32)
    path = root / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    path.unlink()
    path.symlink_to(outside / "state.json")
    with pytest.raises(CollaborationError):
        store.load(created.collaboration_id)

    directory = root / ".forgeagent" / "collaborations"
    original = tmp_path / "original"
    directory.rename(original)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(CollaborationError):
        store.create("Another", "duo", collaboration_id="f" * 32)


def test_store_replace_failure_preserves_old_state_and_close_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="1" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    old = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    with pytest.raises(CollaborationError):
        store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)
    assert path.read_bytes() == old
    store.close()
    store.close()
    with pytest.raises(CollaborationError):
        store.load(created.collaboration_id)


def test_store_refuses_replacing_a_frozen_plan(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="2" * 32)
    replacement = (AcceptanceItem(id="other", behavior="other", acceptance="other"),)

    with pytest.raises(CollaborationError):
        store.save(
            created.model_copy(
                update={"plan": replacement, "plan_digest": plan_digest(replacement)}
            ),
            expected_revision=0,
        )


@pytest.mark.parametrize(
    ("updates", "label"),
    [
        ({"phase": "generator"}, "phase"),
        ({"status": "active", "phase": "generator", "stop_reason": None}, "terminal status"),
        ({"generator_attempts": 1}, "generator attempts"),
        ({"evaluator_attempts": 1}, "evaluator attempts"),
        ({"rejections": 0}, "rejections"),
        ({"rounds": 4}, "rounds"),
        ({"usage": CollaborationUsage(input_tokens=4)}, "usage"),
        ({"goal": "Changed goal"}, "goal"),
        ({"mode": "triad"}, "mode"),
        ({"generator_model": "changed"}, "role config"),
    ],
)
def test_store_rejects_nonmonotonic_state_transitions(
    tmp_path: Path, updates: dict[str, object], label: str
):
    evaluation = (EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),)
    store = CollaborationStore(str(tmp_path))
    created = store.create(
        "Build an artifact",
        "duo",
        collaboration_id="3" * 32,
        generator_model="generator",
        evaluator_model="evaluator",
    )
    evaluated = store.save(
        created.model_copy(
            update={
                "phase": "evaluator",
                "generator_attempts": 2,
                "evaluator_attempts": 2,
                "rejections": 1,
                "rounds": 5,
                "usage": CollaborationUsage(input_tokens=5, output_tokens=3, cost=1.0),
                "last_evaluation": evaluation,
            }
        ),
        expected_revision=0,
    )
    current = store.save(
        evaluated.model_copy(
            update={"status": "completed", "phase": "completed", "stop_reason": "completed"}
        ),
        expected_revision=1,
    )

    expected_error = "state|transition" if label == "goal" else "transition"
    with pytest.raises(CollaborationError, match=expected_error):
        store.save(current.model_copy(update=updates), expected_revision=2)


def test_store_rejects_completed_status_in_an_execution_phase(tmp_path: Path):
    evaluation = (EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),)
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="7" * 32)
    current = store.save(
        created.model_copy(update={"phase": "evaluator", "last_evaluation": evaluation}),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError):
        store.save(
            current.model_copy(update={"status": "completed", "stop_reason": "completed"}),
            expected_revision=1,
        )


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("completed", "completed"),
        ("stopped", "needs_confirmation"),
        ("cancelled", "cancelled"),
        ("failed", "state_failure"),
    ],
)
def test_store_freezes_terminal_snapshots(tmp_path: Path, status: str, reason: str):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="b" * 32)
    if status == "completed":
        evaluated = store.save(
            created.model_copy(
                update={
                    "phase": "evaluator",
                    "last_evaluation": (
                        EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),
                    ),
                }
            ),
            expected_revision=0,
        )
        terminal = store.save(
            evaluated.model_copy(update={"status": status, "phase": status, "stop_reason": reason}),
            expected_revision=1,
        )
    else:
        terminal = store.save(
            created.model_copy(update={"status": status, "phase": status, "stop_reason": reason}),
            expected_revision=0,
        )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(
            terminal.model_copy(update={"rounds": terminal.rounds + 1}),
            expected_revision=terminal.revision,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "last_evaluation": (
                EvaluationItem(id="goal", passed=True, observed="different", expected="yes"),
            )
        },
        {"generator_attempts": 1},
        {"evaluator_attempts": 1},
        {"rejections": 1},
        {"rounds": 1},
        {"usage": CollaborationUsage(input_tokens=1)},
        {"usage_available": False},
    ],
)
def test_store_rejects_every_terminal_business_mutation(tmp_path: Path, updates: dict[str, object]):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="c" * 32)
    evaluated = store.save(
        created.model_copy(
            update={
                "phase": "evaluator",
                "last_evaluation": (
                    EvaluationItem(id="goal", passed=True, observed="yes", expected="yes"),
                ),
            }
        ),
        expected_revision=0,
    )
    terminal = store.save(
        evaluated.model_copy(
            update={"status": "completed", "phase": "completed", "stop_reason": "completed"}
        ),
        expected_revision=1,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(terminal.model_copy(update=updates), expected_revision=terminal.revision)


@pytest.mark.parametrize(
    ("mode", "values"),
    [
        ("duo", {"phase": "planning"}),
        ("duo", {"phase": "needs_confirmation"}),
        ("triad", {"phase": "generator"}),
        ("triad", {"phase": "evaluator"}),
        ("triad", {"plan_digest": "f" * 64}),
    ],
)
def test_store_create_rejects_lifecycle_state_injection(
    tmp_path: Path, mode: Literal["duo", "triad"], values: dict[str, object]
):
    store = CollaborationStore(str(tmp_path))
    with pytest.raises(TypeError):
        store.create(
            "Build an artifact",
            mode,
            collaboration_id="8" * 32,
            **values,
        )


def test_store_rejects_a_caller_supplied_duo_plan(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    with pytest.raises(TypeError):
        store.create(
            "Build an artifact",
            "duo",
            collaboration_id="9" * 32,
            plan=(AcceptanceItem(id="other", behavior="other", acceptance="other"),),
        )


def test_store_rejects_plan_fact_loss_before_plan_freezes(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    current = store.create("Build an artifact", "triad", collaboration_id="4" * 32)
    plan = (AcceptanceItem(id="output", behavior="output", acceptance="exists"),)
    saved = store.save(
        current.model_copy(
            update={"plan": plan, "plan_digest": plan_digest(plan), "phase": "needs_confirmation"}
        ),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(
            saved.model_copy(update={"plan": (), "plan_digest": "", "phase": "planning"}),
            expected_revision=1,
        )


def test_store_rejects_evaluation_fact_loss(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="5" * 32)
    current = store.save(
        created.model_copy(
            update={
                "phase": "evaluator",
                "last_evaluation": (
                    EvaluationItem(id="goal", passed=False, observed="missing", expected="present"),
                ),
            }
        ),
        expected_revision=0,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(current.model_copy(update={"last_evaluation": ()}), expected_revision=1)


def test_store_rejects_restoring_unavailable_usage(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    current = store.create(
        "Build an artifact",
        "duo",
        collaboration_id="6" * 32,
        usage_available=False,
    )

    with pytest.raises(CollaborationError, match="transition"):
        store.save(current.model_copy(update={"usage_available": True}), expected_revision=0)


def test_store_projects_direct_state_evidence_before_environment_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = "store-boundary-secret-value"
    host_path = "/Users/admin/private/result.txt"
    monkeypatch.setenv("COLLABORATION_STORE_SECRET", secret)
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="a" * 32)
    unsafe = EvaluationItem.model_construct(
        id="goal",
        passed=False,
        observed=f"found {secret} at {host_path}",
        expected=f"remove {secret} from {host_path}",
        location="result.txt",
    )

    saved = store.save(
        created.model_copy(update={"phase": "evaluator", "last_evaluation": (unsafe,)}),
        expected_revision=0,
    )
    path = tmp_path / ".forgeagent" / "collaborations" / (created.collaboration_id + ".json")
    persisted = path.read_text()
    monkeypatch.delenv("COLLABORATION_STORE_SECRET")
    loaded = store.load(created.collaboration_id)

    assert secret not in persisted
    assert host_path not in persisted
    assert secret not in loaded.model_dump_json()
    assert host_path not in loaded.model_dump_json()
    assert loaded == saved


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_DIRECTORY"])
def test_store_fails_closed_without_safe_open_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
):
    monkeypatch.delattr(os, flag, raising=False)

    with pytest.raises(CollaborationError, match="safe file access is unavailable"):
        CollaborationStore(str(tmp_path))
