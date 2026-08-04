from __future__ import annotations

import os
import stat

import pytest
from pydantic import ValidationError

from forgeagent.execution_evidence import (
    ExecutionEvidence,
    ExecutionEvidenceRecorder,
    ProgramArtifact,
    ProgramArtifactPersistenceError,
    ProgramArtifactStore,
    ToolExecutionRecord,
    merge_execution_evidence,
    public_execution_evidence,
    resolve_local_artifact_path,
)


def test_recorder_keeps_attempt_order_and_first_128_records():
    recorder = ExecutionEvidenceRecorder()
    for index in range(130):
        recorder.append(
            tool=f"tool-{index}",
            success=index % 2 == 0,
            block_name=None,
            program_artifact=None,
            status=None,
        )
    snapshot = recorder.snapshot()
    assert [item.sequence for item in snapshot.records] == list(range(1, 129))
    assert snapshot.truncated is True
    assert snapshot.omitted_count == 2
    assert [item.status for item in snapshot.records[:2]] == ["succeeded", "failed"]


def test_program_artifact_local_path_is_excluded_from_nested_dump(tmp_path):
    artifact = ProgramArtifact(
        reference="execution-artifacts/" + "a" * 32 + "/programs/0001-main.py",
        local_path=tmp_path / "private" / "0001-main.py",
    )
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool="Exec",
                status="succeeded",
                block="main",
                artifact=artifact,
            ),
        )
    )
    dumped = evidence.model_dump(mode="json")
    assert "local_path" not in repr(dumped)
    assert str(tmp_path) not in repr(dumped)


def test_empty_envelope_has_stable_json_shape():
    assert ExecutionEvidence().model_dump(mode="json") == {
        "records": [],
        "truncated": False,
        "omitted_count": 0,
    }


def test_artifact_persistence_failure_overrides_success_and_has_no_artifact():
    recorder = ExecutionEvidenceRecorder()
    recorder.append(
        tool="Exec",
        success=True,
        block_name=None,
        program_artifact=None,
        status="artifact_persistence_failed",
    )
    record = recorder.snapshot().records[0]
    assert record.artifact is None
    with pytest.raises(ValidationError):
        ToolExecutionRecord(
            sequence=1,
            tool="Exec",
            status="artifact_persistence_failed",
            artifact=ProgramArtifact(
                reference="execution-artifacts/" + "a" * 32 + "/programs/0001-x.py"
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("sequence", -1), ("sequence", True), ("omitted_count", -1), ("omitted_count", True)],
)
def test_counts_reject_negative_values_and_bool_integers(field, value):
    if field == "sequence":
        with pytest.raises(ValidationError):
            ToolExecutionRecord(sequence=value, tool="Exec", status="failed")
    else:
        with pytest.raises(ValidationError):
            ExecutionEvidence(omitted_count=value)


def test_zero_sequence_and_attempt_are_valid_nonnegative_values():
    record = ToolExecutionRecord(
        sequence=0,
        tool="Exec",
        status="failed",
        role="planner",
        attempt=0,
    )
    assert record.sequence == 0
    assert record.attempt == 0


def test_origin_role_and_attempt_must_be_supplied_together():
    with pytest.raises(ValidationError):
        ToolExecutionRecord(sequence=1, tool="Exec", status="failed", role="planner")
    with pytest.raises(ValidationError):
        ToolExecutionRecord(sequence=1, tool="Exec", status="failed", attempt=1)
    assert (
        ToolExecutionRecord(
            sequence=1, tool="Exec", status="failed", role="planner", attempt=1
        ).role
        == "planner"
    )


def test_references_must_be_canonical_and_bounded():
    canonical = "execution-artifacts/" + "a" * 32 + "/programs/0001-main.py"
    assert ProgramArtifact(reference=canonical).reference == canonical
    invalid = [
        "../execution-artifacts/" + "a" * 32 + "/programs/0001-main.py",
        "execution-artifacts/" + "A" * 32 + "/programs/0001-main.py",
        "execution-artifacts/" + "a" * 31 + "/programs/0001-main.py",
        "execution-artifacts/" + "a" * 32 + "/programs/../main.py",
        "execution-artifacts/" + "a" * 32 + "/programs/main.txt",
    ]
    for reference in invalid:
        with pytest.raises(ValidationError):
            ProgramArtifact(reference=reference)
    with pytest.raises(ValidationError):
        ProgramArtifact(reference=canonical + "x" * 512)


def test_public_projection_masks_labels_control_characters_and_local_paths(tmp_path):
    secret = "known-secret-value"
    artifact = ProgramArtifact(
        reference="execution-artifacts/" + "a" * 32 + "/programs/0001-main.py",
        local_path=tmp_path / "private.py",
    )
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool=f"Exec {secret}\n",
                block=f"main\t{secret}",
                status="succeeded",
                artifact=artifact,
                iteration=2,
                role="generator",
                attempt=1,
            ),
        )
    )
    projected = public_execution_evidence(evidence, secret_values=[secret])
    item = projected.records[0]
    assert "REDACTED" in item.tool and secret not in item.tool
    assert "REDACTED" in (item.block or "") and secret not in (item.block or "")
    assert "\n" not in item.tool and "\t" not in (item.block or "")
    assert item.artifact is not None
    assert item.artifact.local_path is None
    assert projected.model_dump(mode="json")["records"][0]["artifact"] == {
        "reference": artifact.reference
    }


def test_public_projection_redacts_posix_and_windows_paths_but_keeps_artifact_reference():
    reference = "execution-artifacts/" + "a" * 32 + "/programs/0001-main.py"
    evidence = ExecutionEvidence(
        records=(
            ToolExecutionRecord(
                sequence=1,
                tool=f"Exec /Users/admin/private/tool.py C:\\Users\\admin\\private.py {reference}",
                block=f"block /tmp/private.py C:\\secret\\block.py {reference}",
                status="succeeded",
            ),
        )
    )

    projected = public_execution_evidence(evidence)
    item = projected.records[0]

    assert "/Users/admin/private/tool.py" not in item.tool
    assert "C:\\Users\\admin\\private.py" not in item.tool
    assert "/tmp/private.py" not in (item.block or "")
    assert "C:\\secret\\block.py" not in (item.block or "")
    assert reference in item.tool
    assert reference in (item.block or "")


def test_internal_record_masks_known_environment_secret(monkeypatch):
    secret = "environment-secret-value"
    monkeypatch.setenv("FORGE_TEST_TOKEN", secret)
    record = ToolExecutionRecord(
        sequence=1,
        tool=f"Exec {secret}",
        block=f"block {secret}",
        status="failed",
    )
    assert secret not in record.tool
    assert secret not in (record.block or "")
    assert "REDACTED" in record.tool


@pytest.mark.parametrize("iteration", [-1, True])
def test_merge_validates_added_origin_fields(iteration):
    incoming = ExecutionEvidence(
        records=(ToolExecutionRecord(sequence=1, tool="Exec", status="failed"),)
    )
    with pytest.raises(ValidationError):
        merge_execution_evidence(
            ExecutionEvidence(),
            incoming,
            iteration=iteration,
            role="planner",
            attempt=1,
        )


def test_label_bound_does_not_cut_escape_sequence():
    record = ToolExecutionRecord(
        sequence=1,
        tool=("a" * 126) + "\n",
        status="failed",
    )
    assert len(record.tool) <= 128
    assert not record.tool.endswith(("\\x", "\\u", "\\U"))


def test_public_projection_keeps_first_32_and_accumulates_omitted_count():
    evidence = ExecutionEvidence(
        records=tuple(
            ToolExecutionRecord(sequence=index, tool=f"tool-{index}", status="failed")
            for index in range(1, 41)
        ),
        truncated=True,
        omitted_count=3,
    )
    projected = public_execution_evidence(evidence)
    assert [item.sequence for item in projected.records] == list(range(1, 33))
    assert projected.truncated is True
    assert projected.omitted_count == 11


def test_merge_adds_origin_and_deduplicates_cumulative_role_records():
    current = ExecutionEvidence(
        records=(ToolExecutionRecord(sequence=1, tool="Exec", status="succeeded"),)
    )
    incoming = ExecutionEvidence(
        records=(
            ToolExecutionRecord(sequence=1, tool="Exec", status="succeeded"),
            ToolExecutionRecord(sequence=2, tool="Edit", status="failed"),
        )
    )
    merged = merge_execution_evidence(
        current,
        incoming,
        iteration=4,
        role="generator",
        attempt=2,
        dedupe_cumulative_roles=True,
    )
    assert [
        (item.sequence, item.tool, item.iteration, item.role, item.attempt)
        for item in merged.records
    ] == [
        (1, "Exec", None, None, None),
        (1, "Exec", 4, "generator", 2),
        (2, "Edit", 4, "generator", 2),
    ]

    duplicate = merge_execution_evidence(
        merged,
        incoming,
        iteration=4,
        role="generator",
        attempt=2,
        dedupe_cumulative_roles=True,
    )
    assert len(duplicate.records) == 3
    assert duplicate.omitted_count == merged.omitted_count


def test_merge_iteration_only_preserves_loop_origins_for_same_sequence():
    incoming = ExecutionEvidence(
        records=(ToolExecutionRecord(sequence=1, tool="Exec", status="succeeded"),)
    )

    first = merge_execution_evidence(ExecutionEvidence(), incoming, iteration=1)
    merged = merge_execution_evidence(first, incoming, iteration=2)

    origins = [(item.sequence, item.iteration, item.role, item.attempt) for item in merged.records]
    assert origins == [
        (1, 1, None, None),
        (1, 2, None, None),
    ]


def test_merge_public_bound_counts_only_unique_new_records():
    current = ExecutionEvidence(
        records=tuple(
            ToolExecutionRecord(
                sequence=index,
                tool=f"tool-{index}",
                status="failed",
                role="planner",
                attempt=1,
                iteration=1,
            )
            for index in range(1, 33)
        )
    )
    incoming = ExecutionEvidence(
        records=tuple(
            ToolExecutionRecord(sequence=index, tool=f"tool-{index}", status="failed")
            for index in range(33, 36)
        )
    )
    merged = merge_execution_evidence(
        current,
        incoming,
        iteration=2,
        role="planner",
        attempt=1,
        dedupe_cumulative_roles=True,
    )
    assert len(merged.records) == 32
    assert merged.omitted_count == 3
    assert merged.truncated is True


def test_program_store_persists_exact_utf8_bytes_with_private_modes(tmp_path):
    store = ProgramArtifactStore(tmp_path, execution_id="a" * 32)
    artifact = store.persist(block_name="Main block", language="python", code="print('中')\n")
    assert artifact.reference == (
        "execution-artifacts/" + "a" * 32 + "/programs/0001-main-block.py"
    )
    assert artifact.local_path is not None
    assert artifact.local_path.read_bytes() == "print('中')\n".encode()
    assert stat.S_IMODE(artifact.local_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(artifact.local_path.parent.stat().st_mode) == 0o700
    assert resolve_local_artifact_path(tmp_path, artifact.reference) == artifact.local_path
    store.close()
    assert artifact.local_path.exists()


def test_program_store_uses_bounded_host_generated_filename(tmp_path, monkeypatch):
    secret = "artifact-secret-value"
    monkeypatch.setenv("FORGE_ARTIFACT_TOKEN", secret)
    store = ProgramArtifactStore(tmp_path, execution_id="b" * 32)
    artifact = store.persist(
        block_name=f"../../路径/{secret}\n" + "x" * 100,
        language="python",
        code="pass\n",
    )
    assert artifact.local_path is not None
    assert artifact.local_path.suffix == ".py"
    assert artifact.local_path.name.startswith("0001-")
    assert len(artifact.local_path.stem.removeprefix("0001-")) <= 64
    assert secret not in artifact.local_path.name
    assert "/" not in artifact.local_path.name


def test_program_store_enforces_count_and_file_size_limits(tmp_path):
    count_store = ProgramArtifactStore(tmp_path, execution_id="c" * 32)
    for index in range(100):
        count_store.persist(block_name=str(index), language="python", code="")
    with pytest.raises(
        ProgramArtifactPersistenceError, match="^program artifact persistence failed$"
    ):
        count_store.persist(block_name="overflow", language="python", code="")

    size_store = ProgramArtifactStore(tmp_path, execution_id="d" * 32)
    size_store.persist(block_name="limit", language="python", code="x" * (1024 * 1024))
    with pytest.raises(ProgramArtifactPersistenceError):
        size_store.persist(block_name="overflow", language="python", code="x" * (1024 * 1024 + 1))


def test_program_store_enforces_total_size_limit(tmp_path):
    store = ProgramArtifactStore(tmp_path, execution_id="e" * 32)
    for index in range(8):
        store.persist(block_name=str(index), language="python", code="x" * (1024 * 1024))
    with pytest.raises(ProgramArtifactPersistenceError):
        store.persist(block_name="overflow", language="python", code="x")


@pytest.mark.parametrize(
    "symlink_level", [".forgeagent", "execution-artifacts", "execution-id", "programs"]
)
def test_program_store_rejects_symlinked_artifact_directories(tmp_path, symlink_level):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("safe")
    execution_id = "f" * 32
    if symlink_level == ".forgeagent":
        (tmp_path / ".forgeagent").symlink_to(outside, target_is_directory=True)
    elif symlink_level == "execution-artifacts":
        forgeagent = tmp_path / ".forgeagent"
        forgeagent.mkdir()
        (forgeagent / "execution-artifacts").symlink_to(outside, target_is_directory=True)
    elif symlink_level == "execution-id":
        artifacts = tmp_path / ".forgeagent" / "execution-artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / execution_id).symlink_to(outside, target_is_directory=True)
    else:
        parent = tmp_path / ".forgeagent" / "execution-artifacts" / execution_id
        parent.mkdir(parents=True)
        (parent / "programs").symlink_to(outside, target_is_directory=True)
    store = ProgramArtifactStore(tmp_path, execution_id=execution_id)
    with pytest.raises(ProgramArtifactPersistenceError):
        store.persist(block_name="main", language="python", code="pass\n")
    assert sentinel.read_text() == "safe"


def test_program_store_rejects_existing_non_private_artifact_directory(tmp_path):
    execution_id = "6" * 32
    programs = tmp_path / ".forgeagent" / "execution-artifacts" / execution_id / "programs"
    programs.mkdir(parents=True)
    for directory in (tmp_path / ".forgeagent", programs.parent.parent, programs.parent, programs):
        directory.chmod(0o700)
    programs.chmod(0o755)
    store = ProgramArtifactStore(tmp_path, execution_id=execution_id)
    with pytest.raises(ProgramArtifactPersistenceError):
        store.persist(block_name="main", language="python", code="pass\n")
    assert list(programs.iterdir()) == []


def test_program_store_cleans_temp_when_replace_fails(tmp_path, monkeypatch):
    store = ProgramArtifactStore(tmp_path, execution_id="1" * 32)

    def fail_replace(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(
        ProgramArtifactPersistenceError, match="^program artifact persistence failed$"
    ):
        store.persist(block_name="main", language="python", code="pass\n")
    assert list(store._programs_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["write", "fsync"])
def test_program_store_cleans_temp_when_write_or_fsync_fails(tmp_path, monkeypatch, operation):
    store = ProgramArtifactStore(tmp_path, execution_id="4" * 32)

    def fail(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(os, operation, fail)
    with pytest.raises(
        ProgramArtifactPersistenceError, match="^program artifact persistence failed$"
    ):
        store.persist(block_name="main", language="python", code="pass\n")
    assert list(store._programs_path.iterdir()) == []


def test_program_store_propagates_interrupt_after_cleaning_temp(tmp_path, monkeypatch):
    store = ProgramArtifactStore(tmp_path, execution_id="5" * 32)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "write", interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.persist(block_name="main", language="python", code="pass\n")
    assert list(store._programs_path.iterdir()) == []


def test_program_store_normalizes_uuid_execution_id(tmp_path):
    store = ProgramArtifactStore(
        tmp_path,
        execution_id="AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
    )
    artifact = store.persist(block_name="main", language="python", code="pass\n")
    assert artifact.reference.startswith("execution-artifacts/" + "a" * 32 + "/")


def test_program_store_removes_published_file_on_directory_rebind(tmp_path, monkeypatch):
    store = ProgramArtifactStore(tmp_path, execution_id="2" * 32)
    original = store._directories_unchanged
    calls = 0

    def rebound(programs_fd):
        nonlocal calls
        calls += 1
        return False if calls == 3 else original(programs_fd)

    monkeypatch.setattr(store, "_directories_unchanged", rebound)
    with pytest.raises(ProgramArtifactPersistenceError):
        store.persist(block_name="main", language="python", code="pass\n")
    assert list(store._programs_path.iterdir()) == []


def test_resolve_local_artifact_path_rejects_invalid_reference_and_symlink(tmp_path):
    store = ProgramArtifactStore(tmp_path, execution_id="3" * 32)
    artifact = store.persist(block_name="main", language="python", code="pass\n")
    assert resolve_local_artifact_path(tmp_path, "../outside.py") is None
    assert artifact.local_path is not None
    artifact.local_path.unlink()
    artifact.local_path.symlink_to(tmp_path / "outside.py")
    assert resolve_local_artifact_path(tmp_path, artifact.reference) is None


def test_resolve_local_artifact_path_rejects_directory_rebinding(tmp_path, monkeypatch):
    execution_id = "7" * 32
    store = ProgramArtifactStore(tmp_path, execution_id=execution_id)
    artifact = store.persist(block_name="main", language="python", code="trusted\n")
    assert artifact.local_path is not None
    programs = artifact.local_path.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / artifact.local_path.name).write_text("outside")
    original_open = os.open
    rebound = False

    def rebind_before_file_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal rebound
        if path == artifact.local_path.name and dir_fd is not None and not rebound:
            rebound = True
            programs.rename(programs.with_name("programs-original"))
            programs.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", rebind_before_file_open)
    assert resolve_local_artifact_path(tmp_path, artifact.reference) is None
