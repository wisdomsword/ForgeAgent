from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from types import SimpleNamespace

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_server import (
    ForgeRequestHandler,
    HttpError,
    _parse_content_length,
    create_http_server,
)
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
    assert [event.event_type for event in sink.events].count("http.auth_failure") == 1
    assert [event.event_type for event in sink.events].count("http.reject") == 0
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
    assert [event.event_type for event in sink.events].count("http.capacity_rejection") == 1
    assert [event.event_type for event in sink.events].count("http.reject") == 0


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


@pytest.mark.parametrize("value", ["", "+12", " 12", "12 ", "１２", "1\t2"])
def test_content_length_accepts_only_ascii_decimal(value):
    with pytest.raises(HttpError, match="invalid_length"):
        _parse_content_length([value])


def test_repeated_content_length_is_rejected_even_when_values_match():
    with pytest.raises(HttpError, match="invalid_length"):
        _parse_content_length(["12", "12"])


def test_short_request_body_is_rejected_without_json_decode():
    class Headers:
        def get_content_type(self):
            return "application/json"

        def get_all(self, name, failobj=None):
            return ["12"] if name == "Content-Length" else (failobj or [])

        def get(self, name, default=None):
            return default

    handler = object.__new__(ForgeRequestHandler)
    handler.headers = Headers()
    handler.rfile = BytesIO(b'{"goal":')
    handler.server = SimpleNamespace(config=SimpleNamespace(max_body_bytes=64 * 1024))
    with pytest.raises(HttpError, match="invalid_length"):
        handler._read_json()


def test_timed_out_request_body_is_a_safe_length_error():
    class TimedOutReader:
        def read(self, _length):
            raise TimeoutError("slow client")

    handler = object.__new__(ForgeRequestHandler)
    handler.headers = _HeaderStub({"Content-Length": ["12"]})
    handler.rfile = TimedOutReader()
    handler.server = SimpleNamespace(config=SimpleNamespace(max_body_bytes=64 * 1024))
    with pytest.raises(HttpError, match="invalid_length"):
        handler._read_json()


def test_handler_sets_finite_connection_read_timeout(monkeypatch):
    class Connection:
        timeout = None

        def settimeout(self, value):
            self.timeout = value

    connection = Connection()
    monkeypatch.setattr(
        BaseHTTPRequestHandler,
        "setup",
        lambda handler: setattr(handler, "connection", connection),
    )
    handler = object.__new__(ForgeRequestHandler)
    handler.setup()
    assert connection.timeout is not None
    assert 0 < connection.timeout <= 30


def test_audit_failure_marks_service_public_projection_degraded():
    class FailingSink:
        degraded = True

        def emit(self, event):
            return False

    config = HttpServiceConfig(token="test-token", max_workers=1, max_queue=1, max_records=4)
    service = TaskService(
        factory=lambda _record: FakeTask(_outcome()), config=config, audit_sink=FailingSink()
    )
    handler = object.__new__(ForgeRequestHandler)
    handler.server = SimpleNamespace(task_service=service, audit_sink=FailingSink())
    try:
        handler._audit("http.submit", task_id="a" * 32, result_status="accepted")
        record = service.submit("goal", {})
        view = service.query(record.task_id)
        assert view["audit_degraded"] is True
    finally:
        service.shutdown(1.0)


class _HeaderStub:
    def __init__(self, values: dict[str, list[str]]) -> None:
        self.values = values

    def get_all(self, name, failobj=None):
        return self.values.get(name, failobj or [])

    def get(self, name, default=None):
        values = self.values.get(name)
        return values[0] if values else default

    def get_content_type(self):
        return "application/json"


def _raw_response(request: bytes) -> tuple[bytes, list[AuditEvent]]:
    sink = RecordingSink()
    service = SimpleNamespace(
        mark_audit_degraded=lambda: None,
        audit_degraded=False,
        query=lambda _task_id: pytest.fail("request must be rejected before query"),
    )
    handler = object.__new__(ForgeRequestHandler)
    handler.rfile = BytesIO(request)
    handler.wfile = BytesIO()
    handler.server = SimpleNamespace(
        config=SimpleNamespace(token="secret", max_body_bytes=64 * 1024),
        task_service=service,
        audit_sink=sink,
    )
    handler.client_address = ("127.0.0.1", 1)
    handler.close_connection = True
    handler.handle_one_request()
    return handler.wfile.getvalue(), sink.events


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer \tsecret",
        "Bearer secret ",
        "Bearer secret\tvalue",
        "Bearer " + "x" * 4097,
        "Bearer t\u00f6ken",
    ],
)
def test_authorization_rejects_ambiguous_or_unsafe_token_before_compare(authorization):
    sink = RecordingSink()
    service = SimpleNamespace(mark_audit_degraded=lambda: None, audit_degraded=False)
    handler = object.__new__(ForgeRequestHandler)
    handler.headers = _HeaderStub({"Authorization": [authorization]})
    handler.server = SimpleNamespace(
        config=SimpleNamespace(token="secret"), task_service=service, audit_sink=sink
    )
    assert handler._authorized() is False


def test_repeated_authorization_is_rejected():
    handler = object.__new__(ForgeRequestHandler)
    handler.headers = _HeaderStub({"Authorization": ["Bearer secret", "Bearer secret"]})
    handler.server = SimpleNamespace(config=SimpleNamespace(token="secret"))
    assert handler._authorized() is False


def test_authentication_rejection_emits_exactly_one_lifecycle_event():
    sink = RecordingSink()
    service = SimpleNamespace(mark_audit_degraded=lambda: None, audit_degraded=False)
    handler = object.__new__(ForgeRequestHandler)
    handler.headers = _HeaderStub({"Authorization": ["Bearer wrong"]})
    handler.server = SimpleNamespace(
        config=SimpleNamespace(token="secret"), task_service=service, audit_sink=sink
    )
    handler.path = "/tasks/" + "a" * 32
    handler.close_connection = False
    handler._send_error = lambda _status, _kind: None
    handler._dispatch("GET")
    assert [event.event_type for event in sink.events] == ["http.auth_failure"]


@pytest.mark.parametrize("target", ["http://127.0.0.1/tasks", "//evil/tasks", "tasks", "*"])
def test_origin_form_rejects_absolute_or_malformed_targets(target):
    handler = object.__new__(ForgeRequestHandler)
    handler.path = target
    with pytest.raises(HttpError, match="invalid_target"):
        handler._origin_form_target()


@pytest.mark.parametrize(
    ("raw_request", "expected_status", "expected_kind"),
    [
        (
            b"GET /tasks/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa HTTP/1.1\r\n"
            b"Authorization: Bearer secret\r\nContent-Length: 1\r\n\r\nx",
            b"400",
            b"invalid_length",
        ),
        (
            b"FROB /tasks HTTP/1.1\r\nAuthorization: Bearer secret\r\n\r\n",
            b"405",
            b"method_not_allowed",
        ),
        (
            b"GET http://127.0.0.1/tasks HTTP/1.1\r\nAuthorization: Bearer secret\r\n\r\n",
            b"400",
            b"invalid_target",
        ),
        (
            b"GET //evil/tasks HTTP/1.1\r\nAuthorization: Bearer secret\r\n\r\n",
            b"400",
            b"invalid_target",
        ),
    ],
)
def test_raw_request_framing_method_and_origin_errors_are_json(
    raw_request, expected_status, expected_kind
):
    response, _events = _raw_response(raw_request)
    status_line, _, body = response.partition(b"\r\n\r\n")
    assert expected_status in status_line
    assert expected_kind in body
    assert b"text/html" not in response


def test_get_with_body_or_transfer_encoding_is_rejected():
    handler = object.__new__(ForgeRequestHandler)
    handler.headers = _HeaderStub({"Content-Length": ["1"]})
    with pytest.raises(HttpError, match="invalid_length"):
        handler._reject_unexpected_body()
    handler.headers = _HeaderStub({"Transfer-Encoding": ["chunked"]})
    with pytest.raises(HttpError, match="invalid_length"):
        handler._reject_unexpected_body()


def test_unknown_method_error_is_json_405_not_501():
    sink = RecordingSink()
    service = SimpleNamespace(mark_audit_degraded=lambda: None, audit_degraded=False)
    handler = object.__new__(ForgeRequestHandler)
    handler.close_connection = False
    handler.server = SimpleNamespace(task_service=service, audit_sink=sink)
    captured: list[tuple[int, str]] = []
    handler._send_error = lambda status, kind: captured.append((status, kind))
    handler.send_error(501, "unsupported")
    assert captured == [(405, "method_not_allowed")]


def test_failing_http_audit_marks_submit_query_and_cancel_responses_degraded():
    class FailingSink:
        degraded = True

        def emit(self, event):
            return False

    sink = FailingSink()
    config = HttpServiceConfig(token="test-token", max_workers=1, max_queue=2, max_records=4)
    service = TaskService(
        factory=lambda _record: FakeTask(_outcome()), config=config, audit_sink=sink
    )
    handler = object.__new__(ForgeRequestHandler)
    handler.server = SimpleNamespace(config=config, task_service=service, audit_sink=sink)
    responses: list[tuple[int, dict[str, object]]] = []
    handler._send_json = lambda status, payload: responses.append((status, payload))
    try:
        body = json.dumps({"goal": "go"}).encode()
        handler.headers = _HeaderStub({"Content-Length": [str(len(body))]})
        handler.rfile = BytesIO(body)
        handler._submit()
        task_id = responses[-1][1]["task_id"]
        handler._query(str(task_id))
        handler.headers = _HeaderStub({"Content-Length": ["2"]})
        handler.rfile = BytesIO(b"{}")
        handler._cancel(str(task_id))
        assert [response["audit_degraded"] for _, response in responses] == [True, True, True]
    finally:
        service.shutdown(1.0)
