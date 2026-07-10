"""Command-line interface: single-command execution and an interactive REPL.

See ACTION_PLAN M5. Two entry points:
  - `forgeagent run "<goal>"`  -> run one task, print the outcome
  - `forgeagent`               -> REPL: read a goal, run it, repeat

Uses argparse (stdlib, lightweight) and rich for output. Default tier is `restricted`;
`--tier trusted` opts out. The real client is assembled from the environment via
the model registry (see model_registry.py — model_id routes to exactly one provider
group, never a priority scan across whichever env vars happen to be set); a
MockClient can be injected for tests.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from rich.console import Console

from .anthropic_client import AnthropicClient
from .client import ModelClient
from .model_registry import RegistryError, load_registry, resolve_model
from .openai_compatible_client import OpenAICompatibleClient
from .step import Termination
from .task import Task, TaskOutcome, Tier

DEFAULT_MODEL = "claude-sonnet-5"

# Injectable client factory: (model) -> ModelClient. Default builds a real client from
# the environment; tests pass a factory returning a MockClient.
ClientFactory = Callable[[str], ModelClient]

# capability.client_kind -> concrete ModelClient class (M6). Dispatch never branches
# on model_id/vendor strings directly — it goes through this one declared mapping.
_CLIENT_CLASSES: dict[str, type[AnthropicClient | OpenAICompatibleClient]] = {
    "anthropic": AnthropicClient,
    "openai_compatible": OpenAICompatibleClient,
}


def build_real_client(model: str, env: dict[str, str] | None = None) -> ModelClient:
    """Assemble a real client from the environment (key never stored).

    Dispatches to AnthropicClient or OpenAICompatibleClient by
    `capability.client_kind` — never by branching on model_id/vendor name. Routing to
    the right provider is by the model's own registered group (model_registry.py),
    not by scanning whichever provider's env vars happen to be set.
    """
    resolved = resolve_model(model, load_registry(), env=env)
    client_class = _CLIENT_CLASSES[resolved.capability.client_kind]
    return client_class(
        capability=resolved.capability,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
    )


def render_outcome(outcome: TaskOutcome, console: Console) -> None:
    """Print a task outcome: status line, then each round's tool results."""
    status = outcome.status
    if status.completed:
        console.print("[bold green]completed[/bold green]")
    elif status.reason == Termination.ANSWERED_IN_PROSE:
        # Solved, but the model answered in prose rather than executing code, so the
        # result is unverified — flag that distinction instead of a plain "completed".
        console.print(
            "[bold green]completed[/bold green] "
            "[dim](answered in prose, not executed)[/dim]"
        )
    else:
        console.print(f"[bold yellow]stopped[/bold yellow]: {status.reason}")
        if status.detail:
            console.print(status.detail)
    for i, rnd in enumerate(outcome.rounds, 1):
        for out in rnd.outcomes:
            marker = "[green]ok[/green]" if out.success else "[red]FAILED[/red]"
            console.print(f"  round {i} [{out.tool} {out.block_name}] {marker}")
            if out.exec_result and out.exec_result.stdout.strip():
                console.print(f"    {out.exec_result.stdout.strip()}")
            if not out.success and out.detail:
                console.print(f"    {out.detail.splitlines()[-1]}")
        if not rnd.outcomes and rnd.body:
            # The model answered in plain text without calling Exec — still show it,
            # since it's the only place the actual answer lives.
            console.print(rnd.body)


def run_once(
    goal: str,
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
) -> TaskOutcome:
    """Run a single goal and render its outcome. Returns the outcome for testing."""
    console = console or Console()
    client = client_factory(model)
    outcome = Task(client, tier=tier).run(goal)
    render_outcome(outcome, console)
    return outcome


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    read_line: Callable[[str], str] = input,
) -> None:
    """Interactive loop: read a goal, run it, repeat. Blank line or EOF/quit exits.

    `read_line` is injectable so tests can drive the REPL without a real terminal.
    """
    console = console or Console()
    console.print("[bold]ForgeAgent[/bold] REPL — enter a goal, blank line or 'quit' to exit.")
    while True:
        try:
            goal = read_line("forge> ").strip()
        except EOFError:
            break
        if not goal or goal in {"quit", "exit"}:
            break
        run_once(goal, tier=tier, model=model, client_factory=client_factory, console=console)


# A tiny set of live goals for the smoke command — deterministic, self-contained,
# no file I/O so they run under restricted without an allowed-root fuss. "Pass" here
# means the task completed end-to-end against a real model (a liveness/integration
# check), NOT full golden-task judging (that is the M5 user-acceptance run).
SMOKE_GOALS = [
    "Compute the sum of the integers 10, 20 and 30 and print the result.",
    "Print the 6th Fibonacci number.",
]

# Models exercised by `smoke` by default; Fable and the OpenAI-compatible models are
# opt-in (Fable: cost + refusal risk; OpenAI-compatible: separate API keys the user may
# not have configured). Order matches docs/m6-openai-compatible-client.md's decision 4:
# gpt-5.4-mini first (verifies the client skeleton), then glm-5.2/deepseek-v4-flash
# (verify the thinking/reasoning_effort capability-gating translation).
SMOKE_MODELS = ("claude-sonnet-5", "claude-haiku-4-5")
FABLE_MODEL = "claude-fable-5"
OPENAI_COMPATIBLE_SMOKE_MODELS = ("gpt-5.4-mini", "glm-5.2", "deepseek-v4-flash")


def run_smoke(
    *,
    tier: Tier,
    models: list[str],
    client_factory: ClientFactory,
    console: Console | None = None,
) -> bool:
    """Run the smoke goals against each model; return True if all completed.

    Uses real models when client_factory builds real clients. Any ConfigError (missing
    key) propagates to main() for a clean message.
    """
    console = console or Console()
    all_ok = True
    for model in models:
        client = client_factory(model)
        console.print(f"[bold]smoke[/bold] model={model} tier={tier}")
        for goal in SMOKE_GOALS:
            outcome = Task(client, tier=tier).run(goal)
            ok = outcome.status.solved
            all_ok = all_ok and ok
            marker = "[green]PASS[/green]" if ok else f"[red]FAIL[/red] ({outcome.status.reason})"
            console.print(f"  {marker}  {goal}")
    console.print("[green]smoke: all passed[/green]" if all_ok else "[red]smoke: failures[/red]")
    return all_ok


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgeagent", description="Lightweight code-as-action agent."
    )
    parser.add_argument("--tier", choices=("trusted", "restricted"), default="restricted",
                        help="sandbox tier (default: restricted)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"model id (default: {DEFAULT_MODEL})")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run a single goal and exit")
    run_p.add_argument("goal", help="the task goal")
    smoke_p = sub.add_parser("smoke", help="run a live smoke check against real models")
    smoke_p.add_argument("--include-fable", action="store_true",
                        help="also run claude-fable-5 (opt-in: extra cost + refusal risk)")
    smoke_p.add_argument("--include-openai-compatible", action="store_true",
                        help="also run gpt-5.4-mini/glm-5.2/deepseek-v4-flash "
                             "(opt-in: separate API keys required)")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory = build_real_client,
) -> int:
    """CLI entry point. Returns a process exit code.

    No subcommand -> REPL. `run <goal>` -> single execution. A missing API key surfaces
    as a clear message and a non-zero exit, never a traceback.
    """
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        if args.command == "run":
            outcome = run_once(
                args.goal, tier=args.tier, model=args.model, client_factory=client_factory,
                console=console,
            )
            return 0 if outcome.status.solved else 1
        if args.command == "smoke":
            models = list(SMOKE_MODELS)
            if args.include_fable:
                models.append(FABLE_MODEL)
            if args.include_openai_compatible:
                models.extend(OPENAI_COMPATIBLE_SMOKE_MODELS)
            ok = run_smoke(
                tier=args.tier, models=models, client_factory=client_factory, console=console
            )
            return 0 if ok else 1
        repl(tier=args.tier, model=args.model, client_factory=client_factory, console=console)
        return 0
    except RegistryError as exc:
        console.print(f"[red]config error[/red]: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
