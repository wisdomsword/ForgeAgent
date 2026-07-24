"""Threat-boundary tests for durable collaboration snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forgeagent.collaboration import (
    MAX_STATE_BYTES,
    AcceptanceItem,
    CollaborationError,
    CollaborationStore,
    plan_digest,
)


def test_store_creates_loads_and_atomically_saves_private_state(tmp_path: Path):
    store = CollaborationStore(str(tmp_path))
    created = store.create("Build an artifact", "duo", collaboration_id="b" * 32)
    path = tmp_path / ".forgeagent" / "collaborations" / ("b" * 32 + ".json")

    assert store.load(created.collaboration_id) == created
    assert path.stat().st_mode & 0o777 == 0o600
    saved = store.save(created.model_copy(update={"rounds": 1}), expected_revision=0)
    assert saved.revision == 1
    assert json.loads(path.read_text())["revision"] == 1


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
