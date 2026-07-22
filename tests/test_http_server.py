from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from types import SimpleNamespace

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.client import MockClient
from forgeagent.context import ContextConfig
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_server import (
    ForgeRequestHandler,
    HttpError,
    _ForgeHttpServer,
    _parse_content_length,
    create_http_server,
)
from forgeagent.http_task_service import ServiceCapacityError, TaskRecord, TaskService
from forgeagent.models import ModelCapability
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


def test_forge_http_server_marks_first_serve_loop_iteration_entered():
    server = object.__new__(_ForgeHttpServer)
    server.serve_entered = threading.Event()

    server.service_actions()

    assert server.serve_entered.is_set()


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


def _request_via_handler(
    server: object,
    method: str,
    path: str,
    *,
    body: object | None = None,
    token: str = "test-token",
) -> tuple[int, dict[str, object] | None, bytes]:
    """Run the real request handler over a socketpair without binding a port."""
    request_body = b""
    headers = [
        f"{method} {path} HTTP/1.0",
        "Host: localhost",
        f"Authorization: Bearer {token}",
        "Connection: close",
    ]
    if body is not None:
        request_body = json.dumps(body).encode()
        headers.extend(
            [
                "Content-Type: application/json",
                f"Content-Length: {len(request_body)}",
            ]
        )
    request = ("\r\n".join(headers) + "\r\n\r\n").encode() + request_body
    client_socket, handler_socket = socket.socketpair()
    handler_errors: list[BaseException] = []

    def run_handler() -> None:
        try:
            ForgeRequestHandler(handler_socket, ("127.0.0.1", 1), server)
        except BaseException as error:
            handler_errors.append(error)

    handler_thread = threading.Thread(
        target=run_handler,
        daemon=True,
    )
    handler_thread.start()
    try:
        client_socket.settimeout(2.0)
        client_socket.sendall(request)
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = client_socket.recv(65536)
            if not chunk:
                break
            raw += chunk
        if b"\r\n\r\n" in raw:
            header_bytes, body_bytes = raw.split(b"\r\n\r\n", 1)
            content_length = next(
                int(line.split(b":", 1)[1].strip())
                for line in header_bytes.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            while len(body_bytes) < content_length:
                chunk = client_socket.recv(65536)
                if not chunk:
                    break
                body_bytes += chunk
            raw = header_bytes + b"\r\n\r\n" + body_bytes
    finally:
        client_socket.close()
        handler_thread.join(timeout=2.0)
        handler_socket.close()
    assert not handler_thread.is_alive()
    assert handler_errors == []
    header_bytes, body_bytes = raw.split(b"\r\n\r\n", 1)
    status = int(header_bytes.split(b" ", 2)[1])
    parsed = json.loads(body_bytes) if body_bytes else None
    return status, parsed, raw


def _wait_for_terminal_via_handler(
    server: object,
    task_id: str,
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while True:
        status, view, _raw = _request_via_handler(server, "GET", f"/tasks/{task_id}")
        assert status == 200
        assert view is not None
        if view["status"] not in {"queued", "running"}:
            return view
        if time.monotonic() >= deadline:
            pytest.fail(f"task {task_id} did not reach a terminal state before timeout")
        time.sleep(0.01)


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
    try:
        server = create_http_server(config, service)
    except PermissionError as error:
        service.shutdown(1.0)
        pytest.skip(f"loopback bind unavailable in this environment: {error}")
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


def test_concurrent_http_handler_submissions_keep_task_records_isolated():
    release = threading.Event()

    class BlockingTask(FakeTask):
        def run(self, goal, *, cancel_event=None):
            assert release.wait(2.0)
            return super().run(goal, cancel_event=cancel_event)

    config = HttpServiceConfig(
        bind_host="127.0.0.1",
        port=0,
        token="test-token",
        max_workers=4,
        max_queue=8,
        max_records=16,
    )
    sink = RecordingSink()
    service = TaskService(
        factory=lambda _record: BlockingTask(_outcome()),
        config=config,
        audit_sink=sink,
    )

    server = SimpleNamespace(config=config, task_service=service, audit_sink=sink)

    def submit(index: int) -> tuple[int, dict[str, object]]:
        status, response, _raw = _request_via_handler(
            server,
            "POST",
            "/tasks",
            body={"goal": f"task-{index}"},
        )
        assert response is not None
        return status, response

    try:
        with ThreadPoolExecutor(max_workers=8) as clients:
            responses = list(clients.map(submit, range(8)))
        assert all(status == 202 for status, _payload in responses)
        task_ids = [str(payload["task_id"]) for _status, payload in responses]
        assert len(set(task_ids)) == 8

        nonterminal_views = [
            _request_via_handler(server, "GET", f"/tasks/{task_id}")[1] for task_id in task_ids
        ]
        assert all(
            view is not None and view["status"] in {"queued", "running"}
            for view in nonterminal_views
        )

        release.set()
        views = [_wait_for_terminal_via_handler(server, task_id) for task_id in task_ids]
        assert [view["task_id"] for view in views] == task_ids
        assert all(view["reason"] == Termination.COMPLETED for view in views)
    finally:
        release.set()
        service.shutdown(2.0)


def test_task_service_shutdown_leaves_no_owned_worker_or_manager_thread():
    baseline_threads = set(threading.enumerate())
    manager_closed = threading.Event()

    class Manager:
        def close(self):
            manager_closed.set()

    config = HttpServiceConfig(
        token="test-token",
        max_workers=2,
        max_queue=2,
        max_records=4,
    )
    service = TaskService(
        factory=lambda _record: FakeTask(_outcome()),
        config=config,
        shared_mcp_manager=Manager(),
    )
    task_ids = [service.submit("go", {}).task_id for _ in range(2)]
    for task_id in task_ids:
        service.wait(task_id, timeout=2.0)
    service.shutdown(2.0)

    deadline = time.monotonic() + 2.0
    owned_threads = []
    while time.monotonic() < deadline:
        owned_threads = [
            thread
            for thread in threading.enumerate()
            if thread not in baseline_threads
            and thread.name.startswith(("forgeagent-task", "forgeagent-mcp"))
        ]
        if not owned_threads:
            break
        time.sleep(0.01)
    assert manager_closed.is_set()
    assert owned_threads == []


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
        (
            {"Content-Type": "application/json"},
            {"goal": "go", "context": {"utilization_ratio": 1}},
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


def test_serve_rejects_invalid_context_before_listener_creation(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text("token: test-token\ncontext:\n  utilization_ratio: 8\n")
    factory_called = False

    def client_factory(_model):
        nonlocal factory_called
        factory_called = True
        return MockClient(script=[])

    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *_args, **_kwargs: pytest.fail("invalid context must not create a listener"),
    )

    with pytest.raises(cli_module.HttpStartupError, match="context"):
        cli_module.serve_http(config_path, client_factory=client_factory, console=SimpleNamespace())

    assert factory_called is False


def test_serve_rejects_resolved_mixed_context_override_before_listener_creation(
    monkeypatch, tmp_path
):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text("token: test-token\ncontext:\n  tool_result_max_tokens: 71\n")
    capability = ModelCapability(
        model_id="injected",
        context_window=1_000,
        max_output_tokens=100,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )
    clients = []

    class CloseTrackingClient(MockClient):
        def __init__(self):
            super().__init__(script=[], capability=capability)
            self.closed = False

        def close(self):
            self.closed = True

    def client_factory(_model):
        client = CloseTrackingClient()
        clients.append(client)
        return client

    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *_args, **_kwargs: pytest.fail("invalid policy must not create a listener"),
    )

    with pytest.raises(cli_module.HttpStartupError, match="context"):
        cli_module.serve_http(config_path, client_factory=client_factory, console=SimpleNamespace())

    assert len(clients) == 1
    assert clients[0].closed is True


def test_serve_task_factory_passes_only_server_context_to_task(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        "token: test-token\nno_identity: true\ncontext:\n  image_token_reserve: 512\n"
    )
    captured = {}
    clients = []

    class CloseTrackingClient(MockClient):
        def __init__(self):
            super().__init__(script=[])
            self.closed = False

        def close(self):
            self.closed = True

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink):
            captured["factory"] = factory
            captured["config"] = config

        def shutdown(self, timeout):
            return None

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def serve_forever(self, poll_interval):
            return None

        def shutdown(self):
            return None

        def server_close(self):
            return None

    def client_factory(_model):
        client = CloseTrackingClient()
        clients.append(client)
        return client

    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda _console: None)
    monkeypatch.setattr(http_server_module, "create_http_server", lambda *_args: FakeServer())

    cli_module.serve_http(
        config_path,
        client_factory=client_factory,
        console=SimpleNamespace(print=lambda *_args: None),
        once=True,
    )

    assert len(clients) == 1
    assert clients[0].closed is True
    task = captured["factory"](SimpleNamespace(task_id="server-owned-context"))
    try:
        assert task._context_policy._config is captured["config"].context_config
        assert task._context_policy._config == ContextConfig(image_token_reserve=512)
    finally:
        task.close()
        task._client.close()


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


def test_capacity_maps_to_429_without_leaking_exception(monkeypatch):
    config = HttpServiceConfig(token="test-token")
    sink = RecordingSink()
    service = TaskService(
        factory=lambda _record: FakeTask(_outcome()),
        config=config,
        audit_sink=sink,
    )
    server = SimpleNamespace(config=config, task_service=service, audit_sink=sink)

    def reject(_goal, _options):
        raise ServiceCapacityError

    monkeypatch.setattr(service, "submit_view", reject)
    try:
        status, payload, raw = _request_via_handler(
            server,
            "POST",
            "/tasks",
            body={"goal": "go"},
        )
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
    finally:
        service.shutdown(1.0)


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
    handler.headers = _HeaderStub({"Authorization": ["Bearer secret"]})
    handler.server = SimpleNamespace(
        config=SimpleNamespace(token="secret"), task_service=service, audit_sink=sink
    )
    captured: list[tuple[int, str]] = []
    handler._send_error = lambda status, kind: captured.append((status, kind))
    handler.send_error(501, "unsupported")
    assert captured == [(405, "method_not_allowed")]


@pytest.mark.parametrize(
    ("authorization", "expected_status", "expected_event"),
    [
        (None, b"401", "http.auth_failure"),
        ("Bearer wrong", b"401", "http.auth_failure"),
        ("Bearer t\u00f6ken", b"401", "http.auth_failure"),
        ("Bearer secret", b"405", "http.reject"),
    ],
)
def test_unknown_method_authenticates_before_405(authorization, expected_status, expected_event):
    headers = b""
    if authorization is not None:
        headers = f"Authorization: {authorization}\r\n".encode()
    response, events = _raw_response(b"FROB /tasks HTTP/1.1\r\n" + headers + b"\r\n")
    assert expected_status in response.split(b"\r\n", 1)[0]
    assert [event.event_type for event in events] == [expected_event]


def test_head_authenticated_405_has_no_body_and_correct_content_length():
    response, events = _raw_response(
        b"HEAD /tasks HTTP/1.1\r\nAuthorization: Bearer secret\r\n\r\n"
    )
    headers, body = response.split(b"\r\n\r\n", 1)
    assert b"405" in headers.split(b"\r\n", 1)[0]
    assert body == b""
    content_length = next(
        line for line in headers.split(b"\r\n") if line.startswith(b"Content-Length:")
    )
    assert int(content_length.split(b":", 1)[1]) > 0
    assert [event.event_type for event in events] == ["http.reject"]


def test_head_auth_failure_has_no_body():
    response, events = _raw_response(b"HEAD /tasks HTTP/1.1\r\nAuthorization: Bearer wrong\r\n\r\n")
    headers, body = response.split(b"\r\n\r\n", 1)
    assert b"401" in headers.split(b"\r\n", 1)[0]
    assert body == b""
    assert [event.event_type for event in events] == ["http.auth_failure"]


def test_unknown_method_repeated_authorization_is_one_auth_failure():
    response, events = _raw_response(
        b"FROB /tasks HTTP/1.1\r\nAuthorization: Bearer secret\r\n"
        b"Authorization: Bearer secret\r\n\r\n"
    )
    assert b"401" in response.split(b"\r\n", 1)[0]
    assert [event.event_type for event in events] == ["http.auth_failure"]


def test_submit_uses_atomic_service_view_without_exposing_record():
    class Service:
        audit_degraded = False

        def submit_view(self, goal, options):
            assert goal == "go"
            assert options == {}
            return {"task_id": "a" * 32, "status": "queued"}

        def mark_audit_degraded(self):
            raise AssertionError("audit should not fail")

    config = HttpServiceConfig(token="test-token")
    sink = RecordingSink()
    handler = object.__new__(ForgeRequestHandler)
    handler.server = SimpleNamespace(config=config, task_service=Service(), audit_sink=sink)
    payload = b'{"goal":"go"}'
    handler.headers = _HeaderStub({"Content-Length": [str(len(payload))]})
    handler.rfile = BytesIO(payload)
    captured = []
    handler._send_json = lambda status, response: captured.append((status, response))
    handler._submit()
    assert captured == [(202, {"task_id": "a" * 32, "status": "queued"})]


def test_atomic_submit_view_returns_queued_before_zero_ttl_worker_can_expire_record():
    release = threading.Event()

    class BlockingTask(FakeTask):
        def run(self, goal, *, cancel_event=None):
            release.wait(1.0)
            return super().run(goal, cancel_event=cancel_event)

    config = HttpServiceConfig(
        token="test-token",
        max_workers=1,
        max_queue=1,
        max_records=4,
        terminal_ttl_seconds=0,
    )
    service = TaskService(factory=lambda _record: BlockingTask(_outcome()), config=config)
    try:
        view = service.submit_view("go", {})
        assert view["status"] == "queued"
        assert view["task_id"]
    finally:
        release.set()
        service.shutdown(1.0)


def test_service_snapshot_calls_record_projection_under_registry_lock(monkeypatch):
    config = HttpServiceConfig(token="test-token", max_workers=1, max_queue=1, max_records=4)
    service = TaskService(factory=lambda _record: FakeTask(_outcome()), config=config)
    record = service.submit("go", {})
    observed: list[bool] = []
    original = TaskRecord.public_view

    def checked(self, **kwargs):
        observed.append(service._lock.locked())
        return original(self, **kwargs)

    monkeypatch.setattr(TaskRecord, "public_view", checked)
    try:
        service.snapshot(record.task_id)
        assert observed and all(observed)
    finally:
        service.shutdown(1.0)


def test_sticky_sink_degraded_marks_service_even_when_emit_returns_true():
    class StickySink:
        degraded = True

        def emit(self, event):
            return True

    marked = []
    service = SimpleNamespace(mark_audit_degraded=lambda: marked.append(True), audit_degraded=False)
    handler = object.__new__(ForgeRequestHandler)
    handler.server = SimpleNamespace(task_service=service, audit_sink=StickySink())
    handler._audit("http.query", task_id="a" * 32, result_status="ok")
    assert marked == [True]


@pytest.mark.parametrize(
    ("method", "path", "body", "event_type", "write_error"),
    [
        ("POST", "/tasks", b'{"goal":"go"}', "http.submit", BrokenPipeError),
        ("GET", "/tasks/" + "a" * 32, None, "http.query", ConnectionResetError),
        ("POST", "/tasks/" + "a" * 32 + "/cancel", b"{}", "http.cancel", BrokenPipeError),
    ],
)
def test_client_disconnect_after_success_does_not_add_rejection(
    method, path, body, event_type, write_error
):
    class Service:
        audit_degraded = False

        def submit_view(self, goal, options):
            return {"task_id": "a" * 32, "status": "queued", "audit_degraded": False}

        def query(self, task_id):
            return {"task_id": task_id, "status": "running", "audit_degraded": False}

        def cancel(self, task_id):
            return {"task_id": task_id, "status": "cancelled", "audit_degraded": False}

        def mark_audit_degraded(self):
            raise AssertionError("audit should not fail")

    sink = RecordingSink()
    handler = object.__new__(ForgeRequestHandler)
    values = {"Authorization": ["Bearer secret"]}
    if body is not None:
        values["Content-Length"] = [str(len(body))]
    handler.headers = _HeaderStub(values)
    handler.rfile = BytesIO(body or b"")
    handler.path = path
    handler.close_connection = False
    handler.server = SimpleNamespace(
        config=SimpleNamespace(token="secret", max_body_bytes=64 * 1024),
        task_service=Service(),
        audit_sink=sink,
    )

    def disconnect(_status, _payload):
        raise write_error("client disconnected")

    handler._send_json = disconnect
    handler._dispatch(method)
    assert [event.event_type for event in sink.events] == [event_type]
    assert handler.close_connection is True


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
