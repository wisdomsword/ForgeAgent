"""Authenticated loopback HTTP adapter for the bounded task service."""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import math
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlsplit

from .audit import AuditEvent, AuditSink, emit_audit
from .http_action_approvals import (
    ApprovalCapacityError,
    ApprovalNotFoundError,
    ApprovalUnavailableError,
)
from .http_config import MAX_BEARER_TOKEN_LENGTH, HttpServiceConfig
from .http_task_service import (
    ReceiptServiceUnavailable,
    ServiceCapacityError,
    ServiceClosedError,
    TaskNotFound,
    TaskReceiptConflict,
    TaskReceiptNotFound,
    TaskService,
)

_logger = logging.getLogger(__name__)
_READ_TIMEOUT_SECONDS = 10.0
_TASK_PATH = re.compile(r"/tasks/([0-9a-f]{32})\Z")
_CANCEL_PATH = re.compile(r"/tasks/([0-9a-f]{32})/cancel\Z")
_APPROVAL_PATH = re.compile(r"/action-approvals/([0-9a-f]{32})\Z")
_APPROVAL_REVOKE_PATH = re.compile(r"/action-approvals/([0-9a-f]{32})/revoke\Z")
_RECEIPTS_PATH = re.compile(r"/tasks/([0-9a-f]{32})/receipts\Z")
_RECEIPT_RESOLVE_PATH = re.compile(r"/tasks/([0-9a-f]{32})/receipts/([0-9a-f]{32})/resolve\Z")
_LOOP_ID = re.compile(r"[0-9a-f]{32}\Z")
_APPROVAL_ID = re.compile(r"[0-9a-f]{32}\Z")
_NEW_LOOP_KEYS = frozenset(
    {
        "goal",
        "mode",
        "token_budget",
        "max_rounds",
        "wall_clock_seconds",
        "max_consecutive_failures",
    }
)
_NEW_COLLABORATIVE_LOOP_KEYS = _NEW_LOOP_KEYS | {"collaboration_mode"}
_TASK_MODE_KEYS = frozenset({"goal", "mode"})
_RESUME_LOOP_KEYS = frozenset({"mode", "resume_loop_id"})
_ERROR_DETAILS = {
    "unauthorized": "Authentication required.",
    "not_found": "Task not found.",
    "method_not_allowed": "Method not allowed.",
    "invalid_content_type": "Content-Type must be application/json.",
    "invalid_length": "A valid Content-Length is required.",
    "body_too_large": "Request body is too large.",
    "invalid_json": "Request body must be a JSON object.",
    "invalid_request": "Request body does not match the accepted schema.",
    "invalid_target": "Request target must use origin form.",
    "capacity_exceeded": "Task service capacity is exhausted.",
    "service_closed": "Task service is shutting down.",
    "approval_not_found": "Action approval not found.",
    "approval_unavailable": "Action approval is unavailable.",
    "approval_capacity": "Action approval capacity is exhausted.",
    "receipt_not_found": "External action receipt not found.",
    "receipt_conflict": "External action receipt state changed.",
    "receipt_unavailable": "External action receipt service is unavailable.",
    "internal_error": "Request failed.",
}


class HttpError(Exception):
    def __init__(self, status: int, kind: str) -> None:
        super().__init__(kind)
        self.status = status
        self.kind = kind


def _parse_content_length(values: list[str]) -> int | None:
    if not values:
        return None
    if len(values) != 1:
        raise HttpError(400, "invalid_length")
    raw = values[0]
    if not raw or not raw.isascii() or any(character < "0" or character > "9" for character in raw):
        raise HttpError(400, "invalid_length")
    try:
        return int(raw, 10)
    except ValueError:
        raise HttpError(400, "invalid_length") from None


class _ForgeHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, config: HttpServiceConfig, service: TaskService) -> None:
        self.address_family = socket.AF_INET6 if ":" in config.bind_host else socket.AF_INET
        self.config = config
        self.task_service = service
        self.audit_sink: AuditSink | None = getattr(service, "_audit_sink", None)
        self.serve_entered = threading.Event()
        super().__init__((config.bind_host, config.port), ForgeRequestHandler)

    def service_actions(self) -> None:
        self.serve_entered.set()


class ForgeRequestHandler(BaseHTTPRequestHandler):
    """Parse authenticated requests and delegate all task work to TaskService."""

    protocol_version = "HTTP/1.1"
    server: _ForgeHttpServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(_READ_TIMEOUT_SECONDS)

    def parse_request(self) -> bool:
        try:
            self._raw_request_target = self.raw_requestline.decode("iso-8859-1").split()[1]
        except (IndexError, UnicodeError):
            self._raw_request_target = ""
        return super().parse_request()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        self._dispatch("OPTIONS")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_CONNECT(self) -> None:
        self._dispatch("CONNECT")

    def do_TRACE(self) -> None:
        self._dispatch("TRACE")

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        del message, explain
        self.close_connection = True
        if code == 501:
            if not self._authorized():
                self._audit("http.auth_failure", result_status="denied")
                self._send_error(401, "unauthorized")
            else:
                self._audit("http.reject", result_status="method_not_allowed")
                self._send_error(405, "method_not_allowed")
            return
        self._audit("http.reject", result_status="invalid_request")
        self._send_error(code, "invalid_request")

    def log_message(self, format: str, *args: object) -> None:
        _logger.debug("HTTP request completed")

    def _dispatch(self, method: str) -> None:
        try:
            if not self._authorized():
                self._audit("http.auth_failure", result_status="denied")
                raise HttpError(401, "unauthorized")
            path = self._origin_form_target()
            if method != "POST":
                self._reject_unexpected_body()
            if path.query or path.fragment:
                raise HttpError(404, "not_found")
            if method == "POST" and path.path == "/tasks":
                self._submit()
                return
            if method == "POST" and path.path == "/action-approvals":
                self._issue_approval()
                return
            approval_match = _APPROVAL_PATH.fullmatch(path.path)
            if method == "GET" and approval_match:
                self._query_approval(approval_match.group(1))
                return
            revoke_approval_match = _APPROVAL_REVOKE_PATH.fullmatch(path.path)
            if method == "POST" and revoke_approval_match:
                self._revoke_approval(revoke_approval_match.group(1))
                return
            receipt_list_match = _RECEIPTS_PATH.fullmatch(path.path)
            if method == "GET" and receipt_list_match:
                self._list_receipts(receipt_list_match.group(1))
                return
            receipt_resolve_match = _RECEIPT_RESOLVE_PATH.fullmatch(path.path)
            if method == "POST" and receipt_resolve_match:
                self._resolve_receipt(
                    receipt_resolve_match.group(1), receipt_resolve_match.group(2)
                )
                return
            query_match = _TASK_PATH.fullmatch(path.path)
            if method == "GET" and query_match:
                self._query(query_match.group(1))
                return
            cancel_match = _CANCEL_PATH.fullmatch(path.path)
            if method == "POST" and cancel_match:
                self._cancel(cancel_match.group(1))
                return
            if (
                path.path in {"/tasks", "/action-approvals"}
                or _TASK_PATH.fullmatch(path.path)
                or cancel_match
                or approval_match
                or revoke_approval_match
                or receipt_list_match
                or receipt_resolve_match
            ):
                raise HttpError(405, "method_not_allowed")
            raise HttpError(404, "not_found")
        except HttpError as error:
            # Rejecting before consuming a request body must not let leftover bytes
            # become a second request on a persistent HTTP/1.1 connection.
            self.close_connection = True
            if error.kind not in {"unauthorized", "capacity_exceeded"}:
                self._audit("http.reject", result_status=error.kind)
            self._send_error(error.status, error.kind)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
            _logger.debug("HTTP client disconnected while writing response")
        except Exception:
            self.close_connection = True
            _logger.error("HTTP request failed")
            self._audit("http.reject", result_status="internal_error")
            self._send_error(500, "internal_error")

    def _authorized(self) -> bool:
        values = self.headers.get_all("Authorization", failobj=[])
        if len(values) != 1:
            return False
        raw = values[0]
        scheme, separator, token = raw.partition(" ")
        if (
            scheme != "Bearer"
            or separator != " "
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or not token.isascii()
            or not token.isprintable()
            or any(character.isspace() for character in token)
        ):
            return False
        return hmac.compare_digest(token, self.server.config.token)

    def _origin_form_target(self):
        raw_target = getattr(self, "_raw_request_target", self.path)
        try:
            target = urlsplit(raw_target)
        except ValueError:
            raise HttpError(400, "invalid_target") from None
        if (
            target.scheme
            or target.netloc
            or raw_target.startswith("//")
            or not target.path.startswith("/")
            or target.path.startswith("//")
        ):
            raise HttpError(400, "invalid_target")
        return target

    def _reject_unexpected_body(self) -> None:
        if self.headers.get_all("Transfer-Encoding", failobj=[]):
            raise HttpError(400, "invalid_length")
        length = _parse_content_length(self.headers.get_all("Content-Length", failobj=[]))
        if length not in {None, 0}:
            raise HttpError(400, "invalid_length")

    def _submit(self) -> None:
        body = self._read_json()
        goal, options, approval_ids = _parse_task_request(body)
        try:
            if approval_ids:
                response = self.server.task_service.submit_view(
                    goal, options, approval_ids=approval_ids
                )
            else:
                response = self.server.task_service.submit_view(goal, options)
        except ServiceCapacityError:
            self._audit("http.capacity_rejection", result_status="capacity_exceeded")
            raise HttpError(429, "capacity_exceeded") from None
        except ServiceClosedError:
            raise HttpError(503, "service_closed") from None
        except ApprovalUnavailableError:
            raise HttpError(409, "approval_unavailable") from None
        task_id = cast(str, response["task_id"])
        self._audit("http.submit", task_id=task_id, result_status="accepted")
        if self.server.task_service.audit_degraded:
            response["audit_degraded"] = True
        self._send_json(202, response)

    def _issue_approval(self) -> None:
        body = self._read_json()
        server, tool, request_digest, expires_in_seconds = _parse_approval_request(body)
        try:
            response = self.server.task_service.issue_action_approval(
                server=server,
                tool=tool,
                request_digest=request_digest,
                expires_in_seconds=expires_in_seconds,
            )
        except ValueError:
            raise HttpError(400, "invalid_request") from None
        except ApprovalCapacityError:
            raise HttpError(429, "approval_capacity") from None
        except ApprovalUnavailableError:
            raise HttpError(409, "approval_unavailable") from None
        self._audit("http.approval_issue", result_status="issued")
        self._send_json(201, response)

    def _query_approval(self, approval_id: str) -> None:
        try:
            response = self.server.task_service.get_action_approval(approval_id)
        except ApprovalNotFoundError:
            raise HttpError(404, "approval_not_found") from None
        except ApprovalUnavailableError:
            raise HttpError(409, "approval_unavailable") from None
        self._audit("http.approval_query", result_status=str(response["status"]))
        self._send_json(200, response)

    def _revoke_approval(self, approval_id: str) -> None:
        if self._read_json():
            raise HttpError(400, "invalid_request")
        try:
            response = self.server.task_service.revoke_action_approval(approval_id)
        except ApprovalNotFoundError:
            raise HttpError(404, "approval_not_found") from None
        except ApprovalUnavailableError:
            raise HttpError(409, "approval_unavailable") from None
        self._audit("http.approval_revoke", result_status=str(response["status"]))
        self._send_json(200, response)

    def _list_receipts(self, task_id: str) -> None:
        try:
            receipts = self.server.task_service.list_task_receipts(task_id)
        except TaskNotFound:
            raise HttpError(404, "not_found") from None
        except ReceiptServiceUnavailable:
            raise HttpError(503, "receipt_unavailable") from None
        self._audit("http.receipt_list", task_id=task_id, result_status="ok")
        self._send_json(200, {"receipts": list(receipts)})

    def _resolve_receipt(self, task_id: str, action_id: str) -> None:
        expected_revision, decision, evidence = _parse_receipt_resolution(self._read_json())
        try:
            response = self.server.task_service.resolve_task_receipt(
                task_id,
                action_id,
                expected_revision=expected_revision,
                decision=decision,
                evidence=evidence,
            )
        except TaskNotFound:
            raise HttpError(404, "not_found") from None
        except TaskReceiptNotFound:
            raise HttpError(404, "receipt_not_found") from None
        except TaskReceiptConflict:
            raise HttpError(409, "receipt_conflict") from None
        except ReceiptServiceUnavailable:
            raise HttpError(503, "receipt_unavailable") from None
        self._audit("http.receipt_resolve", task_id=task_id, result_status=decision)
        self._send_json(200, response)

    def _query(self, task_id: str) -> None:
        try:
            response = self.server.task_service.query(task_id)
        except TaskNotFound:
            raise HttpError(404, "not_found") from None
        self._audit("http.query", task_id=task_id, result_status="ok")
        if self.server.task_service.audit_degraded:
            response["audit_degraded"] = True
        self._send_json(200, response)

    def _cancel(self, task_id: str) -> None:
        body = self._read_json()
        if body:
            raise HttpError(400, "invalid_request")
        try:
            response = self.server.task_service.cancel(task_id)
        except TaskNotFound:
            raise HttpError(404, "not_found") from None
        status = 200 if response["status"] not in {"queued", "running"} else 202
        self._audit("http.cancel", task_id=task_id, result_status=str(response["status"]))
        if self.server.task_service.audit_degraded:
            response["audit_degraded"] = True
        self._send_json(status, response)

    def _read_json(self) -> dict[str, object]:
        if self.headers.get_content_type() != "application/json":
            raise HttpError(415, "invalid_content_type")
        if self.headers.get("Transfer-Encoding") is not None:
            raise HttpError(400, "invalid_length")
        length = _parse_content_length(self.headers.get_all("Content-Length", failobj=[]))
        if length is None:
            raise HttpError(400, "invalid_length")
        if length > self.server.config.max_body_bytes:
            raise HttpError(413, "body_too_large")
        try:
            raw = self.rfile.read(length)
        except OSError:
            raise HttpError(400, "invalid_length") from None
        if len(raw) != length:
            raise HttpError(400, "invalid_length")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HttpError(400, "invalid_json") from None
        if not isinstance(value, dict):
            raise HttpError(400, "invalid_json")
        return cast(dict[str, object], value)

    def _audit(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        result_status: str,
    ) -> None:
        persisted = emit_audit(
            self.server.audit_sink,
            AuditEvent(
                event_type=event_type,
                task_id=task_id,
                parameters={},
                result_status=result_status,
            ),
        )
        try:
            degraded = bool(getattr(self.server.audit_sink, "degraded", False))
        except Exception:
            degraded = True
        if not persisted or degraded:
            self.server.task_service.mark_audit_degraded()

    def _send_error(self, status: int, kind: str) -> None:
        if kind == "unauthorized":
            self.send_response(status)
            self.send_header("WWW-Authenticate", "Bearer")
            self._finish_json_headers({"error": {"kind": kind, "detail": _ERROR_DETAILS[kind]}})
            return
        self._send_json(
            status,
            {"error": {"kind": kind, "detail": _ERROR_DETAILS[kind]}},
        )

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        self.send_response(status)
        self._finish_json_headers(payload)

    def _finish_json_headers(self, payload: dict[str, object]) -> None:
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(raw)


def create_http_server(
    config: HttpServiceConfig,
    service: TaskService,
) -> ThreadingHTTPServer:
    """Create the owner-controlled loopback listener without starting its thread."""
    try:
        is_loopback = ipaddress.ip_address(config.bind_host).is_loopback
    except ValueError as error:
        raise ValueError("HTTP service must bind to a loopback IP address") from error
    if not is_loopback:
        raise ValueError("HTTP service must bind to loopback")
    token = config.token
    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_BEARER_TOKEN_LENGTH
        or not token.isascii()
        or not token.isprintable()
        or any(character.isspace() for character in token)
    ):
        raise ValueError("HTTP bearer token is invalid")
    return _ForgeHttpServer(config, service)


def _parse_task_submission(body: dict[str, object]) -> tuple[str, dict[str, object]]:
    goal, options, _approval_ids = _parse_task_request(body)
    return goal, options


def _parse_task_request(
    body: dict[str, object],
) -> tuple[str, dict[str, object], tuple[str, ...]]:
    task_body = dict(body)
    raw_approval_ids = task_body.pop("approval_ids", None)
    approval_ids: tuple[str, ...] = ()
    if raw_approval_ids is not None:
        if not isinstance(raw_approval_ids, list) or not 1 <= len(raw_approval_ids) <= 16:
            raise HttpError(400, "invalid_request")
        if any(
            not isinstance(approval_id, str) or _APPROVAL_ID.fullmatch(approval_id) is None
            for approval_id in raw_approval_ids
        ):
            raise HttpError(400, "invalid_request")
        approval_ids = tuple(cast(list[str], raw_approval_ids))
        if len(approval_ids) != len(set(approval_ids)):
            raise HttpError(400, "invalid_request")
    goal, options = _parse_task_body(task_body)
    return goal, options, approval_ids


def _parse_task_body(body: dict[str, object]) -> tuple[str, dict[str, object]]:
    keys = frozenset(body)
    if keys == {"goal"}:
        goal = body["goal"]
        if isinstance(goal, str) and goal.strip():
            return goal, {}
        raise HttpError(400, "invalid_request")
    if keys == _TASK_MODE_KEYS:
        goal = body["goal"]
        mode = body["mode"]
        if isinstance(goal, str) and goal.strip() and mode in {"task", "duo", "triad"}:
            return goal, {"mode": mode}
        raise HttpError(400, "invalid_request")
    if keys == _RESUME_LOOP_KEYS:
        loop_id = body["resume_loop_id"]
        if body["mode"] == "loop" and isinstance(loop_id, str) and _LOOP_ID.fullmatch(loop_id):
            return "", {"mode": "loop", "resume_loop_id": loop_id}
        raise HttpError(400, "invalid_request")
    if keys in {_NEW_LOOP_KEYS, _NEW_COLLABORATIVE_LOOP_KEYS}:
        goal = body["goal"]
        if not isinstance(goal, str) or not goal.strip() or body["mode"] != "loop":
            raise HttpError(400, "invalid_request")
        if not all(
            _positive_integer(body[name])
            for name in ("token_budget", "max_rounds", "max_consecutive_failures")
        ) or not _positive_number(body["wall_clock_seconds"]):
            raise HttpError(400, "invalid_request")
        collaboration_mode = body.get("collaboration_mode", "single")
        if collaboration_mode not in {"single", "duo", "triad"}:
            raise HttpError(400, "invalid_request")
        return goal, {name: body[name] for name in body if name != "goal"}
    raise HttpError(400, "invalid_request")


def _parse_approval_request(body: dict[str, object]) -> tuple[str, str, str, int]:
    if frozenset(body) != {
        "action_type",
        "server",
        "tool",
        "request_digest",
        "mode",
        "expires_in_seconds",
    }:
        raise HttpError(400, "invalid_request")
    server = body["server"]
    tool = body["tool"]
    request_digest = body["request_digest"]
    expires_in_seconds = body["expires_in_seconds"]
    if (
        body["action_type"] != "mcp"
        or body["mode"] != "allow_once"
        or not isinstance(server, str)
        or not isinstance(tool, str)
        or not isinstance(request_digest, str)
        or type(expires_in_seconds) is not int
        or not 1 <= expires_in_seconds <= 3600
    ):
        raise HttpError(400, "invalid_request")
    return server, tool, request_digest, expires_in_seconds


def _parse_receipt_resolution(body: dict[str, object]) -> tuple[int, str, str]:
    if frozenset(body) not in {
        frozenset({"expected_revision", "decision"}),
        frozenset({"expected_revision", "decision", "evidence"}),
    }:
        raise HttpError(400, "invalid_request")
    expected_revision = body["expected_revision"]
    decision = body["decision"]
    evidence = body.get("evidence", "")
    if (
        type(expected_revision) is not int
        or expected_revision < 0
        or decision not in {"confirmed", "abandoned", "retry_approved"}
        or not isinstance(evidence, str)
        or len(evidence) > 1000
        or (decision == "confirmed" and not evidence.strip())
    ):
        raise HttpError(400, "invalid_request")
    return expected_revision, cast(str, decision), evidence


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _positive_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )
