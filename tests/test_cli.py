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


def _reply(text: str, stop_reason: str = "end_turn") -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason=stop_reason)


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
