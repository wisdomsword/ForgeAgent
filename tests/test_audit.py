"""Audit event serialization, rotation, and fail-open behavior."""

from __future__ import annotations

import json
import threading

import pytest
from pydantic import ValidationError

from forgeagent.audit import AuditEvent, JsonlAuditSink


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
