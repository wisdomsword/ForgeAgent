"""Host-owned one-time HTTP action approval state tests."""

from __future__ import annotations

import threading

import pytest
from pydantic import ValidationError

from forgeagent.http_action_approvals import (
    APPROVAL_SCHEMA,
    ApprovalCapacityError,
    ApprovalNotFoundError,
    ApprovalUnavailableError,
    HttpActionApproval,
    HttpActionApprovalStore,
)

TASK_ID = "1" * 32
DIGEST = "a" * 64


class FakeClock:
    def __init__(self, value: float = 1_800_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class RecordingSink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> bool:
        self.events.append(event)
        return True


def _issue(
    store: HttpActionApprovalStore,
    *,
    server: str = "github",
    tool: str = "create_issue",
    digest: str = DIGEST,
    ttl: int = 60,
) -> HttpActionApproval:
    return store.issue(
        server=server,
        tool=tool,
        request_digest=digest,
        expires_in_seconds=ttl,
    )


def test_issue_returns_strict_bounded_public_record() -> None:
    store = HttpActionApprovalStore(max_records=2, clock=FakeClock())

    record = _issue(store)
    view = record.public_view()

    assert record.status == "issued"
    assert record.scope == "mcp/github/create_issue"
    assert view["schema"] == APPROVAL_SCHEMA
    assert set(view) == {
        "schema",
        "approval_id",
        "action_type",
        "scope",
        "request_digest",
        "mode",
        "status",
        "task_id",
        "issued_at",
        "expires_at",
    }
    assert "arguments" not in repr(view)
    with pytest.raises(ValidationError):
        HttpActionApproval.model_validate(record.model_dump() | {"unexpected": True})


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"server": "../private"}, ValueError),
        ({"server": "a" * 201}, ValueError),
        ({"tool": "create/issue"}, ValueError),
        ({"digest": "not-a-digest"}, ValueError),
        ({"ttl": True}, ValueError),
        ({"ttl": 0}, ValueError),
        ({"ttl": 3601}, ValueError),
    ],
)
def test_issue_rejects_invalid_scope_digest_and_ttl(
    overrides: dict[str, object], error: type[Exception]
) -> None:
    store = HttpActionApprovalStore(max_records=2)

    with pytest.raises(error):
        _issue(store, **overrides)


def test_bind_many_is_all_or_nothing_and_rejects_duplicates() -> None:
    store = HttpActionApprovalStore(max_records=4)
    first = _issue(store)
    second = _issue(store, tool="close_issue")

    with pytest.raises(ApprovalUnavailableError):
        store.bind_many((first.approval_id, "f" * 32), TASK_ID)
    assert store.get(first.approval_id).status == "issued"

    with pytest.raises(ApprovalUnavailableError):
        store.bind_many((first.approval_id, first.approval_id), TASK_ID)
    assert store.get(first.approval_id).status == "issued"

    bound = store.bind_many((first.approval_id, second.approval_id), TASK_ID)
    assert [record.status for record in bound] == ["bound", "bound"]
    assert {record.task_id for record in bound} == {TASK_ID}


def test_consume_requires_exact_task_scope_and_digest_and_is_once_only() -> None:
    store = HttpActionApprovalStore(max_records=2)
    approval = _issue(store)
    store.bind_many((approval.approval_id,), TASK_ID)

    assert (
        store.consume(
            task_id="2" * 32,
            scope=approval.scope,
            request_digest=approval.request_digest,
        )
        is None
    )
    assert (
        store.consume(
            task_id=TASK_ID,
            scope="mcp/github/close_issue",
            request_digest=approval.request_digest,
        )
        is None
    )
    assert (
        store.consume(
            task_id=TASK_ID,
            scope=approval.scope,
            request_digest="b" * 64,
        )
        is None
    )
    consumed = store.consume(
        task_id=TASK_ID,
        scope=approval.scope,
        request_digest=approval.request_digest,
    )

    assert consumed is not None and consumed.status == "consumed"
    assert (
        store.consume(
            task_id=TASK_ID,
            scope=approval.scope,
            request_digest=approval.request_digest,
        )
        is None
    )


def test_expiry_and_release_close_authority_without_reactivation() -> None:
    clock = FakeClock()
    store = HttpActionApprovalStore(max_records=3, clock=clock)
    expiring = _issue(store, ttl=1)
    released = _issue(store, tool="close_issue")
    consumed = _issue(store, tool="label_issue")
    store.bind_many((expiring.approval_id, released.approval_id, consumed.approval_id), TASK_ID)
    store.consume(
        task_id=TASK_ID,
        scope=consumed.scope,
        request_digest=consumed.request_digest,
    )

    clock.value += 2
    assert store.get(expiring.approval_id).status == "expired"
    store.release_task(TASK_ID)

    assert store.get(released.approval_id).status == "revoked"
    assert store.get(consumed.approval_id).status == "consumed"


def test_capacity_evicts_terminal_record_but_not_live_authority() -> None:
    store = HttpActionApprovalStore(max_records=1)
    first = _issue(store)

    with pytest.raises(ApprovalCapacityError):
        _issue(store, tool="close_issue")

    store.revoke(first.approval_id)
    second = _issue(store, tool="close_issue")

    with pytest.raises(ApprovalNotFoundError):
        store.get(first.approval_id)
    assert store.get(second.approval_id).status == "issued"


def test_revoke_and_consume_race_has_one_terminal_winner() -> None:
    store = HttpActionApprovalStore(max_records=1)
    approval = _issue(store)
    store.bind_many((approval.approval_id,), TASK_ID)
    barrier = threading.Barrier(3)
    results: list[str] = []

    def consume() -> None:
        barrier.wait()
        result = store.consume(
            task_id=TASK_ID,
            scope=approval.scope,
            request_digest=approval.request_digest,
        )
        results.append("denied" if result is None else result.status)

    def revoke() -> None:
        barrier.wait()
        results.append(store.revoke(approval.approval_id).status)

    threads = [threading.Thread(target=consume), threading.Thread(target=revoke)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    terminal = store.get(approval.approval_id).status
    assert terminal in {"consumed", "revoked"}
    if terminal == "consumed":
        assert results.count("consumed") == 2
    else:
        assert sorted(results) == ["denied", "revoked"]


def test_unknown_approval_is_not_disclosed() -> None:
    store = HttpActionApprovalStore(max_records=1)

    with pytest.raises(ApprovalNotFoundError, match="approval is unavailable"):
        store.get("f" * 32)


@pytest.mark.parametrize("operation", ["get", "bind", "revoke"])
def test_expiry_audit_survives_a_rejected_operation(operation: str) -> None:
    clock = FakeClock()
    sink = RecordingSink()
    store = HttpActionApprovalStore(max_records=2, clock=clock, audit_sink=sink)
    expiring = _issue(store, ttl=1)
    sink.events.clear()
    clock.value += 2

    with pytest.raises((ApprovalNotFoundError, ApprovalUnavailableError)):
        if operation == "get":
            store.get("f" * 32)
        elif operation == "bind":
            store.bind_many(("f" * 32,), TASK_ID)
        else:
            store.revoke("f" * 32)

    assert [event.result_status for event in sink.events] == ["expired"]
    assert sink.events[0].operation_id == expiring.approval_id
