"""POSIX process-level admission tests for durable collaboration and memory state."""

from __future__ import annotations

import multiprocessing
import os
import random
import signal
import stat
import time
from pathlib import Path

import pytest

import forgeagent.memory as memory_module
from forgeagent.collaboration import CollaborationError, CollaborationStore
from forgeagent.memory import MemoryManager
from forgeagent.protocol import MemoryCandidate

pytestmark = pytest.mark.skipif(
    memory_module.fcntl is None or not hasattr(signal, "SIGKILL"),
    reason="process locking and SIGKILL are POSIX-only",
)

_COLLABORATION_ID = "a" * 32
_PROCESS_TIMEOUT_SECONDS = 10


def _save_same_revision(
    root: str,
    start: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue,
    rounds: int,
) -> None:
    store = CollaborationStore(root)
    try:
        if not start.wait(timeout=5):
            result_queue.put(("timeout", rounds))
            return
        state = store.load(_COLLABORATION_ID)
        try:
            saved = store.save(state.model_copy(update={"rounds": rounds}), expected_revision=0)
        except CollaborationError as error:
            result_queue.put(("error", str(error)))
        else:
            result_queue.put(("saved", saved.revision))
    finally:
        store.close()


def _apply_project_memory(
    root: str,
    start: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue,
    index: int,
) -> None:
    if not start.wait(timeout=5):
        result_queue.put((index, "timeout"))
        return
    result = MemoryManager(root).apply(
        MemoryCandidate(
            scope="project",
            kind="fact",
            key=f"process-{index}",
            content=f"value-{index}",
        )
    )
    result_queue.put((index, result.status))


def _hold_collaboration_lock(
    root: str,
    ready: multiprocessing.synchronize.Event,
) -> None:
    store = CollaborationStore(root)
    try:
        with store._state_lock(_COLLABORATION_ID):
            ready.set()
            time.sleep(60)
    finally:
        store.close()


def _hold_memory_lock(root: str, ready: multiprocessing.synchronize.Event) -> None:
    manager = MemoryManager(root)
    with manager._project_lock():
        ready.set()
        time.sleep(60)


def _join_all(processes: list[multiprocessing.Process]) -> None:
    for process in processes:
        process.join(timeout=_PROCESS_TIMEOUT_SECONDS)
    alive = [process for process in processes if process.is_alive()]
    for process in alive:
        process.terminate()
    for process in alive:
        process.join(timeout=2)
    assert not alive, f"storage child processes did not exit: {[process.pid for process in alive]}"


def _kill_and_join(process: multiprocessing.Process) -> None:
    assert process.pid is not None
    os.kill(process.pid, signal.SIGKILL)
    process.join(timeout=_PROCESS_TIMEOUT_SECONDS)
    assert not process.is_alive()
    assert process.exitcode == -signal.SIGKILL


def test_collaboration_same_revision_process_race_commits_exactly_once(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    for attempt in range(3):
        root = tmp_path / f"collaboration-race-{attempt}"
        root.mkdir()
        store = CollaborationStore(str(root))
        store.create("Build an artifact", "duo", collaboration_id=_COLLABORATION_ID)
        store.close()
        start = context.Event()
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_save_same_revision,
                args=(str(root), start, result_queue, rounds),
            )
            for rounds in range(1, 5)
        ]
        for process in processes:
            process.start()
        start.set()
        _join_all(processes)
        results = [result_queue.get(timeout=2) for _ in processes]

        assert results.count(("saved", 1)) == 1
        assert (
            sum(result == ("error", "collaboration revision is stale") for result in results)
            == len(processes) - 1
        )
        persisted = CollaborationStore(str(root)).load(_COLLABORATION_ID)
        assert persisted.revision == 1
        assert persisted.rounds in range(1, 5)


def test_memory_concurrent_process_updates_preserve_every_distinct_key(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_apply_project_memory, args=(str(tmp_path), start, result_queue, index)
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    start.set()
    _join_all(processes)
    results = [result_queue.get(timeout=2) for _ in processes]

    assert {status for _index, status in results} == {"accepted"}
    manager = MemoryManager(str(tmp_path))
    manager.load()
    rendered = manager.render()
    for index in range(4):
        assert f"process-{index}" in rendered
        assert f"value-{index}" in rendered


def test_collaboration_lock_is_released_after_lock_holder_sigkill(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id=_COLLABORATION_ID)
    store.close()
    ready = context.Event()
    holder = context.Process(target=_hold_collaboration_lock, args=(str(tmp_path), ready))
    holder.start()
    assert ready.wait(timeout=5)
    _kill_and_join(holder)

    recovered = CollaborationStore(str(tmp_path)).save(
        created.model_copy(update={"rounds": 1}), expected_revision=0
    )
    assert recovered.revision == 1


def test_memory_lock_is_released_after_lock_holder_sigkill(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    holder = context.Process(target=_hold_memory_lock, args=(str(tmp_path), ready))
    holder.start()
    assert ready.wait(timeout=5)
    _kill_and_join(holder)

    result = MemoryManager(str(tmp_path)).apply(
        MemoryCandidate(scope="project", kind="fact", key="recovered", content="after-kill")
    )
    assert result.status == "accepted"
    manager = MemoryManager(str(tmp_path))
    manager.load()
    assert "recovered" in manager.render()


def test_seeded_writer_sigkill_leaves_memory_parseable_and_recoverable(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    seed = 51051
    start = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_apply_project_memory, args=(str(tmp_path), start, result_queue, index)
        )
        for index in range(3)
    ]
    for process in processes:
        process.start()
    start.set()
    victim = random.Random(seed).choice(processes)
    _kill_and_join(victim)
    _join_all([process for process in processes if process is not victim])

    manager = MemoryManager(str(tmp_path))
    manager.load()
    recovered = manager.apply(
        MemoryCandidate(scope="project", kind="fact", key="post-kill", content="recoverable")
    )
    assert recovered.status in {"accepted", "replaced"}, f"seed={seed}"
    manager.load()
    assert "post-kill" in manager.render(), f"seed={seed}"


def test_memory_atomic_replace_syncs_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = MemoryManager(str(tmp_path))
    events: list[tuple[str, bool | None]] = []
    original_fsync = memory_module.os.fsync
    original_replace = memory_module.os.replace

    def record_fsync(descriptor: int) -> None:
        events.append(("fsync", stat.S_ISDIR(os.fstat(descriptor).st_mode)))
        original_fsync(descriptor)

    def record_replace(source: str, destination: Path) -> None:
        events.append(("replace", None))
        original_replace(source, destination)

    monkeypatch.setattr(memory_module.os, "fsync", record_fsync)
    monkeypatch.setattr(memory_module.os, "replace", record_replace)

    manager._atomic_write_bytes(b"storage admission test\n")

    replace_index = events.index(("replace", None))
    assert ("fsync", True) in events[replace_index + 1 :]
