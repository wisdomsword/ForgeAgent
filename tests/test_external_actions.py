from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from forgeagent.external_actions import (
    ExternalActionReceipt,
    ExternalActionReceiptStore,
    ReceiptError,
    canonical_request_digest,
)
from forgeagent.protocol import MCPArgs, ToolCall


def _prepared(**overrides: object) -> ExternalActionReceipt:
    values: dict[str, object] = {
        "task_id": "task-1",
        "action_type": "mcp",
        "server_label": "fixture",
        "tool_label": "write",
        "request_digest": canonical_request_digest({"value": 1}),
    }
    values.update(overrides)
    return ExternalActionReceipt.new_prepared(**values)


def test_receipt_id_is_hex_but_existing_operation_id_stays_arbitrary():
    receipt = _prepared()
    assert re.fullmatch(r"[0-9a-f]{32}", receipt.action_id)
    ToolCall(id="model-generated-id", name="MCP", arguments=MCPArgs(server="s", tool="t"))


def test_receipt_model_defaults_and_digest_are_strict():
    receipt = _prepared(parent_action_id="a" * 32, loop_id="b" * 32)
    assert receipt.schema == "forgeagent.external-action-receipt.v1"
    assert receipt.phase == "prepared"
    assert receipt.resolution == "open"
    assert receipt.dispatch_certainty is None
    assert receipt.remote_ok is None
    assert receipt.revision == 0
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest)
    assert receipt.created_at.endswith("Z") and receipt.updated_at.endswith("Z")
    assert datetime.fromisoformat(receipt.created_at.replace("Z", "+00:00")).tzinfo == UTC
    assert canonical_request_digest({"b": 1, "a": 2}) == canonical_request_digest(
        {"a": 2, "b": 1}
    )
    with pytest.raises(ValidationError):
        _prepared(unexpected="value")


def test_receipt_transitions_and_resolution_are_separate(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        loop_id="a" * 32,
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({"value": 1}),
    )
    dispatched = store.mark_dispatched(receipt.action_id, receipt.revision)
    confirmed = store.mark_confirmed(
        receipt.action_id, dispatched.revision, "confirmed", False, "protocol_error"
    )
    assert confirmed.phase == "confirmed"
    assert confirmed.dispatch_certainty == "confirmed"
    assert confirmed.remote_ok is False
    assert confirmed.resolution == "open"
    resolved = store.resolve(confirmed.action_id, confirmed.revision, "confirmed", "verified")
    assert resolved.phase == "confirmed" and resolved.resolution == "confirmed"
    assert store.list_pending() == ()


def test_unknown_and_stale_revision(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({}),
    )
    unknown = store.mark_unknown(receipt.action_id, receipt.revision, "timeout\nsecret")
    assert unknown.phase == "unknown"
    assert unknown.dispatch_certainty == "unknown"
    assert unknown.remote_ok is None
    assert "\n" not in unknown.evidence_ref
    with pytest.raises(ReceiptError):
        store.mark_dispatched(receipt.action_id, receipt.revision)
    assert store.list_pending() == (unknown,)


def test_store_is_atomic_private_and_rejects_tampering(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({}),
    )
    path = tmp_path / ".forgeagent" / "receipts" / f"{receipt.action_id}.json"
    assert os.stat(path).st_mode & 0o777 == 0o600
    raw = json.loads(path.read_text())
    raw["schema"] = "other"
    path.write_text(json.dumps(raw))
    with pytest.raises(ReceiptError):
        store.load(receipt.action_id)
