from __future__ import annotations

from pathlib import Path

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.headless import HeadlessConfirmer, normalize_allowlist, operation_key
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
            "github/create_issue",
            "reports/out.txt",
            "https/example.com/443/api/report",
        }
    ) == frozenset(
        {
            "github/create_issue",
            "reports/out.txt",
            "https/example.com/443/api/report",
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
        "reports/*.txt",
        "reports/[ab].txt",
        "../outside.txt",
        "reports/../outside.txt",
        "/absolute.txt",
        "reports\\out.txt",
        "https/example.com/not-a-port/a",
        "https/example.com/0/a",
        "https/example.com/65536/a",
        "https/example.com/443/a?scope=wide",
    ],
)
def test_normalize_allowlist_rejects_glob_unsafe_and_escaping_entries(entry: str) -> None:
    with pytest.raises(ValueError, match="allowlist"):
        normalize_allowlist([entry])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://Example.COM/a?token=one#fragment", "http/example.com/80/a"),
        ("https://Example.COM/a?token=two", "https/example.com/443/a"),
        ("https://example.com:8443", "https/example.com/8443/"),
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

    assert key == "reports/out.txt"


def test_file_write_operation_key_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "headless-private"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="project root"):
        operation_key(FileWriteArgs(path="link/out.txt", content="private"), tmp_path)


def test_headless_confirmer_exact_match_audits_preapproval_and_denial(tmp_path: Path) -> None:
    sink = _RecordingAuditSink()
    confirmer = HeadlessConfirmer(
        {"reports/out.txt", "https/example.com/443/a"},
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
        "reports/out.txt",
        "reports/other.txt",
        "https/example.com/443/a",
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
        "github/create_issue"
    )
