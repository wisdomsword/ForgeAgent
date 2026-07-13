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
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.text import Text

from .anthropic_client import AnthropicClient
from .client import ModelClient
from .executor import ContainerRuntimeError
from .image_input import load_images
from .mcp_manager import MCPManager, load_mcp_config
from .model_registry import (
    RegistryError,
    get_capability,
    list_models,
    load_registry,
    reload_registry,
    resolve_model,
)
from .models import ImageItem, StreamEventKind, TokenUsage
from .openai_compatible_client import OpenAICompatibleClient
from .protocol import FileWriteArgs, MCPArgs, SurveyArgs, WebFetchArgs
from .secret_policy import is_secret_name, mask_secrets, sensitive_env_values
from .step import RoundResult, Termination
from .task import Task, TaskOutcome
from .tools import Asker, Confirmer, Tier
from .web_search import ERROR_BLOCKED, ERROR_UNAVAILABLE, search_with_status

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


def _make_stream_callback(console: Console) -> tuple[Live, Callable[[str, StreamEventKind], None]]:
    """A rich.live.Live + callback pair for `--stream` display (design doc §3.3):
    THINKING_DELTA renders dim, TEXT_DELTA plain. auto_refresh is off — the callback
    refreshes synchronously on every delta so the display is deterministic (no
    reliance on Live's background timer thread) rather than for any performance
    reason."""
    text = Text()
    live = Live(text, console=console, auto_refresh=False)

    def _on_delta(delta: str, kind: StreamEventKind) -> None:
        text.append(delta, style="dim" if kind is StreamEventKind.THINKING_DELTA else None)
        live.refresh()

    return live, _on_delta


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
        total.reasoning_tokens += rnd.usage.reasoning_tokens


def _print_usage(total: TokenUsage, console: Console) -> None:
    console.print(
        f"[dim]usage: in={total.input_tokens} out={total.output_tokens} "
        f"cached={total.cached_tokens} reasoning={total.reasoning_tokens} "
        f"(session total)[/dim]"
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


def _redact_confirmation_value(value):
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if is_secret_name(str(key))
            else _redact_confirmation_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_confirmation_value(item) for item in value]
    if isinstance(value, str):
        return mask_secrets(value, sensitive_env_values())
    return value


def _redact_confirmation_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return "<redacted malformed URL>"
        hostname = parts.hostname or ""
        port = parts.port
    except ValueError:
        return "<redacted malformed URL>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname if port is None else f"{hostname}:{port}"
    if parts.username is not None or parts.password is not None:
        netloc = f"<redacted>@{netloc}"
    secret_values = sensitive_env_values()
    query = urlencode(
        [
            (
                key,
                "REDACTED" if is_secret_name(key)
                else mask_secrets(value, secret_values),
            )
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    path = mask_secrets(parts.path, secret_values)
    fragment = "REDACTED" if parts.fragment else ""
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


def _confirmation_filewrite_path(path: str) -> str:
    normalized = Path(os.path.normpath(path))
    if not normalized.is_absolute():
        return normalized.as_posix()
    try:
        relative = normalized.relative_to(Path.cwd())
    except ValueError:
        return f".../{normalized.name or '.'}"
    return relative.as_posix()


def _confirmation_summary(args: BaseModel) -> str:
    if isinstance(args, MCPArgs):
        arguments = json.dumps(_redact_confirmation_value(args.arguments), sort_keys=True)
        return f"MCP {args.server}:{args.tool} {arguments}"
    if isinstance(args, WebFetchArgs):
        return f"WebFetch {_redact_confirmation_url(args.url)}"
    if isinstance(args, FileWriteArgs):
        safe_path = _confirmation_filewrite_path(args.path)
        return f"FileWrite {safe_path} ({len(args.content)} bytes)"
    return type(args).__name__


def make_console_confirmer(
    console: Console, read_line: Callable[[str], str] = input
) -> Confirmer:
    """Console-based `Confirmer` for side-effecting calls with minimal disclosure."""

    def _confirm(args: BaseModel) -> bool:
        console.print(f"[bold yellow]approve[/bold yellow] {_confirmation_summary(args)}")
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
    images: list[ImageItem] | None = None,
    stream: bool = False,
) -> TaskOutcome:
    """Run a single goal and render its outcome. Returns the outcome for testing.

    `asker` handles Survey mid-task questions. Default (None) is headless — a Survey call
    ends the task with NEEDS_INFO. REPL wires a console asker; `run` leaves it None.
    `mcp`/`confirmer` wire the MCP tool + its confirmation gate when servers are configured.
    `usage_total` is the session-scoped token accumulator (docs/m10 §3.2): the REPL passes
    the same instance across tasks so it keeps growing; a bare `run_once` call with no
    accumulator gets a fresh one, since the task itself is the whole session then.
    `images` (M9 Phase 4) attaches image content to the goal via `run --image`/`/image`.
    `stream` (M9 Phase 3) renders each round's text live as it arrives; auto-degrades to
    non-streaming when `console` is not attached to a real terminal (piped/CI, design
    doc §3.3), since a Live display has nothing meaningful to render there.
    """
    console = console or Console()
    usage_total = usage_total if usage_total is not None else TokenUsage()
    client = client_factory(model)
    live: Live | None = None
    on_stream_text = None
    if stream and console.is_terminal:
        live, on_stream_text = _make_stream_callback(console)
    task = Task(
        client, tier=tier, asker=asker, mcp=mcp, confirmer=confirmer,
        container_image=container_image, on_stream_text=on_stream_text,
    )
    try:
        if live is not None:
            with live:
                outcome = task.run(goal, images=images)
        else:
            outcome = task.run(goal, images=images)
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


def _print_mcp_tools(mcp: MCPManager, console: Console) -> None:
    """Tool listing for the `/mcp` slash command, on top of plain `mcp status`
    (design doc §3.5) — same data `tools_prompt()` injects into the system prompt."""
    tools = mcp.list_tools()
    if not tools:
        return
    console.print("[bold]tools[/bold]:")
    for tool in tools:
        desc = tool.description.strip().replace("\n", " ")
        console.print(f"  {tool.server}:{tool.name}" + (f" — {desc}" if desc else ""))


def _handle_mcp_slash(goal: str, mcp: MCPManager | None, console: Console) -> None:
    """`/mcp [status|enable <s>|disable <s>]` — equivalent to `mcp status` plus a tool
    listing (design doc §3.5); `/mcp enable|disable <s>` behaves exactly like the
    compat command, so it goes straight through `_handle_mcp_command`."""
    _handle_mcp_command("mcp" + goal[len("/mcp") :], mcp, console)
    parts = goal.split()
    action = parts[1] if len(parts) > 1 else "status"
    if mcp is not None and action == "status":
        _print_mcp_tools(mcp, console)


def _handle_model_command(goal: str, model: str, console: Console) -> str:
    """`/model` lists registered models (reuses `print_models`); `/model <id-or-alias>`
    switches the current REPL session's model. Returns the model to use for subsequent
    goals — unchanged if no argument was given or the requested id is unknown (an
    unknown id reports an error and never switches, design doc §3.5)."""
    parts = goal.split(maxsplit=1)
    if len(parts) == 1:
        print_models(console)
        return model
    requested = parts[1].strip()
    try:
        get_capability(requested)
    except RegistryError as exc:
        console.print(f"[red]unknown model[/red]: {exc}")
        return model
    console.print(f"[green]switched[/green] to {requested}")
    return requested


def _handle_search_command(goal: str, console: Console) -> None:
    """`/search <query>` — web search (M9 Phase 4, design doc §3.5). Results are only
    printed, never injected into the conversation — the user copies whatever they want
    into their next goal. Best-effort: engine HTML is not a contract interface, and
    failures (SSRF block / non-200 / parse failure) never surface a raw traceback."""
    parts = goal.split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        console.print("[dim]usage: /search <query>[/dim]")
        return
    results, error = search_with_status(query)
    if error == ERROR_BLOCKED:
        console.print("[red]search request was blocked by the security policy[/red]")
        return
    if error == ERROR_UNAVAILABLE:
        console.print("[red]search is temporarily unavailable[/red]")
        return
    if not results:
        console.print("[dim]no results[/dim]")
        return
    for i, result in enumerate(results, 1):
        console.print(f"  {i}. [cyan]{result.title}[/cyan]  {result.url}")
        if result.snippet:
            console.print(f"     {result.snippet}")


def _handle_image_command(
    goal: str, console: Console
) -> tuple[list[ImageItem] | None, str | None]:
    """`/image <path> [goal...]` — load image(s) from a file or directory (design doc
    §3.4/§3.5, shared logic with `image_input.load_images`). With a goal, returns
    (images, goal) so the caller runs it immediately with the images attached; with
    just a path, returns (images, None) so the caller stages them for the next goal
    typed at the prompt. Returns (None, None) on a bad path/usage — nothing to stage."""
    parts = goal.split(maxsplit=2)
    if len(parts) < 2:
        # markup=False: the literal "[goal...]" would otherwise be parsed as a
        # (invalid, silently-dropped) markup tag.
        console.print("usage: /image <path> [goal...]", style="dim", markup=False)
        return None, None
    path, inline_goal = parts[1], parts[2] if len(parts) > 2 else None
    try:
        images = load_images(path)
    except ValueError as exc:
        console.print(f"[red]could not load image(s)[/red]: {exc}")
        return None, None
    console.print(f"[green]loaded[/green] {len(images)} image(s) from {path}")
    return images, inline_goal


# Usage lines for every `/`-prefixed command — the single source `/help` and the bare
# `/` auto-menu (design doc §3.5) both render from, so the two never drift apart.
_SLASH_COMMAND_USAGE: dict[str, str] = {
    "/model": "/model [id-or-alias] — list models, or switch this session's model",
    "/search": "/search <query> — web search; results are printed only, never sent to the model",
    "/image": "/image <path> [goal...] — attach image(s) (file or directory) to a goal",
    "/mcp": "/mcp [status|enable <s>|disable <s>] — MCP server status, tools, and toggles",
    "/reload": "/reload — reload ~/.forgeagent/{models,config}.yaml",
    "/help": "/help [command] — list commands, or show one command's detailed usage",
}


def _print_command_menu(console: Console) -> None:
    # markup=False: usage strings contain literal "[...]" (e.g. "[goal...]") which
    # Rich would otherwise parse as (invalid, silently-dropped) markup tags.
    console.print("[bold]commands[/bold]:")
    for usage in _SLASH_COMMAND_USAGE.values():
        console.print(f"  {usage}", markup=False)


def _handle_help_command(goal: str, console: Console) -> None:
    """`/help` prints every command's usage line; `/help <command>` prints just one."""
    parts = goal.split(maxsplit=1)
    if len(parts) == 1:
        _print_command_menu(console)
        return
    name = parts[1].strip()
    if not name.startswith("/"):
        name = f"/{name}"
    usage = _SLASH_COMMAND_USAGE.get(name)
    if usage:
        console.print(usage, markup=False)
    else:
        console.print(f"[red]unknown command[/red] {name!r}")


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    read_line: Callable[[str], str] = input,
    container_image: str | None = None,
    stream: bool = False,
) -> None:
    """Interactive loop: read a goal, run it, repeat. Blank line or EOF/quit exits.

    `read_line` is injectable so tests can drive the REPL without a real terminal.
    `stream` (M9 Phase 3) renders each goal's response live as it arrives.
    """
    console = console or Console()
    console.print("[bold]ForgeAgent[/bold] REPL — enter a goal, blank line or 'quit' to exit.")
    console.print("[dim]type '/' and enter for the command menu, or '/help'[/dim]")
    # REPL is interactive, so Survey questions and MCP confirmations use the same read_line.
    asker = make_console_asker(console, read_line)
    confirmer = make_console_confirmer(console, read_line)
    mcp = build_mcp_manager(console)
    # One accumulator for the whole REPL session — usage keeps growing across tasks,
    # not reset per goal (docs/m10 §3.2).
    usage_total = TokenUsage()
    # Images staged by a path-only `/image` call, attached to the next goal the user
    # types at the prompt (design doc §3.5).
    staged_images: list[ImageItem] | None = None
    try:
        while True:
            try:
                goal = read_line("forge> ").strip()
            except EOFError:
                break
            if not goal or goal in {"quit", "exit"}:
                break
            # Compat period (design doc §3.5): old bare words keep working this
            # milestone, mapped onto the same handlers, with a deprecation notice.
            # "models" maps to the singular "/model" command (list-models behavior);
            # "reload"/"mcp ..." map onto their same-named slash command unchanged.
            if goal in {"models", "reload", "mcp"} or goal.startswith("mcp "):
                old_word = goal.split()[0]
                new_prefix = "/model" if old_word == "models" else f"/{old_word}"
                console.print(
                    f"[dim]'{old_word}' is deprecated, use "
                    f"'{new_prefix}' instead — removed next milestone[/dim]"
                )
                goal = new_prefix + goal[len(old_word) :]
            if goal == "/":
                _print_command_menu(console)
                continue
            if goal == "/model" or goal.startswith("/model "):
                model = _handle_model_command(goal, model, console)
                continue
            if goal == "/search" or goal.startswith("/search "):
                _handle_search_command(goal, console)
                continue
            if goal == "/image" or goal.startswith("/image "):
                images, inline_goal = _handle_image_command(goal, console)
                if images is None:
                    continue
                if inline_goal is None:
                    staged_images = images
                    continue
                goal = inline_goal
                staged_images = None
                run_once(
                    goal, tier=tier, model=model, client_factory=client_factory,
                    console=console, asker=asker, mcp=mcp,
                    confirmer=confirmer,
                    container_image=container_image,
                    usage_total=usage_total,
                    images=images,
                    stream=stream,
                )
                continue
            if goal == "/mcp" or goal.startswith("/mcp "):
                _handle_mcp_slash(goal, mcp, console)
                continue
            if goal == "/reload":
                # Re-read ~/.forgeagent/{models,config}.yaml now, so a broken edit is
                # caught here rather than on the next `run`. Each run already reloads
                # from disk, so this is a validate-and-report, not a cache refresh.
                try:
                    reloaded = reload_registry()
                    console.print(f"[green]reloaded[/green]: {len(reloaded.models)} models")
                except RegistryError as exc:
                    console.print(f"[red]reload failed[/red]: {exc}")
                continue
            if goal == "/help" or goal.startswith("/help "):
                _handle_help_command(goal, console)
                continue
            if goal.startswith("/"):
                console.print(f"[red]unknown command[/red] {goal!r}")
                _print_command_menu(console)
                continue
            run_once(
                goal, tier=tier, model=model, client_factory=client_factory,
                console=console, asker=asker, mcp=mcp,
                confirmer=confirmer,
                container_image=container_image,
                usage_total=usage_total,
                images=staged_images,
                stream=stream,
            )
            staged_images = None
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
    parser.add_argument("--stream", action="store_true",
                        help="render responses live as they arrive "
                             "(auto-disabled when not attached to a terminal)")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run a single goal and exit")
    run_p.add_argument("goal", help="the task goal")
    run_p.add_argument("--interactive", action="store_true",
                       help="allow mid-task Survey questions (prompts on the terminal)")
    run_p.add_argument("--image", default=None, metavar="PATH",
                       help="attach image(s) at PATH (a file, or a directory of images)")
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
            images = None
            if args.image:
                try:
                    images = load_images(args.image)
                except ValueError as exc:
                    console.print(f"[red]could not load image(s)[/red]: {exc}")
                    return 2
            mcp = build_mcp_manager(console)
            try:
                confirmer = (
                    make_console_confirmer(console)
                    if console.is_terminal and sys.stdin.isatty()
                    else None
                )
                outcome = run_once(
                    args.goal, tier=args.tier, model=args.model, client_factory=client_factory,
                    console=console,
                    asker=make_console_asker(console) if args.interactive else None,
                    mcp=mcp,
                    confirmer=confirmer,
                    container_image=args.container_image,
                    images=images,
                    stream=args.stream,
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
             container_image=args.container_image, stream=args.stream)
        return 0
    except RegistryError as exc:
        console.print(f"[red]config error[/red]: {exc}")
        return 2
    except ContainerRuntimeError as exc:
        console.print(f"[red]container error[/red]: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
