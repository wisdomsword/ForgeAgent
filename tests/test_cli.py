"""Unit tests for the CLI (M5-2).

All tests inject a MockClient factory — no key, no network, no real subprocess. The
CLI logic under test is argument handling, run/REPL flow, outcome rendering, and clear
config-error behavior.
"""

from rich.console import Console

from forgeagent.cli import build_parser, main, run_once
from forgeagent.client import MockClient
from forgeagent.model_registry import RegistryError
from forgeagent.models import AssistantMessage, StreamEvent, StreamEventKind, TokenUsage


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
    return Console(record=True, width=100)


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


def test_repl_reload_command_reports_model_count():
    from forgeagent.cli import repl

    inputs = iter(["reload", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    assert "reloaded" in console.export_text()


def test_repl_models_command_lists_without_running_a_task():
    from forgeagent.cli import repl

    inputs = iter(["models", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),  # never called — models/quit run no task
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


def test_repl_compat_models_word_shows_deprecation_and_still_lists():
    from forgeagent.cli import repl

    inputs = iter(["models", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    assert "deprecated" in text
    assert "/model" in text
    assert "claude-sonnet-5" in text


def test_repl_compat_bare_mcp_word_shows_deprecation():
    from forgeagent.cli import repl

    inputs = iter(["mcp", "quit"])
    console = _console()
    repl(
        tier="trusted",
        model="claude-sonnet-5",
        client_factory=_factory([]),  # never called — "mcp" never reaches run_once
        console=console,
        read_line=lambda prompt: next(inputs),
    )
    text = console.export_text()
    assert "deprecated" in text
    assert "/mcp" in text


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
