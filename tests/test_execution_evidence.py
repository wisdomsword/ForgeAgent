from __future__ import annotations

import pytest
from pydantic import ValidationError

from forgeagent.execution_evidence import (
    ExecutionEvidence,
    ExecutionEvidenceRecorder,
    ProgramArtifact,
    ToolExecutionRecord,
    merge_execution_evidence,
    public_execution_evidence,
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
    assert ToolExecutionRecord(
        sequence=1, tool="Exec", status="failed", role="planner", attempt=1
    ).role == "planner"


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
        records=(
            ToolExecutionRecord(sequence=1, tool="Exec", status="succeeded"),
        )
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
