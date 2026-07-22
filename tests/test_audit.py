"""Audit event serialization, rotation, and fail-open behavior."""

from __future__ import annotations

import json
import os
import stat
import threading

import pytest
from pydantic import ValidationError

from forgeagent.audit import AuditEvent, JsonlAuditSink
from forgeagent.client import MockClient
from forgeagent.executor import TrustedBackend
from forgeagent.models import AssistantMessage, Message, Role, TokenUsage
from forgeagent.runtime import Runtime
from forgeagent.step import Step


def _read_records(path):
    records = []
    for candidate in sorted(path.parent.glob(f"{path.name}*")):
        records.extend(
            json.loads(line) for line in candidate.read_text(encoding="utf-8").splitlines()
        )
    return records


def test_audit_event_is_immutable_and_has_stable_fields():
    event = AuditEvent(event_type="http.submit")

    with pytest.raises(ValidationError):
        event.event_type = "changed"

    assert event.timestamp.endswith("Z")
    assert event.operation_id
    assert event.risk_level == "low"
    assert event.parameters == {}
    assert event.result_status == "unknown"
    assert event.audit_degraded is False


def test_audit_event_masks_secret_and_never_serializes_raw_path(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(
        path,
        max_bytes=1024,
        retention_files=2,
        secret_values={"super-secret-token"},
    )

    assert sink.emit(
        AuditEvent(
            event_type="http.submit",
            task_id="t1",
            parameters={"token": "super-secret-token", "path": "/Users/a"},
        )
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(record)
    assert "super-secret-token" not in rendered
    assert "/Users/a" not in rendered
    assert record["parameters"]["token"] == "***REDACTED***"


def test_audit_serialization_uses_safe_fallback_for_unknown_values(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, secret_values=set())

    assert sink.emit(AuditEvent(event_type="tool.operation", parameters={"opaque": object()}))

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["parameters"]["opaque"] == "<unsupported:object>"


def test_recursive_event_data_writes_fixed_serialization_fallback(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, max_bytes=1_000, secret_values=set())
    event = AuditEvent(event_type="tool.operation", parameters={"detail": []})
    recursive = event.parameters["detail"]
    assert isinstance(recursive, list)
    recursive.append(recursive)

    assert sink.emit(event)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "event_type": "audit.logging_error",
        "result_status": "serialization_error",
    }


def test_audit_serialization_replaces_non_finite_numbers_and_strips_url_secrets(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, secret_values={"hidden-path"})

    assert sink.emit(
        AuditEvent(
            event_type="confirmation.decision",
            parameters={
                "score": float("nan"),
                "url": "https://user:pass@example.test/hidden-path?q=secret#fragment",
            },
        )
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["parameters"]["score"] == "<non-finite>"
    assert record["parameters"]["url"] == "https://example.test/***REDACTED***"
    assert "pass" not in json.dumps(record)
    assert "q=secret" not in json.dumps(record)


def test_audit_rotation_retains_bounded_files_and_marks_runtime_failure_degraded(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, max_bytes=180, retention_files=2, secret_values=set())
    for attempt in range(4):
        assert sink.emit(AuditEvent(event_type="llm.attempt", attempt=attempt))

    assert len(list(tmp_path.glob("audit.jsonl*"))) <= 2

    sink._path = tmp_path / "missing" / "audit.jsonl"
    assert sink.emit(AuditEvent(event_type="http.query")) is False
    assert sink.degraded is True


def test_audit_startup_tightens_current_and_rotated_file_permissions(tmp_path):
    path = tmp_path / "audit.jsonl"
    rotated = tmp_path / "audit.jsonl.1"
    path.write_text('{"event_type":"current"}\n', encoding="utf-8")
    rotated.write_text('{"event_type":"rotated"}\n', encoding="utf-8")
    path.chmod(0o644)
    rotated.chmod(0o644)

    JsonlAuditSink(path, max_bytes=1_000, retention_files=2, secret_values=set())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(rotated.stat().st_mode) == 0o600


def test_audit_rotation_and_active_recreation_keep_permissions_private(tmp_path):
    path = tmp_path / "audit.jsonl"
    previous_umask = os.umask(0)
    try:
        sink = JsonlAuditSink(path, max_bytes=180, retention_files=3, secret_values=set())
        for attempt in range(8):
            assert sink.emit(AuditEvent(event_type="llm.attempt", attempt=attempt))

        retained = list(tmp_path.glob("audit.jsonl*"))
        assert len(retained) == 3
        assert all(stat.S_IMODE(candidate.stat().st_mode) == 0o600 for candidate in retained)

        path.unlink()
        assert sink.emit(AuditEvent(event_type="http.query"))
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        os.umask(previous_umask)


def test_audit_startup_removes_stale_high_index_rotated_files(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"event_type":"current"}\n', encoding="utf-8")
    retained = tmp_path / "audit.jsonl.1"
    retained.write_text('{"event_type":"newest-rotation"}\n', encoding="utf-8")
    stale = tmp_path / "audit.jsonl.99"
    stale.write_text('{"event_type":"stale-rotation"}\n', encoding="utf-8")

    JsonlAuditSink(path, max_bytes=180, retention_files=2, secret_values=set())

    assert retained.exists()
    assert json.loads(retained.read_text(encoding="utf-8"))["event_type"] == "newest-rotation"
    assert not stale.exists()
    assert len(list(tmp_path.glob("audit.jsonl*"))) == 2


def test_audit_rotation_removes_stale_high_index_rotated_files(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"event_type": "current", "padding": "x" * 110}) + "\n",
        encoding="utf-8",
    )
    sink = JsonlAuditSink(path, max_bytes=180, retention_files=2, secret_values=set())
    stale = tmp_path / "audit.jsonl.99"
    stale.write_text('{"event_type":"stale-rotation"}\n', encoding="utf-8")

    assert sink.emit(AuditEvent(event_type="http.query"))

    assert not stale.exists()
    assert len(list(tmp_path.glob("audit.jsonl*"))) <= 2


def test_oversize_event_writes_bounded_parseable_fallback(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, max_bytes=180, retention_files=2, secret_values=set())

    assert sink.emit(AuditEvent(event_type="tool.operation", parameters={"detail": "x" * 10_000}))

    files = list(tmp_path.glob("audit.jsonl*"))
    assert files
    assert all(candidate.stat().st_size <= 180 for candidate in files)
    records = _read_records(path)
    assert records == [{"event_type": "audit.logging_error", "result_status": "oversize"}]


def test_startup_rotation_and_oversize_keep_every_retained_line_parseable(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"event_type":"existing"}\n' * 5, encoding="utf-8")
    sink = JsonlAuditSink(path, max_bytes=180, retention_files=2, secret_values=set())

    assert sink.emit(AuditEvent(event_type="llm.attempt", parameters={"detail": "x" * 2_000}))
    assert sink.emit(AuditEvent(event_type="http.query"))

    files = list(tmp_path.glob("audit.jsonl*"))
    assert len(files) <= 2
    assert all(candidate.stat().st_size <= 180 for candidate in files)
    assert all(
        isinstance(json.loads(line), dict)
        for candidate in files
        for line in candidate.read_text(encoding="utf-8").splitlines()
    )


def test_startup_discards_partial_json_line_before_append(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"event_type":"existing"}\n{"partial":', encoding="utf-8")

    sink = JsonlAuditSink(path, max_bytes=1_000, secret_values=set())
    assert sink.emit(AuditEvent(event_type="http.query"))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["event_type"] for record in records] == ["existing", "http.query"]


def test_audit_concurrent_appends_are_complete_json_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, max_bytes=1_000_000, secret_values=set())

    threads = [
        threading.Thread(
            target=sink.emit,
            args=(AuditEvent(event_type="tool.operation", operation_id=str(index)),),
        )
        for index in range(30)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = _read_records(path)
    assert len(records) == 30
    assert {record["operation_id"] for record in records} == {str(i) for i in range(30)}


@pytest.mark.parametrize(
    ("usage", "expected_rate"),
    [
        (TokenUsage(input_tokens=30, cached_tokens=10, total_prompt_tokens=40), 0.25),
        (TokenUsage(input_tokens=30, cached_tokens=10, total_prompt_tokens=None), None),
        (TokenUsage(input_tokens=30, cached_tokens=50, total_prompt_tokens=40), None),
    ],
)
def test_successful_llm_audit_records_cache_rate_without_changing_raw_usage(
    tmp_path, usage, expected_rate
):
    class RecordingSink:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)
            return True

    path = tmp_path / "audit.jsonl"
    reply = AssistantMessage(
        content="---\ntask_status:\n  completed: true\n---\n",
        usage=usage,
        stop_reason="end_turn",
    )
    recording_sink = RecordingSink()
    Step(
        MockClient(script=[reply]),
        TrustedBackend(),
        Runtime(),
        audit_sink=recording_sink,
    ).run(
        [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="goal"),
        ]
    )
    outcome = next(
        event
        for event in recording_sink.events
        if event.event_type == "llm.outcome" and event.result_status == "success"
    )
    assert outcome.parameters["usage"] == {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached_tokens": usage.cached_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }
    assert set(outcome.parameters["usage"]) == {
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
    }
    assert outcome.parameters["cache_hit_rate"] == expected_rate

    sink = JsonlAuditSink(path, secret_values=set())
    assert sink.emit(outcome)
    persisted = next(
        record for record in _read_records(path) if record["event_type"] == "llm.outcome"
    )
    assert persisted["parameters"]["cache_hit_rate"] == expected_rate
