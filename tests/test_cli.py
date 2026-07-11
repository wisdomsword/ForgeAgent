"""Unit tests for the CLI (M5-2).

All tests inject a MockClient factory — no key, no network, no real subprocess. The
CLI logic under test is argument handling, run/REPL flow, outcome rendering, and clear
config-error behavior.
"""

from rich.console import Console

from forgeagent.cli import build_parser, main, run_once
from forgeagent.client import MockClient
from forgeagent.model_registry import RegistryError
from forgeagent.models import AssistantMessage, TokenUsage


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
    assert "usage: in=1234 out=567 cached=89 (session total)" in console.export_text()


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
    assert "usage: in=18 out=8 cached=2 (session total)" in console.export_text()


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
    assert "usage: in=10 out=5 cached=1 (session total)" in text
    assert "usage: in=30 out=12 cached=4 (session total)" in text


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
