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
from forgeagent.external_actions import ExternalActionReceiptStore
from forgeagent.http_action_approvals import HttpActionApprovalStore
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_server import (
    ForgeRequestHandler,
    HttpError,
    _ForgeHttpServer,
    _parse_content_length,
    _parse_task_request,
    _parse_task_submission,
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


@pytest.mark.parametrize("mode", ["task", "duo", "triad"])
def test_submission_parser_accepts_strict_task_and_collaboration_modes(mode):
    goal, options = _parse_task_submission({"goal": "verify output", "mode": mode})

    assert goal == "verify output"
    assert options == {"mode": mode}


@pytest.mark.parametrize(
    "body",
    [
        {"goal": "x", "mode": "unknown"},
        {"goal": "x", "mode": "duo", "evaluator_model": "owned-by-client"},
        {"goal": "x", "mode": "triad", "max_rejections": 9},
        {"goal": "x", "mode": "triad", "triad_plan_policy": "preauthorize"},
    ],
)
def test_submission_parser_rejects_unknown_and_server_owned_collaboration_fields(body):
    with pytest.raises(HttpError, match="invalid_request"):
        _parse_task_submission(body)


def test_submission_parser_accepts_loop_collaboration_mode_only_on_create():
    body = {
        "goal": "implement parser.py",
        "mode": "loop",
        "collaboration_mode": "triad",
        "token_budget": 100,
        "max_rounds": 10,
        "wall_clock_seconds": 60,
        "max_consecutive_failures": 3,
    }

    goal, options = _parse_task_submission(body)

    assert goal == "implement parser.py"
    assert options["collaboration_mode"] == "triad"
    with pytest.raises(HttpError, match="invalid_request"):
        _parse_task_submission(
            {"mode": "loop", "resume_loop_id": "a" * 32, "collaboration_mode": "triad"}
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


@pytest.fixture
def action_control_server(tmp_path):
    sink = RecordingSink()
    config = HttpServiceConfig(
        token="test-token",
        max_workers=1,
        max_queue=4,
        max_records=8,
    )
    approval_store = HttpActionApprovalStore(max_records=config.max_records, audit_sink=sink)
    receipt_store = ExternalActionReceiptStore(str(tmp_path), audit_sink=sink)
    service = TaskService(
        factory=lambda _record: FakeTask(_outcome()),
        config=config,
        audit_sink=sink,
        approval_store=approval_store,
        receipt_store=receipt_store,
    )
    server = SimpleNamespace(config=config, task_service=service, audit_sink=sink)
    try:
        yield server, approval_store, receipt_store, service, sink
    finally:
        service.shutdown(1.0)
        receipt_store.close()


@pytest.mark.parametrize(
    "body",
    [
        {"goal": "task"},
        {"goal": "task", "mode": "duo"},
        {
            "goal": "loop",
            "mode": "loop",
            "token_budget": 10,
            "max_rounds": 2,
            "wall_clock_seconds": 30,
            "max_consecutive_failures": 1,
        },
        {"mode": "loop", "resume_loop_id": "b" * 32},
    ],
)
def test_task_parser_accepts_bounded_approval_ids_without_putting_them_in_options(
    body,
):
    approval_ids = ["a" * 32]
    extended = body | {"approval_ids": approval_ids}

    goal, options, parsed_ids = _parse_task_request(extended)
    legacy_goal, legacy_options = _parse_task_submission(extended)

    assert parsed_ids == ("a" * 32,)
    assert "approval_ids" not in options
    assert (legacy_goal, legacy_options) == (goal, options)


@pytest.mark.parametrize(
    "approval_ids",
    [
        [],
        ["a" * 32, "a" * 32],
        ["A" * 32],
        ["a" * 31],
        [123],
        [f"{index:032x}" for index in range(17)],
    ],
)
def test_task_parser_rejects_invalid_approval_id_lists(approval_ids) -> None:
    with pytest.raises(HttpError, match="invalid_request"):
        _parse_task_request({"goal": "task", "approval_ids": approval_ids})


def test_http_approval_issue_query_revoke_and_task_claim(action_control_server) -> None:
    server, _approval_store, _receipt_store, service, sink = action_control_server
    issue_body = {
        "action_type": "mcp",
        "server": "github",
        "tool": "create_issue",
        "request_digest": "f" * 64,
        "mode": "allow_once",
        "expires_in_seconds": 60,
    }

    status, issued, raw = _request_via_handler(server, "POST", "/action-approvals", body=issue_body)
    assert status == 201
    assert issued is not None
    approval_id = issued["approval_id"]
    assert issued["status"] == "issued"
    assert "github" in issued["scope"]
    assert "create_issue" in issued["scope"]
    assert b"test-token" not in raw

    status, queried, _raw = _request_via_handler(server, "GET", f"/action-approvals/{approval_id}")
    assert status == 200
    assert queried == issued

    status, submitted, _raw = _request_via_handler(
        server,
        "POST",
        "/tasks",
        body={"goal": "use exact action", "approval_ids": [approval_id]},
    )
    assert status == 202
    assert submitted is not None
    assert "approval" not in repr(submitted)
    service.wait(str(submitted["task_id"]), timeout=1.0)

    second_status, second, _raw = _request_via_handler(
        server, "POST", "/action-approvals", body=issue_body
    )
    assert second_status == 201
    second_id = second["approval_id"]
    status, revoked, _raw = _request_via_handler(
        server, "POST", f"/action-approvals/{second_id}/revoke", body={}
    )
    assert status == 200
    assert revoked["status"] == "revoked"
    assert {event.event_type for event in sink.events} >= {
        "http.approval_issue",
        "http.approval_query",
        "http.approval_revoke",
    }


@pytest.mark.parametrize(
    "body",
    [
        {},
        {
            "action_type": "mcp",
            "server": "github",
            "tool": "create_issue",
            "request_digest": "f" * 64,
            "mode": "allow_once",
            "expires_in_seconds": 0,
        },
        {
            "action_type": "mcp",
            "server": "github",
            "tool": "create_issue",
            "request_digest": "f" * 64,
            "mode": "allow_forever",
            "expires_in_seconds": 60,
        },
        {
            "action_type": "mcp",
            "server": "github",
            "tool": "create_issue",
            "request_digest": "f" * 64,
            "mode": "allow_once",
            "expires_in_seconds": 60,
            "goal": "smuggled authority",
        },
    ],
)
def test_http_approval_issue_rejects_non_exact_body(action_control_server, body) -> None:
    server, *_rest = action_control_server
    status, response, _raw = _request_via_handler(server, "POST", "/action-approvals", body=body)
    assert status == 400
    assert response["error"]["kind"] == "invalid_request"


def test_http_approval_routes_use_fixed_not_found_unavailable_and_auth_errors(
    action_control_server,
) -> None:
    server, *_rest = action_control_server
    status, response, raw = _request_via_handler(server, "GET", f"/action-approvals/{'0' * 32}")
    assert status == 404
    assert response["error"]["kind"] == "approval_not_found"
    assert b"ApprovalNotFound" not in raw

    status, response, _raw = _request_via_handler(
        server,
        "POST",
        "/tasks",
        body={"goal": "invalid claim", "approval_ids": ["0" * 32]},
    )
    assert status == 409
    assert response["error"]["kind"] == "approval_unavailable"

    status, response, _raw = _request_via_handler(
        server, "GET", f"/action-approvals/{'0' * 32}", token="wrong"
    )
    assert status == 401
    assert response["error"]["kind"] == "unauthorized"


def _retained_task(service: TaskService, goal: str) -> TaskRecord:
    record = service.submit(goal, {})
    service.wait(record.task_id, timeout=1.0)
    return record


def _unknown_receipt(
    store: ExternalActionReceiptStore,
    task_id: str,
    marker: str,
):
    receipt = store.create_prepared(
        task_id=task_id,
        server_label="github",
        tool_label="create_issue",
        request_digest=marker * 64,
    )
    receipt = store.mark_dispatched(receipt.action_id, receipt.revision)
    return store.mark_unknown(receipt.action_id, receipt.revision, "result_unknown")


def test_http_receipt_list_and_confirm_are_task_scoped_without_evidence_leak(
    action_control_server,
) -> None:
    server, _approval_store, receipt_store, service, sink = action_control_server
    owner = _retained_task(service, "owner")
    other = _retained_task(service, "other")
    receipt = _unknown_receipt(receipt_store, owner.task_id, "a")

    status, listed, raw = _request_via_handler(server, "GET", f"/tasks/{owner.task_id}/receipts")
    assert status == 200
    assert listed == {"receipts": [service.list_task_receipts(owner.task_id)[0]]}
    assert b"owner" not in raw

    status, hidden, _raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{other.task_id}/receipts/{receipt.action_id}/resolve",
        body={
            "expected_revision": receipt.revision,
            "decision": "confirmed",
            "evidence": "provider event private-evidence-123",
        },
    )
    assert status == 404
    assert hidden["error"]["kind"] == "receipt_not_found"

    status, stale, _raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{owner.task_id}/receipts/{receipt.action_id}/resolve",
        body={
            "expected_revision": receipt.revision - 1,
            "decision": "confirmed",
            "evidence": "provider event private-evidence-123",
        },
    )
    assert status == 409
    assert stale["error"]["kind"] == "receipt_conflict"

    status, resolved, raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{owner.task_id}/receipts/{receipt.action_id}/resolve",
        body={
            "expected_revision": receipt.revision,
            "decision": "confirmed",
            "evidence": "provider event private-evidence-123",
        },
    )
    assert status == 200
    assert resolved["resolution"] == "confirmed"
    assert resolved["evidence_code"] == "provided"
    assert b"private-evidence-123" not in raw
    assert {event.event_type for event in sink.events} >= {
        "http.receipt_list",
        "http.receipt_resolve",
    }


@pytest.mark.parametrize("decision", ["abandoned", "retry_approved"])
def test_http_receipt_closure_never_dispatches(action_control_server, decision) -> None:
    server, _approval_store, receipt_store, service, _sink = action_control_server
    owner = _retained_task(service, "owner")
    receipt = _unknown_receipt(receipt_store, owner.task_id, "b")
    dispatch_count = 0

    status, resolved, _raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{owner.task_id}/receipts/{receipt.action_id}/resolve",
        body={"expected_revision": receipt.revision, "decision": decision},
    )

    assert status == 200
    assert resolved["resolution"] == decision
    assert dispatch_count == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": -1, "decision": "abandoned"},
        {"expected_revision": 1, "decision": "retry"},
        {"expected_revision": 1, "decision": "confirmed"},
        {"expected_revision": 1, "decision": "confirmed", "evidence": ""},
        {"expected_revision": 1, "decision": "abandoned", "evidence": 42},
        {"expected_revision": 1, "decision": "abandoned", "extra": True},
    ],
)
def test_http_receipt_resolve_rejects_invalid_body(action_control_server, body) -> None:
    server, _approval_store, _receipt_store, service, _sink = action_control_server
    owner = _retained_task(service, "owner")
    status, response, _raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{owner.task_id}/receipts/{'0' * 32}/resolve",
        body=body,
    )
    assert status == 400
    assert response["error"]["kind"] == "invalid_request"


def test_http_receipt_routes_use_fixed_task_receipt_and_store_errors(
    action_control_server,
) -> None:
    server, _approval_store, receipt_store, service, _sink = action_control_server
    status, response, _raw = _request_via_handler(server, "GET", f"/tasks/{'0' * 32}/receipts")
    assert status == 404
    assert response["error"]["kind"] == "not_found"

    owner = _retained_task(service, "owner")
    status, response, raw = _request_via_handler(
        server,
        "POST",
        f"/tasks/{owner.task_id}/receipts/{'0' * 32}/resolve",
        body={"expected_revision": 0, "decision": "abandoned"},
    )
    assert status == 404
    assert response["error"]["kind"] == "receipt_not_found"
    assert b"ReceiptError" not in raw

    receipt_store.close()
    status, response, _raw = _request_via_handler(server, "GET", f"/tasks/{owner.task_id}/receipts")
    assert status == 503
    assert response["error"]["kind"] == "receipt_unavailable"


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


@pytest.mark.parametrize(
    ("body", "expected_goal", "expected_options"),
    [
        ({"goal": "ordinary"}, "ordinary", {}),
        (
            {
                "goal": "durable",
                "mode": "loop",
                "token_budget": 200,
                "max_rounds": 12,
                "wall_clock_seconds": 30.5,
                "max_consecutive_failures": 2,
            },
            "durable",
            {
                "mode": "loop",
                "token_budget": 200,
                "max_rounds": 12,
                "wall_clock_seconds": 30.5,
                "max_consecutive_failures": 2,
            },
        ),
        (
            {"mode": "loop", "resume_loop_id": "a" * 32},
            "",
            {"mode": "loop", "resume_loop_id": "a" * 32},
        ),
    ],
)
def test_submit_accepts_exact_task_new_loop_and_resume_loop_schemas(
    body, expected_goal, expected_options
):
    config = HttpServiceConfig(token="test-token")
    sink = RecordingSink()
    submissions = []

    class Service:
        audit_degraded = False

        def submit_view(self, goal, options):
            submissions.append((goal, options))
            return {
                "task_id": "b" * 32,
                "mode": options.get("mode", "task"),
                "status": "queued",
                "reason": None,
                "detail": None,
                "round_count": 0,
                "usage": None,
                "audit_degraded": False,
            }

        def mark_audit_degraded(self):
            return None

    server = SimpleNamespace(config=config, task_service=Service(), audit_sink=sink)
    status, response, _raw = _request_via_handler(server, "POST", "/tasks", body=body)

    assert status == 202
    assert response["mode"] == expected_options.get("mode", "task")
    assert submissions == [(expected_goal, expected_options)]


@pytest.mark.parametrize(
    "body",
    [
        {"goal": "loop", "mode": "loop", "token_budget": 10},
        {
            "goal": "loop",
            "mode": "loop",
            "token_budget": True,
            "max_rounds": 2,
            "wall_clock_seconds": 3.0,
            "max_consecutive_failures": 1,
        },
        {
            "goal": "loop",
            "mode": "loop",
            "token_budget": 10,
            "max_rounds": False,
            "wall_clock_seconds": 3.0,
            "max_consecutive_failures": 1,
        },
        {
            "goal": "loop",
            "mode": "loop",
            "token_budget": 10,
            "max_rounds": 2,
            "wall_clock_seconds": float("inf"),
            "max_consecutive_failures": 1,
        },
        {"mode": "loop", "resume_loop_id": "A" * 32},
        {"mode": "loop", "resume_loop_id": "a" * 32, "goal": "override"},
        {"mode": "loop", "resume_loop_id": "a" * 32, "token_budget": 10},
        {"goal": "loop", "mode": "loop", "token_budget": 10, "tier": "trusted"},
        {"goal": "loop", "checkpoint_path": "/tmp/private"},
        {"goal": "loop", "credentials": "secret"},
    ],
)
def test_submit_rejects_invalid_or_security_sensitive_loop_bodies(body):
    config = HttpServiceConfig(token="test-token")
    sink = RecordingSink()
    service = SimpleNamespace(
        audit_degraded=False,
        mark_audit_degraded=lambda: None,
        submit_view=lambda *_args: pytest.fail("invalid body must not submit"),
    )
    server = SimpleNamespace(config=config, task_service=service, audit_sink=sink)

    status, response, _raw = _request_via_handler(server, "POST", "/tasks", body=body)

    assert status == 400
    assert response["error"]["kind"] == "invalid_request"


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
    monkeypatch.setattr(
        cli_module,
        "JsonlAuditSink",
        lambda *_args, **_kwargs: pytest.fail("invalid policy must not create an audit sink"),
    )
    monkeypatch.setattr(
        cli_module,
        "resolve_cli_identity",
        lambda **_kwargs: pytest.fail("invalid policy must not resolve identity"),
    )
    monkeypatch.setattr(
        cli_module,
        "build_mcp_manager",
        lambda _console: pytest.fail("invalid policy must not start MCP"),
    )
    monkeypatch.setattr(
        cli_module,
        "TaskService",
        lambda **_kwargs: pytest.fail("invalid policy must not create a task service"),
    )

    with pytest.raises(cli_module.HttpStartupError, match="context"):
        cli_module.serve_http(config_path, client_factory=client_factory, console=SimpleNamespace())

    assert len(clients) == 1
    assert clients[0].closed is True


def test_serve_real_client_uses_one_validated_registry_snapshot_for_tasks(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        "token: test-token\nno_identity: true\ncontext:\n  image_token_reserve: 512\n"
    )
    snapshot = object()
    load_calls = []
    validation_snapshots = []
    build_snapshots = []
    captured = {}

    def fake_load_registry():
        load_calls.append(None)
        return snapshot

    def fake_validate_context_policy(model, registry, context_config):
        validation_snapshots.append((model, registry, context_config))

    def fake_real_builder(model, env=None, *, registry=None):
        build_snapshots.append((model, registry))
        return MockClient(script=[])

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink, **_kwargs):
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

    monkeypatch.setattr(cli_module, "load_registry", fake_load_registry)
    monkeypatch.setattr(cli_module, "_validate_context_policy", fake_validate_context_policy)
    monkeypatch.setattr(cli_module, "build_real_client", fake_real_builder)
    monkeypatch.setattr(cli_module, "JsonlAuditSink", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **_kwargs: None)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(http_server_module, "create_http_server", lambda *_args: FakeServer())

    cli_module.serve_http(
        config_path,
        client_factory=cli_module.build_real_client,
        console=SimpleNamespace(print=lambda *_args: None),
        once=True,
    )

    assert load_calls == [None]
    assert validation_snapshots == [
        ("claude-sonnet-5", snapshot, ContextConfig(image_token_reserve=512))
    ]
    assert build_snapshots == []
    task = captured["factory"](SimpleNamespace(task_id="registry-snapshot"))
    try:
        assert build_snapshots == [("claude-sonnet-5", snapshot)]
        assert task._context_policy._config is captured["config"].context_config
    finally:
        task.close()


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
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink, **_kwargs):
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
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
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


def test_serve_factory_selects_server_owned_new_and_resumed_loop(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    allowed_root = tmp_path / "project"
    allowed_root.mkdir()
    config_path = tmp_path / "http.yaml"
    config_path.write_text(f"token: test-token\nno_identity: true\nallowed_root: {allowed_root}\n")
    captured = {}
    loop_calls = []

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink, **_kwargs):
            captured["factory"] = factory

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

    class FakeRunner:
        pass

    def fake_create(**kwargs):
        loop_calls.append(("create", kwargs))
        return FakeRunner()

    def fake_resume(**kwargs):
        loop_calls.append(("resume", kwargs))
        return FakeRunner()

    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module.LoopRunner, "create", fake_create)
    monkeypatch.setattr(cli_module.LoopRunner, "resume", fake_resume)
    monkeypatch.setattr(http_server_module, "create_http_server", lambda *_args: FakeServer())

    cli_module.serve_http(
        config_path,
        client_factory=lambda _model: MockClient(script=[]),
        console=SimpleNamespace(print=lambda *_args: None),
        once=True,
    )

    task_id = "b" * 32
    created = captured["factory"](
        SimpleNamespace(
            task_id=task_id,
            goal="durable",
            options={
                "mode": "loop",
                "token_budget": 200,
                "max_rounds": 12,
                "wall_clock_seconds": 30.5,
                "max_consecutive_failures": 2,
            },
        )
    )
    resumed = captured["factory"](
        SimpleNamespace(
            task_id="c" * 32,
            goal="",
            options={"mode": "loop", "resume_loop_id": "a" * 32},
        )
    )

    assert isinstance(created, FakeRunner)
    assert isinstance(resumed, FakeRunner)
    create_kwargs = loop_calls[0][1]
    assert loop_calls[0][0] == "create"
    assert create_kwargs["allowed_root"] == str(allowed_root)
    assert create_kwargs["goal"] == "durable"
    assert create_kwargs["task_id"] == task_id
    assert create_kwargs["trigger"] == "http"
    assert create_kwargs["collaboration_mode"] == "single"
    assert create_kwargs["collaboration_mode_source"] == "default"
    assert create_kwargs["budgets"].model_dump() == {
        "max_rounds": 12,
        "token_budget": 200,
        "wall_clock_seconds": 30.5,
        "max_consecutive_failures": 2,
    }
    assert loop_calls[1][0] == "resume"
    assert loop_calls[1][1]["allowed_root"] == str(allowed_root)
    assert loop_calls[1][1]["loop_id"] == "a" * 32
    assert "goal" not in loop_calls[1][1]
    assert "budgets" not in loop_calls[1][1]

    for index, collaboration_mode in enumerate(("single", "duo", "triad"), start=2):
        explicit = captured["factory"](
            SimpleNamespace(
                task_id="d" * 32,
                goal=f"explicit {collaboration_mode}",
                options={
                    "mode": "loop",
                    "collaboration_mode": collaboration_mode,
                    "token_budget": 200,
                    "max_rounds": 12,
                    "wall_clock_seconds": 30.5,
                    "max_consecutive_failures": 2,
                },
            )
        )
        assert isinstance(explicit, FakeRunner)
        explicit_kwargs = loop_calls[index][1]
        assert explicit_kwargs["collaboration_mode"] == collaboration_mode
        assert explicit_kwargs["collaboration_mode_source"] == "explicit"


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
