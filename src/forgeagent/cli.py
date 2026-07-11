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
from .executor import ContainerRuntimeError
from .mcp_manager import MCPManager, load_mcp_config
from .model_registry import (
    RegistryError,
    list_models,
    load_registry,
    reload_registry,
    resolve_model,
)
from .models import TokenUsage
from .openai_compatible_client import OpenAICompatibleClient
from .protocol import MCPArgs, SurveyArgs
from .step import RoundResult, Termination
from .task import Task, TaskOutcome
from .tools import Asker, Confirmer, Tier

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


def _accumulate_usage(total: TokenUsage, rounds: list[RoundResult]) -> None:
    """Fold each round's usage into `total` in place (session-scoped accumulator,
    docs/m10-usage-observability-and-tools.md §3.2). Rounds with no usage (e.g.
    ClientError rounds) are skipped."""
    for rnd in rounds:
        if rnd.usage is None:
            continue
        total.input_tokens += rnd.usage.input_tokens
        total.output_tokens += rnd.usage.output_tokens
        total.cached_tokens += rnd.usage.cached_tokens


def _print_usage(total: TokenUsage, console: Console) -> None:
    console.print(
        f"[dim]usage: in={total.input_tokens} out={total.output_tokens} "
        f"cached={total.cached_tokens} (session total)[/dim]"
    )


def make_console_asker(
    console: Console, read_line: Callable[[str], str] = input
) -> Asker:
    """Console-based `Asker` for the Survey tool: print the question (+ options if any)
    and return the user's typed answer. Empty input / EOF returns None so Survey ends
    the task with NEEDS_INFO cleanly (per docs/m7-tools-mcp-survey.md §3.5)."""

    def _ask(args: SurveyArgs) -> str | None:
        console.print(f"[bold cyan]?[/bold cyan] {args.question}")
        if args.options:
            for i, opt in enumerate(args.options, 1):
                console.print(f"  {i}. {opt}")
        try:
            answer = read_line("answer> ").strip()
        except EOFError:
            return None
        return answer or None

    return _ask


def make_console_confirmer(
    console: Console, read_line: Callable[[str], str] = input
) -> Confirmer:
    """Console-based `Confirmer` for side-effecting MCP calls: show the pending call and
    require an explicit y/n. Anything but 'y'/'yes' (incl. EOF) denies — a side-effecting
    call outside a server's autoApprove list never runs without a clear yes (T8a)."""

    def _confirm(args: MCPArgs) -> bool:
        console.print(
            f"[bold yellow]MCP call[/bold yellow] {args.server}:{args.tool} "
            f"[dim]{args.arguments}[/dim]"
        )
        try:
            answer = read_line("approve? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return _confirm


def run_once(
    goal: str,
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    asker: Asker | None = None,
    mcp: MCPManager | None = None,
    confirmer: Confirmer | None = None,
    container_image: str | None = None,
    usage_total: TokenUsage | None = None,
) -> TaskOutcome:
    """Run a single goal and render its outcome. Returns the outcome for testing.

    `asker` handles Survey mid-task questions. Default (None) is headless — a Survey call
    ends the task with NEEDS_INFO. REPL wires a console asker; `run` leaves it None.
    `mcp`/`confirmer` wire the MCP tool + its confirmation gate when servers are configured.
    `usage_total` is the session-scoped token accumulator (docs/m10 §3.2): the REPL passes
    the same instance across tasks so it keeps growing; a bare `run_once` call with no
    accumulator gets a fresh one, since the task itself is the whole session then.
    """
    console = console or Console()
    usage_total = usage_total if usage_total is not None else TokenUsage()
    client = client_factory(model)
    task = Task(
        client, tier=tier, asker=asker, mcp=mcp, confirmer=confirmer,
        container_image=container_image,
    )
    try:
        outcome = task.run(goal)
    finally:
        task.close()
    render_outcome(outcome, console)
    _accumulate_usage(usage_total, outcome.rounds)
    _print_usage(usage_total, console)
    return outcome


def _handle_mcp_command(goal: str, mcp: MCPManager | None, console: Console) -> None:
    """Handle the REPL `mcp status` / `mcp enable <server>` / `mcp disable <server>`
    commands. No-op with a note when no MCP servers are configured."""
    if mcp is None:
        console.print("[dim]no MCP servers configured[/dim]")
        return
    parts = goal.split()
    action = parts[1] if len(parts) > 1 else "status"
    if action == "status":
        for name, status in mcp.server_status().items():
            console.print(f"  {name}: {status}")
    elif action in {"enable", "disable"} and len(parts) > 2:
        server = parts[2]
        ok = mcp.enable(server) if action == "enable" else mcp.disable(server)
        if ok:
            console.print(f"[green]{action}d[/green] {server}: {mcp.server_status()[server]}")
        else:
            console.print(f"[red]unknown server[/red] {server!r}")
    else:
        console.print("[dim]usage: mcp status | mcp enable <server> | mcp disable <server>[/dim]")


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    read_line: Callable[[str], str] = input,
    container_image: str | None = None,
) -> None:
    """Interactive loop: read a goal, run it, repeat. Blank line or EOF/quit exits.

    `read_line` is injectable so tests can drive the REPL without a real terminal.
    """
    console = console or Console()
    console.print("[bold]ForgeAgent[/bold] REPL — enter a goal, blank line or 'quit' to exit.")
    console.print(
        "[dim]commands: 'models', 'reload', 'mcp status|enable <s>|disable <s>', 'quit'[/dim]"
    )
    # REPL is interactive, so Survey questions and MCP confirmations use the same read_line.
    asker = make_console_asker(console, read_line)
    confirmer = make_console_confirmer(console, read_line)
    mcp = build_mcp_manager(console)
    # One accumulator for the whole REPL session — usage keeps growing across tasks,
    # not reset per goal (docs/m10 §3.2).
    usage_total = TokenUsage()
    try:
        while True:
            try:
                goal = read_line("forge> ").strip()
            except EOFError:
                break
            if not goal or goal in {"quit", "exit"}:
                break
            if goal == "models":
                print_models(console)
                continue
            if goal == "reload":
                # Re-read ~/.forgeagent/{models,config}.yaml now, so a broken edit is
                # caught here rather than on the next `run`. Each run already reloads
                # from disk, so this is a validate-and-report, not a cache refresh.
                try:
                    reloaded = reload_registry()
                    console.print(f"[green]reloaded[/green]: {len(reloaded.models)} models")
                except RegistryError as exc:
                    console.print(f"[red]reload failed[/red]: {exc}")
                continue
            if goal.startswith("mcp"):
                _handle_mcp_command(goal, mcp, console)
                continue
            run_once(
                goal, tier=tier, model=model, client_factory=client_factory,
                console=console, asker=asker, mcp=mcp,
                confirmer=confirmer if mcp is not None else None,
                container_image=container_image,
                usage_total=usage_total,
            )
    finally:
        if mcp is not None:
            mcp.close()


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


def build_mcp_manager(console: Console) -> MCPManager | None:
    """Load mcp.yaml and, if any servers are enabled, build + connect a manager.

    Returns None when no servers are configured (the common case) so the MCP tool stays
    off the menu. Connection failures for individual servers are isolated inside the
    manager (reported via server_status), never raised here.
    """
    servers = load_mcp_config()
    manager = MCPManager(servers)
    if not manager.has_enabled_servers:
        return None
    manager.connect()
    for name, status in manager.server_status().items():
        colour = "green" if status == "available" else "yellow"
        console.print(f"[{colour}]MCP[/{colour}] {name}: {status}")
    return manager


def print_models(console: Console) -> None:
    """Print the registered models with their aliases and key capabilities."""
    console.print("[bold]Available models[/bold] (canonical — aliases):")
    for info in list_models():
        aliases = ", ".join(info.aliases) if info.aliases else "—"
        console.print(
            f"  [cyan]{info.model_id}[/cyan] — {aliases}  "
            f"[dim]({info.client_kind}, ctx {info.context_window})[/dim]"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgeagent", description="Lightweight code-as-action agent."
    )
    parser.add_argument("--tier", choices=("trusted", "restricted", "container"),
                        default="restricted",
                        help="sandbox tier (default: restricted; container requires docker)")
    parser.add_argument("--container-image", default=None, metavar="IMAGE",
                        help="container tier image (default: python:3.11-slim)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"model id (default: {DEFAULT_MODEL})")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run a single goal and exit")
    run_p.add_argument("goal", help="the task goal")
    run_p.add_argument("--interactive", action="store_true",
                       help="allow mid-task Survey questions (prompts on the terminal)")
    sub.add_parser("models", help="list available models and their aliases")
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
        if args.command == "models":
            print_models(console)
            return 0
        if args.command == "run":
            mcp = build_mcp_manager(console)
            try:
                outcome = run_once(
                    args.goal, tier=args.tier, model=args.model, client_factory=client_factory,
                    console=console,
                    asker=make_console_asker(console) if args.interactive else None,
                    mcp=mcp,
                    confirmer=make_console_confirmer(console) if mcp is not None else None,
                    container_image=args.container_image,
                )
            finally:
                if mcp is not None:
                    mcp.close()
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
        repl(tier=args.tier, model=args.model, client_factory=client_factory, console=console,
             container_image=args.container_image)
        return 0
    except RegistryError as exc:
        console.print(f"[red]config error[/red]: {exc}")
        return 2
    except ContainerRuntimeError as exc:
        console.print(f"[red]container error[/red]: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
