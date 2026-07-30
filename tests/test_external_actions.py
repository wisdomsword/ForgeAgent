from __future__ import annotations

import json
import os
import re
import threading
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
    assert receipt.schema_version == "forgeagent.external-action-receipt.v1"
    assert receipt.phase == "prepared"
    assert receipt.resolution == "open"
    assert receipt.dispatch_certainty is None
    assert receipt.remote_ok is None
    assert receipt.revision == 0
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest)
    assert receipt.created_at.endswith("Z") and receipt.updated_at.endswith("Z")
    assert datetime.fromisoformat(receipt.created_at.replace("Z", "+00:00")).tzinfo == UTC
    assert canonical_request_digest({"b": 1, "a": 2}) == canonical_request_digest({"a": 2, "b": 1})
    with pytest.raises(ValidationError):
        _prepared(unexpected="value")
    with pytest.raises(ValidationError):
        _prepared(phase="unknown")
    with pytest.raises(ValidationError):
        _prepared(remote_ok=True)


def test_new_prepared_cannot_override_identity_or_state():
    with pytest.raises(ValidationError):
        ExternalActionReceipt.new_prepared(
            task_id="task-1",
            server_label="fixture",
            tool_label="write",
            request_digest=canonical_request_digest({}),
            action_id="a" * 32,
            revision=9,
        )


@pytest.mark.parametrize(
    "override",
    [
        {"action_id": "a" * 32},
        {"phase": "confirmed"},
        {"resolution": "abandoned"},
        {"revision": 9},
        {"created_at": "2020-01-01T00:00:00.000Z"},
    ],
)
def test_factory_rejects_creation_invariant_overrides(override):
    with pytest.raises(ValidationError):
        _prepared(**override)


def test_receipt_rejects_invalid_state_combinations():
    receipt = _prepared()
    for update in (
        {"phase": "prepared", "remote_ok": True},
        {"phase": "dispatched", "remote_ok": False},
        {"phase": "prepared", "evidence_ref": "evidence"},
        {"phase": "confirmed", "dispatch_certainty": "confirmed", "remote_ok": None},
    ):
        with pytest.raises(ValidationError):
            ExternalActionReceipt.model_validate(receipt.model_dump() | update)


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


def test_store_rejects_invalid_labels_as_receipt_error(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    with pytest.raises(ReceiptError):
        store.create_prepared(
            task_id="task-1",
            action_type="mcp",
            server_label="x" * 201,
            tool_label="write",
            request_digest=canonical_request_digest({}),
        )


def test_create_prepared_wraps_invalid_masking_input(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    with pytest.raises(ReceiptError):
        store.create_prepared(
            task_id="task-1",
            action_type="mcp",
            server_label="x" * 201,
            tool_label="write",
            request_digest=canonical_request_digest({}),
        )


def test_store_rejects_directory_replacement(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({}),
    )
    receipts_dir = tmp_path / ".forgeagent" / "receipts"
    moved_dir = tmp_path / ".forgeagent" / "receipts-old"
    receipts_dir.rename(moved_dir)
    receipts_dir.symlink_to(moved_dir, target_is_directory=True)
    with pytest.raises(ReceiptError):
        store.load(receipt.action_id)


def test_store_compare_and_swap_allows_only_one_writer(tmp_path):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({}),
    )
    results: list[object] = []

    def dispatch() -> None:
        try:
            results.append(store.mark_dispatched(receipt.action_id, receipt.revision))
        except ReceiptError as error:
            results.append(error)

    threads = [threading.Thread(target=dispatch) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(isinstance(result, ExternalActionReceipt) for result in results) == 1
    assert sum(isinstance(result, ReceiptError) for result in results) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update({"remote_ok": float("nan")}),
        lambda raw: raw.update({"unknown_field": "x"}),
    ],
)
def test_load_rejects_malformed_receipts(tmp_path, mutate):
    store = ExternalActionReceiptStore(str(tmp_path))
    receipt = store.create_prepared(
        task_id="task-1",
        action_type="mcp",
        server_label="fixture",
        tool_label="write",
        request_digest=canonical_request_digest({}),
    )
    path = tmp_path / ".forgeagent" / "receipts" / f"{receipt.action_id}.json"
    raw = json.loads(path.read_text())
    mutate(raw)
    path.write_text(json.dumps(raw, allow_nan=True))
    with pytest.raises(ReceiptError):
        store.load(receipt.action_id)
