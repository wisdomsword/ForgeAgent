"""Durable Loop checkpoint boundary tests."""

from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

import forgeagent.loop as loop_module
from forgeagent.loop import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_WALL_CLOCK_SECONDS,
    LOOP_SCHEMA,
    MAX_CHECKPOINT_BYTES,
    MAX_HANDOFF_CHARS,
    MAX_ITEMS,
    CheckpointArgs,
    CheckpointTool,
    LoopBudgets,
    LoopCheckpoint,
    LoopCheckpointError,
    LoopCheckpointStore,
    LoopReport,
    build_loop_registry,
)
from forgeagent.tools import default_registry


def test_loop_module_does_not_import_collaboration_on_single_hot_path():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/forgeagent/loop.py").read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "collaboration"
        for node in ast.walk(tree)
    )


def _budgets(**overrides: object) -> LoopBudgets:
    values: dict[str, object] = {"token_budget": 100}
    values.update(overrides)
    return LoopBudgets(**values)


def _checkpoint(**overrides: object) -> LoopCheckpoint:
    values: dict[str, object] = {
        "loop_id": "a" * 32,
        "goal": "Finish the work",
        "budgets": _budgets(),
    }
    values.update(overrides)
    return LoopCheckpoint(**values)


def test_budget_defaults_and_explicit_token_budget_model():
    budgets = _budgets()

    assert budgets.max_rounds == DEFAULT_MAX_ROUNDS
    assert budgets.wall_clock_seconds == DEFAULT_WALL_CLOCK_SECONDS
    assert budgets.max_consecutive_failures == DEFAULT_MAX_CONSECUTIVE_FAILURES
    assert budgets.token_budget == 100


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_rounds", True),
        ("token_budget", True),
        ("max_consecutive_failures", True),
        ("max_rounds", 0),
        ("token_budget", 0),
        ("max_consecutive_failures", -1),
        ("wall_clock_seconds", 0.0),
        ("wall_clock_seconds", math.inf),
        ("wall_clock_seconds", math.nan),
    ],
)
def test_budget_model_rejects_bool_nonpositive_and_nonfinite_values(field: str, value: object):
    with pytest.raises(ValidationError):
        _budgets(**{field: value})


@pytest.mark.parametrize("loop_id", ["A" * 32, "a" * 31, "../" + "a" * 29, "a" * 32 + "\n"])
def test_model_rejects_invalid_loop_ids(loop_id: str):
    with pytest.raises(ValidationError):
        _checkpoint(loop_id=loop_id)


def test_model_forbids_extra_fields_and_control_characters():
    with pytest.raises(ValidationError):
        _checkpoint(unexpected="no")
    with pytest.raises(ValidationError):
        _checkpoint(goal="unsafe\x00 goal")


def test_model_deduplicates_items_and_enforces_item_limits():
    checkpoint = _checkpoint(completed_items=("one", "two", "one"), open_questions=("q", "q"))

    assert checkpoint.completed_items == ("one", "two")
    assert checkpoint.open_questions == ("q",)
    with pytest.raises(ValidationError):
        _checkpoint(completed_items=tuple(str(index) for index in range(MAX_ITEMS + 1)))
    with pytest.raises(ValidationError):
        _checkpoint(completed_items=("   ",))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "active", "stop_reason": "completed"},
        {"status": "stopped", "stop_reason": None},
        {"status": "completed", "stop_reason": "token_budget"},
    ],
)
def test_model_enforces_active_and_terminal_status_invariants(overrides: dict[str, object]):
    with pytest.raises(ValidationError):
        _checkpoint(**overrides)


def test_model_allows_token_usage_to_overshoot_budget_at_a_safe_boundary():
    checkpoint = _checkpoint(tokens_used=101)

    assert checkpoint.tokens_used == 101


@pytest.mark.parametrize("character", ["\u0085", "\u202e", "\ud800", "\u2028", "\u2029"])
@pytest.mark.parametrize(
    ("field", "value_factory"),
    [
        ("goal", lambda character: f"unsafe{character}goal"),
        ("completed_items", lambda character: (f"unsafe{character}item",)),
        ("open_questions", lambda character: (f"unsafe{character}question",)),
        ("handoff", lambda character: f"unsafe{character}handoff"),
        ("last_failure", lambda character: f"unsafe{character}failure"),
    ],
)
def test_model_rejects_dangerous_unicode_in_persisted_prompt_text(
    character: str, field: str, value_factory
):
    with pytest.raises(ValidationError):
        _checkpoint(**{field: value_factory(character)})


def test_report_is_safe_projection_model():
    report = LoopReport.from_checkpoint(
        _checkpoint(
            completed_items=("secret complete",),
            open_questions=("secret question",),
            handoff="secret handoff",
            last_failure="secret failure",
        )
    )

    assert report.model_dump() == {
        "schema": LOOP_SCHEMA,
        "loop_id": "a" * 32,
        "status": "active",
        "stop_reason": None,
        "iterations": 0,
        "rounds_used": 0,
        "tokens_used": 0,
        "elapsed_seconds": 0.0,
        "consecutive_failures": 0,
        "completed_item_count": 1,
        "open_question_count": 1,
        "usage_available": True,
        "collaboration_mode": "single",
    }


def test_old_checkpoint_defaults_to_single_collaboration_mode():
    payload = _checkpoint().model_dump(mode="json")
    payload.pop("collaboration_mode", None)
    payload.pop("collaboration_id", None)
    payload.pop("plan_digest", None)

    loaded = LoopCheckpoint.model_validate(payload)

    assert loaded.collaboration_mode == "single"
    assert loaded.collaboration_id == ""
    assert loaded.plan_digest == ""


def test_collaborative_checkpoint_freezes_mode_id_and_digest():
    checkpoint = _checkpoint(
        collaboration_mode="triad",
        collaboration_id="b" * 32,
        plan_digest="c" * 64,
    )

    assert checkpoint.collaboration_mode == "triad"
    assert checkpoint.collaboration_id == "b" * 32
    assert checkpoint.plan_digest == "c" * 64


@pytest.mark.parametrize(
    ("status", "stop_reason"),
    [
        ("active", "completed"),
        ("completed", "max_rounds"),
        ("stopped", "completed"),
        ("cancelled", "token_budget"),
        ("failed", "cancelled"),
        ("failed", "unexpected_reason"),
    ],
)
def test_report_rejects_unknown_or_status_inconsistent_stop_reasons(status: str, stop_reason: str):
    with pytest.raises(ValidationError):
        LoopReport(
            loop_id="a" * 32,
            status=status,
            stop_reason=stop_reason,
            iterations=0,
            rounds_used=0,
            tokens_used=0,
            elapsed_seconds=0.0,
            consecutive_failures=0,
            completed_item_count=0,
            open_question_count=0,
            usage_available=True,
        )


def test_report_model_rejects_coerced_counters_and_nonfinite_elapsed_time():
    with pytest.raises(ValidationError):
        LoopReport(
            loop_id="a" * 32,
            status="active",
            stop_reason=None,
            iterations=True,
            rounds_used=0,
            tokens_used=0,
            elapsed_seconds=0.0,
            consecutive_failures=0,
            completed_item_count=0,
            open_question_count=0,
            usage_available=True,
        )
    with pytest.raises(ValidationError):
        LoopReport(
            loop_id="a" * 32,
            status="active",
            stop_reason=None,
            iterations=0,
            rounds_used=0,
            tokens_used=0,
            elapsed_seconds=math.inf,
            consecutive_failures=0,
            completed_item_count=0,
            open_question_count=0,
            usage_available=True,
        )


def test_store_creates_loads_and_writes_stable_json(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    created = store.create("Build it", _budgets(), loop_id="b" * 32)
    path = tmp_path / ".forgeagent" / "loops" / ("b" * 32 + ".json")

    assert store.load(created.loop_id) == created
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert (
        raw
        == json.dumps(
            created.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )


@pytest.mark.parametrize(
    "payload",
    [b'{"schema":"unknown"}', b"{bad", b'{"schema":"forgeagent.loop.v1","elapsed_seconds":NaN}'],
)
def test_store_rejects_unknown_schema_malformed_and_nonfinite_input(tmp_path: Path, payload: bytes):
    store = LoopCheckpointStore(str(tmp_path))
    path = tmp_path / ".forgeagent" / "loops" / ("c" * 32 + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    with pytest.raises(LoopCheckpointError):
        store.load("c" * 32)


def test_store_rejects_oversize_input_and_path_escape(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    path = tmp_path / ".forgeagent" / "loops" / ("d" * 32 + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * (MAX_CHECKPOINT_BYTES + 1))

    with pytest.raises(LoopCheckpointError):
        store.load("d" * 32)
    with pytest.raises(LoopCheckpointError):
        store.load("../" + "d" * 29)


def test_store_rejects_symlink_root_and_file(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(LoopCheckpointError):
        LoopCheckpointStore(str(root_link))

    store = LoopCheckpointStore(str(tmp_path))
    created = store.create("Build it", _budgets(), loop_id="e" * 32)
    path = tmp_path / ".forgeagent" / "loops" / (created.loop_id + ".json")
    path.unlink()
    path.symlink_to(tmp_path / "outside.json")
    with pytest.raises(LoopCheckpointError):
        store.load(created.loop_id)


def test_store_fails_closed_when_loop_directory_is_replaced_by_symlink(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LoopCheckpointStore(str(root))
    created = store.create("Build it", _budgets(), loop_id="4" * 32)
    loops = root / ".forgeagent" / "loops"
    original_loops = tmp_path / "original-loops"
    loops.rename(original_loops)
    loops.symlink_to(outside, target_is_directory=True)
    outside_checkpoint = outside / (created.loop_id + ".json")
    outside_checkpoint.write_text(
        json.dumps(created.model_copy(update={"goal": "Outside"}).model_dump(mode="json")),
        encoding="utf-8",
    )
    outside_before = outside_checkpoint.read_bytes()

    with pytest.raises(LoopCheckpointError):
        store.load(created.loop_id)
    with pytest.raises(LoopCheckpointError):
        store.save(created.model_copy(update={"handoff": "next"}), expected_revision=0)
    with pytest.raises(LoopCheckpointError):
        store.create("Another", _budgets(), loop_id="5" * 32)

    assert outside_checkpoint.read_bytes() == outside_before
    assert not (outside / ("5" * 32 + ".json")).exists()


def test_store_close_fails_closed_after_descriptor_number_is_reused(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    created = store.create("Build it", _budgets(), loop_id="6" * 32)
    descriptor = store._loop_directory_descriptor
    loops = tmp_path / ".forgeagent" / "loops"

    store.close()
    store.close()
    reused_descriptor = os.open(loops, os.O_RDONLY | os.O_DIRECTORY)
    assert reused_descriptor == descriptor

    try:
        with pytest.raises(LoopCheckpointError):
            store.load(created.loop_id)
        with pytest.raises(LoopCheckpointError):
            store.save(created.model_copy(update={"handoff": "next"}), expected_revision=0)
        with pytest.raises(LoopCheckpointError):
            store.create("Another", _budgets(), loop_id="7" * 32)
    finally:
        os.close(reused_descriptor)


def test_store_save_fails_if_loop_directory_is_replaced_during_write(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LoopCheckpointStore(str(root))
    created = store.create("Build it", _budgets(), loop_id="8" * 32)
    loops = root / ".forgeagent" / "loops"
    original_loops = tmp_path / "original-loops"
    original_replace = os.replace

    def replace_then_swap(source, destination, **kwargs):
        original_replace(source, destination, **kwargs)
        loops.rename(original_loops)
        loops.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(os, "replace", replace_then_swap)

    with pytest.raises(LoopCheckpointError):
        store.save(created.model_copy(update={"handoff": "next"}), expected_revision=0)

    assert not (outside / (created.loop_id + ".json")).exists()


def test_atomic_save_replaces_snapshot_and_stale_revision_preserves_old_bytes(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    created = store.create("Build it", _budgets(), loop_id="f" * 32)
    path = tmp_path / ".forgeagent" / "loops" / (created.loop_id + ".json")
    old = path.read_bytes()
    saved = store.save(created.model_copy(update={"handoff": "next"}), expected_revision=0)

    assert saved.revision == 1
    assert path.read_bytes() != old
    before_stale = path.read_bytes()
    with pytest.raises(LoopCheckpointError):
        store.save(created, expected_revision=0)
    assert path.read_bytes() == before_stale


def test_overlapping_saves_from_distinct_stores_commit_once(tmp_path: Path, monkeypatch):
    first = LoopCheckpointStore(str(tmp_path))
    checkpoint = first.create("Build it", _budgets(), loop_id="9" * 32)
    second = LoopCheckpointStore(str(tmp_path))
    barrier = threading.Barrier(2)
    first_load = first.load
    second_load = second.load

    def stale_read(load, loop_id):
        current = load(loop_id)
        barrier.wait(timeout=2)
        return current

    monkeypatch.setattr(first, "load", lambda loop_id: stale_read(first_load, loop_id))
    monkeypatch.setattr(second, "load", lambda loop_id: stale_read(second_load, loop_id))
    results = []

    def save(store, handoff):
        try:
            results.append(
                store.save(checkpoint.model_copy(update={"handoff": handoff}), expected_revision=0)
            )
        except LoopCheckpointError as error:
            results.append(error)

    threads = [
        threading.Thread(target=save, args=(first, "first")),
        threading.Thread(target=save, args=(second, "second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert sum(isinstance(result, LoopCheckpoint) for result in results) == 1
    assert sum(isinstance(result, LoopCheckpointError) for result in results) == 1
    assert first_load(checkpoint.loop_id).revision == 1


def test_overlapping_creates_from_distinct_stores_commit_once(tmp_path: Path):
    both_writing = threading.Event()
    write_count = 0
    count_lock = threading.Lock()

    class CoordinatedStore(LoopCheckpointStore):
        def _write(self, name, checkpoint):
            nonlocal write_count
            with count_lock:
                write_count += 1
                if write_count == 2:
                    both_writing.set()
            both_writing.wait(timeout=0.5)
            super()._write(name, checkpoint)

    first = CoordinatedStore(str(tmp_path))
    second = CoordinatedStore(str(tmp_path))
    start = threading.Barrier(2)
    results = []

    def create(store):
        start.wait(timeout=2)
        try:
            results.append(store.create("Build it", _budgets(), loop_id="a" * 32))
        except LoopCheckpointError as error:
            results.append(error)

    threads = [threading.Thread(target=create, args=(store,)) for store in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert sum(isinstance(result, LoopCheckpoint) for result in results) == 1
    assert sum(isinstance(result, LoopCheckpointError) for result in results) == 1


def test_store_rejects_symlink_checkpoint_lock(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("Build it", _budgets(), loop_id="b" * 32)
    lock_path = tmp_path / ".forgeagent" / "loops" / f".{checkpoint.loop_id}.lock"
    outside = tmp_path / "outside-lock"
    outside.write_text("unchanged")
    if lock_path.exists():
        lock_path.unlink()
    lock_path.symlink_to(outside)

    with pytest.raises(LoopCheckpointError):
        store.save(checkpoint.model_copy(update={"handoff": "next"}), expected_revision=0)

    assert outside.read_text() == "unchanged"
    assert store.load(checkpoint.loop_id).revision == 0


@pytest.mark.skipif(loop_module.fcntl is None, reason="flock is POSIX-only")
def test_checkpoint_lock_failure_preserves_revision(tmp_path: Path, monkeypatch):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("Build it", _budgets(), loop_id="e" * 32)
    before = (tmp_path / ".forgeagent" / "loops" / f"{checkpoint.loop_id}.json").read_bytes()

    def fail_lock(*args, **kwargs):
        raise OSError("lock unavailable")

    monkeypatch.setattr(loop_module.fcntl, "flock", fail_lock)

    with pytest.raises(LoopCheckpointError):
        store.save(checkpoint.model_copy(update={"handoff": "next"}), expected_revision=0)

    path = tmp_path / ".forgeagent" / "loops" / f"{checkpoint.loop_id}.json"
    assert path.read_bytes() == before


def test_checkpoint_create_fails_closed_without_platform_locking(tmp_path: Path, monkeypatch):
    store = LoopCheckpointStore(str(tmp_path))
    monkeypatch.setattr("forgeagent.loop.fcntl", None)

    with pytest.raises(LoopCheckpointError):
        store.create("Build it", _budgets(), loop_id="f" * 32)

    assert not (tmp_path / ".forgeagent" / "loops" / ("f" * 32 + ".json")).exists()


def test_distinct_checkpoint_ids_do_not_share_one_process_lock(tmp_path: Path):
    both_writing = threading.Event()
    write_count = 0
    count_lock = threading.Lock()

    class CoordinatedStore(LoopCheckpointStore):
        def _write(self, name, checkpoint):
            nonlocal write_count
            with count_lock:
                write_count += 1
                if write_count == 2:
                    both_writing.set()
            both_writing.wait(timeout=1)
            super()._write(name, checkpoint)

    first = CoordinatedStore(str(tmp_path))
    second = CoordinatedStore(str(tmp_path))
    start = threading.Barrier(2)

    def create(store, loop_id):
        start.wait(timeout=2)
        store.create("Build it", _budgets(), loop_id=loop_id)

    threads = [
        threading.Thread(target=create, args=(first, "c" * 32)),
        threading.Thread(target=create, args=(second, "d" * 32)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert both_writing.is_set()
    assert not any(thread.is_alive() for thread in threads)


def test_atomic_save_failure_preserves_old_bytes_and_cleans_temp(tmp_path: Path, monkeypatch):
    store = LoopCheckpointStore(str(tmp_path))
    created = store.create("Build it", _budgets(), loop_id="1" * 32)
    path = tmp_path / ".forgeagent" / "loops" / (created.loop_id + ".json")
    old = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda source, destination: (_ for _ in ()).throw(OSError()))

    with pytest.raises(LoopCheckpointError):
        store.save(created.model_copy(update={"handoff": "next"}), expected_revision=0)

    assert path.read_bytes() == old
    assert list(path.parent.glob(".loop-checkpoint.*")) == []


def test_checkpoint_tool_commits_before_return_and_refuses_completed_item_deletion(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("Build it", _budgets(), loop_id="2" * 32)
    tool = CheckpointTool(store, checkpoint)
    result = tool.run(CheckpointArgs(completed_items=["done"], handoff="next"), None)

    assert result.success is True
    assert store.load(checkpoint.loop_id).completed_items == ("done",)
    assert result.detail == "checkpoint saved revision=1 completed=1 open_questions=0"
    refused = tool.run(CheckpointArgs(completed_items=[]), None)
    assert refused.success is False
    assert refused.detail == "Checkpoint rejected: completed items cannot be removed"


def test_checkpoint_tool_bounds_detail_and_registry_isolated_from_default(tmp_path: Path):
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("Build it", _budgets(), loop_id="3" * 32)
    registry = build_loop_registry(store=store, checkpoint=checkpoint, with_mcp=False, skills=None)

    assert registry.get("Checkpoint") is not None
    assert "Checkpoint" not in default_registry().arg_schemas()
    # This bypasses parser validation so the Tool's defensive failure remains bounded.
    outcome = registry.get("Checkpoint").run(
        CheckpointArgs.model_construct(handoff="x" * (MAX_HANDOFF_CHARS + 1)), None
    )
    assert outcome.success is False
    assert len(outcome.detail) < 100
