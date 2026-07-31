#!/usr/bin/env python3
"""Exercise M44 approval binding and receipt recovery over real loopback HTTP."""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

from forgeagent import HttpServiceConfig, TaskService, create_http_server
from forgeagent.executor import TrustedBackend
from forgeagent.external_actions import ExternalActionReceiptStore, canonical_request_digest
from forgeagent.headless import HeadlessConfirmer
from forgeagent.http_action_approvals import HttpActionApprovalStore
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import MCPArgs
from forgeagent.runtime import Runtime
from forgeagent.step import Termination
from forgeagent.task import TaskOutcome, TaskStatus
from forgeagent.tools import CodeBlockStore, MCPTool, ToolContext

TOKEN = "m44-private-token"
ARGUMENTS = {"repository": "private-repository"}


class DeterministicMCP:
    def __init__(self) -> None:
        self.dispatch_count = 0

    def is_auto_approved(self, _server: str, _tool: str) -> bool:
        return False

    def call_tool(self, _server: str, _tool: str, _arguments: dict) -> dict[str, object]:
        self.dispatch_count += 1
        return {"ok": True, "text": "completed", "dispatch_certainty": "confirmed"}


class ApprovalRunner:
    def __init__(
        self,
        *,
        task_id: str,
        root: Path,
        confirmer: HeadlessConfirmer,
        mcp: DeterministicMCP,
        receipt_store: ExternalActionReceiptStore,
    ) -> None:
        self._task_id = task_id
        self._root = root
        self._confirmer = confirmer
        self._mcp = mcp
        self._receipt_store = receipt_store

    def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
        if not goal or cancel_event is None:
            raise RuntimeError("invalid verifier task")
        outcome = MCPTool().run(
            MCPArgs(server="m44", tool="apply", arguments=ARGUMENTS),
            ToolContext(
                blocks=CodeBlockStore(),
                backend=TrustedBackend(),
                runtime=Runtime(),
                analyzer=CodeAnalyzer(),
                mcp=self._mcp,
                confirmer=self._confirmer,
                tier="trusted",
                allowed_root=str(self._root),
                task_id=self._task_id,
                operation_id="m44-verifier-dispatch",
                allow_auto_approve=False,
                cancel_event=cancel_event,
                receipt_store=self._receipt_store,
            ),
        )
        if not outcome.success:
            raise RuntimeError("verified dispatch failed")
        return TaskOutcome(
            status=TaskStatus(completed=True, reason=Termination.COMPLETED),
            rounds=[],
        )

    def close(self) -> None:
        return None


def _request(
    address: tuple[str, int],
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection(*address, timeout=3)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _require_status(actual: int, expected: int) -> None:
    if actual != expected:
        raise RuntimeError("unexpected verifier response")


def verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="forgeagent-m44-") as temporary:
        root = Path(temporary)
        approval_store = HttpActionApprovalStore(max_records=8)
        receipt_store = ExternalActionReceiptStore(str(root))
        mcp = DeterministicMCP()
        confirmer = HeadlessConfirmer((), audit=None, root=root, approval_store=approval_store)
        config = HttpServiceConfig(
            bind_host="127.0.0.1",
            port=0,
            token=TOKEN,
            max_workers=1,
            max_queue=2,
            max_records=4,
        )
        service = TaskService(
            factory=lambda record: ApprovalRunner(
                task_id=record.task_id,
                root=root,
                confirmer=confirmer,
                mcp=mcp,
                receipt_store=receipt_store,
            ),
            config=config,
            approval_store=approval_store,
            receipt_store=receipt_store,
        )
        server = create_http_server(config, service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address = server.server_address
            status, approval = _request(
                address,
                "POST",
                "/action-approvals",
                {
                    "action_type": "mcp",
                    "server": "m44",
                    "tool": "apply",
                    "request_digest": canonical_request_digest(ARGUMENTS),
                    "mode": "allow_once",
                    "expires_in_seconds": 60,
                },
            )
            _require_status(status, 201)
            approval_id = str(approval["approval_id"])
            status, submitted = _request(
                address,
                "POST",
                "/tasks",
                {
                    "goal": "complete private goal",
                    "approval_ids": [approval_id],
                },
            )
            _require_status(status, 202)
            task_id = str(submitted["task_id"])
            final = service.wait(task_id, timeout=5)
            if final["status"] != "completed":
                raise RuntimeError("verifier task did not complete")

            status, approval = _request(address, "GET", f"/action-approvals/{approval_id}")
            _require_status(status, 200)
            status, receipt_response = _request(address, "GET", f"/tasks/{task_id}/receipts")
            _require_status(status, 200)
            receipts = receipt_response["receipts"]
            if not isinstance(receipts, list) or len(receipts) != 1:
                raise RuntimeError("verified receipt is unavailable")
            confirmed_receipt = receipts[0]
            if not isinstance(confirmed_receipt, dict):
                raise RuntimeError("verified receipt is invalid")

            unknown = receipt_store.create_prepared(
                task_id=task_id,
                server_label="m44",
                tool_label="recover",
                request_digest=canonical_request_digest({"operation": "unknown"}),
            )
            unknown = receipt_store.mark_dispatched(unknown.action_id, unknown.revision)
            unknown = receipt_store.mark_unknown(
                unknown.action_id, unknown.revision, "result_unknown"
            )
            dispatch_before_reconcile = mcp.dispatch_count
            status, resolved = _request(
                address,
                "POST",
                f"/tasks/{task_id}/receipts/{unknown.action_id}/resolve",
                {
                    "expected_revision": unknown.revision,
                    "decision": "confirmed",
                    "evidence": "provider confirmation",
                },
            )
            _require_status(status, 200)
            return {
                "approval_status": approval["status"],
                "dispatch_count": mcp.dispatch_count,
                "receipt_phase": confirmed_receipt["phase"],
                "reconcile_dispatch_delta": mcp.dispatch_count - dispatch_before_reconcile,
                "unknown_resolution": resolved["resolution"],
            }
        finally:
            server.shutdown()
            server.server_close()
            service.shutdown(5)
            thread.join(timeout=5)


def main() -> int:
    try:
        result = verify()
    except Exception:
        print(json.dumps({"reason": "verification_failed", "status": "failed"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
