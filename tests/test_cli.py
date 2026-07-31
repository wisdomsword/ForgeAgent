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
import signal
import stat
import sys
import threading
import time
import warnings
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from pydantic import BaseModel
from rich.console import Console

import forgeagent.cli as cli_module
import forgeagent.mcp_manager as mcp_manager_module
from forgeagent.cli import (
    build_parser,
    main,
    render_outcome,
    repl,
    run_loop_once,
    run_once,
)
from forgeagent.client import MockClient
from forgeagent.collaboration import CollaborationReport, CollaborationUsage
from forgeagent.evaluator import EvaluationRequest, EvaluatorResult
from forgeagent.executor import TrustedBackend
from forgeagent.loop import LoopBudgets, LoopCheckpointStore
from forgeagent.mcp_manager import MCPManager, MCPServerConfig, MCPServerDiagnostic
from forgeagent.model_registry import RegistryError
from forgeagent.models import (
    AssistantMessage,
    ModelCapability,
    StreamEvent,
    StreamEventKind,
    TokenUsage,
)
from forgeagent.protocol import FileListArgs, FileWriteArgs, MCPArgs, ToolCall, WebFetchArgs
from forgeagent.runtime import Runtime
from forgeagent.skills import SkillDefinition, SkillRegistry
from forgeagent.step import RoundResult, Step, Termination
from forgeagent.task import TaskOutcome, TaskStatus
from forgeagent.tools import ToolOutcome, default_registry


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


def _terminal_console() -> Console:
    return Console(record=True, width=100, force_terminal=True)


class _DiagnosticManager:
    def __init__(self, values: tuple[MCPServerDiagnostic, ...]) -> None:
        self._values = values

    def diagnostics(self) -> tuple[MCPServerDiagnostic, ...]:
        return self._values

    def required_failures(self) -> dict[str, str]:
        return {}

    def server_status(self) -> dict[str, str]:
        return {item.name: item.status for item in self._values}

    def list_tools(self) -> list:
        return []

    def close(self) -> None:
        return None


def _diagnostic(
    name: str,
    *,
    enabled: bool = True,
    required: bool = False,
    status: str = "available",
    tool_count: int = 0,
    reason: str | None = None,
    impact: str | None = None,
    action: str | None = None,
) -> MCPServerDiagnostic:
    return MCPServerDiagnostic(
        name=name,
        enabled=enabled,
        required=required,
        status=status,
        tool_count=tool_count,
        reason=reason,
        impact=impact,
        action=action,
    )


class _RecordedLive:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _display_with_recorded_live(monkeypatch, *, width: int = 100):
    lives = []
    for name in ("NO_COLOR", "CI", "GITHUB_ACTIONS", "BUILD_NUMBER", "TERM"):
        monkeypatch.delenv(name, raising=False)

    def make_live(**kwargs):
        live = _RecordedLive(**kwargs)
        lives.append(live)
        return live

    monkeypatch.setattr(cli_module, "Live", make_live)
    console = Console(record=True, width=width, force_terminal=True, color_system="standard")
    return cli_module._StartupDisplay(console), lives


def test_startup_renderer_requires_default_reader_and_both_ttys(monkeypatch):
    console = _terminal_console()
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)

    assert cli_module._interactive_repl(console, default_reader=True) is True
    assert cli_module._interactive_repl(console, default_reader=False) is False

    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: False)
    assert cli_module._interactive_repl(console, default_reader=True) is False
    assert cli_module._interactive_repl(_console(), default_reader=True) is False


def test_startup_display_starts_one_eight_fps_live_and_cycles_seven_colours(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    clock = {"now": 0.0}
    monkeypatch.setattr(cli_module.time, "monotonic", lambda: clock["now"])

    display.start("Loading identity")
    display.start("Loading skills")

    assert len(lives) == 1
    assert lives[0].started is True
    assert lives[0].kwargs == {
        "console": display._console,
        "refresh_per_second": 8,
        "transient": True,
        "get_renderable": display.renderable,
    }
    colours = []
    for phase in range(7):
        clock["now"] = phase / 8
        colours.append(str(display.logo_renderable().style))
    assert colours == [
        "red",
        "yellow",
        "green",
        "cyan",
        "blue",
        "magenta",
        "bright_magenta",
    ]
    assert "Loading skills" in lives[0].kwargs["get_renderable"]().plain


def test_startup_display_pauses_for_confirmation_and_recreates_live(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    display.start("Loading identity")
    display.pause()
    assert lives[0].stopped is True
    display.resume()
    display.stop()

    assert [live.started for live in lives] == [True, True]
    assert all(live.stopped for live in lives)


def test_startup_display_narrow_terminal_is_single_line(monkeypatch):
    display, _ = _display_with_recorded_live(monkeypatch, width=12)
    assert display.logo_renderable().plain == "ForgeAgent"


@pytest.mark.parametrize("environment_name", ["NO_COLOR", "CI", "GITHUB_ACTIONS", "BUILD_NUMBER"])
def test_startup_display_environment_disables_live(monkeypatch, environment_name):
    display, lives = _display_with_recorded_live(monkeypatch)
    monkeypatch.setenv(environment_name, "1")

    display.start("Loading identity")

    assert lives == []


def test_startup_display_dumb_terminal_disables_live(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")

    display.start("Loading identity")

    assert lives == []


@pytest.mark.parametrize(
    "console",
    [
        Console(record=True, width=100, force_terminal=False),
        Console(record=True, width=100, force_terminal=True, no_color=True),
        Console(record=True, width=100, force_terminal=True, color_system=None),
    ],
)
def test_startup_display_console_capability_disables_live(monkeypatch, console):
    lives = []
    monkeypatch.setattr(cli_module, "Live", lambda **kwargs: lives.append(kwargs))

    cli_module._StartupDisplay(console).start("Loading identity")

    assert lives == []


def test_startup_summary_reports_model_sandbox_project_and_enabled_mcp_denominator():
    console = _terminal_console()
    diagnostics = (
        _diagnostic("available", tool_count=2),
        _diagnostic(
            "optional",
            status="unavailable: docker_unavailable",
            reason="Docker is not running",
            impact="Only this configured integration is disabled",
            action="Start Docker or disable this server",
        ),
        _diagnostic("disabled", enabled=False, status="unavailable: disabled"),
    )

    cli_module._render_startup_summary(
        console,
        model="claude-sonnet-5",
        tier="restricted",
        root="/project",
        diagnostics=diagnostics,
    )

    rendered = console.export_text()
    assert "Ready | MCP 1/2 | model claude-sonnet-5" in rendered
    assert "sandbox restricted | project /project" in rendered
    assert rendered.count("Docker is not running") == 1
    assert "MCP disabled" not in rendered


def test_startup_summary_omits_mcp_count_when_no_server_is_enabled():
    console = _terminal_console()

    cli_module._render_startup_summary(
        console,
        model="gpt-5.5",
        tier="trusted",
        root="/project",
        diagnostics=(_diagnostic("disabled", enabled=False, status="unavailable: disabled"),),
    )

    rendered = console.export_text()
    assert "Ready | model gpt-5.5 | sandbox trusted | project /project" in rendered
    assert "MCP " not in rendered


def test_startup_summary_optional_failure_uses_only_fixed_diagnostic_fields():
    console = _terminal_console()
    hostile = "ExceptionGroup RuntimeError /private/secret --token=secret ENV=secret"

    cli_module._render_startup_summary(
        console,
        model="model",
        tier="container",
        root="/project",
        diagnostics=(
            _diagnostic(
                "docker",
                status="unavailable: docker_unavailable",
                reason="Docker is not running",
                impact="Only this configured integration is disabled",
                action="Start Docker or disable this server",
            ),
        ),
    )

    rendered = console.export_text()
    assert rendered.count("Docker is not running") == 1
    assert "Only this configured integration is disabled" in rendered
    assert "Start Docker or disable this server" in rendered
    assert hostile not in rendered
    for forbidden in ("ExceptionGroup", "RuntimeError", "/private/secret", "--token", "ENV="):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("console", "environment"),
    [
        (Console(record=True, width=100, force_terminal=True), {"NO_COLOR": "1"}),
        (Console(record=True, width=100, force_terminal=True, no_color=True), {}),
        (Console(record=True, width=100, force_terminal=True, color_system=None), {}),
    ],
    ids=("no-color-environment", "console-no-color", "no-color-system"),
)
def test_interactive_degraded_color_renders_static_startup_mark_without_live(
    monkeypatch, console, environment
):
    for name in ("NO_COLOR", "CI", "GITHUB_ACTIONS", "BUILD_NUMBER", "TERM"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli_module, "Live", lambda **kwargs: pytest.fail("must not construct"))
    monkeypatch.setattr(cli_module, "_make_interactive_reader", lambda: lambda _prompt: "quit")
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)

    cli_module.repl(
        tier="restricted",
        model="mock",
        client_factory=_factory([]),
        console=console,
        read_line=None,
        no_identity=True,
        no_memory=True,
        skills=SkillRegistry({}),
        use_registry_snapshot=False,
    )

    assert " _____" in console.export_text()


def test_repl_stops_startup_display_when_startup_raises(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    monkeypatch.setattr(cli_module, "_StartupDisplay", lambda console: display)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli_module, "_make_interactive_reader", lambda: lambda _prompt: "quit")
    monkeypatch.setattr(
        cli_module,
        "build_mcp_manager",
        lambda: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        cli_module.repl(
            tier="restricted",
            model="mock",
            client_factory=_factory([]),
            console=display._console,
            read_line=None,
            no_identity=True,
            skills=SkillRegistry({}),
            use_registry_snapshot=False,
        )

    assert [live.started for live in lives] == [True]
    assert all(live.stopped for live in lives)


def test_repl_stops_startup_display_after_confirmation_keyboard_interrupt(monkeypatch):
    display, lives = _display_with_recorded_live(monkeypatch)
    monkeypatch.setattr(cli_module, "_StartupDisplay", lambda console: display)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)

    def interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "_make_interactive_reader", lambda: interrupt)
    from forgeagent.identity import IdentityTrustRequest

    def resolve_identity(**kwargs):
        kwargs["confirmer"](IdentityTrustRequest(project_label="project", summary="summary"))
        return None

    monkeypatch.setattr(cli_module, "resolve_cli_identity", resolve_identity)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)

    with pytest.raises(KeyboardInterrupt):
        cli_module.repl(
            tier="restricted",
            model="mock",
            client_factory=_factory([]),
            console=display._console,
            read_line=None,
            skills=SkillRegistry({}),
            use_registry_snapshot=False,
        )

    assert all(live.stopped for live in lives)


def test_repl_explicit_reader_never_constructs_prompt_session(monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "PromptSession",
        lambda *args, **kwargs: pytest.fail("must not construct"),
        raising=False,
    )

    repl(
        tier="restricted",
        model="mock",
        client_factory=_factory([]),
        read_line=lambda _: "quit",
    )


@pytest.mark.parametrize("prefix", ["/", "/m", "/mo"])
def test_default_interactive_reader_uses_command_table_and_memory_history(monkeypatch, prefix):
    captured = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def prompt(self, prompt):
            captured["prompt"] = prompt
            return "quit"

    monkeypatch.setattr(cli_module, "PromptSession", FakeSession, raising=False)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)

    repl(
        tier="restricted",
        model="mock",
        client_factory=_factory([]),
        console=_terminal_console(),
        read_line=None,
    )

    completer = captured["completer"]
    candidates = {
        item.text for item in completer.get_completions(Document(prefix), CompleteEvent())
    }
    assert candidates == {
        command for command in cli_module._SLASH_COMMAND_USAGE if command.startswith(prefix)
    }
    assert completer.words == list(cli_module._SLASH_COMMAND_USAGE)
    assert completer.meta_dict == cli_module._SLASH_COMMAND_USAGE
    assert completer.sentence is True
    assert completer.match_middle is False
    assert captured["complete_while_typing"] is True
    assert isinstance(captured["history"], InMemoryHistory)
    assert "FileHistory" not in repr(captured["history"])
    assert captured["prompt"] == "forge> "


def test_non_tty_default_reader_uses_builtin_input(monkeypatch):
    prompts = []
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "quit")

    repl(tier="restricted", model="mock", client_factory=_factory([]), read_line=None)

    assert prompts == [""]


def test_explicit_reader_receives_no_interactive_goal_prompt():
    prompts = []

    repl(
        tier="restricted",
        model="mock",
        client_factory=_factory([]),
        read_line=lambda prompt: prompts.append(prompt) or "quit",
    )

    assert prompts == [""]


def _registry_with_skill(marker: str = "SKILL-BODY-UNIQUE") -> SkillRegistry:
    return SkillRegistry(
        {
            "review-python": SkillDefinition(
                name="review-python",
                trigger="Use when reviewing Python.",
                steps=marker,
                failure_branches="Ask for missing context.",
                completion_criteria="Report findings.",
                source="user",
            )
        }
    )


def test_parser_accepts_no_memory_switch():
    args = build_parser().parse_args(["--no-memory", "run", "goal"])
    assert args.no_memory is True


def test_repl_remember_and_memory_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    console = _console()
    inputs = iter(["/remember project editor=nvim", "/memory", "quit"])
    repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        console=console,
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        use_registry_snapshot=False,
    )
    assert "editor: nvim" in console.export_text()
    assert "editor: nvim" in (tmp_path / ".forgeagent" / "MEMORY.md").read_text()


def test_repl_no_memory_does_not_persist_remember(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    console = _console()
    inputs = iter(["/remember project editor=nvim", "/memory", "quit"])
    repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        console=console,
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_memory=True,
        use_registry_snapshot=False,
    )
    assert "editor: nvim" not in console.export_text()
    assert not (tmp_path / ".forgeagent" / "MEMORY.md").exists()


def test_run_once_renders_disabled_model_memory_result(tmp_path):
    from forgeagent.memory import MemoryManager

    console = _console()
    run_once(
        "remember formatter",
        tier="trusted",
        model="mock",
        client_factory=_factory(
            [
                _reply(
                    _done() + '\n<!-- Memory: {"scope":"session","kind":"preference",'
                    '"key":"formatter","content":"ruff"} -->'
                )
            ]
        ),
        console=console,
        memory_manager=MemoryManager(str(tmp_path), enabled=False),
    )
    rendered = console.export_text()
    assert "memory disabled" in rendered
    assert "formatter" in rendered
    assert "ruff" not in rendered


def test_repl_no_identity_also_disables_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    console = _console()
    inputs = iter(["/remember project editor=nvim", "quit"])
    repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        console=console,
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        use_registry_snapshot=False,
    )
    assert not (tmp_path / ".forgeagent" / "MEMORY.md").exists()


def test_http_runtime_settings_accept_no_memory(tmp_path):
    from forgeagent.cli import _load_http_runtime_settings

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        f"token: test-token\nallowed_root: {tmp_path}\nno_memory: true\n",
        encoding="utf-8",
    )
    assert _load_http_runtime_settings(config_path).no_memory is True


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


def test_run_once_threads_supplied_skill_snapshot_to_task(monkeypatch):
    import forgeagent.cli as cli_module

    captured = {}

    class FakeTask:
        def __init__(self, **kwargs):
            captured["skills"] = kwargs["skills"]

        def run(self, goal, *, images=None):
            return TaskOutcome(
                status=TaskStatus(completed=True, reason=Termination.COMPLETED), rounds=[]
            )

        def close(self):
            pass

    monkeypatch.setattr(cli_module, "Task", lambda client, **kwargs: FakeTask(**kwargs))
    skills = _registry_with_skill()

    run_once(
        "goal",
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        skills=skills,
    )

    assert captured["skills"] is skills
    assert captured["skills"].read("review-python") is not None


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


# --- durable loop command ----------------------------------------------------


def test_loop_parser_accepts_new_goal_and_uses_budget_defaults():
    args = build_parser().parse_args(["loop", "finish the work", "--token-budget", "25"])

    assert args.command == "loop"
    assert args.goal == "finish the work"
    assert args.token_budget == 25
    assert args.max_rounds is None
    assert args.wall_clock_seconds is None
    assert args.max_consecutive_failures is None
    assert args.resume is None


def test_loop_parser_accepts_resume_without_a_goal_or_budget():
    args = build_parser().parse_args(["loop", "--resume", "a" * 32])

    assert args.goal is None
    assert args.resume == "a" * 32
    assert args.token_budget is None


@pytest.mark.parametrize(
    "argv",
    [
        ["loop", "goal"],
        ["loop", "goal", "--token-budget", "0"],
        ["loop", "goal", "--token-budget", "-1"],
        ["loop", "goal", "--token-budget", "true"],
        ["loop", "goal", "--token-budget", "1", "--wall-clock-seconds", "nan"],
        ["loop", "goal", "--token-budget", "1", "--wall-clock-seconds", "inf"],
        ["loop", "goal", "--token-budget", "1", "--resume", "a" * 32],
        ["loop", "--resume", "a" * 32, "--max-rounds", "5"],
    ],
)
def test_main_loop_rejects_invalid_or_conflicting_inputs(argv):
    assert main(argv, client_factory=_factory([])) == 2


@pytest.mark.parametrize(
    "option",
    [
        ["--collaboration-mode", "duo"],
        ["--planner-model", "planner"],
        ["--evaluator-model", "evaluator"],
        ["--max-rejections", "3"],
    ],
)
def test_main_loop_resume_rejects_collaboration_policy_overrides(tmp_path, monkeypatch, option):
    monkeypatch.chdir(tmp_path)
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("private initial goal", LoopBudgets(token_budget=25))
    store.close()

    assert (
        main(
            ["--no-identity", "--no-memory", "loop", "--resume", checkpoint.loop_id, *option],
            client_factory=_factory([]),
        )
        == 2
    )


def test_main_loop_completes_with_mock_client_and_renders_safe_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    console = _console()
    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
    secret = "secret-loop-value"

    assert (
        main(
            ["--tier", "trusted", "loop", f"finish {secret}", "--token-budget", "25"],
            client_factory=_factory([_reply(_done(), usage=TokenUsage(input_tokens=3))]),
        )
        == 0
    )

    rendered = console.export_text()
    assert "loop id:" in rendered
    assert "status: completed" in rendered
    assert "stop reason: completed" in rendered
    assert "iterations=1" in rendered
    assert secret not in rendered
    assert str(tmp_path) not in rendered
    assert ".forgeagent/loops" not in rendered


def test_main_loop_resume_uses_checkpoint_goal_without_disclosing_it(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.create("private initial goal", LoopBudgets(token_budget=25))
    resumed_id = checkpoint.loop_id
    store.close()
    resume_console = _console()
    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: resume_console)
    assert (
        main(
            ["--tier", "trusted", "loop", "--resume", resumed_id],
            client_factory=_factory([_reply(_done(), usage=TokenUsage(input_tokens=2))]),
        )
        == 0
    )
    rendered = resume_console.export_text()
    assert "private initial goal" not in rendered
    assert resumed_id in rendered


def test_run_loop_once_closes_runner_and_reuses_cli_assembly(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    console = _console()
    report = run_loop_once(
        "finish the work",
        tier="trusted",
        model="mock",
        client_factory=_factory([_reply(_done(), usage=TokenUsage(input_tokens=1))]),
        console=console,
        token_budget=5,
    )

    assert report.status == "completed"
    assert report.tokens_used == 1


@pytest.mark.parametrize(
    ("collaboration_mode", "expected_source"),
    [(None, "default"), ("single", "explicit"), ("duo", "explicit"), ("triad", "explicit")],
)
def test_run_loop_once_projects_default_and_explicit_collaboration_source(
    monkeypatch, tmp_path, collaboration_mode, expected_source
):
    captured: dict[str, object] = {}

    class FakeRunner:
        @classmethod
        def create(cls, **kwargs):
            captured.update(kwargs)
            return cls()

        def run(self, *, cancel_event=None):
            del cancel_event
            return SimpleNamespace(status="completed")

        def close(self):
            return None

    monkeypatch.setattr(cli_module, "LoopRunner", FakeRunner)
    monkeypatch.setattr(cli_module, "_render_loop_report", lambda _report, _console: None)

    run_loop_once(
        "finish the work",
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        allowed_root=str(tmp_path),
        console=_console(),
        token_budget=5,
        collaboration_mode=collaboration_mode,
    )

    assert captured["collaboration_mode"] == (collaboration_mode or "single")
    assert captured["collaboration_mode_source"] == expected_source


def test_collaborative_loop_shares_remaining_rounds_and_forwards_loop_context(
    monkeypatch, tmp_path
):
    task_round_limits: list[int] = []
    task_recovery_limits: list[int] = []
    forwarded: dict[str, object] = {}
    role_outcomes = iter(
        [
            TaskOutcome(
                status=TaskStatus(completed=True, reason=Termination.COMPLETED),
                rounds=[RoundResult(text=""), RoundResult(text="")],
            ),
            TaskOutcome(
                status=TaskStatus(completed=True, reason=Termination.COMPLETED),
                rounds=[RoundResult(text="")],
            ),
        ]
    )

    class RecordingTask:
        def __init__(self, _client, **kwargs):
            task_round_limits.append(kwargs["max_rounds"])
            task_recovery_limits.append(kwargs["max_submission_recovery_attempts"])

        def run(self, _goal, *, cancel_event=None):
            del cancel_event
            return next(role_outcomes)

        def close(self):
            pass

    class FakeCollaboration:
        def __init__(self, builder):
            self._builder = builder
            self._state = SimpleNamespace(plan_digest="")

        def run(self, _goal, *, cancel_event=None):
            del cancel_event
            generator = self._builder("generator", 1, default_registry(), "generator")
            generator.run("generator data")
            generator.close()
            evaluator = self._builder("evaluator", 1, default_registry(), "evaluator")
            evaluator.run("evaluator data")
            evaluator.close()
            return CollaborationReport(
                collaboration_id="c" * 32,
                mode="duo",
                status="completed",
                stop_reason="completed",
                phase="completed",
                plan_item_count=1,
                passed_item_count=1,
                failed_item_count=0,
                generator_attempts=1,
                evaluator_attempts=1,
                rejections=0,
                rounds=3,
                usage=CollaborationUsage(),
                usage_available=False,
                evidence=(),
            )

        def close(self):
            pass

    class FakeCollaborationRunner:
        @classmethod
        def create(cls, **kwargs):
            forwarded.update(kwargs)
            return FakeCollaboration(kwargs["role_task_builder"])

    monkeypatch.setattr(cli_module, "Task", RecordingTask)
    monkeypatch.setattr(cli_module, "CollaborationRunner", FakeCollaborationRunner)
    monkeypatch.setattr(cli_module, "_validate_client_context_policy", lambda *args: None)

    report = run_loop_once(
        "finish",
        tier="trusted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(close=lambda: None),
        allowed_root=str(tmp_path),
        console=_console(),
        token_budget=10,
        max_rounds=3,
        collaboration_mode="duo",
    )

    assert report.status == "completed"
    assert task_round_limits == [3, 1]
    assert task_recovery_limits == [2, 2]
    assert "UNTRUSTED LOOP STATE" in forwarded["task_data_suffix"]
    assert "Checkpoint" in forwarded["generator_registry"].arg_schemas()
    assert forwarded["recover_role_failures"] is True


def test_collaborative_loop_retries_recoverable_generator_failure(monkeypatch, tmp_path):
    evaluation = {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "goal",
                    "passed": True,
                    "observed": "artifact is present",
                    "expected": "artifact is present",
                    "location": "artifact.txt",
                }
            ]
        },
    }
    scripts = iter(
        [
            [
                _reply(
                    "---\ntask_status:\n  completed: false\n  status: failed\n---\nretry later",
                    usage=TokenUsage(input_tokens=1, total_prompt_tokens=1),
                ),
            ],
            [
                _reply(
                    '<!-- ToolCall: {"name":"SubmitCandidate","arguments":{}} -->',
                    usage=TokenUsage(input_tokens=1, total_prompt_tokens=1),
                )
            ],
            [
                _reply(
                    f"<!-- ToolCall: {json.dumps(evaluation)} -->",
                    usage=TokenUsage(input_tokens=1, total_prompt_tokens=1),
                ),
            ],
        ]
    )
    clients = []

    class RecordingClient(MockClient):
        def __init__(self, script):
            super().__init__(script)
            self.first_user_message = ""

        def complete(self, messages, params=None):
            if not self.first_user_message:
                self.first_user_message = str(messages[-1].content)
            return super().complete(messages, params)

    def client_factory(_model):
        client = RecordingClient(next(scripts))
        clients.append(client)
        return client

    report = run_loop_once(
        "finish",
        tier="trusted",
        model="mock",
        client_factory=client_factory,
        allowed_root=str(tmp_path),
        console=_console(),
        token_budget=10,
        max_rounds=6,
        max_consecutive_failures=2,
        collaboration_mode="duo",
    )

    assert report.status == "completed"
    assert report.iterations == 2
    assert report.rounds_used == 3
    assert report.consecutive_failures == 0
    assert len(clients) == 3
    retried_generator_data = json.loads(clients[1].first_user_message)
    assert "role_failed" in retried_generator_data["loop_context"]
    assert "UNTRUSTED LOOP STATE" in retried_generator_data["loop_context"]


def test_run_loop_once_closes_each_fresh_iteration_client_once(monkeypatch, tmp_path):
    clients = []
    tasks = []

    class CloseTrackingClient(MockClient):
        def __init__(self):
            super().__init__(script=[])
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    class IterationTask:
        def __init__(self, client, **kwargs):
            del kwargs
            self.client = client
            self.close_calls = 0
            tasks.append(self)

        def run(self, goal, *, cancel_event=None):
            del goal, cancel_event
            completed = len(tasks) == 2
            return TaskOutcome(
                status=TaskStatus(
                    completed=completed,
                    reason=Termination.COMPLETED if completed else Termination.MAX_ROUNDS,
                ),
                rounds=[RoundResult(text="", usage=TokenUsage(input_tokens=1))],
            )

        def close(self):
            self.close_calls += 1

    def client_factory(model):
        del model
        client = CloseTrackingClient()
        clients.append(client)
        return client

    monkeypatch.setattr(cli_module, "Task", IterationTask)

    report = run_loop_once(
        "finish",
        tier="trusted",
        model="mock",
        client_factory=client_factory,
        allowed_root=str(tmp_path),
        console=_console(),
        token_budget=10,
    )

    assert report.status == "completed"
    assert len(clients) == len(tasks) == 2
    assert [client.close_calls for client in clients] == [1, 1]
    assert [task.close_calls for task in tasks] == [1, 1]


@pytest.mark.parametrize("failure_stage", ["construct", "run", "close"])
def test_run_loop_once_closes_owned_client_once_on_task_failure(
    monkeypatch, tmp_path, failure_stage
):
    class CloseTrackingClient(MockClient):
        def __init__(self):
            super().__init__(script=[])
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    client = CloseTrackingClient()

    class FailingTask:
        def __init__(self, model_client, **kwargs):
            del model_client, kwargs
            if failure_stage == "construct":
                raise RuntimeError("construct failed")

        def run(self, goal, *, cancel_event=None):
            del goal, cancel_event
            if failure_stage == "run":
                raise RuntimeError("run failed")
            return TaskOutcome(
                status=TaskStatus(completed=True, reason=Termination.COMPLETED),
                rounds=[RoundResult(text="", usage=TokenUsage(input_tokens=1))],
            )

        def close(self):
            if failure_stage == "close":
                raise RuntimeError("close failed")

    monkeypatch.setattr(cli_module, "Task", FailingTask)

    with pytest.raises(RuntimeError, match=failure_stage):
        run_loop_once(
            "finish",
            tier="trusted",
            model="mock",
            client_factory=lambda model: client,
            allowed_root=str(tmp_path),
            console=_console(),
            token_budget=10,
        )

    assert client.close_calls == 1


def test_run_loop_once_sigint_requests_cancel_and_restores_handler(monkeypatch, tmp_path):
    previous_calls: list[int] = []

    def previous_handler(signum, _frame):
        previous_calls.append(signum)

    current_handler = previous_handler
    signal_calls: list[object] = []

    def fake_getsignal(signum):
        assert signum == signal.SIGINT
        return current_handler

    def fake_signal(signum, handler):
        nonlocal current_handler
        assert signum == signal.SIGINT
        signal_calls.append(handler)
        old_handler = current_handler
        current_handler = handler
        return old_handler

    class InterruptingTask:
        def __init__(self, *_args, **_kwargs):
            self.closed = False

        def run(self, _goal, *, cancel_event=None):
            assert cancel_event is not None
            assert callable(current_handler)
            current_handler(signal.SIGINT, None)
            assert cancel_event.is_set()
            current_handler(signal.SIGINT, None)
            return TaskOutcome(
                status=TaskStatus(completed=False, reason=Termination.CANCELLED),
                rounds=[RoundResult(text="", stopped_reason=Termination.CANCELLED)],
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli_module.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(cli_module.signal, "signal", fake_signal)
    monkeypatch.setattr(cli_module, "Task", InterruptingTask)
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "--tier",
                "trusted",
                "--no-identity",
                "--no-memory",
                "loop",
                "finish the work",
                "--token-budget",
                "5",
            ],
            client_factory=_factory([]),
        )
        == 1
    )

    checkpoint_path = next((tmp_path / ".forgeagent" / "loops").glob("*.json"))
    store = LoopCheckpointStore(str(tmp_path))
    checkpoint = store.load(checkpoint_path.stem)
    store.close()

    assert checkpoint.status == "cancelled"
    assert checkpoint.stop_reason == "cancelled"
    assert signal_calls[-1] is previous_handler
    assert current_handler is previous_handler
    assert previous_calls == [signal.SIGINT]


def test_run_loop_once_non_main_thread_keeps_existing_signal_behavior(monkeypatch, tmp_path):
    signal_calls = 0

    def reject_signal_install(_signum, _handler):
        nonlocal signal_calls
        signal_calls += 1
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(cli_module.signal, "getsignal", lambda _signum: signal.default_int_handler)
    monkeypatch.setattr(cli_module.signal, "signal", reject_signal_install)

    report = run_loop_once(
        "finish the work",
        tier="trusted",
        model="mock",
        client_factory=_factory([_reply(_done(), usage=TokenUsage(input_tokens=1))]),
        allowed_root=str(tmp_path),
        console=_console(),
        token_budget=5,
    )

    assert report.status == "completed"
    assert signal_calls == 1


def test_ordinary_run_and_repl_do_not_create_loop_checkpoints_or_import_evaluator(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    imported = []
    original_import = __import__

    def record_import(name, *args, **kwargs):
        if name == "forgeagent.evaluator":
            imported.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", record_import)

    assert (
        main(["--tier", "trusted", "run", "goal"], client_factory=_factory([_reply(_done())])) == 0
    )
    responses = iter(["goal", ""])
    repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([_reply(_done())]),
        read_line=lambda _prompt: next(responses),
    )

    assert not (tmp_path / ".forgeagent" / "loops").exists()
    assert imported == []


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


def test_build_mcp_manager_has_no_console_output(monkeypatch, capsys):
    class QuietManager:
        def __init__(self, servers):
            self.closed = False

        def connect(self):
            return None

        def required_failures(self):
            return {}

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"optional": MCPServerConfig(command="unused")},
    )
    monkeypatch.setattr(cli_module, "MCPManager", QuietManager)

    assert cli_module.build_mcp_manager() is not None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_build_mcp_manager_sanitizes_connect_and_cleanup_failures(monkeypatch, caplog):
    secret = "startup-secret"

    class HostileManager:
        def __init__(self, servers):
            self._closed = False

        def connect(self):
            raise RuntimeError(f"{secret} command=/private/command --token={secret} ExceptionGroup")

        def close(self):
            self._closed = True
            raise ValueError(f"cleanup leaked {secret} RuntimeError")

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", HostileManager)

    with pytest.raises(cli_module.MCPStartupError) as raised:
        cli_module.build_mcp_manager()

    rendered = str(raised.value)
    assert rendered == "startup_failed"
    assert caplog.messages == ["MCP connect cleanup incomplete"]
    for forbidden in (secret, "/private/command", "--token", "RuntimeError", "ExceptionGroup"):
        assert forbidden not in rendered
        assert forbidden not in caplog.text


def test_build_mcp_manager_sanitizes_non_control_base_exception_group(monkeypatch):
    secret = "exception-group-secret"

    class GroupFailureManager:
        def __init__(self, servers):
            self.closed = False

        def connect(self):
            raise BaseExceptionGroup(secret, [asyncio.CancelledError(secret)])

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", GroupFailureManager)

    with pytest.raises(cli_module.MCPStartupError) as raised:
        cli_module.build_mcp_manager()

    assert str(raised.value) == "startup_failed"
    assert secret not in str(raised.value)


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_build_mcp_manager_extracts_process_control_from_exception_group(monkeypatch, control):
    class GroupFailureManager:
        def __init__(self, servers):
            pass

        def connect(self):
            raise BaseExceptionGroup("hostile ExceptionGroup", [control("stop")])

        def close(self):
            pytest.fail("process control must not be replaced by cleanup")

    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", GroupFailureManager)

    with pytest.raises(control, match="stop"):
        cli_module.build_mcp_manager()


def test_bare_mcp_renders_bounded_sanitized_diagnostics(monkeypatch):
    manager = _DiagnosticManager(
        (
            _diagnostic("ready", tool_count=3),
            _diagnostic(
                "docker",
                status="unavailable: docker_unavailable",
                reason="Docker is not running",
                impact="Only this configured integration is disabled",
                action="Start Docker or disable this server",
            ),
        )
    )
    console = _terminal_console()

    cli_module._handle_mcp_slash("/mcp", manager, console)

    lines = [line for line in console.export_text().splitlines() if line.strip()]
    assert any(line == "Status: available" for line in lines)
    assert any(line == "Tools: 3" for line in lines)
    assert any(line == "Status: unavailable: docker_unavailable" for line in lines)
    assert any(line == "Reason: Docker is not running" for line in lines)
    assert any(line == "Impact: Only this configured integration is disabled" for line in lines)
    assert any(line == "Action: Start Docker or disable this server" for line in lines)
    assert all(
        line.startswith(("ready", "docker", "Status:", "Tools:", "Reason:", "Impact:", "Action:"))
        for line in lines
    )
    assert len(lines) <= 10


def test_mcp_diagnostic_uses_only_fixed_public_labels():
    secret = "diagnostic-secret-value"
    manager = MCPManager({"docker": MCPServerConfig(command="unused")})
    manager._secret_values = {secret}
    capture = mcp_manager_module._BoundedStderrCapture()
    capture.__enter__()
    assert capture.stream is not None
    capture.stream.write(f"RuntimeError: cannot connect to /var/run/docker.sock token={secret}")
    capture.close()
    manager._publish_unavailable("docker", 0, capture)
    console = _terminal_console()

    cli_module._handle_mcp_slash("/mcp", manager, console)

    rendered = console.export_text()
    for label in ("Status", "Tools", "Reason", "Impact", "Action"):
        assert f"{label}:" in rendered
    assert "Docker is not running" in rendered
    for internal in ("docker.sock", "RuntimeError", secret):
        assert internal not in rendered


def test_mcp_command_usage_lists_status_tools_and_toggles():
    console = _console()

    cli_module._handle_mcp_slash("/mcp unknown", _DiagnosticManager(()), console)

    rendered = console.export_text()
    assert "status" in rendered
    assert "tools" in rendered
    assert "enable <server>" in rendered
    assert "disable <server>" in rendered


def test_handle_mcp_slash_tools_lists_tools_without_status():
    console = _console()

    cli_module._handle_mcp_slash("/mcp tools", _FakeMCPWithTools(), console)

    rendered = console.export_text()
    assert "fs:read" in rendered
    assert "read a file" in rendered
    assert "fs: available" not in rendered


def test_build_mcp_manager_closes_and_raises_for_required_failures(monkeypatch):
    import forgeagent.cli as cli_module

    _RequiredStartupFailureManager.instances.clear()
    monkeypatch.setattr(
        cli_module,
        "load_mcp_config",
        lambda: {"required": MCPServerConfig(command="unused", required=True)},
    )
    monkeypatch.setattr(cli_module, "MCPManager", _RequiredStartupFailureManager)

    with pytest.raises(cli_module.MCPStartupError) as error:
        cli_module.build_mcp_manager()

    assert _RequiredStartupFailureManager.instances[0].closed is True
    assert str(error.value) == "required_server_unavailable"


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

    assert cli_module.build_mcp_manager() is None
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
        cli_module.build_mcp_manager()

    assert _CleanupFailureRequiredStartupManager.instances[0].closed is True
    assert str(error.value) == "required_server_unavailable"


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
        cli_module.build_mcp_manager()

    assert _CleanupFailureRequiredStartupManager.instances[0].closed is True
    assert str(error.value) == "required_server_unavailable"


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
        cli_module.build_mcp_manager()

    expected_primary = (
        "startup_failed" if failure_kind == "connect" else "required_server_unavailable"
    )
    assert str(raised.value) == expected_primary
    assert caplog.messages == [f"MCP {failure_kind} cleanup incomplete"]
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
        cli_module.build_mcp_manager()


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
    manager = cli_module.build_mcp_manager()
    assert manager is not None
    try:
        repl_console = _console()
        cli_module._handle_mcp_command("mcp status", manager, repl_console)
    finally:
        manager.close()

    rendered = console.export_text() + repl_console.export_text()
    assert "optional: unavailable" in rendered
    assert "RuntimeError" not in rendered
    assert raw_status not in rendered
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
        cli_module.build_mcp_manager()

    assert InfrastructureFailureManager.instance.closed is True
    assert str(raised.value) == "startup_failed"
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
        cli_module.build_mcp_manager()

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
        cli_module.build_mcp_manager()

    assert secret not in str(raised.value)
    assert str(raised.value) == "required_server_unavailable"


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
            cli_module.build_mcp_manager()
        assert str(raised.value) == "startup_failed"
    else:
        with pytest.raises(expected_error, match="cleanup failure"):
            cli_module.build_mcp_manager()


def test_main_reports_required_mcp_startup_error_without_running_task(monkeypatch):
    import forgeagent.cli as cli_module

    console = _console()
    ran_task: list[bool] = []
    _RequiredStartupFailureManager.instances.clear()
    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
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


def test_main_routes_sanitized_mcp_startup_error_to_stderr(monkeypatch, capsys):
    secret = "hostile-startup-secret"
    monkeypatch.setattr(
        cli_module,
        "build_mcp_manager",
        lambda: (_ for _ in ()).throw(
            cli_module.MCPStartupError(
                f"RuntimeError ExceptionGroup /private/path --token={secret} ENV={secret}"
            )
        ),
    )
    monkeypatch.setattr(cli_module, "load_mcp_config", lambda: {})

    assert cli_module.main(["run", "goal"], client_factory=_factory([])) == 2

    captured = capsys.readouterr()
    assert "MCP startup error" in captured.err
    assert "startup_failed" in captured.err
    assert captured.out == ""
    for forbidden in (secret, "RuntimeError", "ExceptionGroup", "/private/path", "--token", "ENV="):
        assert forbidden not in captured.err


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
        cli_module.build_mcp_manager()

    assert secret not in str(error.value)


def test_main_run_wires_confirmer_only_with_terminal_console_and_tty_stdin(monkeypatch):
    import forgeagent.cli as cli_module

    seen: list[object] = []
    real_run_once = cli_module.run_once
    console = Console(record=True, force_terminal=True)

    def spy_run_once(*args, **kwargs):
        seen.append(kwargs["confirmer"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
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

    monkeypatch.setattr(
        cli_module,
        "Console",
        lambda **kwargs: Console(record=True, force_terminal=False),
    )
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: _MCP())
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

    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
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

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
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
    assert console.export_text() == ""


def test_repl_exits_cleanly_on_keyboard_interrupt(monkeypatch):
    import forgeagent.cli as cli_module

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)

    def interrupt(_prompt):
        raise KeyboardInterrupt

    repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        console=_console(),
        read_line=interrupt,
        confirmation_available=False,
        no_identity=True,
        use_registry_snapshot=False,
    )


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


def test_usage_line_uses_cache_hit_ratio_of_sums_and_rejects_unusable_denominators():
    from forgeagent.cli import _accumulate_usage, _print_usage

    total = TokenUsage()
    _accumulate_usage(
        total,
        [RoundResult(text="", usage=TokenUsage(cached_tokens=10, total_prompt_tokens=40))],
    )
    _accumulate_usage(
        total,
        [RoundResult(text="", usage=TokenUsage(cached_tokens=30, total_prompt_tokens=60))],
    )
    console = _console()
    _print_usage(total, console)
    assert "cache_hit=40.0%" in console.export_text()

    _accumulate_usage(total, [RoundResult(text="", usage=TokenUsage(total_prompt_tokens=None))])
    console = _console()
    _print_usage(total, console)
    assert "cache_hit=n/a" in console.export_text()

    for usage in (
        TokenUsage(cached_tokens=0, total_prompt_tokens=0),
        TokenUsage(cached_tokens=-1, total_prompt_tokens=10),
        TokenUsage(cached_tokens=11, total_prompt_tokens=10),
    ):
        console = _console()
        _print_usage(usage, console)
        assert "cache_hit=n/a" in console.export_text()


def test_repl_cache_rate_accumulates_without_reusing_task_messages():
    from forgeagent.cli import repl

    received_message_counts: list[int] = []

    class RecordingClient(MockClient):
        def complete(self, messages, params=None):
            received_message_counts.append(len(messages))
            return super().complete(messages, params)

    per_task_scripts = iter(
        [
            [_reply(_done(), usage=TokenUsage(cached_tokens=10, total_prompt_tokens=40))],
            [_reply(_done(), usage=TokenUsage(cached_tokens=30, total_prompt_tokens=60))],
        ]
    )
    console = _console()
    inputs = iter(["first goal", "second goal", "quit"])
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=lambda model: RecordingClient(script=next(per_task_scripts)),
        console=console,
        read_line=lambda prompt: next(inputs),
    )

    assert received_message_counts == [2, 2]
    assert console.export_text().count("cache_hit=40.0%") == 1


def test_repl_falsey_context_reload_keeps_previous_registry_and_context(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.context as context_module
    from forgeagent.context import ContextConfig
    from forgeagent.model_registry import load_registry

    old_registry = load_registry()
    candidate_registry = old_registry.model_copy(deep=True)
    old_context = ContextConfig(image_token_reserve=111)
    inputs = iter(["/reload", "do a thing", "quit"])
    seen_contexts = []
    seen_registries = []
    real_run_once = cli_module.run_once
    config_path = tmp_path / "config.yaml"
    config_path.write_text("false\n")

    monkeypatch.setattr(context_module, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "reload_registry", lambda: candidate_registry)

    def real_factory(model, *, registry=None, env=None):
        seen_registries.append(registry)
        return MockClient(script=[_reply(_done())])

    def record_run_once(*args, **kwargs):
        seen_contexts.append(kwargs["context_config"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "build_real_client", real_factory)
    monkeypatch.setattr(cli_module, "run_once", record_run_once)
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=real_factory,
        console=console,
        read_line=lambda prompt: next(inputs),
        context_config=old_context,
        registry=old_registry,
    )

    text = console.export_text()
    assert "reload failed" in text
    assert "reloaded:" not in text
    assert seen_contexts == [old_context]
    assert seen_registries == [old_registry]


def test_repl_context_reload_swaps_context_only_after_both_configs_validate(monkeypatch):
    import forgeagent.cli as cli_module
    from forgeagent.context import ContextConfig

    old_context = ContextConfig(image_token_reserve=111)
    new_context = ContextConfig(image_token_reserve=222)
    inputs = iter(["/reload", "do a thing", "quit"])
    seen_contexts = []
    real_run_once = cli_module.run_once

    monkeypatch.setattr(cli_module, "load_context_config", lambda: new_context)

    def record_run_once(*args, **kwargs):
        seen_contexts.append(kwargs["context_config"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", record_run_once)
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([_reply(_done())]),
        console=console,
        read_line=lambda prompt: next(inputs),
        context_config=old_context,
    )

    assert "reloaded:" in console.export_text()
    assert seen_contexts == [new_context]


def test_repl_reload_swaps_skills_only_after_all_candidates_are_valid(monkeypatch):
    import forgeagent.cli as cli_module

    old = _registry_with_skill("old skill")
    new = _registry_with_skill("new skill")
    inputs = iter(["/reload", "goal", "quit"])
    observed = []
    real_run_once = cli_module.run_once

    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **kwargs: new)

    def record_run_once(*args, **kwargs):
        observed.append(kwargs["skills"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", record_run_once)
    cli_module.repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([_reply(_done())]),
        console=_console(),
        read_line=lambda prompt: next(inputs),
        confirmation_available=False,
        use_registry_snapshot=False,
        skills=old,
    )

    assert observed == [new]
    assert observed[0].read("review-python") == new.read("review-python")


def test_repl_reload_keeps_existing_skill_snapshot_when_skill_loading_fails(monkeypatch):
    import forgeagent.cli as cli_module

    old = _registry_with_skill("old skill")
    inputs = iter(["/reload", "goal", "quit"])
    observed = []
    real_run_once = cli_module.run_once

    def fail_load(**kwargs):
        raise OSError("skill storage unavailable")

    monkeypatch.setattr(cli_module, "_load_skill_registry", fail_load)

    def record_run_once(*args, **kwargs):
        observed.append(kwargs["skills"])
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(cli_module, "run_once", record_run_once)
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([_reply(_done())]),
        console=console,
        read_line=lambda prompt: next(inputs),
        confirmation_available=False,
        use_registry_snapshot=False,
        skills=old,
    )

    assert observed == [old]
    assert "reload failed" in console.export_text()


def test_repl_reload_preserves_session_memory_while_reloading_project_memory_access(
    monkeypatch, tmp_path
):
    import forgeagent.cli as cli_module

    project_memory = tmp_path / ".forgeagent" / "MEMORY.md"
    project_memory.parent.mkdir()
    project_memory.write_text(
        "<!-- forgeagent-memory-v1 -->\n- language: python\n",
        encoding="utf-8",
    )
    identities = iter([None, SimpleNamespace(memory="trusted project memory")])
    inputs = iter(["/remember session editor=nvim", "/reload", "/memory", "quit"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: next(identities))

    console = _console()
    cli_module.repl(
        tier="trusted",
        model="mock",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
        confirmation_available=False,
        use_registry_snapshot=False,
    )

    rendered = console.export_text()
    assert "editor: nvim" in rendered
    assert "language: python" in rendered


def test_repl_reload_rejects_unresolvable_policy_and_keeps_old_registry_pair(monkeypatch):
    import forgeagent.cli as cli_module
    from forgeagent.context import ContextConfig
    from forgeagent.model_registry import load_registry

    old_registry = load_registry()
    candidate_registry = old_registry.model_copy(deep=True)
    old_context = ContextConfig()
    invalid_context = ContextConfig(tool_result_max_tokens=100_000)
    used_registries = []
    inputs = iter(["/reload", "do a thing", "quit"])

    monkeypatch.setattr(cli_module, "reload_registry", lambda: candidate_registry)
    monkeypatch.setattr(cli_module, "load_context_config", lambda: invalid_context)

    def real_factory(model, *, registry=None, env=None):
        used_registries.append(registry)
        return MockClient(script=[_reply(_done())])

    monkeypatch.setattr(cli_module, "build_real_client", real_factory)
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=real_factory,
        console=console,
        read_line=lambda prompt: next(inputs),
        context_config=old_context,
        registry=old_registry,
    )

    assert "reload failed" in console.export_text()
    assert "reloaded:" not in console.export_text()
    assert used_registries == [old_registry]


def test_repl_reload_uses_new_registry_and_context_after_candidate_validation(monkeypatch):
    import forgeagent.cli as cli_module
    from forgeagent.context import ContextConfig
    from forgeagent.model_registry import load_registry

    old_registry = load_registry()
    new_registry = old_registry.model_copy(deep=True)
    old_context = ContextConfig(image_token_reserve=111)
    new_context = ContextConfig(image_token_reserve=222)
    used_registries = []
    inputs = iter(["/reload", "do a thing", "quit"])

    monkeypatch.setattr(cli_module, "reload_registry", lambda: new_registry)
    monkeypatch.setattr(cli_module, "load_context_config", lambda: new_context)

    def real_factory(model, *, registry=None, env=None):
        used_registries.append(registry)
        return MockClient(script=[_reply(_done())])

    monkeypatch.setattr(cli_module, "build_real_client", real_factory)
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=real_factory,
        console=_console(),
        read_line=lambda prompt: next(inputs),
        context_config=old_context,
        registry=old_registry,
    )

    assert used_registries == [new_registry]


def test_repl_registry_snapshot_never_bypasses_injected_factory():
    import forgeagent.cli as cli_module
    from forgeagent.model_registry import load_registry

    calls = []
    inputs = iter(["do a thing", "quit"])

    def injected_factory(model):
        calls.append(model)
        return MockClient(script=[_reply(_done())])

    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=injected_factory,
        console=_console(),
        read_line=lambda prompt: next(inputs),
        registry=load_registry(),
    )

    assert calls == ["claude-sonnet-5"]


def test_repl_rejects_model_switch_when_current_context_cannot_fit_its_capability(monkeypatch):
    import forgeagent.cli as cli_module
    from forgeagent.context import ContextConfig
    from forgeagent.model_registry import load_registry

    models = []
    inputs = iter(["/model claude-haiku-4-5", "do a thing", "quit"])

    def real_factory(model, *, registry=None, env=None):
        models.append(model)
        return MockClient(script=[_reply(_done())])

    monkeypatch.setattr(cli_module, "build_real_client", real_factory)
    console = _console()
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=real_factory,
        console=console,
        read_line=lambda prompt: next(inputs),
        context_config=ContextConfig(tool_result_max_tokens=10_000),
        registry=load_registry(),
    )

    assert "model switch failed" in console.export_text()
    assert models == ["claude-sonnet-5"]


def test_main_returns_config_error_for_initial_unresolvable_context_policy(monkeypatch, capsys):
    import forgeagent.cli as cli_module
    from forgeagent.context import ContextConfig

    monkeypatch.setattr(
        cli_module,
        "load_context_config",
        lambda: ContextConfig(tool_result_max_tokens=100_000),
    )

    assert cli_module.main(["run", "do a thing"], client_factory=_factory([_reply(_done())])) == 2
    assert "config error" in capsys.readouterr().err


def test_cli_context_config_uses_default_loader_without_internal_override(monkeypatch):
    from forgeagent.context import ContextConfig

    expected = ContextConfig(image_token_reserve=123)
    calls = []
    monkeypatch.delenv(cli_module._CONTEXT_CONFIG_ENVIRONMENT, raising=False)

    def fake_load_context_config(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(cli_module, "load_context_config", fake_load_context_config)

    assert cli_module._load_cli_context_config() is expected
    assert calls == [((), {})]


def test_cli_context_config_accepts_internal_json_override(monkeypatch):
    monkeypatch.setenv(
        cli_module._CONTEXT_CONFIG_ENVIRONMENT,
        '{"context":{"round_feedback_max_tokens":4000,"tool_result_max_tokens":2000}}',
    )

    config = cli_module._load_cli_context_config()

    assert config.round_feedback_max_tokens == 4_000
    assert config.tool_result_max_tokens == 2_000


@pytest.mark.parametrize(
    "value",
    ["{", "[]"],
    ids=["malformed", "non-mapping"],
)
def test_cli_context_config_rejects_invalid_internal_json(monkeypatch, value):
    monkeypatch.setenv(cli_module._CONTEXT_CONFIG_ENVIRONMENT, value)
    monkeypatch.setattr(
        cli_module,
        "load_context_config",
        lambda *args, **kwargs: pytest.fail("invalid JSON reached context loader"),
    )

    with pytest.raises(RegistryError, match="Invalid context configuration"):
        cli_module._load_cli_context_config()


def test_cli_context_config_converts_json_recursion_error(monkeypatch):
    monkeypatch.setenv(cli_module._CONTEXT_CONFIG_ENVIRONMENT, "{}")
    monkeypatch.setattr(
        cli_module.json,
        "loads",
        lambda value: (_ for _ in ()).throw(RecursionError("synthetic secret")),
    )

    with pytest.raises(RegistryError, match="Invalid context configuration") as error:
        cli_module._load_cli_context_config()

    assert "synthetic secret" not in str(error.value)


def test_cli_candidate_file_configuration_defaults_to_empty(monkeypatch):
    monkeypatch.delenv(cli_module._CANDIDATE_FILES_ENVIRONMENT, raising=False)

    assert cli_module._load_required_candidate_files_from_environment() == ()


def test_cli_candidate_file_configuration_accepts_internal_json(monkeypatch):
    monkeypatch.setenv(
        cli_module._CANDIDATE_FILES_ENVIRONMENT,
        '["calc.py","test_calc.py"]',
    )

    assert cli_module._load_required_candidate_files_from_environment() == (
        "calc.py",
        "test_calc.py",
    )


@pytest.mark.parametrize(
    "value",
    ["{", "{}", '"calc.py"', '["calc.py","calc.py"]', '["../secret"]'],
)
def test_cli_candidate_file_configuration_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv(cli_module._CANDIDATE_FILES_ENVIRONMENT, value)

    with pytest.raises(RegistryError, match="Invalid candidate file configuration") as error:
        cli_module._load_required_candidate_files_from_environment()

    assert value not in str(error.value)


def test_cli_candidate_file_configuration_converts_json_recursion_error(monkeypatch):
    monkeypatch.setenv(cli_module._CANDIDATE_FILES_ENVIRONMENT, "[]")
    monkeypatch.setattr(
        cli_module.json,
        "loads",
        lambda value: (_ for _ in ()).throw(RecursionError("synthetic secret")),
    )

    with pytest.raises(RegistryError, match="Invalid candidate file configuration") as error:
        cli_module._load_required_candidate_files_from_environment()

    assert "synthetic secret" not in str(error.value)


def test_main_threads_candidate_file_configuration_only_to_collaboration(monkeypatch):
    captured = {}
    monkeypatch.setenv(
        cli_module._CANDIDATE_FILES_ENVIRONMENT,
        '["calc.py","test_calc.py"]',
    )
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)

    def fake_collaboration(*args, **kwargs):
        captured.update(kwargs)
        return CollaborationReport(
            collaboration_id="c" * 32,
            mode="duo",
            status="completed",
            stop_reason="completed",
            phase="completed",
            plan_item_count=1,
            passed_item_count=1,
            failed_item_count=0,
            generator_attempts=1,
            evaluator_attempts=1,
            rejections=0,
            rounds=2,
            usage=CollaborationUsage(),
            usage_available=False,
            evidence=(),
        )

    monkeypatch.setattr(cli_module, "run_collaboration_once", fake_collaboration)

    assert (
        cli_module.main(
            ["--tier", "trusted", "run", "--mode", "duo", "explain a concept"],
            client_factory=_factory([]),
        )
        == 0
    )
    assert captured["required_candidate_files"] == ("calc.py", "test_calc.py")


def test_main_single_ignores_private_candidate_file_configuration(monkeypatch):
    monkeypatch.setenv(cli_module._CANDIDATE_FILES_ENVIRONMENT, "not-json")

    assert (
        cli_module.main(
            ["--tier", "trusted", "run", "--mode", "single", "explain a concept"],
            client_factory=_factory([_reply(_done())]),
        )
        == 0
    )


def test_main_custom_injected_model_uses_factory_without_registry_lookup():
    custom_capability = ModelCapability(
        model_id="custom-model",
        context_window=1_000_000,
        max_output_tokens=128_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )
    calls = []

    def injected_factory(model):
        calls.append(model)
        return MockClient(script=[_reply(_done())], capability=custom_capability)

    assert main(["--model", "custom-model", "run", "goal"], client_factory=injected_factory) == 0
    assert calls == ["custom-model"]


def test_main_injected_capability_policy_failure_is_structured_and_single_use(capsys):
    incompatible_capability = ModelCapability(
        model_id="claude-sonnet-5",
        context_window=100,
        max_output_tokens=100,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )
    clients = []

    def injected_factory(model):
        client = MockClient(script=[_reply(_done())], capability=incompatible_capability)
        clients.append(client)
        return client

    assert main(["run", "goal"], client_factory=injected_factory) == 2
    assert "config error" in capsys.readouterr().err
    assert len(clients) == 1
    assert clients[0].calls_made == 0


def test_direct_repl_registry_does_not_prevalidate_injected_custom_model():
    import forgeagent.cli as cli_module
    from forgeagent.model_registry import load_registry

    custom_capability = ModelCapability(
        model_id="custom-model",
        context_window=1_000_000,
        max_output_tokens=128_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )
    calls = []
    inputs = iter(["goal", "quit"])

    def injected_factory(model):
        calls.append(model)
        return MockClient(script=[_reply(_done())], capability=custom_capability)

    console = _console()
    cli_module.repl(
        tier="trusted",
        model="custom-model",
        client_factory=injected_factory,
        console=console,
        read_line=lambda prompt: next(inputs),
        registry=load_registry(),
    )

    assert calls == ["custom-model"]
    assert "completed" in console.export_text()


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


@pytest.mark.parametrize("command", ["run", "serve", "models", "smoke"])
def test_noninteractive_commands_do_not_render_repl_startup_information(
    monkeypatch, tmp_path, command
):
    import forgeagent.cli as cli_module

    class OptionalMCP:
        def tools_prompt(self):
            return ""

        def close(self):
            pass

    console = _console()
    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
    monkeypatch.setattr(cli_module, "_StartupDisplay", lambda *_: pytest.fail("unexpected logo"))
    monkeypatch.setattr(
        cli_module,
        "_render_startup_summary",
        lambda **kwargs: pytest.fail("unexpected startup summary"),
    )
    monkeypatch.setattr(cli_module, "build_mcp_manager", OptionalMCP)
    monkeypatch.setattr(
        cli_module,
        "serve_http",
        lambda *args, console, **kwargs: console.print("serving on 127.0.0.1:8765"),
    )

    argv = {
        "run": ["run", "goal"],
        "serve": ["serve", "--config", str(tmp_path / "http.yaml")],
        "models": ["models"],
        "smoke": ["smoke"],
    }[command]
    factory = _smoke_factory() if command == "smoke" else _factory([_reply(_done())])

    assert main(argv, client_factory=factory) == 0
    rendered = console.export_text()
    assert "ForgeAgent" not in rendered
    assert "Ready |" not in rendered
    assert "MCP 1/1" not in rendered
    assert "unavailable" not in rendered


# --- models / reload commands (M7 Phase 4) -----------------------------------


def test_models_command_lists_registered_models():
    code = main(["models"], client_factory=_factory([]))  # factory unused by `models`
    assert code == 0


# --- explicit evaluator command (M20) ---------------------------------------


def _evaluate_argv(tmp_path, *extra: str) -> list[str]:
    return [
        "evaluate",
        "--model",
        "mock-evaluator",
        "--artifact-root",
        str(tmp_path),
        "--task-description",
        "check result",
        "--expected-behavior",
        "result is correct",
        "--artifact",
        "result.txt",
        *extra,
    ]


def test_evaluate_parser_requires_explicit_contract(tmp_path):
    args = build_parser().parse_args(_evaluate_argv(tmp_path))

    assert args.command == "evaluate"
    assert args.evaluate_model == "mock-evaluator"
    assert args.artifacts == ["result.txt"]


def test_evaluate_fails_before_artifact_read_when_model_is_unusable(monkeypatch, tmp_path, capsys):
    inspected = False

    def observe_manifest(root, paths):
        nonlocal inspected
        inspected = True
        raise AssertionError("artifact inspection must happen after model preflight")

    def fail_client(model):
        raise RegistryError("secret provider detail")

    monkeypatch.setattr(cli_module, "validate_artifact_manifest", observe_manifest)

    code = main(_evaluate_argv(tmp_path), client_factory=fail_client)

    captured = capsys.readouterr()
    assert code == 2
    assert not inspected
    assert "evaluation preflight failed" in captured.err
    assert "secret provider detail" not in captured.err


def test_evaluate_constructs_only_declared_isolated_request(monkeypatch, tmp_path, capsys):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    captured_request: EvaluationRequest | None = None

    def fake_run_evaluator(client, request):
        nonlocal captured_request
        captured_request = request
        return EvaluatorResult(
            status="passed",
            observed_evidence=("result matched",),
            unmet_expectations=(),
        )

    monkeypatch.setattr(cli_module, "run_evaluator", fake_run_evaluator)
    monkeypatch.setattr(
        cli_module,
        "resolve_cli_identity",
        lambda **kwargs: pytest.fail("evaluate must not load identity"),
    )
    monkeypatch.setattr(
        cli_module,
        "_make_memory_manager",
        lambda *args, **kwargs: pytest.fail("evaluate must not load memory"),
    )
    monkeypatch.setattr(
        cli_module,
        "_load_skill_registry",
        lambda **kwargs: pytest.fail("evaluate must not load skills"),
    )
    monkeypatch.setattr(
        cli_module,
        "build_mcp_manager",
        lambda: pytest.fail("evaluate must not load MCP"),
    )

    code = main(_evaluate_argv(tmp_path), client_factory=_factory([]))

    rendered = capsys.readouterr().out
    assert code == 0
    assert captured_request is not None
    assert captured_request.task_description == "check result"
    assert captured_request.expected_behavior == "result is correct"
    assert captured_request.artifacts[0].path == "result.txt"
    assert str(tmp_path) not in rendered
    assert "passed" in rendered


def test_evaluate_failed_result_returns_one(monkeypatch, tmp_path):
    (tmp_path / "result.txt").write_text("wrong", encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult(
            status="failed",
            observed_evidence=("wrong value",),
            unmet_expectations=("expected value missing",),
        ),
    )

    assert main(_evaluate_argv(tmp_path), client_factory=_factory([])) == 1


def test_evaluate_renders_null_metrics_as_na(monkeypatch, tmp_path, capsys):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult("passed", (), ()),
    )

    code = main(_evaluate_argv(tmp_path), client_factory=_factory([]))

    assert code == 0
    assert "n/a" in capsys.readouterr().out


def test_evaluate_persistence_failure_returns_two_without_claiming_pass(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    record_dir = tmp_path / "records"
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult("passed", (), ()),
    )
    monkeypatch.setattr(
        cli_module,
        "append_trend",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private path")),
    )

    code = main(
        _evaluate_argv(tmp_path, "--record-dir", str(record_dir)),
        client_factory=_factory([]),
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "evaluation persistence failed" in captured.err
    assert "private path" not in captured.err
    assert "passed" not in captured.out


def test_evaluate_rejects_relative_record_directory_before_model_call(monkeypatch, tmp_path):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    called = False

    def fake_run_evaluator(client, request):
        nonlocal called
        called = True
        return EvaluatorResult("passed", (), ())

    monkeypatch.setattr(cli_module, "run_evaluator", fake_run_evaluator)

    code = main(
        _evaluate_argv(tmp_path, "--record-dir", "relative-records"),
        client_factory=_factory([]),
    )

    assert code == 2
    assert not called


def test_evaluate_loads_optional_golden_and_audit_evidence(monkeypatch, tmp_path, capsys):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    golden_report = tmp_path / "golden.json"
    golden_report.write_text(
        json.dumps({"schema": "forgeagent.golden.v1", "total": 4, "passed": 3}),
        encoding="utf-8",
    )
    audit_jsonl = tmp_path / "audit.jsonl"
    audit_jsonl.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "event_type": "llm.outcome",
                    "result_status": "success",
                    "parameters": {"usage": {"cached_tokens": 5, "total_prompt_tokens": 20}},
                },
                {
                    "event_type": "task.outcome",
                    "result_status": "completed",
                    "parameters": {"completed": True, "round_count": 1},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult("passed", (), ()),
    )

    code = main(
        _evaluate_argv(
            tmp_path,
            "--golden-report",
            str(golden_report),
            "--audit-jsonl",
            str(audit_jsonl),
        ),
        client_factory=_factory([]),
    )

    rendered = capsys.readouterr().out
    assert code == 0
    assert "golden_pass_rate: 75" in rendered
    assert "first_pass_correctness: 100" in rendered
    assert "correction_rounds: 0" in rendered
    assert "cache_hit_rate: 0.25" in rendered


def test_evaluate_uses_audit_metrics_without_golden_report(monkeypatch, tmp_path, capsys):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    audit_jsonl = tmp_path / "audit.jsonl"
    audit_jsonl.write_text(
        json.dumps(
            {
                "event_type": "llm.outcome",
                "result_status": "success",
                "parameters": {"usage": {"cached_tokens": 1, "total_prompt_tokens": 4}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult("passed", (), ()),
    )

    code = main(
        _evaluate_argv(tmp_path, "--audit-jsonl", str(audit_jsonl)),
        client_factory=_factory([]),
    )

    assert code == 0
    assert "cache_hit_rate: 0.25" in capsys.readouterr().out


def test_evaluate_persists_record_to_absolute_directory(monkeypatch, tmp_path):
    (tmp_path / "result.txt").write_text("ok", encoding="utf-8")
    record_dir = (tmp_path / "records").resolve()
    monkeypatch.setattr(
        cli_module,
        "run_evaluator",
        lambda client, request: EvaluatorResult("passed", (), ()),
    )

    code = main(
        _evaluate_argv(tmp_path, "--record-dir", str(record_dir)),
        client_factory=_factory([]),
    )

    assert code == 0
    index = json.loads((record_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index["run_ids"]) == 1
    assert (record_dir / f"{index['run_ids'][0]}.json").is_file()


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
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: fake)
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
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: fake)

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
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
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

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: fake_mcp)
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


def test_repl_explicit_confirmation_uses_injected_read_line_without_goal_prompt(monkeypatch):
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

    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "run_once", run_goal)
    cli_module.repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=_console(),
        read_line=read_line,
        confirmation_available=True,
    )

    assert prompts == ["", "approve? [y/N] ", ""]


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


def test_main_run_loads_one_skill_snapshot_and_no_identity_disables_project_discovery(
    monkeypatch, tmp_path
):
    import forgeagent.cli as cli_module

    skills = _registry_with_skill()
    calls = []
    seen = []
    real_run_once = cli_module.run_once

    def load_skills(**kwargs):
        calls.append(kwargs)
        return skills

    def record_run_once(*args, **kwargs):
        seen.append(kwargs["skills"])
        return real_run_once(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_load_skill_registry", load_skills)
    monkeypatch.setattr(cli_module, "run_once", record_run_once)

    assert main(["--no-identity", "run", "goal"], client_factory=_factory([_reply(_done())])) == 0

    assert len(calls) == 1
    assert calls[0]["home"] == str(cli_module.Path.home())
    assert calls[0]["allowed_root"] == str(tmp_path.resolve())
    assert calls[0]["no_identity"] is True
    assert calls[0]["confirmer"] is None
    assert callable(calls[0]["diagnostic"])
    assert seen == [skills]


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
    monkeypatch.setattr(
        cli_module,
        "Console",
        lambda **kwargs: Console(record=True, force_terminal=True),
    )
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


def test_make_console_skill_confirmer_uses_skill_specific_wording():
    from forgeagent.cli import make_console_skill_confirmer
    from forgeagent.identity import IdentityTrustRequest

    prompts = []
    console = _console()
    confirmer = make_console_skill_confirmer(
        console,
        read_line=lambda prompt: prompts.append(prompt) or "yes",
    )

    assert (
        confirmer(IdentityTrustRequest(project_label=".../repo", summary="review-python")) is True
    )

    rendered = console.export_text()
    assert "trust project Skills .../repo" in rendered
    assert "identity" not in rendered
    assert prompts == ["load these project Skills? [y/N] "]


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
        ["--no-memory"],
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
    console = _console()
    identity = object()
    skills = _registry_with_skill("user-only skill")
    skill_load_calls = []

    class FakeMCP:
        def close(self):
            events.append("mcp.close")

    mcp = FakeMCP()

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink, **_kwargs):
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
    monkeypatch.setattr(cli_module, "Console", lambda **kwargs: console)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: mcp)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: identity)
    monkeypatch.setattr(
        cli_module,
        "_load_skill_registry",
        lambda **kwargs: skill_load_calls.append(kwargs) or skills,
    )
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
    rendered = console.export_text()
    assert "ForgeAgent" not in rendered
    assert "Ready |" not in rendered
    assert "MCP 1/1" not in rendered
    assert "unavailable" not in rendered

    task = captured["factory"](SimpleNamespace(task_id="task-123"))
    other_task = captured["factory"](SimpleNamespace(task_id="task-456"))
    try:
        assert task._tier == "trusted"
        assert task._allowed_root == str(allowed_root.resolve())
        assert task._identity is identity
        assert task._mcp is mcp
        assert task._audit_sink is captured["audit_sink"]
        assert task._task_id == "task-123"
        assert task._confirmer.is_headless is True
        assert task._memory_manager is not other_task._memory_manager
        assert task._memory_manager.enabled is False
        assert task._skills is other_task._skills is skills
        assert task._skills.read("review-python") is not None
        assert task._skills.read("project-only") is None
    finally:
        task.close()
        other_task.close()

    assert len(skill_load_calls) == 1
    assert skill_load_calls[0]["confirmer"] is None
    assert skill_load_calls[0]["no_identity"] is True


def test_serve_task_factory_does_not_inherit_mcp_auto_approve(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        "\n".join(
            [
                "token: file-token",
                "tier: trusted",
                "no_identity: true",
                f"audit_path: {tmp_path / 'audit.jsonl'}",
                "allowlist: []",
            ]
        )
        + "\n"
    )
    captured: dict[str, object] = {}

    class AutoApprovedMCP:
        def __init__(self):
            self.auto_approval_checks: list[tuple[str, str]] = []
            self.calls: list[tuple[str, str, dict]] = []

        def tools_prompt(self):
            return ""

        def is_auto_approved(self, server, tool):
            self.auto_approval_checks.append((server, tool))
            return True

        def call_tool(self, server, tool, arguments):
            self.calls.append((server, tool, arguments))
            return {"ok": True, "text": "unexpected MCP execution"}

        def close(self):
            pass

    mcp = AutoApprovedMCP()

    class FakeService:
        def __init__(self, *, factory, config, shared_mcp_manager, audit_sink, **_kwargs):
            captured["factory"] = factory
            self.shared_mcp_manager = shared_mcp_manager

        def shutdown(self, timeout):
            self.shared_mcp_manager.close()

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def serve_forever(self, poll_interval):
            pass

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: mcp)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda config, service: FakeServer(),
    )
    tool_call = (
        '<!-- ToolCall: {"name":"MCP","arguments":'
        '{"server":"filesystem","tool":"write_file","arguments":{"path":"x"}}} -->'
    )

    assert (
        cli_module.main(
            ["serve", "--config", str(config_path), "--once"],
            client_factory=_factory([_reply(tool_call), _reply(_done())]),
        )
        == 0
    )

    task = captured["factory"](SimpleNamespace(task_id="http-task-auto-approve"))
    try:
        outcome = task.run("attempt an MCP write")
    finally:
        task.close()

    assert outcome.rounds[0].outcomes[0].success is False
    assert mcp.auto_approval_checks == []
    assert mcp.calls == []


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
        lambda: pytest.fail("audit failure must happen before MCP startup"),
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
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("invalid policy must not create a listener"),
    )

    assert cli_module.main(["serve", "--config", str(config_path), "--once"]) == 2


def test_serve_rejects_non_path_audit_config_before_listener(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text("token: file-token\naudit_path: true\n")
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda *args, **kwargs: pytest.fail("invalid audit path must not create a listener"),
    )

    assert cli_module.main(["serve", "--config", str(config_path), "--once"]) == 2


@pytest.mark.parametrize(
    "container_image",
    ["image\nnext", "image\x00next", "image\x7fnext"],
    ids=["newline", "nul", "delete"],
)
def test_http_runtime_config_rejects_container_image_control_characters(tmp_path, container_image):
    import forgeagent.cli as cli_module

    config_path = tmp_path / "http.json"
    config_path.write_text(json.dumps({"token": "file-token", "container_image": container_image}))

    with pytest.raises(cli_module.HttpStartupError, match="container"):
        cli_module._load_http_runtime_settings(config_path)


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


@pytest.mark.parametrize(
    ("console_error", "process_control"),
    [
        (RuntimeError("console unavailable"), False),
        (KeyboardInterrupt(), True),
    ],
    ids=["ordinary", "keyboard-interrupt"],
)
def test_serve_closes_listener_service_and_mcp_when_startup_output_fails(
    monkeypatch, tmp_path, console_error, process_control
):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        f"token: file-token\nno_identity: true\naudit_path: {tmp_path / 'audit.jsonl'}\n"
    )
    events: list[str] = []
    server_entered = threading.Event()
    release_server = threading.Event()

    class FakeMCP:
        def close(self):
            events.append("mcp.close")

    mcp = FakeMCP()

    class FakeService:
        def __init__(self, *, shared_mcp_manager, **kwargs):
            self._mcp = shared_mcp_manager

        def shutdown(self, timeout):
            events.append("service.shutdown")
            self._mcp.close()

    class FakeServer:
        server_address = ("127.0.0.1", 8765)
        serve_entered = server_entered

        def serve_forever(self, poll_interval):
            server_entered.set()
            release_server.wait(1.0)

        def shutdown(self):
            events.append("server.shutdown")
            release_server.set()

        def server_close(self):
            events.append("server.close")

    class FailingConsole:
        def print(self, *args, **kwargs):
            raise console_error

    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: mcp)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: None)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda config, service: FakeServer(),
    )

    expected_error = KeyboardInterrupt if process_control else cli_module.HttpStartupError
    with pytest.raises(expected_error):
        cli_module.serve_http(
            config_path,
            client_factory=_factory([]),
            console=FailingConsole(),
            once=True,
        )

    assert events == ["server.shutdown", "service.shutdown", "mcp.close", "server.close"]


def test_serve_wires_single_approval_and_receipt_authorities(monkeypatch, tmp_path):
    import forgeagent.cli as cli_module
    import forgeagent.http_server as http_server_module

    config_path = tmp_path / "http.yaml"
    config_path.write_text(
        f"token: file-token\nno_identity: true\nallowed_root: {tmp_path}\n"
        f"audit_path: {tmp_path / 'audit.jsonl'}\n"
    )
    captured = {}

    class FakeAuditSink:
        def __init__(self, *_args, **_kwargs):
            pass

    class FakeApprovalStore:
        def __init__(self, *, max_records, audit_sink):
            captured["approval_store"] = self
            captured["approval_max_records"] = max_records
            captured["approval_audit"] = audit_sink

    class FakeReceiptStore:
        def __init__(self, _root, *, audit_sink):
            captured["receipt_store"] = self
            captured["receipt_audit"] = audit_sink

        def close(self):
            pass

    class FakeConfirmer:
        def __init__(self, _allowlist, *, audit, root, approval_store):
            captured["confirmer_approval"] = approval_store
            captured["confirmer_audit"] = audit
            captured["confirmer_root"] = root

    class FakeService:
        def __init__(
            self,
            *,
            factory,
            config,
            shared_mcp_manager,
            audit_sink,
            approval_store,
            receipt_store,
        ):
            captured["factory"] = factory
            captured["service_approval"] = approval_store
            captured["service_receipt"] = receipt_store
            captured["service_audit"] = audit_sink

        def shutdown(self, timeout):
            pass

    monkeypatch.setattr(cli_module, "JsonlAuditSink", FakeAuditSink)
    monkeypatch.setattr(cli_module, "HttpActionApprovalStore", FakeApprovalStore, raising=False)
    monkeypatch.setattr(cli_module, "ExternalActionReceiptStore", FakeReceiptStore)
    monkeypatch.setattr(cli_module, "HeadlessConfirmer", FakeConfirmer)
    monkeypatch.setattr(cli_module, "TaskService", FakeService)
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "load_registry", lambda: object())
    monkeypatch.setattr(cli_module, "_validate_context_policy", lambda *_args: None)
    monkeypatch.setattr(cli_module, "_validate_client_context_policy", lambda *_args: None)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **_kwargs: None)
    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **_kwargs: None)
    monkeypatch.setattr(cli_module, "_make_memory_manager", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        http_server_module,
        "create_http_server",
        lambda _config, _service: SimpleNamespace(server_address=("127.0.0.1", 8765)),
    )
    monkeypatch.setattr(
        cli_module._cli_http,
        "run_owned_http_server",
        lambda _server, _service, **_kwargs: None,
    )

    cli_module.serve_http(
        config_path,
        client_factory=lambda _model: MockClient(script=[]),
        console=_console(),
        once=True,
    )

    assert captured["confirmer_approval"] is captured["approval_store"]
    assert captured["service_approval"] is captured["approval_store"]
    assert captured["service_receipt"] is captured["receipt_store"]
    assert captured["approval_audit"] is captured["service_audit"]
    assert captured["receipt_audit"] is captured["service_audit"]


def test_http_owner_restores_partial_signal_install_and_closes_resources(monkeypatch):
    import forgeagent.cli as cli_module

    events: list[str] = []
    signal_calls: list[tuple[object, object]] = []
    failed_sigterm = False

    class FakeServer:
        def server_close(self):
            events.append("server.close")

    class FakeService:
        def shutdown(self, timeout):
            events.extend(["service.shutdown", "mcp.close"])

    def fake_getsignal(signal_number):
        return f"previous:{signal_number}"

    def fake_signal(signal_number, handler):
        nonlocal failed_sigterm
        signal_calls.append((signal_number, handler))
        if signal_number == signal.SIGTERM and not failed_sigterm:
            failed_sigterm = True
            raise RuntimeError("SIGTERM unavailable")

    monkeypatch.setattr(cli_module.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(cli_module.signal, "signal", fake_signal)

    with pytest.raises(cli_module.HttpStartupError):
        cli_module._run_owned_http_server(
            FakeServer(),
            FakeService(),
            shutdown_timeout=0.25,
            once=False,
        )

    assert events == ["service.shutdown", "mcp.close", "server.close"]
    assert signal_calls[-1] == (signal.SIGINT, f"previous:{signal.SIGINT}")


def test_http_owner_once_waits_until_serve_forever_has_entered():
    import forgeagent.cli as cli_module

    entered = threading.Event()
    release = threading.Event()
    events: list[str] = []

    class FakeServer:
        serve_entered = entered

        def serve_forever(self, poll_interval):
            threading.Event().wait(0.05)
            entered.set()
            release.wait(1.0)

        def shutdown(self):
            was_entered = entered.is_set()
            events.append("server.shutdown")
            release.set()
            assert was_entered, "shutdown ran before serve_forever entered"

        def server_close(self):
            events.append("server.close")

    class FakeService:
        def shutdown(self, timeout):
            events.append("service.shutdown")

    cli_module._run_owned_http_server(
        FakeServer(),
        FakeService(),
        shutdown_timeout=0.25,
        once=True,
    )

    assert events == ["server.shutdown", "service.shutdown", "server.close"]


def test_http_owner_preserves_server_process_control_over_cleanup_failure():
    import forgeagent.cli as cli_module

    entered = threading.Event()

    class FakeServer:
        serve_entered = entered

        def serve_forever(self, poll_interval):
            entered.set()
            raise KeyboardInterrupt

        def shutdown(self):
            pass

        def server_close(self):
            pass

    class FakeService:
        def shutdown(self, timeout):
            raise RuntimeError("cleanup failed")

    with pytest.raises(KeyboardInterrupt):
        cli_module._run_owned_http_server(
            FakeServer(),
            FakeService(),
            shutdown_timeout=0.25,
            once=False,
        )


def test_http_owner_restores_signals_when_thread_join_is_interrupted(monkeypatch):
    import forgeagent.cli as cli_module

    entered = threading.Event()
    signal_calls: list[tuple[object, object]] = []
    real_join = threading.Thread.join

    class FakeServer:
        serve_entered = entered

        def serve_forever(self, poll_interval):
            entered.set()

        def shutdown(self):
            pass

        def server_close(self):
            pass

    class FakeService:
        def shutdown(self, timeout):
            pass

    def interrupted_join(thread, timeout=None):
        real_join(thread, timeout)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        cli_module.signal,
        "getsignal",
        lambda signal_number: f"previous:{signal_number}",
    )
    monkeypatch.setattr(
        cli_module.signal,
        "signal",
        lambda signal_number, handler: signal_calls.append((signal_number, handler)),
    )
    monkeypatch.setattr(cli_module.threading.Thread, "join", interrupted_join)

    with pytest.raises(KeyboardInterrupt):
        cli_module._run_owned_http_server(
            FakeServer(),
            FakeService(),
            shutdown_timeout=0.25,
            once=False,
        )

    assert signal_calls[-2:] == [
        (signal.SIGTERM, f"previous:{signal.SIGTERM}"),
        (signal.SIGINT, f"previous:{signal.SIGINT}"),
    ]
