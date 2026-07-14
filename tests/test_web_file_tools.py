"""Unit tests for WebFetchTool and the File tools (M10 Phase 3/4).

Covers docs/m10-usage-observability-and-tools.md §3.4/§3.5: WebFetch's hybrid
save-to-disk + preview return and its confirmer gate (a real security boundary under
restricted/container tiers), and the three File tools' project-root lock plus
FileWrite's confirmer gate (UX-only, see FileWriteTool's docstring).

`guarded_urlopen` is monkeypatched throughout so no real network call is made; the SSRF
guard itself is covered by tests/test_ssrf_guard.py.
"""

import http.client
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from forgeagent.executor import TrustedBackend
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import FileListArgs, FileReadArgs, FileWriteArgs, WebFetchArgs
from forgeagent.runtime import Runtime
from forgeagent.ssrf_guard import SSRFGuardError
from forgeagent.tools import (
    CodeBlockStore,
    FileListTool,
    FileReadTool,
    FileWriteTool,
    ToolContext,
    WebFetchTool,
    _validate_path,
)


def _webfetch_ctx(*, tier="trusted", confirmer=None, allowed_root=".") -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=confirmer,
        tier=tier,
        allowed_root=allowed_root,
    )


def _file_ctx(*, tier="trusted", confirmer=None, allowed_root=".") -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=confirmer,
        tier=tier,
        allowed_root=allowed_root,
    )


class _FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _FakeResponse:
    """Minimal stand-in for the object urllib's opener.open()/guarded_urlopen return."""

    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self._body = body
        self.headers = _FakeHeaders(content_type)

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class _RaisingResponse(_FakeResponse):
    def __init__(self, exc: Exception, *, stage: str = "read") -> None:
        super().__init__(b"")
        self._exc = exc
        self._stage = stage

    def read(self, n: int = -1) -> bytes:
        if self._stage == "read":
            raise self._exc
        return super().read(n)

    def __exit__(self, *exc_info) -> bool:
        if self._stage == "exit":
            raise self._exc
        return False


# --- WebFetchTool (M10 Phase 3) ----------------------------------------------


def test_webfetch_success_saves_to_disk_and_masks_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: _FakeResponse(b"hello supersecretvalue123 world", "text/plain"),
    )
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {"supersecretvalue123"})
    ctx = _webfetch_ctx(allowed_root=str(tmp_path))

    outcome = WebFetchTool().run(WebFetchArgs(url="http://example.com/"), ctx)

    assert outcome.success is True
    assert "supersecretvalue123" not in outcome.detail
    assert "REDACTED" in outcome.detail
    saved = list(tmp_path.glob("webfetch_*"))
    assert len(saved) == 1
    saved_content = saved[0].read_text()
    assert "supersecretvalue123" not in saved_content
    assert "REDACTED" in saved_content


def test_webfetch_ssrf_guard_error_becomes_failed_outcome(monkeypatch):
    def _raise(url, **kw):
        raise SSRFGuardError(f"blocked non-public address for {url!r}")

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", _raise)

    outcome = WebFetchTool().run(WebFetchArgs(url="http://127.0.0.1/"), _webfetch_ctx())

    assert outcome.success is False
    assert outcome.detail == "WebFetch blocked by network policy"


@pytest.mark.parametrize("stage", ["open", "read", "exit"])
@pytest.mark.parametrize(
    "exc",
    [
        http.client.InvalidURL("nonnumeric port"),
        http.client.BadStatusLine("secret-host.invalid"),
        http.client.LineTooLong("status line"),
        http.client.IncompleteRead(b"partial", 10),
        http.client.RemoteDisconnected("secret-host.invalid closed connection"),
    ],
)
def test_webfetch_http_protocol_failures_are_fixed_and_do_not_raise(stage, exc, monkeypatch):
    def fake_open(url, **kwargs):
        if stage == "open":
            raise exc
        return _RaisingResponse(exc, stage=stage)

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", fake_open)

    outcome = WebFetchTool().run(
        WebFetchArgs(url="https://secret-host.invalid/"), _webfetch_ctx()
    )

    assert outcome.success is False
    assert outcome.detail == "WebFetch request failed"


def test_webfetch_invalid_url_value_error_is_fixed_and_does_not_raise(monkeypatch):
    def fake_open(url, **kwargs):
        raise ValueError("invalid URL")

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", fake_open)

    outcome = WebFetchTool().run(
        WebFetchArgs(url="https://secret-host.invalid/"), _webfetch_ctx()
    )

    assert outcome.success is False
    assert outcome.detail == "WebFetch request failed"


def test_webfetch_artifact_write_failure_is_fixed_and_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda url, **kwargs: _FakeResponse(b"body")
    )

    with patch.object(Path, "write_text", side_effect=OSError("/host/private/path")):
        outcome = WebFetchTool().run(
            WebFetchArgs(url="https://secret-host.invalid/"),
            _webfetch_ctx(allowed_root=str(tmp_path)),
        )

    assert outcome.success is False
    assert outcome.detail == "WebFetch response save failed"


def test_webfetch_restricted_tier_confirmer_denial_blocks_fetch(monkeypatch):
    calls = []
    secret_url = (
        "https://alice:password-value@example.com/private"
        "?token=query-secret#fragment-secret"
    )
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: calls.append(url) or _FakeResponse(b"body"),
    )
    ctx = _webfetch_ctx(tier="restricted", confirmer=lambda args: False)

    outcome = WebFetchTool().run(WebFetchArgs(url=secret_url), ctx)

    assert outcome.success is False
    assert outcome.detail == "WebFetch was not approved by the user"
    assert secret_url not in outcome.detail
    for secret in ("alice", "password-value", "query-secret", "fragment-secret"):
        assert secret not in outcome.detail
    assert calls == []  # denied -> never fetched


def test_webfetch_restricted_tier_without_confirmer_reports_missing_channel(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: calls.append(url) or _FakeResponse(b"body"),
    )

    outcome = WebFetchTool().run(
        WebFetchArgs(url="http://example.com/"), _webfetch_ctx(tier="restricted")
    )

    assert outcome.success is False
    assert outcome.detail == "rejected: no interactive confirmation channel available"
    assert calls == []


def test_webfetch_restricted_tier_confirmer_approval_allows_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: _FakeResponse(b"ok", "application/json"),
    )
    ctx = _webfetch_ctx(tier="restricted", confirmer=lambda args: True, allowed_root=str(tmp_path))

    outcome = WebFetchTool().run(WebFetchArgs(url="http://example.com/data.json"), ctx)

    assert outcome.success is True


def test_webfetch_trusted_tier_skips_confirmer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda url, **kw: _FakeResponse(b"ok")
    )
    # A confirmer that always denies — trusted tier must never consult it.
    ctx = _webfetch_ctx(tier="trusted", confirmer=lambda args: False, allowed_root=str(tmp_path))

    outcome = WebFetchTool().run(WebFetchArgs(url="http://example.com/"), ctx)

    assert outcome.success is True


# --- File tools (M10 Phase 4) -------------------------------------------------


def test_file_read_within_root_masks_secrets(tmp_path, monkeypatch):
    (tmp_path / "f.txt").write_text("token=supersecretvalue123")
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {"supersecretvalue123"})
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileReadTool().run(FileReadArgs(path="f.txt"), ctx)

    assert outcome.success is True
    assert "supersecretvalue123" not in outcome.detail
    assert "REDACTED" in outcome.detail


def test_file_read_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileReadTool().run(FileReadArgs(path="../../etc/passwd"), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileRead failed"
    assert str(tmp_path) not in outcome.detail


def test_validate_path_accepts_descendant_when_allowed_root_is_filesystem_root(tmp_path):
    assert _validate_path(str(tmp_path / "file.txt"), os.path.abspath(os.sep)) == (
        tmp_path / "file.txt"
    ).resolve()


@pytest.mark.parametrize(
    ("tool", "args", "detail"),
    [
        (FileReadTool(), FileReadArgs(path="bad\x00path"), "FileRead failed"),
        (FileWriteTool(), FileWriteArgs(path="bad\x00path", content="x"), "FileWrite failed"),
        (FileListTool(), FileListArgs(path="bad\x00path"), "FileList failed"),
    ],
)
def test_file_tools_contain_invalid_path_value_error(tool, args, detail, tmp_path):
    outcome = tool.run(args, _file_ctx(allowed_root=str(tmp_path)))

    assert outcome.success is False
    assert outcome.detail == detail


@pytest.mark.parametrize(
    ("tool", "args", "detail", "operation"),
    [
        (FileReadTool(), FileReadArgs(path="inside.txt"), "FileRead failed", "read_text"),
        (
            FileWriteTool(),
            FileWriteArgs(path="inside.txt", content="x"),
            "FileWrite failed",
            "write_text",
        ),
        (FileListTool(), FileListArgs(path="."), "FileList failed", "iterdir"),
    ],
)
def test_file_tool_os_errors_do_not_disclose_paths(
    tool, args, detail, operation, tmp_path, monkeypatch
):
    def fail(*args, **kwargs):
        raise OSError(f"host failure at {tmp_path}")

    monkeypatch.setattr(Path, operation, fail)
    outcome = tool.run(args, _file_ctx(allowed_root=str(tmp_path)))

    assert outcome.success is False
    assert outcome.detail == detail
    assert str(tmp_path) not in outcome.detail


def test_file_write_within_root_is_unmasked(tmp_path, monkeypatch):
    # A secret-looking value in the CONTENT must survive verbatim — write never masks.
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {"supersecretvalue123"})
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileWriteTool().run(
        FileWriteArgs(path="out.txt", content="token=supersecretvalue123"), ctx
    )

    assert outcome.success is True
    assert (tmp_path / "out.txt").read_text() == "token=supersecretvalue123"


@pytest.mark.parametrize("allowed_root", [".", "absolute"])
def test_file_write_success_uses_canonical_project_relative_path(
    tmp_path, monkeypatch, allowed_root
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nested").mkdir()
    root = "." if allowed_root == "." else str(tmp_path)

    outcome = FileWriteTool().run(
        FileWriteArgs(path=str(tmp_path / "nested" / "file.txt"), content="x"),
        _file_ctx(allowed_root=root),
    )

    assert outcome.success is True
    assert outcome.detail == "wrote nested/file.txt"


def test_file_write_static_symlink_escape_is_blocked(tmp_path):
    outside = tmp_path.parent / "private-secrets"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)

    outcome = FileWriteTool().run(
        FileWriteArgs(path="link/escape.txt", content="x"), _file_ctx(allowed_root=str(tmp_path))
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite path is outside project root"
    assert not (outside / "escape.txt").exists()


def test_file_write_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))
    external_path = tmp_path.parent / "private-secrets" / "escape.txt"
    content = "do not disclose this write payload"

    outcome = FileWriteTool().run(
        FileWriteArgs(path=str(external_path), content=content), ctx
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite path is outside project root"
    assert str(external_path) not in outcome.detail
    assert content not in outcome.detail


def test_file_write_restricted_tier_confirmer_denial_blocks_write(tmp_path):
    ctx = _file_ctx(tier="restricted", confirmer=lambda args: False, allowed_root=str(tmp_path))
    external_path = tmp_path.parent / "private-secrets" / "out.txt"
    content = "do not disclose this write payload"

    outcome = FileWriteTool().run(
        FileWriteArgs(path=str(external_path), content=content), ctx
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite was not approved by the user"
    assert str(external_path) not in outcome.detail
    assert content not in outcome.detail
    assert not (tmp_path / "out.txt").exists()


def test_file_write_restricted_tier_without_confirmer_reports_missing_channel(tmp_path):
    outcome = FileWriteTool().run(
        FileWriteArgs(path="out.txt", content="x"),
        _file_ctx(tier="restricted", allowed_root=str(tmp_path)),
    )

    assert outcome.success is False
    assert outcome.detail == "rejected: no interactive confirmation channel available"
    assert not (tmp_path / "out.txt").exists()


def test_file_write_restricted_tier_confirmer_approval_allows_write(tmp_path):
    ctx = _file_ctx(tier="restricted", confirmer=lambda args: True, allowed_root=str(tmp_path))

    outcome = FileWriteTool().run(FileWriteArgs(path="out.txt", content="x"), ctx)

    assert outcome.success is True
    assert (tmp_path / "out.txt").read_text() == "x"


def test_file_write_trusted_tier_skips_confirmer(tmp_path):
    # A confirmer that always denies — trusted tier must never consult it.
    ctx = _file_ctx(tier="trusted", confirmer=lambda args: False, allowed_root=str(tmp_path))

    outcome = FileWriteTool().run(FileWriteArgs(path="out.txt", content="x"), ctx)

    assert outcome.success is True
    assert (tmp_path / "out.txt").read_text() == "x"


def test_file_list_returns_sorted_relative_paths(tmp_path):
    (tmp_path / "b.txt").write_text("")
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "sub").mkdir()
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileListTool().run(FileListArgs(path="."), ctx)

    assert outcome.success is True
    entries = outcome.detail.splitlines()
    assert entries == sorted(entries)
    assert set(entries) == {"a.txt", "b.txt", "sub"}
    assert all(not os.path.isabs(entry) for entry in entries)


def test_file_list_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileListTool().run(FileListArgs(path=".."), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileList failed"
    assert str(tmp_path) not in outcome.detail
