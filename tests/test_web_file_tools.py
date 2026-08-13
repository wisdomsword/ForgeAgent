"""Unit tests for WebFetchTool and the File tools (M10 Phase 3/4).

Covers docs/m10-usage-observability-and-tools.md §3.4/§3.5: WebFetch's hybrid
save-to-disk + preview return and its confirmer gate (a real security boundary under
restricted/container tiers), and the three File tools' project-root lock plus
FileWrite's confirmer gate (UX-only, see FileWriteTool's docstring).

`guarded_urlopen` is monkeypatched throughout so no real network call is made; the SSRF
guard itself is covered by tests/test_ssrf_guard.py.
"""

import hashlib
import http.client
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from forgeagent.executor import TrustedBackend
from forgeagent.headless import HeadlessConfirmer, operation_key
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import (
    FileListArgs,
    FileReadArgs,
    FileWriteArgs,
    RequestFilesystemAccessArgs,
    WebFetchArgs,
)
from forgeagent.runtime import Runtime
from forgeagent.ssrf_guard import SSRFGuardError
from forgeagent.tools import (
    _MAX_FETCH_BYTES,
    CodeBlockStore,
    FileListTool,
    FileReadTool,
    FileWriteTool,
    RequestFilesystemAccessTool,
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


def test_webfetch_success_reports_continuation_after_saving_artifact(tmp_path, monkeypatch):
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
    assert outcome.truncation_mode == "head"
    assert outcome.continuation == f"完整响应已保存至 {saved[0].name}；可使用 FileRead 读取"


def test_full_disk_grant_keeps_relative_file_and_web_artifacts_project_scoped(
    tmp_path, monkeypatch, caplog
):
    project = tmp_path / "project"
    project.mkdir()
    ctx = ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=lambda args: True,
        tier="restricted",
        allowed_root=str(project),
        project_root=str(project),
        full_disk_root=project.anchor,
        full_disk_backend_factory=TrustedBackend,
    )
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: _FakeResponse(b"relative web artifact", "text/plain"),
    )

    grant = RequestFilesystemAccessTool().run(RequestFilesystemAccessArgs(path=str(tmp_path)), ctx)
    written = FileWriteTool().run(
        FileWriteArgs(path="relative.txt", content="project relative"), ctx
    )
    listed = FileListTool().run(FileListArgs(path="."), ctx)
    fetched = WebFetchTool().run(WebFetchArgs(url="https://example.com/report"), ctx)
    caplog.set_level(logging.INFO, logger="forgeagent.tools")
    read = FileReadTool().run(FileReadArgs(path="relative.txt"), ctx)

    assert grant.success is True
    assert written.success is True
    assert listed.success is True
    assert fetched.success is True
    assert read.success is True
    assert (project / "relative.txt").read_text() == "project relative"
    assert written.detail == "wrote relative.txt"
    assert listed.detail.splitlines()[0] == "relative.txt"
    assert [
        record.getMessage() for record in caplog.records if record.name == "forgeagent.tools"
    ] == ["FileRead: relative.txt"]
    assert list(project.glob("webfetch_*"))


def test_full_disk_grant_discloses_only_external_file_basename(tmp_path, caplog):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "private" / "report.txt"
    external.parent.mkdir()
    ctx = ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=lambda args: True,
        tier="restricted",
        allowed_root=str(project),
        project_root=str(project),
        full_disk_root=project.anchor,
        full_disk_backend_factory=TrustedBackend,
    )

    grant = RequestFilesystemAccessTool().run(RequestFilesystemAccessArgs(path=str(external)), ctx)
    written = FileWriteTool().run(FileWriteArgs(path=str(external), content="external result"), ctx)
    listed = FileListTool().run(FileListArgs(path=str(external.parent)), ctx)
    caplog.set_level(logging.INFO, logger="forgeagent.tools")
    read = FileReadTool().run(FileReadArgs(path=str(external)), ctx)

    assert grant.success is True
    assert written.detail == "wrote report.txt"
    assert listed.detail == "report.txt"
    assert read.success is True
    assert [
        record.getMessage() for record in caplog.records if record.name == "forgeagent.tools"
    ] == ["FileRead: report.txt"]
    assert str(external.parent) not in written.detail
    assert str(external.parent) not in listed.detail
    assert str(external.parent) not in caplog.text


def test_full_disk_grant_does_not_approve_later_file_write(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "private" / "report.txt"
    external.parent.mkdir()
    confirmations = []
    audit_events = []
    decisions = iter((True, False))

    def confirm(args):
        confirmations.append(type(args))
        return next(decisions)

    ctx = ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=confirm,
        tier="restricted",
        allowed_root=str(project),
        project_root=str(project),
        full_disk_root=project.anchor,
        full_disk_backend_factory=TrustedBackend,
        audit_sink=SimpleNamespace(emit=lambda event: audit_events.append(event) or True),
    )

    grant = RequestFilesystemAccessTool().run(RequestFilesystemAccessArgs(path=str(external)), ctx)
    written = FileWriteTool().run(FileWriteArgs(path=str(external), content="external result"), ctx)

    assert grant.success is True
    assert written.success is False
    assert confirmations == [RequestFilesystemAccessArgs, FileWriteArgs]
    assert not external.exists()
    filewrite_event = next(
        event for event in audit_events if event.parameters.get("tool") == "FileWrite"
    )
    assert filewrite_event.parameters["path"] == "report.txt"
    assert str(external.parent) not in filewrite_event.model_dump_json()


def test_webfetch_truncated_response_reports_truncated_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: _FakeResponse(b"x" * (_MAX_FETCH_BYTES + 1), "text/plain"),
    )

    outcome = WebFetchTool().run(
        WebFetchArgs(url="http://example.com/large.txt"),
        _webfetch_ctx(allowed_root=str(tmp_path)),
    )

    saved = next(tmp_path.glob("webfetch_*.txt"))
    assert saved.read_bytes() == b"x" * _MAX_FETCH_BYTES
    assert outcome.continuation == f"截断响应已保存至 {saved.name}；可使用 FileRead 读取"


def test_webfetch_success_detail_reports_utf8_artifact_byte_length(tmp_path, monkeypatch):
    secret = "supersecretvalue123"
    body = f"héllo {secret} 世界"
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda url, **kw: _FakeResponse(body.encode("utf-8"), "text/plain"),
    )
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {secret})

    outcome = WebFetchTool().run(
        WebFetchArgs(url="http://example.com/utf8.txt"),
        _webfetch_ctx(allowed_root=str(tmp_path)),
    )

    saved = next(tmp_path.glob("webfetch_*.txt"))
    saved_bytes = saved.read_bytes()
    assert outcome.success is True
    assert secret not in saved.read_text()
    assert len(saved_bytes) != len(body.encode("utf-8"))
    assert f"({len(saved_bytes)} bytes," in outcome.detail


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

    outcome = WebFetchTool().run(WebFetchArgs(url="https://secret-host.invalid/"), _webfetch_ctx())

    assert outcome.success is False
    assert outcome.detail == "WebFetch request failed"


def test_webfetch_invalid_url_value_error_is_fixed_and_does_not_raise(monkeypatch):
    def fake_open(url, **kwargs):
        raise ValueError("invalid URL")

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", fake_open)

    outcome = WebFetchTool().run(WebFetchArgs(url="https://secret-host.invalid/"), _webfetch_ctx())

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


def test_webfetch_writes_to_path_returned_by_validator(tmp_path, monkeypatch):
    url = "https://example.com/model-derived.txt"
    body = b"canonical body"
    canonical = tmp_path / "canonical-artifact.txt"
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    filename = f"webfetch_{digest}.txt"
    validated = []

    def fake_validate(path, allowed_root):
        validated.append((path, allowed_root))
        return canonical

    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda requested_url, **kwargs: _FakeResponse(body)
    )
    monkeypatch.setattr("forgeagent.tools._validate_path", fake_validate)

    outcome = WebFetchTool().run(WebFetchArgs(url=url), _webfetch_ctx(allowed_root=str(tmp_path)))

    assert validated == [(filename, str(tmp_path))]
    assert canonical.read_text() == body.decode()
    assert not (tmp_path / filename).exists()
    assert not (tmp_path / "model-derived.txt").exists()
    assert outcome.success is True


def test_webfetch_artifact_value_error_is_fixed_and_does_not_disclose(tmp_path, monkeypatch):
    sensitive_path = str(tmp_path / "host-private" / "secret.txt")
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda url, **kwargs: _FakeResponse(b"body")
    )

    with patch.object(
        Path, "write_text", side_effect=ValueError(f"invalid save path: {sensitive_path}")
    ):
        outcome = WebFetchTool().run(
            WebFetchArgs(url="https://secret-host.invalid/"),
            _webfetch_ctx(allowed_root=str(tmp_path)),
        )

    assert outcome.success is False
    assert outcome.detail == "WebFetch response save failed"
    assert sensitive_path not in outcome.detail


def test_webfetch_artifact_digest_surrogate_is_fixed_and_does_not_raise(tmp_path, monkeypatch):
    url = "https://example.com/#\ud800"
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda requested_url, **kwargs: _FakeResponse(b"body")
    )

    outcome = WebFetchTool().run(WebFetchArgs(url=url), _webfetch_ctx(allowed_root=str(tmp_path)))

    assert outcome.success is False
    assert outcome.detail == "WebFetch response save failed"
    assert url not in outcome.detail


def test_webfetch_artifact_symlink_escape_is_blocked(tmp_path, monkeypatch):
    url = "https://example.com/static-artifact"
    body = b"fetched body"
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    artifact = allowed_root / f"webfetch_{digest}.txt"
    artifact.symlink_to(outside)
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen", lambda requested_url, **kwargs: _FakeResponse(body)
    )

    outcome = WebFetchTool().run(
        WebFetchArgs(url=url), _webfetch_ctx(allowed_root=str(allowed_root))
    )

    assert outside.read_text() == "original"
    assert outcome.success is False
    assert outcome.detail == "WebFetch response save failed"


def test_full_disk_grant_keeps_relative_webfetch_symlink_project_scoped(tmp_path, monkeypatch):
    url = "https://example.com/static-artifact"
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    (project / f"webfetch_{digest}.txt").symlink_to(outside)
    monkeypatch.setattr(
        "forgeagent.tools.guarded_urlopen",
        lambda requested_url, **kwargs: _FakeResponse(b"network-body"),
    )
    ctx = ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        confirmer=lambda args: True,
        tier="restricted",
        allowed_root=str(project),
        project_root=str(project),
        full_disk_root=project.anchor,
        full_disk_backend_factory=TrustedBackend,
    )

    grant = RequestFilesystemAccessTool().run(RequestFilesystemAccessArgs(path=str(outside)), ctx)
    fetched = WebFetchTool().run(WebFetchArgs(url=url), ctx)
    escaped_read = FileReadTool().run(FileReadArgs(path="../outside.txt"), ctx)

    assert grant.success is True
    assert fetched.success is False
    assert fetched.detail == "WebFetch response save failed"
    assert escaped_read.success is False
    assert outside.read_text() == "original"


def test_webfetch_restricted_tier_confirmer_denial_blocks_fetch(monkeypatch):
    calls = []
    secret_url = (
        "https://alice:password-value@example.com/private?token=query-secret#fragment-secret"
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


def test_webfetch_passes_headless_allowlist_validator_to_redirect_guard(tmp_path, monkeypatch):
    initial_url = "https://public.example/allowed?account=public"
    redirected_url = "https://public.example/allowed?account=admin&include_secrets=true"
    seen = []

    def fake_open(url, **kwargs):
        validator = kwargs["url_validator"]
        seen.extend([validator(url), validator(redirected_url)])
        return _FakeResponse(b"ok", "text/plain")

    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", fake_open)
    initial_key = operation_key(WebFetchArgs(url=initial_url), tmp_path)
    confirmer = HeadlessConfirmer({initial_key}, audit=None, root=tmp_path)
    ctx = _webfetch_ctx(tier="restricted", confirmer=confirmer, allowed_root=str(tmp_path))

    outcome = WebFetchTool().run(WebFetchArgs(url=initial_url), ctx)

    assert outcome.success is True
    assert seen == [True, False]


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
    monkeypatch.setattr("forgeagent.tools.guarded_urlopen", lambda url, **kw: _FakeResponse(b"ok"))
    # A confirmer that always denies — trusted tier must never consult it.
    ctx = _webfetch_ctx(tier="trusted", confirmer=lambda args: False, allowed_root=str(tmp_path))

    outcome = WebFetchTool().run(WebFetchArgs(url="http://example.com/"), ctx)

    assert outcome.success is True


# --- File tools (M10 Phase 4) -------------------------------------------------


def test_file_read_within_root_masks_secrets_and_reports_continuation(tmp_path, monkeypatch):
    (tmp_path / "f.txt").write_text("token=supersecretvalue123")
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {"supersecretvalue123"})
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileReadTool().run(FileReadArgs(path="f.txt"), ctx)

    assert outcome.success is True
    assert "supersecretvalue123" not in outcome.detail
    assert "REDACTED" in outcome.detail
    assert outcome.truncation_mode == "head"
    assert outcome.continuation == (
        "Read another path with FileRead, or process this file with Exec."
    )


@pytest.mark.parametrize("tier", ["restricted", "container"])
def test_file_read_audit_logs_only_masked_canonical_project_relative_path(
    tier, tmp_path, monkeypatch, caplog
):
    secret = "known-secret-value"
    allowed_root = tmp_path / f"project-{secret}"
    report_dir = allowed_root / f"reports-{secret}"
    report_dir.mkdir(parents=True)
    (report_dir / "result.txt").write_text("unchanged file result")
    raw_model_path = str(allowed_root / "staging" / ".." / report_dir.name / "result.txt")
    confirmer_calls = []
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {secret})
    caplog.set_level(logging.INFO, logger="forgeagent.tools")
    ctx = _file_ctx(
        tier=tier,
        confirmer=lambda args: confirmer_calls.append(args) or False,
        allowed_root=str(allowed_root),
    )

    outcome = FileReadTool().run(FileReadArgs(path=raw_model_path), ctx)

    assert outcome.success is True
    assert outcome.detail == "unchanged file result"
    assert confirmer_calls == []
    records = [record for record in caplog.records if record.name == "forgeagent.tools"]
    assert [record.getMessage() for record in records] == [
        "FileRead: reports-***REDACTED***/result.txt"
    ]
    assert raw_model_path not in caplog.text
    assert str(allowed_root) not in caplog.text
    assert secret not in caplog.text


@pytest.mark.parametrize("path_kind", ["invalid", "outside"])
def test_file_read_rejected_paths_emit_no_audit_log(path_kind, tmp_path, monkeypatch, caplog):
    secret = "known-secret-value"
    allowed_root = tmp_path / "project"
    allowed_root.mkdir()
    raw_model_path = (
        f"bad\x00{secret}"
        if path_kind == "invalid"
        else str(tmp_path.parent / f"outside-{secret}" / "result.txt")
    )
    monkeypatch.setattr("forgeagent.tools.sensitive_env_values", lambda: {secret})
    caplog.set_level(logging.INFO, logger="forgeagent.tools")
    ctx = _file_ctx(
        tier="restricted",
        confirmer=lambda args: True,
        allowed_root=str(allowed_root),
    )

    outcome = FileReadTool().run(FileReadArgs(path=raw_model_path), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileRead failed"
    assert [record for record in caplog.records if record.name == "forgeagent.tools"] == []
    assert raw_model_path not in caplog.text
    assert secret not in caplog.text


def test_file_read_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileReadTool().run(FileReadArgs(path="../../etc/passwd"), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileRead failed"
    assert str(tmp_path) not in outcome.detail


def test_validate_path_accepts_descendant_when_allowed_root_is_filesystem_root(tmp_path):
    assert (
        _validate_path(str(tmp_path / "file.txt"), os.path.abspath(os.sep))
        == (tmp_path / "file.txt").resolve()
    )


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

    if operation == "write_text":
        monkeypatch.setattr("forgeagent.tools._write_file_safely", fail)
    else:
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


def test_file_write_rejects_target_symlink_created_after_validation(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-target.txt"
    outside.write_text("unchanged")
    target = tmp_path / "result.txt"
    original_validate = _validate_path

    def replace_target_after_validation(path, allowed_root):
        resolved = original_validate(path, allowed_root)
        target.symlink_to(outside)
        return resolved

    monkeypatch.setattr("forgeagent.tools._validate_path", replace_target_after_validation)

    outcome = FileWriteTool().run(
        FileWriteArgs(path="result.txt", content="overwritten"),
        _file_ctx(allowed_root=str(tmp_path)),
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite failed"
    assert outside.read_text() == "unchanged"


def test_file_write_rejects_parent_symlink_created_after_validation(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-parent"
    outside.mkdir()
    parent = tmp_path / "nested"
    parent.mkdir()
    original_validate = _validate_path

    def replace_parent_after_validation(path, allowed_root):
        resolved = original_validate(path, allowed_root)
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr("forgeagent.tools._validate_path", replace_parent_after_validation)

    outcome = FileWriteTool().run(
        FileWriteArgs(path="nested/result.txt", content="overwritten"),
        _file_ctx(allowed_root=str(tmp_path)),
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite failed"
    assert not (outside / "result.txt").exists()


def test_file_write_rejects_root_rebound_after_validation(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-root"
    outside.mkdir()
    original_root = tmp_path.parent / f"{tmp_path.name}-original-root"
    original_validate = _validate_path

    def replace_root_after_validation(path, allowed_root):
        resolved = original_validate(path, allowed_root)
        tmp_path.rename(original_root)
        tmp_path.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr("forgeagent.tools._validate_path", replace_root_after_validation)
    try:
        outcome = FileWriteTool().run(
            FileWriteArgs(path="result.txt", content="overwritten"),
            _file_ctx(allowed_root=str(tmp_path)),
        )
    finally:
        if tmp_path.is_symlink():
            tmp_path.unlink()
        if original_root.exists():
            original_root.rename(tmp_path)

    assert outcome.success is False
    assert outcome.detail == "FileWrite failed"
    assert not (outside / "result.txt").exists()


def test_file_write_rejects_non_regular_target_without_blocking(tmp_path):
    target = tmp_path / "result.pipe"
    os.mkfifo(target)

    outcome = FileWriteTool().run(
        FileWriteArgs(path="result.pipe", content="overwritten"),
        _file_ctx(allowed_root=str(tmp_path)),
    )

    assert outcome.success is False
    assert outcome.detail == "FileWrite failed"
    assert target.is_fifo()


def test_file_write_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))
    external_path = tmp_path.parent / "private-secrets" / "escape.txt"
    content = "do not disclose this write payload"

    outcome = FileWriteTool().run(FileWriteArgs(path=str(external_path), content=content), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileWrite path is outside project root"
    assert str(external_path) not in outcome.detail
    assert content not in outcome.detail


def test_file_write_restricted_tier_confirmer_denial_blocks_write(tmp_path):
    ctx = _file_ctx(tier="restricted", confirmer=lambda args: False, allowed_root=str(tmp_path))
    external_path = tmp_path.parent / "private-secrets" / "out.txt"
    content = "do not disclose this write payload"

    outcome = FileWriteTool().run(FileWriteArgs(path=str(external_path), content=content), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileWrite was not approved by the user"
    assert str(external_path) not in outcome.detail
    assert content not in outcome.detail
    assert not (tmp_path / "out.txt").exists()


def test_headless_file_write_root_mismatch_fails_closed(tmp_path):
    confirmer_root = tmp_path / "confirmed"
    context_root = tmp_path / "runtime"
    confirmer_root.mkdir()
    context_root.mkdir()
    confirmer = HeadlessConfirmer({"file/out.txt"}, audit=None, root=confirmer_root)
    ctx = _file_ctx(tier="restricted", confirmer=confirmer, allowed_root=str(context_root))

    outcome = FileWriteTool().run(FileWriteArgs(path="out.txt", content="secret"), ctx)

    assert outcome.success is False
    assert outcome.detail == "rejected: operation is not in the headless allowlist"
    assert not (confirmer_root / "out.txt").exists()
    assert not (context_root / "out.txt").exists()


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


def test_file_list_returns_sorted_relative_paths_and_reports_continuation(tmp_path):
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
    assert outcome.truncation_mode == "head"
    assert outcome.continuation == "Narrow the directory path and call FileList again."


def test_file_list_escaping_root_is_blocked(tmp_path):
    ctx = _file_ctx(allowed_root=str(tmp_path))

    outcome = FileListTool().run(FileListArgs(path=".."), ctx)

    assert outcome.success is False
    assert outcome.detail == "FileList failed"
    assert str(tmp_path) not in outcome.detail
