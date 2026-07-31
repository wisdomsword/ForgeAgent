from __future__ import annotations

from pathlib import Path

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.external_actions import canonical_request_digest
from forgeagent.headless import HeadlessConfirmer, normalize_allowlist, operation_key
from forgeagent.http_action_approvals import HttpActionApprovalStore
from forgeagent.protocol import FileWriteArgs, MCPArgs, WebFetchArgs


class _RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def test_normalize_allowlist_accepts_exact_canonical_operation_keys() -> None:
    assert normalize_allowlist(
        {
            "mcp/github/create_issue",
            "file/reports/out.txt",
            "web/https/example.com/443/api/report",
        }
    ) == frozenset(
        {
            "mcp/github/create_issue",
            "file/reports/out.txt",
            "web/https/example.com/443/api/report",
        }
    )


def test_normalize_allowlist_rejects_bare_string_collection() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        normalize_allowlist("abc")


@pytest.mark.parametrize(
    "entry",
    [
        "",
        " reports/out.txt",
        "reports/out.txt ",
        "github/create_issue",
        "reports/out.txt",
        "https/example.com/443/a",
        "mcp/server/tool/extra",
        "mcp/server\x1f/tool",
        "reports/*.txt",
        "reports/[ab].txt",
        "../outside.txt",
        "reports/../outside.txt",
        "/absolute.txt",
        "reports\\out.txt",
        "web/https/example.com/not-a-port/a",
        "web/https/example.com/0/a",
        "web/https/example.com/65536/a",
        "web/https/example.com/443/a?scope=wide",
    ],
)
def test_normalize_allowlist_rejects_glob_unsafe_and_escaping_entries(entry: str) -> None:
    with pytest.raises(ValueError, match="allowlist"):
        normalize_allowlist([entry])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://Example.COM/a?token=one#fragment", "web/http/example.com/80/a"),
        ("https://Example.COM/a?token=two", "web/https/example.com/443/a"),
        ("https://example.com:8443", "web/https/example.com/8443/"),
    ],
)
def test_operation_key_uses_scheme_specific_default_port_and_omits_query(
    url: str, expected: str, tmp_path: Path
) -> None:
    assert operation_key(WebFetchArgs(url=url), tmp_path) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:0/a",
        "https://user:password@example.com/a",
        "https://example.com/a/../admin",
    ],
)
def test_webfetch_operation_key_rejects_unsafe_authority_and_path(url: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="WebFetch"):
        operation_key(WebFetchArgs(url=url), tmp_path)


def test_file_write_operation_key_is_canonical_project_relative_path(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()

    key = operation_key(
        FileWriteArgs(path="staging/../reports/out.txt", content="private"),
        tmp_path,
    )

    assert key == "file/reports/out.txt"


def test_file_write_operation_key_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "headless-private"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="project root"):
        operation_key(FileWriteArgs(path="link/out.txt", content="private"), tmp_path)


def test_headless_confirmer_exact_match_audits_preapproval_and_denial(tmp_path: Path) -> None:
    sink = _RecordingAuditSink()
    confirmer = HeadlessConfirmer(
        {"file/reports/out.txt", "web/https/example.com/443/a"},
        audit=sink,
        root=tmp_path,
    )

    assert confirmer(FileWriteArgs(path="reports/out.txt", content="x")) is True
    assert confirmer(FileWriteArgs(path="reports/other.txt", content="x")) is False
    assert confirmer(WebFetchArgs(url="https://example.com/a?ignored=yes")) is True

    assert [event.result_status for event in sink.events] == [
        "preapproved",
        "denied",
        "preapproved",
    ]
    assert [event.parameters["operation"] for event in sink.events] == [
        "file/reports/out.txt",
        "file/reports/other.txt",
        "web/https/example.com/443/a",
    ]


def test_headless_confirmer_denies_invalid_operation_without_disclosing_path(
    tmp_path: Path,
) -> None:
    sink = _RecordingAuditSink()
    secret_path = tmp_path.parent / "private-secret" / "out.txt"
    confirmer = HeadlessConfirmer([], audit=sink, root=tmp_path)

    assert confirmer(FileWriteArgs(path=str(secret_path), content="private")) is False

    assert len(sink.events) == 1
    assert sink.events[0].result_status == "denied"
    assert sink.events[0].parameters == {"operation": "invalid"}
    assert str(secret_path) not in repr(sink.events[0])


def test_mcp_operation_key_is_exact_server_and_tool(tmp_path: Path) -> None:
    assert operation_key(MCPArgs(server="github", tool="create_issue"), tmp_path) == (
        "mcp/github/create_issue"
    )


@pytest.mark.parametrize(
    ("server", "tool"),
    [
        ("github/admin", "create_issue"),
        ("github", "admin/create_issue"),
        ("github\\admin", "create_issue"),
        ("github", "create\nissue"),
    ],
)
def test_mcp_operation_key_rejects_separator_and_control_characters(
    server: str, tool: str, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="MCP"):
        operation_key(MCPArgs(server=server, tool=tool), tmp_path)


def test_web_allowlist_and_runtime_share_idna_host_canonicalization(tmp_path: Path) -> None:
    configured = normalize_allowlist(["web/https/B\u00dcCHER.Example/443/report"])
    runtime = operation_key(WebFetchArgs(url="https://b\u00fccher.example/report"), tmp_path)

    assert configured == frozenset({"web/https/xn--bcher-kva.example/443/report"})
    assert runtime in configured


def _bound_approval(
    store: HttpActionApprovalStore,
    *,
    task_id: str,
    arguments: dict[str, object],
) -> str:
    record = store.issue(
        server="github",
        tool="create_issue",
        request_digest=canonical_request_digest(arguments),
        expires_in_seconds=60,
    )
    store.bind_many([record.approval_id], task_id)
    return record.approval_id


def test_dynamic_mcp_approval_requires_exact_task_scope_and_digest(tmp_path: Path) -> None:
    store = HttpActionApprovalStore(max_records=4)
    task_id = "a" * 32
    approval_id = _bound_approval(store, task_id=task_id, arguments={"repo": "safe"})
    sink = _RecordingAuditSink()
    confirmer = HeadlessConfirmer([], audit=sink, root=tmp_path, approval_store=store)

    assert (
        confirmer.confirm_with_context(
            MCPArgs(server="github", tool="create_issue", arguments={"repo": "changed"}),
            task_id=task_id,
            operation_id="wrong-digest",
        )
        is False
    )
    assert (
        confirmer.confirm_with_context(
            MCPArgs(server="github", tool="create_issue", arguments={"repo": "safe"}),
            task_id="b" * 32,
            operation_id="wrong-task",
        )
        is False
    )
    assert (
        confirmer.confirm_with_context(
            MCPArgs(server="github", tool="delete_repo", arguments={"repo": "safe"}),
            task_id=task_id,
            operation_id="wrong-scope",
        )
        is False
    )
    assert store.get(approval_id).status == "bound"

    exact = MCPArgs(server="github", tool="create_issue", arguments={"repo": "safe"})
    assert confirmer.confirm_with_context(exact, task_id=task_id, operation_id="exact") is True
    assert confirmer.confirm_with_context(exact, task_id=task_id, operation_id="reuse") is False
    assert store.get(approval_id).status == "consumed"
    assert [event.result_status for event in sink.events] == [
        "denied",
        "denied",
        "denied",
        "allow_once",
        "denied",
    ]


def test_static_allowlist_does_not_consume_dynamic_approval(tmp_path: Path) -> None:
    store = HttpActionApprovalStore(max_records=2)
    task_id = "c" * 32
    approval_id = _bound_approval(store, task_id=task_id, arguments={})
    confirmer = HeadlessConfirmer(
        ["mcp/github/create_issue"],
        audit=None,
        root=tmp_path,
        approval_store=store,
    )

    assert (
        confirmer.confirm_with_context(
            MCPArgs(server="github", tool="create_issue"),
            task_id=task_id,
            operation_id="static",
        )
        is True
    )
    assert store.get(approval_id).status == "bound"


def test_dynamic_approval_never_authorizes_non_mcp_tools(tmp_path: Path) -> None:
    store = HttpActionApprovalStore(max_records=2)
    task_id = "d" * 32
    approval_id = _bound_approval(store, task_id=task_id, arguments={})
    confirmer = HeadlessConfirmer([], audit=None, root=tmp_path, approval_store=store)

    assert (
        confirmer.confirm_with_context(
            FileWriteArgs(path="result.txt", content="safe"),
            task_id=task_id,
            operation_id="file",
        )
        is False
    )
    assert (
        confirmer.confirm_with_context(
            WebFetchArgs(url="https://example.com/"),
            task_id=task_id,
            operation_id="web",
        )
        is False
    )
    assert store.get(approval_id).status == "bound"
