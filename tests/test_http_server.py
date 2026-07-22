from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_server import create_http_server
from forgeagent.http_task_service import ServiceCapacityError, TaskRecord, TaskService
from forgeagent.step import RoundResult, Termination
from forgeagent.task import TaskOutcome, TaskStatus


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.degraded = False

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


class FakeTask:
    def __init__(self, outcome: TaskOutcome) -> None:
        self._outcome = outcome
        self._client = SimpleNamespace(close=lambda: None)
        self._audit_sink = None

    def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
        assert goal
        assert cancel_event is not None
        return self._outcome

    def close(self) -> None:
        return None


def _outcome() -> TaskOutcome:
    return TaskOutcome(
        status=TaskStatus(completed=True, reason=Termination.COMPLETED),
        rounds=[RoundResult(text="private answer")],
    )


def _request(
    address: tuple[str, int],
    method: str,
    path: str,
    *,
    token: str | None = "test-token",
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object] | None, bytes]:
    connection = HTTPConnection(*address, timeout=3)
    request_headers = dict(headers or {})
    payload: bytes | None = None
    if body is not None and not isinstance(body, bytes):
        payload = json.dumps(body).encode()
        if "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        request_headers.setdefault("Content-Length", str(len(payload)))
    elif isinstance(body, bytes):
        payload = body
        request_headers.setdefault("Content-Length", str(len(payload)))
    if token is not None:
        request_headers.setdefault("Authorization", f"Bearer {token}")
    connection.request(method, path, body=payload, headers=request_headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    parsed = json.loads(raw) if raw else None
    return response.status, parsed, raw


@pytest.fixture
def running_server(tmp_path):
    sink = RecordingSink()
    config = HttpServiceConfig(
        bind_host="127.0.0.1",
        port=0,
        token="test-token",
        max_workers=1,
        max_queue=4,
        max_records=8,
        audit_path=tmp_path / "audit.jsonl",
    )

    def factory(_record: TaskRecord) -> FakeTask:
        return FakeTask(_outcome())

    service = TaskService(factory=factory, config=config, audit_sink=sink)
    server = create_http_server(config, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address, sink, service
    finally:
        server.shutdown()
        server.server_close()
        service.shutdown(1.0)
        thread.join(timeout=1.0)


def test_submit_query_cancel_and_auth(running_server):
    address, sink, _service = running_server
    private_goal = "private-request-body"
    status, submitted, _raw = _request(address, "POST", "/tasks", body={"goal": private_goal})
    assert status == 202
    assert submitted is not None
    task_id = submitted["task_id"]
    status, queried, raw = _request(address, "GET", f"/tasks/{task_id}")
    assert status == 200
    assert queried["task_id"] == task_id
    assert b"private answer" not in raw
    status, cancelled, _ = _request(address, "POST", f"/tasks/{task_id}/cancel", body={})
    assert status in {200, 202}
    assert cancelled["task_id"] == task_id
    status, error, _ = _request(address, "GET", f"/tasks/{task_id}", token="wrong")
    assert status == 401
    assert error == {"error": {"kind": "unauthorized", "detail": "Authentication required."}}
    assert {event.event_type for event in sink.events} >= {
        "http.submit",
        "http.query",
        "http.cancel",
        "http.auth_failure",
    }
    assert "test-token" not in repr(sink.events)
    assert private_goal not in repr(sink.events)


@pytest.mark.parametrize(
    ("headers", "body", "expected_status", "kind"),
    [
        ({"Content-Type": "text/plain"}, {"goal": "go"}, 415, "invalid_content_type"),
        (
            {"Content-Type": "application/json", "Content-Length": "-1"},
            {"goal": "go"},
            400,
            "invalid_length",
        ),
        ({"Content-Type": "application/json"}, [], 400, "invalid_json"),
        ({"Content-Type": "application/json"}, {"goal": ""}, 400, "invalid_request"),
        (
            {"Content-Type": "application/json"},
            {"goal": "go", "tier": "trusted"},
            400,
            "invalid_request",
        ),
    ],
)
def test_invalid_request_matrix(running_server, headers, body, expected_status, kind):
    address, _sink, _service = running_server
    status, payload, _ = _request(address, "POST", "/tasks", body=body, headers=headers)
    assert status == expected_status
    assert payload["error"]["kind"] == kind


def test_unknown_task_and_unknown_route_use_safe_errors(running_server):
    address, _sink, _service = running_server
    status, payload, _ = _request(address, "GET", "/tasks/not-retained")
    assert status == 404
    assert payload == {"error": {"kind": "not_found", "detail": "Task not found."}}
    status, payload, _ = _request(address, "GET", "/shutdown")
    assert status == 404
    assert payload["error"]["kind"] == "not_found"


def test_body_size_is_bounded(running_server):
    address, _sink, _service = running_server
    body = {"goal": "x" * 70_000}
    status, payload, _ = _request(address, "POST", "/tasks", body=body)
    assert status == 413
    assert payload["error"]["kind"] == "body_too_large"


def test_capacity_maps_to_429_without_leaking_exception(running_server, monkeypatch):
    address, sink, service = running_server

    def reject(_goal, _options):
        raise ServiceCapacityError

    monkeypatch.setattr(service, "submit", reject)
    status, payload, raw = _request(address, "POST", "/tasks", body={"goal": "go"})
    assert status == 429
    assert payload == {
        "error": {
            "kind": "capacity_exceeded",
            "detail": "Task service capacity is exhausted.",
        }
    }
    assert b"ServiceCapacityError" not in raw
    assert any(event.event_type == "http.capacity_rejection" for event in sink.events)


def test_server_does_not_expose_shutdown_method(running_server):
    address, _sink, _service = running_server
    status, payload, _ = _request(address, "POST", "/shutdown", body={})
    assert status == 404
    assert payload["error"]["kind"] == "not_found"


@pytest.mark.parametrize("token", ["", " ", "line\nbreak", "t\u00f6ken"])
def test_server_refuses_invalid_direct_config_before_binding(token):
    config = HttpServiceConfig(token=token)
    service = TaskService(factory=lambda _record: FakeTask(_outcome()), config=config)
    try:
        with pytest.raises(ValueError, match="token"):
            create_http_server(config, service)
    finally:
        service.shutdown(1.0)


def test_server_refuses_non_loopback_direct_config_before_binding():
    config = HttpServiceConfig(bind_host="0.0.0.0", token="test-token")
    service = TaskService(factory=lambda _record: FakeTask(_outcome()), config=config)
    try:
        with pytest.raises(ValueError, match="loopback"):
            create_http_server(config, service)
    finally:
        service.shutdown(1.0)
