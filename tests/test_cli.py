"""Unit tests for the CLI (M5-2).

All tests inject a MockClient factory — no key, no network, no real subprocess. The
CLI logic under test is argument handling, run/REPL flow, outcome rendering, and clear
config-error behavior.
"""

import asyncio
import copy
import gc
import json
import logging
import stat
import sys
import threading
import time
import warnings
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest
from pydantic import BaseModel
from rich.console import Console

from forgeagent.cli import (
    build_parser,
    main,
    render_outcome,
    run_once,
)
from forgeagent.client import MockClient
from forgeagent.executor import TrustedBackend
from forgeagent.mcp_manager import MCPManager, MCPServerConfig
from forgeagent.model_registry import RegistryError
from forgeagent.models import AssistantMessage, StreamEvent, StreamEventKind, TokenUsage
from forgeagent.protocol import FileListArgs, FileWriteArgs, MCPArgs, ToolCall, WebFetchArgs
from forgeagent.runtime import Runtime
from forgeagent.step import RoundResult, Step, Termination
from forgeagent.task import TaskOutcome, TaskStatus
from forgeagent.tools import ToolOutcome


def _reply(
    text: str, stop_reason: str = "end_turn", usage: TokenUsage | None = None
) -> AssistantMessage:
    return AssistantMessage(content=text, usage=usage or TokenUsage(), stop_reason=stop_reason)


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\n"


def _factory(script):
    # Trusted tier keeps CLI tests in-process/fast; the CLI wiring is what's under test.
    return lambda model: MockClient(script=script)


def _console() -> Console:
    # record=True lets us assert on rendered text without a real terminal.
    return Console(record=True, width=100, force_terminal=False)


class _UnknownConfirmationArgs(BaseModel):
    secret: str


def test_confirmation_summary_masks_nested_mcp_secret_arguments(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {"known-secret-value"})
    summary = _confirmation_summary(
        MCPArgs(
            server="github",
            tool="create_issue",
            arguments={
                "token": "nested-token",
                "settings": {"password": "nested-password", "safe": "known-secret-value"},
                "items": [{"key": "nested-key"}],
            },
        )
    )

    for secret in ("nested-token", "nested-password", "known-secret-value", "nested-key"):
        assert secret not in summary
    assert "<redacted>" in summary


def _mcp_summary_arguments(summary: str) -> dict:
    return json.loads(summary.split(" ", 2)[2])


def test_confirmation_summary_preserves_top_level_colliding_mcp_argument_labels(
    monkeypatch,
):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    raw_arguments = {
        f"unsafe-{secret}": "public-left",
        "unsafe-***REDACTED***": "public-right",
        "api_token": "hidden-token",
    }
    original_arguments = raw_arguments.copy()
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(
        MCPArgs(server="github", tool="create_issue", arguments=raw_arguments)
    )
    displayed = _mcp_summary_arguments(summary)

    assert raw_arguments == original_arguments
    assert secret not in summary
    assert "hidden-token" not in summary
    assert displayed["unsafe-***REDACTED***"] == "public-left"
    assert displayed["unsafe-***REDACTED*** 2"] == "public-right"
    assert displayed["api_token"] == "<redacted>"


def test_confirmation_summary_preserves_nested_colliding_mcp_argument_labels(
    monkeypatch,
):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    raw_arguments = {
        "outer": {
            f"field-{secret}": "public-nested-left",
            "field-***REDACTED***": "public-nested-right",
            "password": "hidden-password",
        },
        "items": [
            {
                f"item-{secret}": "public-list-left",
                "item-***REDACTED***": "public-list-right",
            }
        ],
    }
    original_arguments = copy.deepcopy(raw_arguments)
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(
        MCPArgs(server="github", tool="create_issue", arguments=raw_arguments)
    )
    displayed = _mcp_summary_arguments(summary)

    assert raw_arguments == original_arguments
    assert secret not in summary
    assert "hidden-password" not in summary
    assert displayed["outer"]["field-***REDACTED***"] == "public-nested-left"
    assert displayed["outer"]["field-***REDACTED*** 2"] == "public-nested-right"
    assert displayed["outer"]["password"] == "<redacted>"
    assert displayed["items"][0]["item-***REDACTED***"] == "public-list-left"
    assert displayed["items"][0]["item-***REDACTED*** 2"] == "public-list-right"


def test_confirmation_summary_redacts_url_userinfo_and_sensitive_query(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {"known-secret-value"})
    summary = _confirmation_summary(
        WebFetchArgs(
            url="https://alice:password-value@example.com/path?token=query-token&q=known-secret-value"
        )
    )

    for secret in ("alice", "password-value", "query-token", "known-secret-value"):
        assert secret not in summary
    assert "example.com/path" in summary


def test_confirmation_summary_masks_known_secret_in_url_hostname(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(WebFetchArgs(url=f"https://{secret}.example.com/public"))

    assert secret not in summary
    assert "example.com/public" in summary
    assert "REDACTED" in summary


@pytest.mark.parametrize(
    ("secret", "url"),
    [
        ("OPAQUE-VALUE-12345", "https://opaque-value-12345.example.com/public"),
        ("opaque-value-12345", "https://%6fpaque-value-12345.example.com/public"),
    ],
)
def test_confirmation_summary_masks_case_and_percent_encoded_hostname(secret, url, monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})
    summary = _confirmation_summary(WebFetchArgs(url=url))

    assert secret.casefold() not in unquote(summary).casefold()
    assert "REDACTED" in unquote(summary)


@pytest.mark.parametrize("encoded", ["%40", "%2F", "%3F", "%23", "%3A"])
def test_confirmation_summary_does_not_reinterpret_encoded_hostname_delimiters(encoded):
    from forgeagent.cli import _confirmation_summary

    summary = _confirmation_summary(WebFetchArgs(url=f"https://safe{encoded}host/public"))

    assert summary == "WebFetch <redacted malformed URL>"


def test_confirmation_summary_handles_ipv6_zone_and_masks_each_component_once(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})
    summary = _confirmation_summary(
        WebFetchArgs(
            url=("https://[fe80::1%25en0]/opaque-value-12345?q=opaque-value-12345#discard-me")
        )
    )
    rendered = unquote(summary)

    assert "[fe80::1%en0]" in rendered
    assert secret not in rendered
    assert rendered.count("***REDACTED***") == 2
    assert "discard-me" not in rendered


def test_confirmation_summary_prefers_longest_overlapping_hostname_secret(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr(
        "forgeagent.cli.sensitive_env_values",
        lambda: {"opaque-value-12345", "value-12345"},
    )
    rendered = unquote(
        _confirmation_summary(WebFetchArgs(url="https://opaque-value-12345.example.com/public"))
    )

    assert rendered.count("***REDACTED***") == 1
    assert "value-12345" not in rendered


def test_confirmation_summary_masks_known_secret_in_query_key(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(
        WebFetchArgs(url=f"https://example.com/public?{secret}=visible")
    )

    assert secret not in summary
    assert parse_qsl(urlsplit(summary.removeprefix("WebFetch ")).query) == [
        ("***REDACTED***", "visible")
    ]


def test_confirmation_summary_masks_known_secret_in_percent_encoded_path(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(
        WebFetchArgs(url="https://example.com/public/opaque%20value-12345/file")
    )
    path = urlsplit(summary.removeprefix("WebFetch ")).path

    assert secret not in summary
    assert "opaque%20value-12345" not in summary
    assert path == "/public/%2A%2A%2AREDACTED%2A%2A%2A/file"
    assert unquote(path) == "/public/***REDACTED***/file"


def test_confirmation_summary_preserves_duplicate_query_order(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "opaque-value-12345"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(
        WebFetchArgs(url=f"https://example.com/public?{secret}=first&token=hidden&{secret}=second")
    )

    assert parse_qsl(urlsplit(summary.removeprefix("WebFetch ")).query) == [
        ("***REDACTED***", "first"),
        ("token", "REDACTED"),
        ("***REDACTED***", "second"),
    ]


def test_confirmation_summary_removes_url_userinfo_entirely(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: set())

    summary = _confirmation_summary(
        WebFetchArgs(url="https://alice:password-value@example.com/public")
    )

    assert "alice" not in summary
    assert "password-value" not in summary
    assert "@" not in summary
    assert "example.com/public" in summary


def test_confirmation_summary_redacts_url_fragment(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: set())
    summary = _confirmation_summary(
        WebFetchArgs(url="https://example.com/public#fragment-secret-value")
    )

    assert "example.com/public" in summary
    assert "fragment-secret-value" not in summary
    assert "#" not in summary
    assert urlsplit(summary.removeprefix("WebFetch ")).fragment == ""


@pytest.mark.parametrize(
    "url",
    [
        "https:///sensitive/path#fragment-secret-value",
        "sensitive/path?token=query-secret#fragment-secret-value",
        "https://[malformed/sensitive/path#fragment-secret-value",
    ],
)
def test_confirmation_summary_never_echoes_malformed_url_material(url):
    from forgeagent.cli import _confirmation_summary

    summary = _confirmation_summary(WebFetchArgs(url=url))

    assert summary == "WebFetch <redacted malformed URL>"


@pytest.mark.parametrize(
    "url",
    [
        "https://surrogate-secret-value\ud800.example.com/public",
        "https://example.com/surrogate-secret-value\ud800/public",
        "https://example.com/public?q=surrogate-secret-value\ud800",
    ],
    ids=["hostname", "path", "query"],
)
def test_confirmation_summary_contains_unpaired_surrogate_in_url_components(
    monkeypatch,
    url,
):
    from forgeagent.cli import _confirmation_summary

    secret = "surrogate-secret-value"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})

    summary = _confirmation_summary(WebFetchArgs(url=url))

    assert summary == "WebFetch <redacted malformed URL>"
    assert summary.isascii()
    assert secret not in summary


def test_confirmation_summary_preserves_normalized_project_relative_filewrite_path(
    tmp_path, monkeypatch
):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.chdir(tmp_path)
    content = "do not disclose this write payload"
    summary = _confirmation_summary(
        FileWriteArgs(path="notes/../reports/report.txt", content=content)
    )

    assert content not in summary
    assert "reports/report.txt" in summary
    assert str(len(content)) in summary


def test_filewrite_confirmation_labels_unicode_character_count():
    from forgeagent.cli import _confirmation_summary

    summary = _confirmation_summary(FileWriteArgs(path="out.txt", content="\u4f60\u597d"))

    assert summary.endswith("(2 characters)")


def test_confirmation_summary_shows_cwd_contained_absolute_filewrite_path_as_relative(
    tmp_path, monkeypatch
):
    from forgeagent.cli import _confirmation_summary

    monkeypatch.chdir(tmp_path)
    summary = _confirmation_summary(
        FileWriteArgs(path=str(tmp_path / "reports" / "report.txt"), content="x")
    )

    assert "reports/report.txt" in summary
    assert str(tmp_path) not in summary


def test_confirmation_summary_limits_external_filewrite_path_to_basename(tmp_path, monkeypatch):
    from forgeagent.cli import _confirmation_summary

    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    external_path = tmp_path / "private-secrets" / "report.txt"

    summary = _confirmation_summary(FileWriteArgs(path=str(external_path), content="x"))

    assert ".../report.txt" in summary
    assert str(external_path.parent) not in summary


def test_confirmation_summary_limits_unknown_models_to_type_name():
    from forgeagent.cli import _confirmation_summary

    summary = _confirmation_summary(_UnknownConfirmationArgs(secret="do not disclose"))

    assert summary == "_UnknownConfirmationArgs"


def test_console_confirmer_rejects_eof_empty_and_other_input():
    from forgeagent.cli import make_console_confirmer

    args = MCPArgs(server="github", tool="delete_issue")
    for read_line in (
        lambda prompt: (_ for _ in ()).throw(EOFError),
        lambda prompt: "",
        lambda prompt: "no",
    ):
        assert make_console_confirmer(_console(), read_line)(args) is False


def test_console_confirmer_accepts_trimmed_yes():
    from forgeagent.cli import make_console_confirmer

    confirmer = make_console_confirmer(_console(), lambda prompt: " y\n")
    assert confirmer(MCPArgs(server="github", tool="create_issue")) is True


def test_confirmation_summary_masks_known_secrets_in_identifiers_keys_and_file_paths(monkeypatch):
    from forgeagent.cli import _confirmation_summary

    secret = "known-secret-value"
    monkeypatch.setattr("forgeagent.cli.sensitive_env_values", lambda: {secret})
    summaries = [
        _confirmation_summary(
            MCPArgs(
                server=f"server-{secret}",
                tool=f"tool-{secret}",
                arguments={f"key-{secret}": {"safe": secret}},
            )
        ),
        _confirmation_summary(FileWriteArgs(path=f"reports/{secret}.txt", content="hidden")),
        _confirmation_summary(FileWriteArgs(path=f"/private/{secret}.txt", content="hidden")),
    ]

    assert all(secret not in summary for summary in summaries)
    assert "<redacted>" in summaries[0]
    assert "***REDACTED***" in summaries[1]
    assert "***REDACTED***" in summaries[2]
    assert "hidden" not in "\n".join(summaries)


@pytest.mark.parametrize(
    "unsafe",
    [
        "bad[/red]",
        "[bold]fake[/bold]",
        "\x1b[31mred\x1b[0m",
        "before\rafter\nnext",
        "line\u2028separator\u2029end",
        "rtl\u202evalue",
        "isolate\u2066value\u2069",
        "mark\u200evalue",
        "surrogate\ud800value",
    ],
)
def test_console_confirmer_renders_unsafe_confirmation_values_as_literal_single_lines(unsafe):
    from forgeagent.cli import make_console_confirmer

    console = Console(record=True, width=1000, force_terminal=False)
    reads = 0

    def read_line(prompt):
        nonlocal reads
        reads += 1
        return "y"

    mcp_args = MCPArgs.model_construct(
        server=unsafe,
        tool=unsafe,
        arguments={unsafe: {"nested": unsafe}},
    )
    filewrite_args = FileWriteArgs.model_construct(path=unsafe, content="not displayed")
    assert make_console_confirmer(console, read_line)(mcp_args)
    assert make_console_confirmer(console, read_line)(filewrite_args)

    rendered = console.export_text()
    expected = unsafe.encode("unicode_escape").decode("ascii")
    assert reads == 2
    assert "approve" in rendered
    assert "not displayed" not in rendered
    assert expected in rendered
    assert len(rendered.splitlines()) == 2
    assert all(ord(char) >= 32 or char == "\n" for char in rendered)


# --- single-command run ------------------------------------------------------


def test_run_once_completes(monkeypatch):
    console = _console()
    outcome = run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done())]),
        console=console,
    )
    assert outcome.status.completed is True
    assert "completed" in console.export_text()


def _exec_call(code: str) -> str:
    import json

    return f"<!-- ToolCall: {json.dumps({'name': 'Exec', 'arguments': {'code': code}})} -->"


def test_run_once_renders_exec_output():
    console = _console()
    run_once(
        "print hi",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_exec_call("print('hi')")), _reply(_done())]),
        console=console,
    )
    assert "hi" in console.export_text()


def test_render_outcome_discloses_only_fixed_webfetch_failure_detail():
    secret_url = "https://secret-host.invalid/private?token=secret-value"
    console = _console()
    outcome = TaskOutcome(
        status=TaskStatus(completed=False, reason=Termination.MAX_ROUNDS),
        rounds=[
            RoundResult(
                text="",
                outcomes=[
                    ToolOutcome(tool="WebFetch", success=False, detail="WebFetch request failed")
                ],
            )
        ],
    )

    render_outcome(outcome, console)

    rendered = console.export_text()
    assert "WebFetch request failed" in rendered
    assert secret_url not in rendered


def test_render_outcome_discloses_only_real_filelist_failure_detail(tmp_path):
    outside_path = tmp_path.parent / f"{tmp_path.name}-private"
    outside_path.mkdir()
    step = Step(
        MockClient([]),
        TrustedBackend(),
        Runtime(),
        tier="trusted",
        allowed_root=str(tmp_path),
    )
    file_list_outcome = step._dispatch(
        ToolCall(
            id="list-outside",
            name="FileList",
            arguments=FileListArgs(path=str(outside_path)),
        )
    )
    console = Console(
        record=True,
        width=max(100, len(str(outside_path)) + 80),
        force_terminal=False,
    )
    outcome = TaskOutcome(
        status=TaskStatus(completed=False, reason=Termination.MAX_ROUNDS),
        rounds=[
            RoundResult(
                text="",
                outcomes=[file_list_outcome],
            )
        ],
    )

    render_outcome(outcome, console)

    rendered = console.export_text()
    assert file_list_outcome.success is False
    assert "FileList failed" in rendered
    assert str(outside_path) not in rendered


def test_run_once_renders_plain_text_answer_without_exec():
    # A model can answer in prose and signal completion without ever calling Exec
    # (e.g. gpt-5.4-mini answering "60" directly). render_outcome must still show
    # that text -- there's no tool outcome to fall back on.
    console = _console()
    run_once(
        "compute 10 + 20 + 30",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory(
            [_reply("---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\n60")]
        ),
        console=console,
    )
    assert "60" in console.export_text()


def test_run_once_prints_usage_status_line():
    console = _console()
    usage = TokenUsage(input_tokens=1234, output_tokens=567, cached_tokens=89)
    run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done(), usage=usage)]),
        console=console,
    )
    assert "usage: in=1234 out=567 cached=89 reasoning=0 (session total)" in console.export_text()


def test_run_once_accumulates_usage_across_rounds_in_one_task():
    console = _console()
    round_one_usage = TokenUsage(input_tokens=10, output_tokens=5)
    round_one = _reply(_exec_call("print('hi')"), usage=round_one_usage)
    round_two = _reply(_done(), usage=TokenUsage(input_tokens=8, output_tokens=3, cached_tokens=2))
    run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([round_one, round_two]),
        console=console,
    )
    assert "usage: in=18 out=8 cached=2 reasoning=0 (session total)" in console.export_text()


def test_run_once_prints_nonzero_reasoning_tokens():
    # design doc §3.4: reasoning/thinking output is billable and must show up in the
    # CLI usage line, not just be tracked internally on TokenUsage.
    console = _console()
    usage = TokenUsage(input_tokens=10, output_tokens=5, reasoning_tokens=42)
    run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done(), usage=usage)]),
        console=console,
    )
    assert "reasoning=42" in console.export_text()


def test_main_run_returns_zero_on_completion():
    code = main(
        ["run", "goal"],
        client_factory=_factory([_reply(_done())]),
    )
    assert code == 0


def test_main_run_returns_one_when_not_completed():
    # Refusal -> not solved -> exit code 1.
    code = main(
        ["run", "goal"],
        client_factory=_factory([_reply("cannot", stop_reason="refusal")]),
    )
    assert code == 1


class _RequiredStartupFailureManager:
    instances: list["_RequiredStartupFailureManager"] = []

    def __init__(self, servers):
        self.closed = False
        self.connected = False
        self.__class__.instances.append(self)

    @property
    def has_enabled_servers(self):
        return True

    def connect(self):
        self.connected = True

    def required_failures(self):
        return {
            "zeta": "unavailable: connection refused",
            "alpha": "unavailable: handshake failed",
        }

    def server_status(self):
        return self.required_failures()

    def close(self):
        self.closed = True


class _CleanupFailureRequiredStartupManager(_RequiredStartupFailureManager):
    cleanup_error: type[BaseException] = RuntimeError

    def close(self):
        super().close()
        raise self.cleanup_error("cleanup failed")


def test_build_mcp_manager_closes_and_raises_for_required_failures(monkeypatch):
    import forgeagent.cli as cli_module

    _RequiredStartupFailureManager.instances.clear()
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _RequiredStartupFailureManager)

    with pytest.raises(RuntimeError) as error:
        cli_module.build_mcp_manager(_console())

    assert _RequiredStartupFailureManager.instances[0].closed is True
    message = str(error.value)
    assert message.index("alpha: unavailable: handshake failed") < message.index(
        "zeta: unavailable: connection refused"
    )


def test_build_mcp_manager_skips_constructor_when_all_servers_are_disabled(monkeypatch):
    import forgeagent.cli as cli_module

    calls: list[str] = []

    class ManagerSpy:
        def __init__(self, servers):
            calls.append("construct")

        def connect(self):
            calls.append("connect")

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {
            "required": MCPServerConfig(
                command="unused",
                enabled=False,
                required=True,
            )
        },
    )
    monkeypatch.setattr(cli_module, "MCPManager", ManagerSpy)

    assert cli_module.build_mcp_manager(_console()) is None
    assert calls == []


def test_build_mcp_manager_preserves_startup_error_when_cleanup_raises(monkeypatch):
    import forgeagent.cli as cli_module

    _CleanupFailureRequiredStartupManager.instances.clear()
    monkeypatch.setattr(_CleanupFailureRequiredStartupManager, "cleanup_error", RuntimeError)
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _CleanupFailureRequiredStartupManager)

    with pytest.raises(cli_module.MCPStartupError) as error:
        cli_module.build_mcp_manager(_console())

    assert _CleanupFailureRequiredStartupManager.instances[0].closed is True
    assert str(error.value).startswith("alpha: unavailable: handshake failed")


def test_build_mcp_manager_preserves_required_startup_error_when_cleanup_is_cancelled(
    monkeypatch,
):
    import forgeagent.cli as cli_module

    _CleanupFailureRequiredStartupManager.instances.clear()
    monkeypatch.setattr(
        _CleanupFailureRequiredStartupManager,
        "cleanup_error",
        asyncio.CancelledError,
    )
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _CleanupFailureRequiredStartupManager)

    with pytest.raises(cli_module.MCPStartupError) as error:
        cli_module.build_mcp_manager(_console())

    assert _CleanupFailureRequiredStartupManager.instances[0].closed is True
    assert str(error.value).startswith("alpha: unavailable: handshake failed")


@pytest.mark.parametrize("failure_kind", ["connect", "required"])
def test_build_mcp_manager_logs_non_control_cleanup_type_without_replacing_primary(
    monkeypatch,
    caplog,
    failure_kind,
):
    import forgeagent.cli as cli_module

    secret = "cleanup-warning-secret"

    class CleanupFailureManager:
        def __init__(self, servers):
            self.closed = False

        @property
        def has_enabled_servers(self):
            return True

        def connect(self):
            if failure_kind == "connect":
                raise RuntimeError("primary startup failure")

        def required_failures(self):
            if failure_kind == "required":
                return {"required": "unavailable: RuntimeError"}
            return {}

        def close(self):
            self.closed = True
            raise asyncio.CancelledError(f"cleanup failed: {secret}")

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", CleanupFailureManager)
    caplog.set_level(logging.WARNING, logger="forgeagent.cli")

    with pytest.raises(cli_module.MCPStartupError) as raised:
        cli_module.build_mcp_manager(_console())

    expected_primary = (
        "MCP manager startup failed: RuntimeError"
        if failure_kind == "connect"
        else "required: unavailable: RuntimeError"
    )
    assert str(raised.value) == expected_primary
    assert caplog.messages == [f"MCP {failure_kind} cleanup failed: CancelledError"]
    assert secret not in caplog.text


@pytest.mark.parametrize("cleanup_error", [KeyboardInterrupt, SystemExit])
def test_build_mcp_manager_does_not_swallow_base_cleanup_errors(monkeypatch, cleanup_error):
    import forgeagent.cli as cli_module

    _CleanupFailureRequiredStartupManager.instances.clear()
    monkeypatch.setattr(_CleanupFailureRequiredStartupManager, "cleanup_error", cleanup_error)
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _CleanupFailureRequiredStartupManager)

    with pytest.raises(cleanup_error, match="cleanup failed"):
        cli_module.build_mcp_manager(_console())


def test_optional_status_does_not_expose_secret_exception_text(monkeypatch):
    import forgeagent.cli as cli_module
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.mcp_manager import MCPManager, MCPServerConfig

    secret = "optional-status-secret"
    command = "/tmp/optional-secret-command"
    argument = "--token=optional-secret-argument"
    raw_status = (
        f"unavailable: RuntimeError: {secret} command={command} "
        f"args={argument} env=optional-secret-env"
    )

    class OptionalSecretStatusManager(MCPManager):
        def connect(self):
            self._states["optional"].status = raw_status

    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"optional": MCPServerConfig(command="unused")},
    )
    monkeypatch.setattr(cli_module, "MCPManager", OptionalSecretStatusManager)

    console = _console()
    manager = cli_module.build_mcp_manager(console)
    assert manager is not None
    try:
        repl_console = _console()
        cli_module._handle_mcp_command("mcp status", manager, repl_console)
    finally:
        manager.close()

    rendered = console.export_text() + repl_console.export_text()
    assert "optional: unavailable: RuntimeError" in rendered
    for secret_text in (secret, command, argument, "optional-secret-env"):
        assert secret_text not in rendered


def test_build_mcp_manager_maps_connect_infrastructure_error_after_cleanup(monkeypatch):
    import forgeagent.cli as cli_module

    startup_error = RuntimeError("startup-secret command=/tmp/secret --token=secret")

    class InfrastructureFailureManager:
        instance = None

        def __init__(self, servers):
            self.closed = False
            self.__class__.instance = self

        @property
        def has_enabled_servers(self):
            return True

        def connect(self):
            raise startup_error

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", InfrastructureFailureManager)

    with pytest.raises(cli_module.MCPStartupError) as raised:
        cli_module.build_mcp_manager(_console())

    assert InfrastructureFailureManager.instance.closed is True
    assert str(raised.value) == "MCP manager startup failed: RuntimeError"
    assert "startup-secret" not in str(raised.value)


def test_build_mcp_manager_does_not_close_manager_already_closed_by_connect(monkeypatch):
    import forgeagent.cli as cli_module

    class SelfClosingInfrastructureFailureManager:
        instance = None

        def __init__(self, servers):
            self._closed = False
            self.close_calls = 0
            self.__class__.instance = self

        @property
        def has_enabled_servers(self):
            return True

        def connect(self):
            self.close()
            raise RuntimeError("startup failure")

        def close(self):
            self.close_calls += 1
            self._closed = True

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", SelfClosingInfrastructureFailureManager)

    with pytest.raises(cli_module.MCPStartupError):
        cli_module.build_mcp_manager(_console())

    assert SelfClosingInfrastructureFailureManager.instance.close_calls == 1


def test_build_mcp_manager_masks_sensitive_required_server_identity(monkeypatch):
    import forgeagent.cli as cli_module
    import forgeagent.mcp_manager as mcp_manager_module

    secret = "required-server-secret"
    server = f"external-{secret}"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {server: MCPServerConfig(command="unused", required=True)},
    )

    def fail_required(self):
        self._states[server].status = "unavailable: RuntimeError"

    monkeypatch.setattr(cli_module.MCPManager, "connect", fail_required)

    with pytest.raises(cli_module.MCPStartupError) as raised:
        cli_module.build_mcp_manager(_console())

    assert secret not in str(raised.value)
    assert "external-***REDACTED***" in str(raised.value)


@pytest.mark.parametrize(
    ("cleanup_error", "expected_error"),
    [
        (asyncio.CancelledError, None),
        (KeyboardInterrupt, KeyboardInterrupt),
        (SystemExit, SystemExit),
    ],
)
def test_build_mcp_manager_connect_cleanup_only_propagates_process_control(
    monkeypatch, cleanup_error, expected_error
):
    import forgeagent.cli as cli_module

    class InfrastructureFailureManager:
        def __init__(self, servers):
            pass

        @property
        def has_enabled_servers(self):
            return True

        def connect(self):
            raise RuntimeError("primary startup failure")

        def close(self):
            raise cleanup_error("cleanup failure")

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", InfrastructureFailureManager)

    if expected_error is None:
        with pytest.raises(cli_module.MCPStartupError) as raised:
            cli_module.build_mcp_manager(_console())
        assert str(raised.value) == "MCP manager startup failed: RuntimeError"
    else:
        with pytest.raises(expected_error, match="cleanup failure"):
            cli_module.build_mcp_manager(_console())


def test_main_reports_required_mcp_startup_error_without_running_task(monkeypatch):
    import forgeagent.cli as cli_module

    console = _console()
    ran_task: list[bool] = []
    _RequiredStartupFailureManager.instances.clear()
    monkeypatch.setattr(cli_module, "Console", lambda: console)
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _RequiredStartupFailureManager)

    def run_once(*args, **kwargs):
        from types import SimpleNamespace

        ran_task.append(True)
        return SimpleNamespace(status=SimpleNamespace(solved=True))

    monkeypatch.setattr(cli_module, "run_once", run_once)

    assert cli_module.main(["run", "goal"], client_factory=_factory([])) == 2
    assert ran_task == []
    assert "MCP startup error" in console.export_text()


def test_required_mcp_startup_error_uses_only_server_status(monkeypatch):
    import forgeagent.cli as cli_module

    secret = "opaque-secret-value"
    _RequiredStartupFailureManager.instances.clear()
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {
            "required": MCPServerConfig(
                command="unused",
                env={"TOKEN": secret},
                required=True,
            )
        },
    )
    monkeypatch.setattr(cli_module, "MCPManager", _RequiredStartupFailureManager)

    with pytest.raises(RuntimeError) as error:
        cli_module.build_mcp_manager(_console())

    assert secret not in str(error.value)


def test_main_run_wires_confirmer_only_with_terminal_console_and_tty_stdin(monkeypatch):
    import forgeagent.cli as cli_module

    seen: list[object] = []
    real_run_once = cli_module.run_once
    console = Console(record=True, force_terminal=True)

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["confirmer"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "Console", lambda: console)
    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    assert main(["run", "goal"], client_factory=_factory([_reply(_done())])) == 0
    assert callable(seen[0])


def test_main_run_omits_confirmer_without_terminal_console(monkeypatch):
    import forgeagent.cli as cli_module

    class _MCP:
        def tools_prompt(self):
            return ""

        def close(self):
            pass

    seen: list[object] = []
    real_run_once = cli_module.run_once

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["confirmer"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "Console", lambda: Console(record=True, force_terminal=False))
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: _MCP())
    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    assert main(["run", "goal"], client_factory=_factory([_reply(_done())])) == 0
    assert seen == [None]


def test_main_run_omits_confirmer_without_tty_even_if_interactive(monkeypatch):
    import forgeagent.cli as cli_module

    seen: list[tuple[object, object]] = []
    real_run_once = cli_module.run_once
    console = Console(record=True, force_terminal=True)

    def spy_run_once(*args, **kwargs):
        seen.append((kwargs["asker"], kwargs["confirmer"]))
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "Console", lambda: console)
    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert main(["run", "--interactive", "goal"], client_factory=_factory([_reply(_done())])) == 0
    assert callable(seen[0][0])
    assert seen[0][1] is None


# --- tier / argument parsing -------------------------------------------------


def test_parser_defaults_to_restricted():
    args = build_parser().parse_args(["run", "x"])
    assert args.tier == "restricted"


def test_parser_trusted_selectable():
    args = build_parser().parse_args(["--tier", "trusted", "run", "x"])
    assert args.tier == "trusted"


def test_parser_container_selectable_with_image():
    args = build_parser().parse_args(
        ["--tier", "container", "--container-image", "python:3.12-slim", "run", "x"]
    )
    assert args.tier == "container"
    assert args.container_image == "python:3.12-slim"
    # Default image is None -> ContainerBackend's own default applies.
    assert build_parser().parse_args(["run", "x"]).container_image is None


def test_parser_model_override():
    args = build_parser().parse_args(["--model", "claude-haiku-4-5", "run", "x"])
    assert args.model == "claude-haiku-4-5"


def test_parser_stream_flag_defaults_off_and_is_settable():
    assert build_parser().parse_args(["run", "x"]).stream is False
    assert build_parser().parse_args(["--stream", "run", "x"]).stream is True


# --- streaming (M9 Phase 3) ---------------------------------------------------


def _make_terminal_console() -> Console:
    # force_terminal=True makes console.is_terminal True regardless of the underlying
    # file, so the Live-based streaming path is exercised without a real TTY.
    return Console(record=True, width=100, force_terminal=True)


class _StreamOnlyClient(MockClient):
    """A MockClient whose complete() raises -- proving a --stream run never falls back
    to the non-streaming path -- and whose stream() replays a scripted reply."""

    def __init__(self, reply: AssistantMessage, thinking: str = ""):
        super().__init__(script=[])
        self._reply = reply
        self._thinking = thinking

    def complete(self, messages, params=None):
        raise AssertionError("complete() must not be called when stream=True")

    def stream(self, messages, params=None):
        if self._thinking:
            yield StreamEvent(kind=StreamEventKind.THINKING_DELTA, text=self._thinking)
        yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, text=self._reply.content)
        yield StreamEvent(kind=StreamEventKind.DONE, message=self._reply)


def test_make_stream_callback_styles_thinking_dim_and_text_plain():
    from forgeagent.cli import _make_stream_callback

    console = _make_terminal_console()
    live, on_delta = _make_stream_callback(console)
    with live:
        on_delta("pondering ", StreamEventKind.THINKING_DELTA)
        on_delta("answer", StreamEventKind.TEXT_DELTA)
    styled = console.export_text(styles=True)
    assert "pondering" in styled and "answer" in styled
    # THINKING_DELTA is wrapped in a dim SGR code; TEXT_DELTA's "answer" is not.
    assert "\x1b[2mpondering " in styled
    assert "\x1b[2manswer" not in styled


def test_run_once_stream_true_on_terminal_console_uses_stream_not_complete():
    console = _make_terminal_console()
    client = _StreamOnlyClient(_reply(_done()), thinking="thinking...")
    outcome = run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=lambda model: client,
        console=console,
        stream=True,
    )
    assert outcome.status.completed is True
    assert "completed" in console.export_text()


def test_run_once_stream_true_on_non_terminal_console_degrades_to_complete():
    # _console() (no force_terminal) is not attached to a real terminal, so stream=True
    # must auto-degrade: complete() is used, never stream() (design doc §3.3).
    class _CompleteOnlyClient(MockClient):
        def stream(self, messages, params=None):
            raise AssertionError("stream() must not be called when console.is_terminal is False")

    console = _console()
    assert console.is_terminal is False
    outcome = run_once(
        "do a thing",
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=lambda model: _CompleteOnlyClient(script=[_reply(_done())]),
        console=console,
        stream=True,
    )
    assert outcome.status.completed is True


def test_repl_stream_true_threads_into_run_once(tmp_path):
    from forgeagent.cli import repl

    client = _StreamOnlyClient(_reply(_done()))
    console = _make_terminal_console()
    inputs = iter(["do a thing", ""])
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=lambda model: client,
        console=console,
        read_line=lambda prompt: next(inputs),
        stream=True,
    )
    assert "completed" in console.export_text()


def test_main_run_threads_stream_flag_into_run_once(monkeypatch):
    # main() builds its own plain Console() (no force_terminal), so this checks the
    # --stream flag reaches run_once's `stream` kwarg, not the Live-rendering path
    # itself (covered by the run_once/repl tests above).
    seen_stream: list[bool] = []
    import forgeagent.cli as cli_module

    real_run_once = cli_module.run_once

    def spy_run_once(*args, **kwargs):
        seen_stream.append(kwargs.get("stream", False))
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    code = main(
        ["--stream", "run", "goal"],
        client_factory=_factory([_reply(_done())]),
    )
    assert code == 0
    assert seen_stream == [True]


# --- REPL --------------------------------------------------------------------


def test_repl_runs_then_exits_on_blank():
    from forgeagent.cli import repl

    inputs = iter(["do thing", ""])  # one goal, then blank to exit
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done())]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "completed" in console.export_text()


def test_repl_wires_confirmer_without_mcp_manager(monkeypatch):
    import forgeagent.cli as cli_module

    seen: list[object] = []
    real_run_once = cli_module.run_once
    inputs = iter(["do thing", ""])

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["confirmer"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: None)
    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done())]),
        console=_console(),
        read_line=lambda prompt: next(inputs),
        confirmation_available=True,
    )

    assert callable(seen[0])


def test_repl_exits_on_quit():
    from forgeagent.cli import repl

    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),  # never called — quits immediately
        console=console,
        read_line=lambda prompt: "quit",
    )
    # No task ran; just the banner.
    assert "REPL" in console.export_text()


def test_repl_accumulates_usage_across_tasks_in_one_session():
    from forgeagent.cli import repl

    # repl() calls client_factory once per task, so each task needs its own script --
    # unlike _factory (which replays the same script from index 0 on every call).
    per_task_scripts = iter(
        [
            [_reply(_done(), usage=TokenUsage(input_tokens=10, output_tokens=5, cached_tokens=1))],
            [_reply(_done(), usage=TokenUsage(input_tokens=20, output_tokens=7, cached_tokens=3))],
        ]
    )
    inputs = iter(["first goal", "second goal", ""])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=lambda model: MockClient(script=next(per_task_scripts)),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    # First task's total is printed after task 1, then the running total after task 2
    # reflects both tasks combined (session total, not reset per goal).
    assert "usage: in=10 out=5 cached=1 reasoning=0 (session total)" in text
    assert "usage: in=30 out=12 cached=4 reasoning=0 (session total)" in text


def test_repl_reload_unchanged_identity_does_not_reconfirm(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forgeagent").mkdir()
    (project / ".forgeagent" / "AGENTS.md").write_text("VERSION ONE")

    monkeypatch.setattr(cli_module.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(project)

    confirm_count = {"n": 0}
    goal_inputs = iter(["/reload", "quit"])

    def read_line(prompt: str) -> str:
        if prompt.startswith("inject"):
            confirm_count["n"] += 1
            return "y"
        return next(goal_inputs)

    cli_module.repl(
        tier="restricted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=read_line,
        confirmation_available=True,
    )
    assert confirm_count["n"] == 1


def test_repl_reload_recognizes_changed_project_identity(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forgeagent").mkdir()
    agents_path = project / ".forgeagent" / "AGENTS.md"
    agents_path.write_text("VERSION ONE")

    monkeypatch.setattr(cli_module.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(project)

    confirm_count = {"n": 0}
    step = {"n": 0}

    def read_line(prompt: str) -> str:
        if prompt.startswith("inject"):
            confirm_count["n"] += 1
            return "y"
        step["n"] += 1
        if step["n"] == 1:
            return "/reload"
        if step["n"] == 2:
            agents_path.write_text("VERSION TWO")
            return "/reload"
        return "quit"

    console = _console()
    cli_module.repl(
        tier="restricted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=read_line,
        confirmation_available=True,
    )
    assert confirm_count["n"] == 2
    assert "identity reloaded" in console.export_text()


# --- config error handling ---------------------------------------------------


def test_main_missing_key_returns_clear_error():
    def failing_factory(model):
        raise RegistryError("No API key found. Set one of LLM_API_KEY / ANTHROPIC_API_KEY")

    code = main(["run", "goal"], client_factory=failing_factory)
    assert code == 2  # clean exit code, not a traceback


# --- smoke command (M5-3) ----------------------------------------------------


def _smoke_factory():
    # Each model gets a fresh MockClient that completes every smoke goal. The smoke
    # command runs len(SMOKE_GOALS) tasks per model, so the script must complete each.
    from forgeagent.cli import SMOKE_GOALS

    def factory(model):
        # One completion reply per goal is enough (Task ends on the front-matter status).
        return MockClient(script=[_reply(_done()) for _ in SMOKE_GOALS])

    return factory


def test_smoke_all_pass_with_mock():
    from forgeagent.cli import SMOKE_MODELS, run_smoke

    console = _console()
    ok = run_smoke(
        tier="trusted",
        models=list(SMOKE_MODELS),
        client_factory=_smoke_factory(),
        console=console,
    )
    assert ok is True
    assert "all passed" in console.export_text()


def test_smoke_reports_failure_when_not_completed():
    from forgeagent.cli import SMOKE_GOALS, run_smoke

    console = _console()
    # One non-completion reply per goal (smoke runs every SMOKE_GOAL on the one client).
    ok = run_smoke(
        tier="trusted",
        models=["claude-sonnet-5"],
        client_factory=lambda model: MockClient(
            script=[_reply("refused", stop_reason="refusal") for _ in SMOKE_GOALS]
        ),
        console=console,
    )
    assert ok is False
    assert "failures" in console.export_text()


def test_smoke_missing_key_returns_clear_error():
    def failing_factory(model):
        raise RegistryError("No API key found. Set one of LLM_API_KEY / ANTHROPIC_API_KEY")

    code = main(["smoke"], client_factory=failing_factory)
    assert code == 2  # clean message + non-zero exit, never mock-fakes success


def test_smoke_include_fable_adds_model():
    # With --include-fable, the smoke run also drives claude-fable-5.
    from forgeagent.cli import SMOKE_GOALS

    seen: list[str] = []

    def factory(model):
        seen.append(model)
        return MockClient(script=[_reply(_done()) for _ in SMOKE_GOALS])

    code = main(["smoke", "--include-fable"], client_factory=factory)
    assert code == 0
    assert "claude-fable-5" in seen


def test_smoke_include_openai_compatible_adds_models():
    # With --include-openai-compatible, the smoke run also drives the three
    # openai_compatible models (M6 decision 4's verification order).
    from forgeagent.cli import OPENAI_COMPATIBLE_SMOKE_MODELS, SMOKE_GOALS

    seen: list[str] = []

    def factory(model):
        seen.append(model)
        return MockClient(script=[_reply(_done()) for _ in SMOKE_GOALS])

    code = main(["smoke", "--include-openai-compatible"], client_factory=factory)
    assert code == 0
    for model in OPENAI_COMPATIBLE_SMOKE_MODELS:
        assert model in seen


# --- models / reload commands (M7 Phase 4) -----------------------------------


def test_models_command_lists_registered_models():
    code = main(["models"], client_factory=_factory([]))  # factory unused by `models`
    assert code == 0


def test_print_models_shows_canonical_and_aliases():
    from forgeagent.cli import print_models

    console = _console()
    print_models(console)
    text = console.export_text()
    assert "claude-sonnet-5" in text
    assert "sonnet" in text  # an alias is shown alongside its canonical id


class _FakeMCP:
    """Records enable/disable calls for the REPL mcp-command test (no real servers)."""

    def __init__(self):
        self._status = {"fs": "available"}
        self.actions: list[tuple[str, str]] = []

    def server_status(self):
        return dict(self._status)

    def enable(self, server):
        self.actions.append(("enable", server))
        if server in self._status:
            self._status[server] = "available"
            return True
        return False

    def disable(self, server):
        self.actions.append(("disable", server))
        if server in self._status:
            self._status[server] = "unavailable: disabled"
            return True
        return False

    def close(self):
        pass


def test_handle_mcp_command_status_enable_disable():
    from forgeagent.cli import _handle_mcp_command

    fake = _FakeMCP()
    console = _console()
    _handle_mcp_command("mcp status", fake, console)
    assert "fs" in console.export_text()

    _handle_mcp_command("mcp disable fs", fake, console)
    _handle_mcp_command("mcp enable fs", fake, console)
    assert ("disable", "fs") in fake.actions
    assert ("enable", "fs") in fake.actions


def test_handle_mcp_command_no_manager_is_noop():
    from forgeagent.cli import _handle_mcp_command

    console = _console()
    _handle_mcp_command("mcp status", None, console)
    assert "no MCP servers configured" in console.export_text()


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_handle_mcp_command_timeout_prints_masked_literal_pending(monkeypatch, action):
    import forgeagent.cli as cli_module

    secret = "known-server-secret"
    server = f"{secret}[bold]literal[/bold]"
    exception_text = "timeout-exception-must-not-leak"

    class TimeoutMCP(_FakeMCP):
        def enable(self, name):
            raise TimeoutError(exception_text)

        def disable(self, name):
            raise TimeoutError(exception_text)

    monkeypatch.setattr(cli_module, "sensitive_env_values", lambda: {secret})
    console = _console()

    cli_module._handle_mcp_command(f"mcp {action} {server}", TimeoutMCP(), console)

    rendered = console.export_text()
    assert rendered == f"MCP {action} pending: ***REDACTED***[bold]literal[/bold]\n"
    assert secret not in rendered
    assert exception_text not in rendered


def test_handle_mcp_enable_with_real_blocked_manager_prints_pending(monkeypatch):
    import forgeagent.cli as cli_module

    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    blocked = threading.Event()
    release = threading.Event()
    intent_ran = threading.Event()
    mgr._loop = loop
    mgr._thread = thread

    async def holder(name, generation, ready, stop):
        intent_ran.set()
        ready.set()
        await stop.wait()

    def block_loop() -> None:
        blocked.set()
        release.wait(timeout=1)

    monkeypatch.setattr(mgr, "_holder", holder)
    console = _console()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        loop.call_soon_threadsafe(block_loop)
        assert blocked.wait(timeout=1)
        try:
            cli_module._handle_mcp_command("mcp enable pending", mgr, console)
            assert console.export_text() == "MCP enable pending: pending\n"

            release.set()
            assert intent_ran.wait(timeout=1)
            deadline = time.monotonic() + 1
            while mgr._lifecycle_tasks and time.monotonic() < deadline:
                time.sleep(0.005)
            assert mgr._lifecycle_tasks == set()
            assert mgr.close() is None
            thread.join(timeout=1)
            gc.collect()
        finally:
            release.set()
            if thread.is_alive():
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
            if not loop.is_closed():
                loop.close()

    assert not thread.is_alive()
    assert loop.is_closed()
    assert loop_messages == []
    assert not any(isinstance(item.message, RuntimeWarning) for item in caught)


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_handle_mcp_command_unknown_server_keeps_existing_error(action):
    import forgeagent.cli as cli_module

    console = _console()

    cli_module._handle_mcp_command(f"mcp {action} missing", _FakeMCP(), console)

    assert console.export_text() == "unknown server 'missing'\n"


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
def test_handle_mcp_command_propagates_process_control(action, control_error):
    import forgeagent.cli as cli_module

    expected = control_error("process control")

    class ProcessControlMCP(_FakeMCP):
        def enable(self, name):
            raise expected

        def disable(self, name):
            raise expected

    with pytest.raises(control_error) as raised:
        cli_module._handle_mcp_command(
            f"mcp {action} fs",
            ProcessControlMCP(),
            _console(),
        )

    assert raised.value is expected


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_repl_mcp_timeout_processes_next_command_and_quit(monkeypatch, action):
    import forgeagent.cli as cli_module

    secret = "known-server-secret"
    server = f"{secret}[bold]literal[/bold]"
    exception_text = "timeout-exception-must-not-leak"

    class TimeoutMCP(_FakeMCP):
        def __init__(self):
            super().__init__()
            self.closed = False

        def enable(self, name):
            raise TimeoutError(exception_text)

        def disable(self, name):
            raise TimeoutError(exception_text)

        def close(self):
            self.closed = True

    fake = TimeoutMCP()
    inputs = iter([f"/mcp {action} {server}", "/help model", "quit"])
    monkeypatch.setattr(cli_module, "sensitive_env_values", lambda: {secret})
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: fake)
    console = _console()

    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )

    rendered = console.export_text()
    assert f"MCP {action} pending: ***REDACTED***[bold]literal[/bold]" in rendered
    assert "/model [id-or-alias]" in rendered
    assert secret not in rendered
    assert exception_text not in rendered
    assert fake.closed is True


def test_repl_runtime_toggle_of_required_server_keeps_session_running(monkeypatch):
    import forgeagent.cli as cli_module

    fake = _FakeMCP()
    fake.required = True
    inputs = iter(["/mcp disable fs", "/mcp enable fs", "quit"])
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: fake)

    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=lambda prompt: next(inputs),
    )

    assert fake.actions == [("disable", "fs"), ("enable", "fs")]


def test_repl_reload_slash_command_reports_model_count():
    from forgeagent.cli import repl

    inputs = iter(["/reload", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "reloaded" in console.export_text()


def test_repl_model_slash_command_lists_without_running_a_task():
    from forgeagent.cli import repl

    inputs = iter(["/model", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),  # never called — /model/quit run no task
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "claude-sonnet-5" in console.export_text()


# --- build_real_client dispatch (M6) ------------------------------------------
# Constructing a client never touches the network (the SDK is imported lazily inside
# the transport closure, only invoked on complete()) — safe to assert on the class
# built, with no real key or API call.


def test_build_real_client_dispatches_anthropic_by_client_kind():
    from forgeagent.anthropic_client import AnthropicClient
    from forgeagent.cli import build_real_client

    client = build_real_client("claude-sonnet-5", env={"ANTHROPIC_API_KEY": "test-key"})
    assert isinstance(client, AnthropicClient)


def test_build_real_client_dispatches_openai_compatible_by_client_kind():
    from forgeagent.cli import build_real_client
    from forgeagent.openai_compatible_client import OpenAICompatibleClient

    client = build_real_client("gpt-5.4-mini", env={"OPENAI_API_KEY": "test-key"})
    assert isinstance(client, OpenAICompatibleClient)
    assert client.capability.model_id == "gpt-5.4-mini"


# --- slash commands (M9 Phase 4) ----------------------------------------------


def test_handle_model_command_no_arg_lists_models():
    from forgeagent.cli import _handle_model_command

    console = _console()
    result = _handle_model_command("/model", "claude-sonnet-5", console)
    assert result == "claude-sonnet-5"
    assert "claude-sonnet-5" in console.export_text()


def test_handle_model_command_switches_to_known_model():
    from forgeagent.cli import _handle_model_command

    console = _console()
    result = _handle_model_command("/model claude-haiku-4-5", "claude-sonnet-5", console)
    assert result == "claude-haiku-4-5"
    assert "switched" in console.export_text()


def test_handle_model_command_unknown_id_keeps_current_model():
    from forgeagent.cli import _handle_model_command

    console = _console()
    result = _handle_model_command("/model no-such-model", "claude-sonnet-5", console)
    assert result == "claude-sonnet-5"
    assert "unknown model" in console.export_text()


def test_handle_search_command_prints_results(monkeypatch):
    from forgeagent.cli import _handle_search_command
    from forgeagent.web_search import SearchResult

    monkeypatch.setattr(
        "forgeagent.cli.search_with_status",
        lambda query, **kwargs: ([SearchResult(title="T", url="https://x", snippet="s")], None),
    )
    console = _console()
    _handle_search_command("/search python", console)
    text = console.export_text()
    assert "T" in text and "https://x" in text and "s" in text


def test_handle_search_command_zero_results(monkeypatch):
    from forgeagent.cli import _handle_search_command

    monkeypatch.setattr("forgeagent.cli.search_with_status", lambda query, **kwargs: ([], None))
    console = _console()
    _handle_search_command("/search nonsense", console)
    assert "no results" in console.export_text()


def test_handle_search_command_blocked(monkeypatch):
    from forgeagent.cli import ERROR_BLOCKED, _handle_search_command

    monkeypatch.setattr(
        "forgeagent.cli.search_with_status", lambda query, **kwargs: ([], ERROR_BLOCKED)
    )
    console = _console()
    _handle_search_command("/search python", console)
    assert "blocked" in console.export_text()


def test_handle_search_command_unavailable(monkeypatch):
    from forgeagent.cli import ERROR_UNAVAILABLE, _handle_search_command

    monkeypatch.setattr(
        "forgeagent.cli.search_with_status", lambda query, **kwargs: ([], ERROR_UNAVAILABLE)
    )
    console = _console()
    _handle_search_command("/search python", console)
    assert "unavailable" in console.export_text()


def test_handle_search_command_empty_query_shows_usage():
    from forgeagent.cli import _handle_search_command

    console = _console()
    _handle_search_command("/search", console)
    assert "usage" in console.export_text()


def test_handle_image_command_path_only_stages(tmp_path):
    from forgeagent.cli import _handle_image_command
    from tests.test_multimodal import _PNG_BYTES

    img = tmp_path / "a.png"
    img.write_bytes(_PNG_BYTES)
    console = _console()
    images, inline_goal = _handle_image_command(f"/image {img}", console)
    assert images is not None and len(images) == 1
    assert inline_goal is None
    assert "loaded" in console.export_text()


def test_handle_image_command_with_inline_goal(tmp_path):
    from forgeagent.cli import _handle_image_command
    from tests.test_multimodal import _PNG_BYTES

    img = tmp_path / "a.png"
    img.write_bytes(_PNG_BYTES)
    console = _console()
    images, inline_goal = _handle_image_command(f"/image {img} describe this", console)
    assert images is not None and len(images) == 1
    assert inline_goal == "describe this"


def test_handle_image_command_bad_path_returns_none():
    from forgeagent.cli import _handle_image_command

    console = _console()
    images, inline_goal = _handle_image_command("/image /no/such/path", console)
    assert images is None
    assert inline_goal is None
    assert "could not load image" in console.export_text()


def test_handle_image_command_missing_arg_shows_usage():
    from forgeagent.cli import _handle_image_command

    console = _console()
    images, inline_goal = _handle_image_command("/image", console)
    assert images is None and inline_goal is None
    assert "usage" in console.export_text()


def test_handle_help_command_full_menu():
    from forgeagent.cli import _handle_help_command

    console = _console()
    _handle_help_command("/help", console)
    text = console.export_text()
    assert "/model" in text and "/search" in text and "/image" in text and "/mcp" in text


def test_handle_help_command_single_command_with_slash():
    from forgeagent.cli import _handle_help_command

    console = _console()
    _handle_help_command("/help /search", console)
    text = console.export_text()
    assert "/search <query>" in text
    assert "/image" not in text


def test_handle_help_command_single_command_bare_word():
    from forgeagent.cli import _handle_help_command

    console = _console()
    _handle_help_command("/help model", console)
    assert "/model [id-or-alias]" in console.export_text()


def test_handle_help_command_unknown_command():
    from forgeagent.cli import _handle_help_command

    console = _console()
    _handle_help_command("/help nope", console)
    assert "unknown command" in console.export_text()


class _FakeMCPWithTools(_FakeMCP):
    """Extends _FakeMCP with list_tools, for the /mcp tool-listing test."""

    def list_tools(self):
        from forgeagent.mcp_manager import MCPToolInfo

        return [MCPToolInfo(server="fs", name="read", description="read a file")]


def test_handle_mcp_slash_status_lists_tools():
    from forgeagent.cli import _handle_mcp_slash

    fake = _FakeMCPWithTools()
    console = _console()
    _handle_mcp_slash("/mcp status", fake, console)
    text = console.export_text()
    assert "fs" in text
    assert "fs:read" in text and "read a file" in text


def test_handle_mcp_slash_status_uses_masked_discovery_catalog(monkeypatch):
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.cli import _handle_mcp_slash

    secret = "cli-discovery-secret"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    manager = MCPManager({"server": MCPServerConfig(command="unused")})
    state = manager._states["server"]
    state.status = "available"
    state.tools = manager._filter_tools(
        "server",
        state.config,
        [type("Tool", (), {"name": "safe", "description": f"description {secret}"})()],
    )

    console = _console()
    _handle_mcp_slash("/mcp status", manager, console)
    rendered = console.export_text()

    assert secret not in rendered
    assert "server:safe" in rendered


def test_handle_mcp_slash_status_masks_sensitive_server_identity(monkeypatch):
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.cli import _handle_mcp_slash

    secret = "cli-server-secret"
    server = f"external-{secret}"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    manager = MCPManager({server: MCPServerConfig(command="unused")})
    state = manager._states[server]
    state.status = "available"
    state.tools = manager._filter_tools(
        server,
        state.config,
        [type("Tool", (), {"name": "safe", "description": "safe description"})()],
    )

    console = _console()
    _handle_mcp_slash("/mcp status", manager, console)
    rendered = console.export_text()

    assert secret not in rendered
    assert "external-***REDACTED***" in rendered
    assert ":safe" not in rendered


def test_handle_mcp_disable_uses_exact_collision_free_public_label(monkeypatch):
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.cli import _handle_mcp_command

    first_secret = "first-cli-secret"
    second_secret = "second-cli-secret"
    first = f"external-{first_secret}"
    second = f"external-{second_secret}"
    safe = "external-***REDACTED***"
    monkeypatch.setattr(
        mcp_manager_module,
        "sensitive_env_values",
        lambda: {first_secret, second_secret},
    )
    manager = MCPManager(
        {
            first: MCPServerConfig(command="unused"),
            second: MCPServerConfig(command="unused"),
            safe: MCPServerConfig(command="unused"),
        }
    )

    console = _console()
    _handle_mcp_command(f"mcp disable {second}", manager, console)
    rendered = console.export_text()

    assert first_secret not in rendered
    assert second_secret not in rendered
    assert "external-***REDACTED*** #3: unavailable: disabled" in rendered


def test_handle_mcp_slash_enable_disable_delegates():
    from forgeagent.cli import _handle_mcp_slash

    fake = _FakeMCPWithTools()
    console = _console()
    _handle_mcp_slash("/mcp disable fs", fake, console)
    assert ("disable", "fs") in fake.actions


def test_repl_bare_slash_prints_menu():
    from forgeagent.cli import repl

    inputs = iter(["/", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "/model" in console.export_text()


def test_repl_unknown_slash_command_shows_menu():
    from forgeagent.cli import repl

    inputs = iter(["/nope", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    assert "unknown command" in text
    assert "/model" in text


def test_repl_slash_model_switches_session_model():
    from forgeagent.cli import repl

    seen: list[str] = []

    def factory(model):
        seen.append(model)
        return MockClient(script=[_reply(_done())])

    inputs = iter(["/model claude-haiku-4-5", "do a thing", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=factory,
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert seen == ["claude-haiku-4-5"]


def test_repl_image_staged_then_consumed_by_next_goal(tmp_path):
    from forgeagent.cli import repl
    from tests.test_multimodal import _PNG_BYTES

    img = tmp_path / "a.png"
    img.write_bytes(_PNG_BYTES)

    def factory(model):
        return MockClient(script=[_reply(_done())])

    inputs = iter([f"/image {img}", "describe it", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=factory,
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    assert "loaded" in text
    assert "completed" in text


@pytest.mark.parametrize("goal", ["models", "reload", "mcp", "mcp status"])
def test_repl_bare_former_commands_run_as_goals(goal, monkeypatch):
    import forgeagent.cli as cli_module

    seen: list[str] = []
    inputs = iter([goal, "quit"])
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda received_goal, **kwargs: seen.append(received_goal),
    )

    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=lambda prompt: next(inputs),
        confirmation_available=False,
    )

    assert seen == [goal]


class _NonAutoApprovedMCP:
    """MCP stub for the real REPL/Task/Tool path; calls must stay blocked."""

    def __init__(self):
        self.auto_approval_checks: list[tuple[str, str]] = []
        self.calls: list[tuple[str, str, dict]] = []

    def tools_prompt(self):
        return ""

    def is_auto_approved(self, server, tool):
        self.auto_approval_checks.append((server, tool))
        return False

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return {"ok": True, "text": "unexpected MCP execution"}

    def close(self):
        pass


@pytest.mark.parametrize(
    ("scenario", "tool_call", "uses_mcp"),
    [
        (
            "web fetch",
            '<!-- ToolCall: {"name":"WebFetch","arguments":{"url":"https://example.com"}} -->',
            False,
        ),
        (
            "file write",
            '<!-- ToolCall: {"name":"FileWrite","arguments":'
            '{"path":"blocked.txt","content":"should not be written"}} -->',
            False,
        ),
        (
            "non-auto-approved MCP",
            '<!-- ToolCall: {"name":"MCP","arguments":'
            '{"server":"fake","tool":"write","arguments":{"value":"x"}}} -->',
            True,
        ),
    ],
    ids=["web-fetch", "file-write", "mcp"],
)
def test_repl_non_tty_rejects_restricted_calls_and_continues(
    monkeypatch, scenario, tool_call, uses_mcp
):
    import forgeagent.cli as cli_module

    first_goal = f"trigger {scenario}"
    inputs = iter([first_goal, "second goal", "quit"])
    seen_goals: list[str] = []
    outcomes: dict[str, TaskOutcome] = {}
    confirmation_reads = 0
    fake_mcp = _NonAutoApprovedMCP() if uses_mcp else None

    def read_line(prompt):
        nonlocal confirmation_reads
        if prompt.startswith("approve?"):
            confirmation_reads += 1
            raise AssertionError("confirmation reader must not run without a TTY")
        return next(inputs)

    real_run_once = cli_module.run_once

    def run_goal(goal, **kwargs):
        seen_goals.append(goal)
        assert kwargs["confirmer"] is None
        script = [_reply(tool_call), _reply(_done())] if goal == first_goal else [_reply(_done())]
        outcome = real_run_once(
            goal,
            **{
                **kwargs,
                "client_factory": lambda model: MockClient(script=script),
            },
        )
        outcomes[goal] = outcome
        return outcome

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: fake_mcp)
    monkeypatch.setattr(cli_module, "run_once", run_goal)
    cli_module.repl(
        tier="restricted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=read_line,
    )

    first_round = outcomes[first_goal].rounds[0]
    assert len(first_round.outcomes) == 1
    assert first_round.outcomes[0].detail == (
        "rejected: no interactive confirmation channel available"
    )
    assert confirmation_reads == 0
    assert seen_goals == [first_goal, "second goal"]
    assert outcomes["second goal"].status.completed is True
    if fake_mcp is not None:
        assert fake_mcp.auto_approval_checks == [("fake", "write")]
        assert fake_mcp.calls == []


def test_repl_explicit_tty_confirmation_uses_injected_read_line(monkeypatch):
    import forgeagent.cli as cli_module

    inputs = iter(["restricted goal", "y", "quit"])
    prompts: list[str] = []

    def read_line(prompt):
        prompts.append(prompt)
        return next(inputs)

    def run_goal(goal, **kwargs):
        assert kwargs["confirmer"] is not None
        assert kwargs["confirmer"](MCPArgs(server="server", tool="tool")) is True
        return None

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: None)
    monkeypatch.setattr(cli_module, "run_once", run_goal)
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=read_line,
        confirmation_available=True,
    )

    assert prompts == ["forge> ", "approve? [y/N] ", "forge> "]


def test_repl_goal_starting_with_mcp_substring_runs_as_normal_task():
    # Regression: goal.startswith("mcp") without a word boundary used to misroute any
    # goal beginning with the literal substring "mcp" (e.g. "mcpherson's algorithm...")
    # into the deprecated bare-word compat path instead of running it as a task.
    from forgeagent.cli import repl

    inputs = iter(["mcpherson's algorithm should not be misrouted", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done())]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    assert "deprecated" not in text
    assert "completed" in text


def test_main_run_no_identity_never_calls_load_identity(monkeypatch):
    import forgeagent.cli as cli_module

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("load_identity must not be called under --no-identity")

    monkeypatch.setattr(cli_module, "load_identity", _fail_if_called)
    assert main(["--no-identity", "run", "goal"], client_factory=_factory([_reply(_done())])) == 0


def test_main_run_headless_strips_project_identity_but_keeps_soul(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module

    home = tmp_path / "home"
    home.mkdir()
    (home / ".forgeagent").mkdir()
    (home / ".forgeagent" / "SOUL.md").write_text("CUSTOM SOUL MARKER")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forgeagent").mkdir()
    (project / ".forgeagent" / "AGENTS.md").write_text("PROJECT RULE MARKER")

    monkeypatch.setattr(cli_module.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(project)

    seen: list[object] = []
    real_run_once = cli_module.run_once

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["identity"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", spy_run_once)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert main(["run", "goal"], client_factory=_factory([_reply(_done())])) == 0
    identity = seen[0]
    assert identity.soul == "CUSTOM SOUL MARKER"
    assert identity.project_agents is None


def test_main_run_interactive_approves_project_identity(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forgeagent").mkdir()
    (project / ".forgeagent" / "AGENTS.md").write_text("PROJECT RULE MARKER")

    monkeypatch.setattr(cli_module.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(project)
    monkeypatch.setattr(cli_module, "Console", lambda: Console(record=True, force_terminal=True))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        cli_module,
        "make_console_identity_confirmer",
        lambda console: lambda request: True,
    )

    seen: list[object] = []
    real_run_once = cli_module.run_once

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["identity"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", spy_run_once)

    assert main(["run", "goal"], client_factory=_factory([_reply(_done())])) == 0
    assert seen[0].project_agents == "PROJECT RULE MARKER"


def test_make_console_identity_confirmer_uses_injected_reader_and_plain_text():
    from forgeagent.cli import make_console_identity_confirmer
    from forgeagent.identity import IdentityTrustRequest

    console = _console()
    confirmer = make_console_identity_confirmer(console, read_line=lambda prompt: "yes")
    request = IdentityTrustRequest(
        project_label=".../repo/[bold]literal label[/bold]",
        summary="AGENTS.md:\n[bold]literal markup[/bold]\\x1b",
    )
    assert confirmer(request) is True
    rendered = console.export_text()
    assert ".../repo/[bold]literal label[/bold]" in rendered
    assert "[bold]literal markup[/bold]" in rendered
    assert "\\x1b" in rendered


def test_main_default_does_not_create_http_server(monkeypatch):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("default CLI must not create an HTTP server"),
    )
    monkeypatch.setattr(cli_module, "repl", lambda **kwargs: None)

    assert cli_module.main([], client_factory=_factory([])) == 0


@pytest.mark.parametrize(
    "override",
    [
        ["--tier", "trusted"],
        ["--model", "claude-haiku-4-5"],
        ["--container-image", "custom-image"],
        ["--no-identity"],
    ],
)
def test_serve_rejects_cli_execution_policy_overrides(monkeypatch, tmp_path, override):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text("token: file-token\n")
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("invalid serve invocation must not bind"),
    )

    assert cli_module.main([*override, "serve", "--config", str(config_path)]) == 2


def test_serve_builds_server_owned_task_factory_and_closes_in_order(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    allowed_root = tmp_path / "project"
    allowed_root.mkdir()
    audit_path = tmp_path / "audit" / "events.jsonl"
    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        "\n".join(
            [
                "token: file-token",
                "bind_host: 127.0.0.1",
                "port: 8765",
                "tier: trusted",
                "model: claude-sonnet-5",
                f"allowed_root: {allowed_root}",
                "no_identity: true",
                f"audit_path: {audit_path}",
                "allowlist:",
                "  - file/reports/result.txt",
                "shutdown_timeout_seconds: 0.1",
            ]
        )
        + "\n"
    )
    monkeypatch.setenv("FORGEAGENT_HTTP_TOKEN", "environment-token")

    events: list[str] = []
    captured: dict[str, object] = {}
    identity = object()

    class FakeMCP:
        def close(self):
            events.append("mcp.close")

    mcp = FakeMCP()

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink):
            captured.update(
                factory=factory,
                config=config,
                shared_mcp_manager=shared_mcp_manager,
                audit_sink=audit_sink,
            )
            self.shared_mcp_manager = shared_mcp_manager

        def shutdown(self, timeout):
            captured["shutdown_timeout"] = timeout
            events.append("service.shutdown")
            self.shared_mcp_manager.close()

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def serve_forever(self, poll_interval):
            pass

        def shutdown(self):
            events.append("server.shutdown")

        def server_close(self):
            events.append("server.close")

    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: mcp)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: identity)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda config, service: FakeServer(),
    )

    assert (
        cli_module.main(
            ["serve", "--config", str(config_path), "--once"],
            client_factory=_factory([]),
        )
        == 0
    )

    config = captured["config"]
    assert config.token == "environment-token"
    assert captured["shared_mcp_manager"] is mcp
    assert captured["shutdown_timeout"] == 0.1
    assert events == ["server.shutdown", "service.shutdown", "mcp.close", "server.close"]
    assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600

    task = captured["factory"](SimpleNamespace(task_id="task-123"))
    try:
        assert task._tier == "trusted"
        assert task._allowed_root == str(allowed_root.resolve())
        assert task._identity is identity
        assert task._mcp is mcp
        assert task._audit_sink is captured["audit_sink"]
        assert task._task_id == "task-123"
        assert task._confirmer.is_headless is True
    finally:
        task.close()


def test_serve_audit_startup_failure_does_not_create_listener(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file")
    config_path = tmp_path / "http.yaml"
    config_path.write_text(f"token: file-token\naudit_path: {blocked_parent / 'audit.jsonl'}\n")
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("audit failure must happen before listener creation"),
    )
    monkeypatch.setattr(
        cli_module,
        "build_mcp_manager",
        lambda console: pytest.fail("audit failure must happen before MCP startup"),
    )

    assert cli_module.main(["serve", "--config", str(config_path), "--once"]) == 2


@pytest.mark.parametrize(
    "extra_config",
    [
        "allowlist:\n  - file/*.txt\n",
        "audit_max_bytes: 1\n",
    ],
    ids=["invalid-allowlist", "audit-line-too-small"],
)
def test_serve_validates_headless_and_audit_policy_before_listener(
    monkeypatch, tmp_path, extra_config
):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        f"token: file-token\naudit_path: {tmp_path / 'audit.jsonl'}\n{extra_config}"
    )
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda console: None)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("invalid policy must not create a listener"),
    )

    assert cli_module.main(["serve", "--config", str(config_path), "--once"]) == 2


def test_http_owner_closes_bound_resources_when_server_thread_cannot_start(monkeypatch):
    import forgeagent.cli as cli_module

    events: list[str] = []

    class FakeServer:
        def server_close(self):
            events.append("server.close")

    class FakeService:
        def shutdown(self, timeout):
            events.append(f"service.shutdown:{timeout}")

    monkeypatch.setattr(
        cli_module.threading.Thread,
        "start",
        lambda self: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )

    with pytest.raises(cli_module.HttpStartupError):
        cli_module._run_owned_http_server(
            FakeServer(),
            FakeService(),
            shutdown_timeout=0.25,
            once=False,
        )

    assert events == ["service.shutdown:0.25", "server.close"]
