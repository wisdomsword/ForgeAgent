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

import ipaddress
import json
import logging
import math
import os
import re
import signal
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import cast
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import yaml
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.text import Text

from . import _cli_collaboration, _cli_parser, _cli_repl, http_server
from .anthropic_client import AnthropicClient
from .audit import AuditSink, JsonlAuditSink
from .client import ModelClient
from .collaboration import (
    CollaborationMode,
    CollaborationReport,
    CollaborationRole,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    CollaborationStore,
    ModeDecision,
    emit_collaboration_route,
    headless_plan_confirmer,
    normalize_required_candidate_files,
    resolve_collaboration_mode,
)
from .context import ContextConfig, SlidingWindowContextPolicy, load_context_config
from .executor import ContainerRuntimeError
from .external_actions import ExternalActionReceiptStore, ReceiptError
from .headless import HeadlessConfirmer
from .http_config import HttpServiceConfig
from .http_task_service import TaskRecord, TaskService
from .identity import (
    ApprovedIdentity,
    IdentityConfigError,
    IdentityConfirmer,
    IdentityDiagnostic,
    IdentityTrustRequest,
    compose_system_prompt,
    load_identity,
    resolve_project_trust,
)
from .image_input import load_images
from .loop import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_WALL_CLOCK_SECONDS,
    LoopBudgets,
    LoopCheckpointError,
    LoopReport,
    LoopRunner,
)
from .mcp_manager import MCPManager, MCPServerDiagnostic, load_mcp_config
from .memory import MemoryManager
from .model_registry import (
    Registry,
    RegistryError,
    get_capability,
    list_models,
    load_registry,
    reload_registry,
    resolve_model,
)
from .models import ImageItem, StreamEventKind, TokenUsage
from .openai_compatible_client import OpenAICompatibleClient
from .protocol import FileWriteArgs, MCPArgs, MemoryCandidate, SurveyArgs, WebFetchArgs
from .secret_policy import REDACTED, is_secret_name, mask_secrets, sensitive_env_values
from .skills import SkillRegistry
from .step import RoundResult, Termination
from .task import Task, TaskOutcome
from .tools import Asker, Confirmer, Tier
from .web_search import ERROR_BLOCKED, ERROR_UNAVAILABLE, search_with_status

DEFAULT_MODEL = _cli_parser.DEFAULT_MODEL
append_trend = _cli_parser.append_trend
build_parser = _cli_parser.build_parser
_evaluation_record = _cli_parser.evaluation_record
_load_strict_json = _cli_parser.load_strict_json
_metric_text = _cli_parser.metric_text
_render_evaluation = _cli_parser.render_evaluation
_run_evaluate_command_impl = _cli_parser.run_evaluate_command
run_evaluator = _cli_parser.run_evaluator
validate_artifact_manifest = _cli_parser.validate_artifact_manifest
_console_plan_confirmer = _cli_collaboration.console_plan_confirmer
_confirmed_collaboration_mode = _cli_collaboration.confirmed_collaboration_mode
_render_collaboration_report = _cli_collaboration.render_collaboration_report

_CONTEXT_CONFIG_ENVIRONMENT = "FORGEAGENT_INTERNAL_CONTEXT_CONFIG_JSON"
_CANDIDATE_FILES_ENVIRONMENT = "FORGEAGENT_INTERNAL_CANDIDATE_REQUIRED_FILES_JSON"

logger = logging.getLogger(__name__)


class MCPStartupError(RuntimeError):
    """MCP manager startup failed or an enabled required service was unavailable."""

    _CODES = frozenset({"startup_failed", "required_server_unavailable"})

    def __init__(self, code: str) -> None:
        super().__init__(code if code in self._CODES else "startup_failed")


class HttpStartupError(RuntimeError):
    """The opt-in HTTP service could not be configured, bound, or started."""


@dataclass(frozen=True)
class _HttpRuntimeSettings:
    service: HttpServiceConfig
    model: str
    tier: Tier
    allowed_root: str
    no_identity: bool
    no_memory: bool
    container_image: str | None
    shutdown_timeout_seconds: float


_HTTP_RUNTIME_KEYS = frozenset(
    {
        "model",
        "tier",
        "allowed_root",
        "no_identity",
        "no_memory",
        "container_image",
        "shutdown_timeout_seconds",
    }
)
_HTTP_CONFIG_KEYS = frozenset(
    {
        *(field.name for field in fields(HttpServiceConfig) if field.name != "context_config"),
        "context",
    }
)
_SERVE_FORBIDDEN_CLI_OPTIONS = (
    "--tier",
    "--container-image",
    "--model",
    "--stream",
    "--no-identity",
    "--no-memory",
)


# Injectable client factory: (model) -> ModelClient. Default builds a real client from
# the environment; tests pass a factory returning a MockClient.
ClientFactory = Callable[[str], ModelClient]

# capability.client_kind -> concrete ModelClient class (M6). Dispatch never branches
# on model_id/vendor strings directly — it goes through this one declared mapping.
_CLIENT_CLASSES: dict[str, type[AnthropicClient | OpenAICompatibleClient]] = {
    "anthropic": AnthropicClient,
    "openai_compatible": OpenAICompatibleClient,
}


def build_real_client(
    model: str,
    env: dict[str, str] | None = None,
    *,
    registry: Registry | None = None,
) -> ModelClient:
    """Assemble a real client from the environment (key never stored).

    Dispatches to AnthropicClient or OpenAICompatibleClient by
    `capability.client_kind` — never by branching on model_id/vendor name. Routing to
    the right provider is by the model's own registered group (model_registry.py),
    not by scanning whichever provider's env vars happen to be set.
    """
    resolved = resolve_model(model, registry if registry is not None else load_registry(), env=env)
    client_class = _CLIENT_CLASSES[resolved.capability.client_kind]
    return client_class(
        capability=resolved.capability,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
    )


def _client_factory_for_registry(
    registry: Registry | None, fallback: ClientFactory
) -> ClientFactory:
    if registry is None:
        return fallback

    def build_from_snapshot(model: str) -> ModelClient:
        return build_real_client(model, registry=registry)

    return build_from_snapshot


def _validate_context_policy(model: str, registry: Registry, context_config: ContextConfig) -> None:
    """Resolve the selected model and its context limits before publishing a snapshot."""
    SlidingWindowContextPolicy(get_capability(model, registry), None, context_config)


def _validate_client_context_policy(client: ModelClient, context_config: ContextConfig) -> None:
    """Validate an injected client's actual capability before constructing its Task."""
    SlidingWindowContextPolicy(client.capability, None, context_config)


def _http_client_factory_with_validated_context(
    model: str,
    client_factory: ClientFactory,
    context_config: ContextConfig,
) -> ClientFactory:
    """Validate HTTP context limits against the exact capability source used by tasks."""
    if client_factory is build_real_client:
        registry = load_registry()
        _validate_context_policy(model, registry, context_config)
        return _client_factory_for_registry(registry, client_factory)

    probe = client_factory(model)
    try:
        _validate_client_context_policy(probe, context_config)
    finally:
        close = getattr(probe, "close", None)
        if callable(close):
            close()
    return client_factory


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
            "[bold green]completed[/bold green] [dim](answered in prose, not executed)[/dim]"
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
    for result in outcome.memory_results:
        colour = "green" if result.status in {"accepted", "replaced"} else "yellow"
        detail = f" ({result.reason})" if result.reason else ""
        console.print(
            f"[{colour}]memory {result.status}[/{colour}]: {result.scope}/{result.key}{detail}"
        )


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
        total.accumulate_cache_rate(rnd.usage)


def _print_usage(total: TokenUsage, console: Console) -> None:
    cache_hit = total.cache_hit_rate
    cache_hit_display = "n/a" if cache_hit is None else f"{cache_hit * 100:.1f}%"
    console.print(
        f"[dim]usage: in={total.input_tokens} out={total.output_tokens} "
        f"cached={total.cached_tokens} reasoning={total.reasoning_tokens} "
        f"(session total) cache_hit={cache_hit_display}[/dim]"
    )


def make_console_asker(console: Console, read_line: Callable[[str], str] = input) -> Asker:
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


def _redact_confirmation_value(value, secret_values: set[str]):
    if isinstance(value, dict):
        displayed = {}
        used_labels: set[str] = set()
        for key, item in value.items():
            base_label = mask_secrets(str(key), secret_values)
            label = base_label
            suffix = 2
            while label in used_labels:
                label = f"{base_label} {suffix}"
                suffix += 1
            used_labels.add(label)
            displayed[label] = (
                "<redacted>"
                if is_secret_name(str(key))
                else _redact_confirmation_value(item, secret_values)
            )
        return displayed
    if isinstance(value, list):
        return [_redact_confirmation_value(item, secret_values) for item in value]
    if isinstance(value, str):
        return mask_secrets(value, secret_values)
    return value


def _mask_confirmation_hostname(hostname: str, secret_values: set[str]) -> str:
    candidates = sorted(
        (value for value in secret_values if value),
        key=lambda value: (-len(value), value.casefold(), value),
    )
    if not candidates:
        return hostname
    pattern = re.compile(
        "|".join(re.escape(value) for value in candidates),
        flags=re.IGNORECASE | re.ASCII,
    )
    return pattern.sub(REDACTED, hostname)


def _redact_confirmation_url(url: str, secret_values: set[str]) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return "<redacted malformed URL>"
        port = parts.port
    except ValueError:
        return "<redacted malformed URL>"
    raw_authority = parts.netloc.rsplit("@", 1)[-1]
    decoded_hostname = unquote(parts.hostname or "", errors="replace")
    if raw_authority.startswith("["):
        try:
            ipaddress.IPv6Address(decoded_hostname)
        except ValueError:
            return "<redacted malformed URL>"
        masked_hostname = _mask_confirmation_hostname(decoded_hostname, secret_values)
        hostname = f"[{quote(masked_hostname, safe=':')}]"
    else:
        if any(delimiter in decoded_hostname for delimiter in "@/:?#"):
            return "<redacted malformed URL>"
        hostname = quote(_mask_confirmation_hostname(decoded_hostname, secret_values), safe="")
    netloc = hostname if port is None else f"{hostname}:{port}"
    query = urlencode(
        [
            (
                mask_secrets(key, secret_values),
                "REDACTED" if is_secret_name(key) else mask_secrets(value, secret_values),
            )
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    path = quote(
        mask_secrets(unquote(parts.path, errors="replace"), secret_values),
        safe="/",
    )
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def _confirmation_filewrite_path(path: str, secret_values: set[str]) -> str:
    normalized = Path(os.path.normpath(path))
    if not normalized.is_absolute():
        return mask_secrets(normalized.as_posix(), secret_values)
    try:
        relative = normalized.relative_to(Path.cwd())
    except ValueError:
        return mask_secrets(f".../{normalized.name or '.'}", secret_values)
    return mask_secrets(relative.as_posix(), secret_values)


def _confirmation_summary(args: BaseModel) -> str:
    secret_values = sensitive_env_values()
    if isinstance(args, MCPArgs):
        arguments = json.dumps(
            _redact_confirmation_value(args.arguments, secret_values), sort_keys=True
        )
        return (
            f"MCP {mask_secrets(args.server, secret_values)}:"
            f"{mask_secrets(args.tool, secret_values)} {arguments}"
        )
    if isinstance(args, WebFetchArgs):
        try:
            safe_url = _redact_confirmation_url(args.url, secret_values)
        except (UnicodeError, ValueError):
            safe_url = "<redacted malformed URL>"
        return f"WebFetch {safe_url}"
    if isinstance(args, FileWriteArgs):
        safe_path = _confirmation_filewrite_path(args.path, secret_values)
        return f"FileWrite {safe_path} ({len(args.content)} characters)"
    return type(args).__name__


def _confirmation_single_line(value: str) -> str:
    """Escape control and formatting characters in confirmation-only output."""
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if (
            codepoint < 32
            or 127 <= codepoint <= 159
            or character in {"\u2028", "\u2029"}
            or unicodedata.category(character) in {"Cf", "Cs"}
        ):
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def make_console_confirmer(console: Console, read_line: Callable[[str], str] = input) -> Confirmer:
    """Console-based `Confirmer` for side-effecting calls with minimal disclosure."""

    def _confirm(args: BaseModel) -> bool:
        prompt = Text("approve", style="bold yellow")
        prompt.append(" ")
        prompt.append(_confirmation_single_line(_confirmation_summary(args)))
        console.print(prompt)
        try:
            answer = read_line("approve? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return _confirm


def make_console_identity_confirmer(
    console: Console, read_line: Callable[[str], str] = input
) -> IdentityConfirmer:
    """Build a console trust gate for project-level identity files."""

    def _confirm(request: IdentityTrustRequest) -> bool:
        heading = Text("trust project identity", style="bold yellow")
        heading.append(" ")
        heading.append(request.project_label)
        console.print(heading)
        console.print(request.summary, markup=False)
        try:
            answer = read_line("inject this project's AGENTS.md/MEMORY.md? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return _confirm


def make_console_skill_confirmer(
    console: Console, read_line: Callable[[str], str] = input
) -> IdentityConfirmer:
    """Build a console trust gate for project-level Skill definitions."""

    def _confirm(request: IdentityTrustRequest) -> bool:
        heading = Text("trust project Skills", style="bold yellow")
        heading.append(" ")
        heading.append(request.project_label)
        console.print(heading)
        console.print(request.summary, markup=False)
        try:
            answer = read_line("load these project Skills? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return _confirm


def make_console_identity_diagnostic(console: Console) -> IdentityDiagnostic:
    def _diagnose(message: str) -> None:
        console.print(Text(message))

    return _diagnose


def _load_skill_registry(
    *,
    home: str,
    allowed_root: str,
    no_identity: bool,
    confirmer: IdentityConfirmer | None,
    diagnostic: IdentityDiagnostic,
) -> SkillRegistry:
    return SkillRegistry.load(
        home=home,
        allowed_root=allowed_root,
        allow_project=not no_identity,
        confirmer=None if no_identity else confirmer,
        diagnostic=diagnostic,
    )


def resolve_cli_identity(
    *,
    no_identity: bool,
    allowed_root: str,
    confirmer: IdentityConfirmer | None,
    diagnostic: IdentityDiagnostic | None = None,
) -> ApprovedIdentity | None:
    """Resolve runtime identity without file I/O when explicitly disabled."""
    if no_identity:
        return None
    home = str(Path.home())
    snapshot = load_identity(home, allowed_root, diagnostic=diagnostic)
    return resolve_project_trust(
        snapshot,
        allowed_root,
        home,
        confirmer,
        diagnostic=diagnostic,
    )


def _make_memory_manager(
    allowed_root: str,
    *,
    identity: ApprovedIdentity | None,
    no_memory: bool,
    no_identity: bool,
    audit_sink: AuditSink | None = None,
    diagnostic: IdentityDiagnostic | None = None,
) -> MemoryManager:
    """Keep project memory behind the same M17 identity trust decision."""
    memory_path = Path(allowed_root) / ".forgeagent" / "MEMORY.md"
    project_trusted = identity is not None and getattr(identity, "memory", None) is not None
    allow_project = not os.path.lexists(memory_path) or project_trusted
    manager = MemoryManager(
        allowed_root,
        audit_sink=audit_sink,
        enabled=not no_memory and not no_identity,
        allow_project=allow_project,
        diagnostic=diagnostic,
    )
    if manager.enabled and allow_project and project_trusted:
        manager.load()
    return manager


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
    identity: ApprovedIdentity | None = None,
    container_image: str | None = None,
    usage_total: TokenUsage | None = None,
    images: list[ImageItem] | None = None,
    stream: bool = False,
    context_config: ContextConfig | None = None,
    memory_manager: MemoryManager | None = None,
    skills: SkillRegistry | None = None,
) -> TaskOutcome:
    """Run a single goal and render its outcome. Returns the outcome for testing.

    `asker` handles Survey mid-task questions. Default (None) is headless — a Survey call
    ends the task with NEEDS_INFO. REPL wires a console asker; `run` leaves it None.
    `mcp` wires the MCP catalog/manager; `confirmer` independently gates side-effecting
    MCP/WebFetch/FileWrite calls.
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
    resolved_context_config = context_config or ContextConfig()
    try:
        _validate_client_context_policy(client, resolved_context_config)
    except ValueError as exc:
        raise RegistryError(f"Invalid context configuration: {exc}") from exc
    live: Live | None = None
    on_stream_text = None
    if stream and console.is_terminal:
        live, on_stream_text = _make_stream_callback(console)
    try:
        task = Task(
            client,
            tier=tier,
            asker=asker,
            mcp=mcp,
            confirmer=confirmer,
            identity=identity,
            container_image=container_image,
            on_stream_text=on_stream_text,
            context_config=resolved_context_config,
            memory_manager=memory_manager,
            skills=skills,
        )
    except ValueError as exc:
        raise RegistryError(f"Invalid context configuration: {exc}") from exc
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


def run_collaboration_once(
    goal: str,
    *,
    mode: str,
    tier: Tier,
    model: str,
    planner_model: str | None,
    evaluator_model: str | None,
    max_rejections: int,
    client_factory: ClientFactory,
    allowed_root: str | None = None,
    console: Console | None = None,
    plan_confirmer: Callable[[str], bool] | None = None,
    asker: Asker | None = None,
    mcp: MCPManager | None = None,
    confirmer: Confirmer | None = None,
    identity: ApprovedIdentity | None = None,
    container_image: str | None = None,
    context_config: ContextConfig | None = None,
    memory_manager: MemoryManager | None = None,
    skills: SkillRegistry | None = None,
    audit_sink: AuditSink | None = None,
    task_id: str | None = None,
    route_decision: ModeDecision | None = None,
    required_candidate_files: tuple[str, ...] = (),
) -> CollaborationReport:
    return _cli_collaboration.run_collaboration_once(
        goal,
        mode=mode,
        tier=tier,
        model=model,
        planner_model=planner_model,
        evaluator_model=evaluator_model,
        max_rejections=max_rejections,
        client_factory=client_factory,
        bindings=_cli_collaboration.CollaborationBindings(
            runner_type=CollaborationRunner,
            task_type=Task,
            validate_context_policy=_validate_client_context_policy,
        ),
        allowed_root=allowed_root,
        console=console,
        plan_confirmer=plan_confirmer,
        asker=asker,
        mcp=mcp,
        confirmer=confirmer,
        identity=identity,
        container_image=container_image,
        context_config=context_config,
        memory_manager=memory_manager,
        skills=skills,
        audit_sink=audit_sink,
        task_id=task_id,
        route_decision=route_decision,
        required_candidate_files=required_candidate_files,
    )


def _loop_system_prompt(
    identity: ApprovedIdentity | None,
    memory_manager: MemoryManager | None,
    suffix: str,
) -> str:
    base_identity = identity or ApprovedIdentity(
        soul=None, user=None, project_agents=None, memory=None
    )
    if memory_manager is not None:
        base_identity = ApprovedIdentity(
            soul=base_identity.soul,
            user=base_identity.user,
            project_agents=base_identity.project_agents,
            memory=memory_manager.render() or None,
        )
    return f"{compose_system_prompt(base_identity)}\n\n{suffix}"


def _render_loop_report(report: LoopReport, console: Console) -> None:
    """Render the fixed public report projection without checkpoint contents."""
    console.print(f"loop id: {report.loop_id}")
    console.print(f"status: {report.status}")
    console.print(f"stop reason: {report.stop_reason or 'active'}")
    console.print(
        "counters: "
        f"iterations={report.iterations} rounds={report.rounds_used} "
        f"tokens={report.tokens_used} elapsed_seconds={report.elapsed_seconds:.3f} "
        f"consecutive_failures={report.consecutive_failures} "
        f"completed_items={report.completed_item_count} "
        f"open_questions={report.open_question_count} "
        f"usage_available={report.usage_available}"
    )


def run_loop_once(
    goal: str | None,
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    allowed_root: str | None = None,
    console: Console | None = None,
    asker: Asker | None = None,
    mcp: MCPManager | None = None,
    confirmer: Confirmer | None = None,
    identity: ApprovedIdentity | None = None,
    container_image: str | None = None,
    context_config: ContextConfig | None = None,
    memory_manager: MemoryManager | None = None,
    skills: SkillRegistry | None = None,
    token_budget: int | None = None,
    max_rounds: int | None = None,
    wall_clock_seconds: float | None = None,
    max_consecutive_failures: int | None = None,
    resume: str | None = None,
    collaboration_mode: str | None = None,
    planner_model: str | None = None,
    evaluator_model: str | None = None,
    max_rejections: int | None = None,
    plan_confirmer: Callable[[str], bool] | None = None,
    audit_sink: AuditSink | None = None,
) -> LoopReport:
    """Run one durable Loop through the same Task assembly as the CLI run command."""
    if resume is None:
        if goal is None:
            raise ValueError("a Loop goal is required")
        if token_budget is None:
            raise ValueError("token budget is required")
        budgets = LoopBudgets(
            token_budget=token_budget,
            max_rounds=DEFAULT_MAX_ROUNDS if max_rounds is None else max_rounds,
            wall_clock_seconds=(
                DEFAULT_WALL_CLOCK_SECONDS if wall_clock_seconds is None else wall_clock_seconds
            ),
            max_consecutive_failures=(
                DEFAULT_MAX_CONSECUTIVE_FAILURES
                if max_consecutive_failures is None
                else max_consecutive_failures
            ),
        )
    elif any(
        value is not None
        for value in (
            goal,
            token_budget,
            max_rounds,
            wall_clock_seconds,
            max_consecutive_failures,
            collaboration_mode,
            planner_model,
            evaluator_model,
            max_rejections,
        )
    ):
        raise ValueError("resume cannot override the frozen Loop configuration")

    resolved_collaboration_mode = collaboration_mode or "single"
    collaboration_mode_source = "explicit" if collaboration_mode is not None else "default"
    resolved_max_rejections = 2 if max_rejections is None else max_rejections

    root = str(Path.cwd().resolve()) if allowed_root is None else allowed_root
    receipt_store = (
        ExternalActionReceiptStore(root, audit_sink=audit_sink) if mcp is not None else None
    )
    resolved_context_config = context_config or ContextConfig()

    def build_task(iteration: int, remaining_rounds: int, suffix: str, registry):
        del iteration
        client = client_factory(model)
        client_closed = False

        def close_client() -> None:
            nonlocal client_closed
            if client_closed:
                return
            client_closed = True
            close = getattr(client, "close", None)
            if callable(close):
                close()

        try:
            _validate_client_context_policy(client, resolved_context_config)
            task = Task(
                client,
                tier=tier,
                allowed_root=root,
                system_prompt=_loop_system_prompt(identity, memory_manager, suffix),
                max_rounds=remaining_rounds,
                asker=asker,
                mcp=mcp,
                confirmer=confirmer,
                container_image=container_image,
                context_config=resolved_context_config,
                memory_manager=memory_manager,
                skills=skills,
                tool_registry=registry,
                max_submission_recovery_attempts=2,
            )
        except BaseException:
            close_client()
            raise

        class OwnedLoopTask:
            def __init__(self) -> None:
                self._closed = False

            def run(self, task_goal: str, *, cancel_event=None):
                return task.run(task_goal, cancel_event=cancel_event)

            def close(self) -> None:
                if self._closed:
                    return
                self._closed = True
                try:
                    task.close()
                finally:
                    close_client()

        return OwnedLoopTask()

    def build_collaboration(iteration: int, remaining_rounds: int, suffix: str, registry):
        del iteration
        rounds_left = remaining_rounds
        role_models = {
            "planner": planner_model or model,
            "generator": model,
            "evaluator": evaluator_model or model,
        }

        def build_role(role: CollaborationRole, attempt: int, registry, prompt: str):
            del attempt
            nonlocal rounds_left
            if rounds_left <= 0:
                raise CollaborationRoleConfigurationError
            client = None
            task = None
            try:
                client = client_factory(role_models[role])
                _validate_client_context_policy(client, resolved_context_config)
                task = Task(
                    client,
                    tier="restricted" if role == "evaluator" else tier,
                    allowed_root=root,
                    system_prompt=prompt,
                    max_rounds=rounds_left,
                    asker=asker if role == "generator" else None,
                    mcp=mcp if role == "generator" else None,
                    confirmer=confirmer if role == "generator" else None,
                    container_image=container_image,
                    context_config=resolved_context_config,
                    memory_manager=memory_manager if role == "generator" else None,
                    skills=skills if role == "generator" else None,
                    tool_registry=registry,
                    receipt_store=receipt_store if role == "generator" else None,
                    max_submission_recovery_attempts=2,
                )
            except Exception as error:
                if task is not None:
                    task.close()
                close = getattr(client, "close", None)
                if callable(close):
                    close()
                raise CollaborationRoleConfigurationError from error

            class OwnedRole:
                def run(self, task_goal: str, *, cancel_event=None):
                    nonlocal rounds_left
                    outcome = task.run(task_goal, cancel_event=cancel_event)
                    rounds_left = max(0, rounds_left - len(outcome.rounds))
                    return outcome

                def close(self):
                    try:
                        task.close()
                    finally:
                        close = getattr(client, "close", None)
                        if callable(close):
                            close()

            return OwnedRole()

        loop_id = runner._checkpoint.collaboration_id
        state_path = Path(root) / ".forgeagent" / "collaborations" / f"{loop_id}.json"
        if state_path.exists():
            store = CollaborationStore(root, loop_id=runner._checkpoint.loop_id)
            state = store.load(loop_id)
            collaboration = CollaborationRunner(
                store=store,
                state=state,
                role_task_builder=build_role,
                plan_confirmer=plan_confirmer,
                generator_registry=registry,
                task_data_suffix=suffix,
                recover_role_failures=True,
                execution_tier=tier,
                loop_id=runner._checkpoint.loop_id,
            )
        else:
            collaboration = CollaborationRunner.create(
                mode=runner._checkpoint.collaboration_mode,
                goal=runner._checkpoint.goal,
                allowed_root=root,
                collaboration_id=loop_id,
                role_task_builder=build_role,
                plan_confirmer=plan_confirmer,
                planner_model=role_models["planner"],
                generator_model=role_models["generator"],
                evaluator_model=role_models["evaluator"],
                max_rejections=resolved_max_rejections,
                generator_registry=registry,
                task_data_suffix=suffix,
                recover_role_failures=True,
                execution_tier=tier,
                loop_id=runner._checkpoint.loop_id,
            )

        class OwnedCollaboration:
            @property
            def plan_digest(self):
                return collaboration._state.plan_digest

            def run(self, task_goal: str, *, cancel_event=None):
                return collaboration.run(task_goal, cancel_event=cancel_event)

            def close(self):
                collaboration.close()

        return OwnedCollaboration()

    if resume is None:
        runner = LoopRunner.create(
            allowed_root=root,
            task_builder=build_task,
            goal=goal,
            budgets=budgets,
            trigger="cli",
            with_mcp=mcp is not None,
            skills=skills,
            collaboration_builder=(
                build_collaboration if resolved_collaboration_mode != "single" else None
            ),
            collaboration_mode=resolved_collaboration_mode,
            collaboration_mode_source=collaboration_mode_source,
            collaboration_id=(uuid4().hex if resolved_collaboration_mode != "single" else ""),
            audit_sink=audit_sink,
            receipt_store=receipt_store,
        )
    else:
        runner = LoopRunner.resume(
            allowed_root=root,
            task_builder=build_task,
            loop_id=resume,
            trigger="cli",
            with_mcp=mcp is not None,
            skills=skills,
            collaboration_builder=build_collaboration,
            audit_sink=audit_sink,
            receipt_store=receipt_store,
        )
    cancel_event = threading.Event()
    previous_sigint = None
    sigint_installed = False

    def request_cancel(signum, frame) -> None:
        if cancel_event.is_set():
            if callable(previous_sigint):
                previous_sigint(signum, frame)
                return
            raise KeyboardInterrupt
        cancel_event.set()

    try:
        try:
            previous_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, request_cancel)
            sigint_installed = True
        except ValueError:
            # signal handlers can only be installed by the main thread.
            pass
        try:
            report = runner.run(cancel_event=cancel_event)
        finally:
            if sigint_installed:
                signal.signal(signal.SIGINT, previous_sigint)
    finally:
        runner.close()
    _render_loop_report(report, console if console is not None else Console())
    return report


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
        labeler = getattr(mcp, "public_server_name", None)
        safe_server = (
            labeler(server) if callable(labeler) else mask_secrets(server, sensitive_env_values())
        )
        try:
            ok = mcp.enable(server) if action == "enable" else mcp.disable(server)
        except TimeoutError:
            console.print(Text(f"MCP {action} pending: {safe_server}"))
            return
        if ok:
            status = mcp.server_status().get(safe_server, "unavailable")
            console.print(f"[green]{action}d[/green] {safe_server}: {status}")
        else:
            console.print(f"[red]unknown server[/red] {safe_server!r}")
    else:
        console.print(
            "[dim]usage: mcp status | mcp tools | mcp enable <server> | mcp disable <server>[/dim]"
        )


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
    """Render MCP diagnostics, status, tools, and runtime toggles."""
    if mcp is None:
        _handle_mcp_command("mcp status", mcp, console)
        return
    parts = goal.split()
    if len(parts) == 1:
        for diagnostic in mcp.diagnostics():
            console.print(Text(diagnostic.name))
            console.print(Text(f"Status: {diagnostic.status}"))
            console.print(Text(f"Tools: {diagnostic.tool_count}"))
            for label, value in (
                ("Reason", diagnostic.reason),
                ("Impact", diagnostic.impact),
                ("Action", diagnostic.action),
            ):
                if value is not None:
                    console.print(Text(f"{label}: {value}"))
        return
    action = parts[1]
    if action == "tools" and len(parts) == 2:
        _print_mcp_tools(mcp, console)
        return
    _handle_mcp_command("mcp" + goal[len("/mcp") :], mcp, console)
    if action == "status":
        _print_mcp_tools(mcp, console)


def _handle_model_command(
    goal: str,
    model: str,
    console: Console,
    registry: Registry | None = None,
    context_config: ContextConfig | None = None,
    validate_context: bool = True,
) -> str:
    """`/model` lists registered models (reuses `print_models`); `/model <id-or-alias>`
    switches the current REPL session's model. Returns the model to use for subsequent
    goals — unchanged if no argument was given or the requested id is unknown (an
    unknown id reports an error and never switches, design doc §3.5)."""
    parts = goal.split(maxsplit=1)
    if len(parts) == 1:
        print_models(console, registry)
        return model
    requested = parts[1].strip()
    if validate_context:
        try:
            _validate_context_policy(
                requested,
                registry if registry is not None else load_registry(),
                context_config or ContextConfig(),
            )
        except RegistryError as exc:
            console.print(f"[red]unknown model[/red]: {exc}")
            return model
        except ValueError as exc:
            console.print(f"[red]model switch failed[/red]: invalid context configuration: {exc}")
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


def _handle_image_command(goal: str, console: Console) -> tuple[list[ImageItem] | None, str | None]:
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
    "/single": "/single <goal> — Force the standard single-agent route",
    "/duo": "/duo <goal> — Generator plus independent Evaluator (higher cost)",
    "/triad": "/triad <goal> — Planner confirmation, Generator, and Evaluator (highest cost)",
    "/model": "/model [id-or-alias] — list models, or switch this session's model",
    "/search": "/search <query> — web search; results are printed only, never sent to the model",
    "/image": "/image <path> [goal...] — attach image(s) (file or directory) to a goal",
    "/mcp": "/mcp [status|tools|enable <s>|disable <s>] — MCP diagnostics, tools, and toggles",
    "/memory": "/memory — show effective session and project memory",
    "/remember": "/remember <session|project> <key>=<value> — store one declarative fact",
    "/reload": "/reload — reload ~/.forgeagent/{models,config}.yaml",
    "/help": "/help [command] — list commands, or show one command's detailed usage",
}


def _handle_memory_command(manager: MemoryManager, console: Console) -> None:
    rendered = manager.render()
    console.print(rendered if rendered else "[dim]no memory[/dim]", markup=False)


def _handle_remember_command(goal: str, manager: MemoryManager, console: Console) -> None:
    parts = goal.split(maxsplit=2)
    if len(parts) != 3 or parts[1] not in {"session", "project"} or "=" not in parts[2]:
        console.print("usage: /remember <session|project> <key>=<value>", style="dim")
        return
    key, content = parts[2].split("=", 1)
    try:
        candidate = MemoryCandidate(
            scope=parts[1],
            kind="fact",
            key=key.strip(),
            content=content.strip(),
        )
    except ValueError:
        console.print("[red]memory rejected[/red]: invalid candidate")
        return
    outcome = manager.apply(candidate)
    colour = "green" if outcome.status in {"accepted", "replaced"} else "yellow"
    detail = f": {outcome.reason}" if outcome.reason else ""
    console.print(f"[{colour}]memory {outcome.status}[/{colour}]{detail}")


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


def _make_interactive_reader() -> Callable[[str], str]:
    """Return a terminal reader with slash-command completion and session-only history."""
    completer = WordCompleter(
        list(_SLASH_COMMAND_USAGE),
        meta_dict=_SLASH_COMMAND_USAGE,
        sentence=True,
        match_middle=False,
    )
    session = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True,
    )
    return session.prompt


_STARTUP_COLOURS = (
    "red",
    "yellow",
    "green",
    "cyan",
    "blue",
    "magenta",
    "bright_magenta",
)
_STARTUP_LOGO = (
    " _____                    _                    _   ",
    "|  ___|__  _ __ __ _  ___| | __ _  ___ _ __ | |_ ",
    "| |_ / _ \\| '__/ _` |/ _ \\ |/ _` |/ _ \\ '_ \\| __|",
    "|  _| (_) | | | (_| |  __/ | (_| |  __/ | | | |_ ",
    "|_|  \\___/|_|  \\__, |\\___|_|\\__, |\\___|_| |_|\\__|",
    "                |___/        |___/                  ",
)


def _interactive_repl(console: Console, *, default_reader: bool) -> bool:
    return default_reader and console.is_terminal and sys.stdin.isatty()


def _startup_mark_available(console: Console) -> bool:
    return (
        console.is_terminal
        and os.environ.get("TERM") != "dumb"
        and not any(name in os.environ for name in ("CI", "GITHUB_ACTIONS", "BUILD_NUMBER"))
    )


def _startup_ui_available(console: Console) -> bool:
    return (
        _startup_mark_available(console)
        and console.color_system is not None
        and not console.no_color
        and "NO_COLOR" not in os.environ
    )


class _StartupDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._stage: str | None = None
        self._live: Live | None = None
        self._static_mark_rendered = False

    def _logo_text(self) -> str:
        return (
            "ForgeAgent"
            if self._console.width < max(map(len, _STARTUP_LOGO))
            else "\n".join(_STARTUP_LOGO)
        )

    def logo_renderable(self) -> Text:
        colour = _STARTUP_COLOURS[int(time.monotonic() * 8) % len(_STARTUP_COLOURS)]
        return Text(self._logo_text(), style=colour)

    def static_logo_renderable(self) -> Text:
        return Text(self._logo_text())

    def renderable(self) -> Text:
        rendered = self.logo_renderable()
        if self._stage:
            rendered.append("\n")
            rendered.append(self._stage, style="dim")
        return rendered

    def start(self, stage: str) -> None:
        self._stage = stage
        if _startup_ui_available(self._console):
            self._start_live()
        elif _startup_mark_available(self._console) and not self._static_mark_rendered:
            self._console.print(self.static_logo_renderable())
            self._static_mark_rendered = True

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def pause(self) -> None:
        self.stop()

    def resume(self) -> None:
        if self._stage is not None:
            self._start_live()

    def stop(self) -> None:
        live = self._live
        if live is None:
            return
        try:
            live.stop()
        finally:
            self._live = None

    def _start_live(self) -> None:
        if self._live is not None or not _startup_ui_available(self._console):
            return
        self._live = Live(
            console=self._console,
            refresh_per_second=8,
            transient=True,
            get_renderable=self.renderable,
        )
        self._live.start()


@contextmanager
def _startup_confirmation(display: _StartupDisplay):
    should_resume = display._live is not None
    if should_resume:
        display.pause()
    try:
        yield
    except BaseException:
        raise
    else:
        if should_resume:
            display.resume()


def _with_startup_display_pause(
    confirmer: IdentityConfirmer | None, display: _StartupDisplay
) -> IdentityConfirmer | None:
    if confirmer is None:
        return None

    def confirm(request: IdentityTrustRequest) -> bool:
        with _startup_confirmation(display):
            return confirmer(request)

    return confirm


def _render_startup_summary(
    console: Console,
    *,
    model: str,
    tier: Tier,
    root: str,
    diagnostics: tuple[MCPServerDiagnostic, ...],
) -> None:
    enabled = [item for item in diagnostics if item.enabled]
    available = sum(item.status == "available" for item in enabled)
    fields = ["Ready", f"model {model}", f"sandbox {tier}", f"project {root}"]
    if enabled:
        fields.insert(1, f"MCP {available}/{len(enabled)}")
    console.print(Text(" | ".join(fields)))
    for item in enabled:
        if item.required or item.status == "available":
            continue
        detail = [f"MCP {item.name} unavailable"]
        detail.extend(
            f"{label}: {value}"
            for label, value in (
                ("Reason", item.reason),
                ("Impact", item.impact),
                ("Action", item.action),
            )
            if value is not None
        )
        console.print(Text(" | ".join(detail)), soft_wrap=True)


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    console: Console | None = None,
    read_line: Callable[[str], str] | None = None,
    confirmation_available: bool | None = None,
    container_image: str | None = None,
    stream: bool = False,
    no_identity: bool = False,
    no_memory: bool = False,
    context_config: ContextConfig | None = None,
    registry: Registry | None = None,
    use_registry_snapshot: bool | None = None,
    skills: SkillRegistry | None = None,
    audit_sink: AuditSink | None = None,
) -> None:
    """Interactive loop: read a goal, run it, repeat. Blank line or EOF/quit exits.

    `read_line` is injectable so tests can drive the REPL without a real terminal.
    `stream` (M9 Phase 3) renders each goal's response live as it arrives.
    """
    return _cli_repl.repl(
        tier=tier,
        model=model,
        client_factory=client_factory,
        bindings=_cli_repl.ReplBindings(
            build_real_client=build_real_client,
            build_mcp_manager=build_mcp_manager,
            confirmed_collaboration_mode=_confirmed_collaboration_mode,
            console_plan_confirmer=_console_plan_confirmer,
            handle_help_command=_handle_help_command,
            handle_image_command=_handle_image_command,
            handle_mcp_slash=_handle_mcp_slash,
            handle_memory_command=_handle_memory_command,
            handle_model_command=_handle_model_command,
            handle_remember_command=_handle_remember_command,
            handle_search_command=_handle_search_command,
            interactive_repl=_interactive_repl,
            load_context_config=load_context_config,
            load_skill_registry=_load_skill_registry,
            make_console_asker=make_console_asker,
            make_console_confirmer=make_console_confirmer,
            make_console_identity_confirmer=make_console_identity_confirmer,
            make_console_identity_diagnostic=make_console_identity_diagnostic,
            make_console_skill_confirmer=make_console_skill_confirmer,
            make_interactive_reader=_make_interactive_reader,
            make_memory_manager=_make_memory_manager,
            print_command_menu=_print_command_menu,
            reload_registry=reload_registry,
            render_startup_summary=_render_startup_summary,
            resolve_cli_identity=resolve_cli_identity,
            run_collaboration_once=run_collaboration_once,
            run_once=run_once,
            startup_display_type=_StartupDisplay,
            validate_context_policy=_validate_context_policy,
            with_startup_display_pause=_with_startup_display_pause,
        ),
        console=console,
        read_line=read_line,
        confirmation_available=confirmation_available,
        container_image=container_image,
        stream=stream,
        no_identity=no_identity,
        no_memory=no_memory,
        context_config=context_config,
        registry=registry,
        use_registry_snapshot=use_registry_snapshot,
        skills=skills,
        audit_sink=audit_sink,
    )


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


def _process_control(error: BaseException) -> KeyboardInterrupt | SystemExit | None:
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            if control := _process_control(nested):
                return control
    return None


def build_mcp_manager() -> MCPManager | None:
    """Load mcp.yaml and, if any servers are enabled, build + connect a manager.

    Returns None when no servers are configured (the common case) so the MCP tool stays
    off the menu. Optional server failures degrade to `server_status()` diagnostics;
    an enabled required server failure closes the manager and raises `MCPStartupError`.
    """
    servers = load_mcp_config()
    if not any(config.enabled for config in servers.values()):
        return None
    manager = MCPManager(servers)
    try:
        manager.connect()
    except BaseException as error:
        if control := _process_control(error):
            raise control from None
        if not getattr(manager, "_closed", False):
            try:
                manager.close()
            except BaseException as cleanup:
                if control := _process_control(cleanup):
                    raise control from None
                logger.warning("MCP connect cleanup incomplete")
        raise MCPStartupError("startup_failed") from None
    failures = manager.required_failures()
    if failures:
        try:
            manager.close()
        except BaseException as cleanup:
            if control := _process_control(cleanup):
                raise control from None
            logger.warning("MCP required cleanup incomplete")
        raise MCPStartupError("required_server_unavailable")
    return manager


def print_models(console: Console, registry: Registry | None = None) -> None:
    """Print the registered models with their aliases and key capabilities."""
    console.print("[bold]Available models[/bold] (canonical — aliases):")
    for info in list_models(registry):
        aliases = ", ".join(info.aliases) if info.aliases else "—"
        console.print(
            f"  [cyan]{info.model_id}[/cyan] — {aliases}  "
            f"[dim]({info.client_kind}, ctx {info.context_window})[/dim]"
        )


def _load_cli_context_config() -> ContextConfig:
    """Translate context parsing failures to the CLI's existing config-error path."""
    try:
        raw_override = os.environ.get(_CONTEXT_CONFIG_ENVIRONMENT)
        if raw_override is None:
            return load_context_config()
        override = json.loads(raw_override)
        if not isinstance(override, Mapping):
            raise ValueError("context configuration root must be a mapping")
        return load_context_config(data=override)
    except RecursionError:
        raise RegistryError("Invalid context configuration: nesting is too deep") from None
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RegistryError(f"Invalid context configuration: {exc}") from exc


def _load_required_candidate_files_from_environment() -> tuple[str, ...]:
    raw = os.environ.get(_CANDIDATE_FILES_ENVIRONMENT)
    if raw is None:
        return ()
    try:
        return normalize_required_candidate_files(json.loads(raw))
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise RegistryError("Invalid candidate file configuration") from None


def _load_http_runtime_settings(path: str | Path) -> _HttpRuntimeSettings:
    config_path = Path(path).expanduser()
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise HttpStartupError("HTTP service configuration is invalid or unavailable.") from error
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise HttpStartupError("HTTP service configuration must be a mapping.")
    values = cast(dict[str, object], loaded)
    if set(values) - _HTTP_CONFIG_KEYS - _HTTP_RUNTIME_KEYS:
        raise HttpStartupError("HTTP service configuration contains unknown fields.")

    try:
        service = HttpServiceConfig.from_sources(
            {key: value for key, value in values.items() if key in _HTTP_CONFIG_KEYS}
        )
    except (TypeError, ValueError) as error:
        if str(error).startswith("context "):
            raise HttpStartupError("HTTP service context configuration is invalid.") from error
        raise HttpStartupError("HTTP service configuration is invalid.") from error

    model = values.get("model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model.strip() or any(ord(char) < 32 for char in model):
        raise HttpStartupError("HTTP service model configuration is invalid.")

    tier_value = values.get("tier", "restricted")
    if tier_value not in {"trusted", "restricted", "container"}:
        raise HttpStartupError("HTTP service tier configuration is invalid.")
    tier = cast(Tier, tier_value)

    allowed_root_value = values.get("allowed_root", str(Path.cwd()))
    if not isinstance(allowed_root_value, str) or not allowed_root_value.strip():
        raise HttpStartupError("HTTP service allowed root is invalid.")
    try:
        allowed_root_path = Path(allowed_root_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise HttpStartupError("HTTP service allowed root is invalid.") from error
    if not allowed_root_path.is_dir():
        raise HttpStartupError("HTTP service allowed root is invalid.")

    no_identity = values.get("no_identity", False)
    if not isinstance(no_identity, bool):
        raise HttpStartupError("HTTP service identity configuration is invalid.")

    no_memory = values.get("no_memory", False)
    if not isinstance(no_memory, bool):
        raise HttpStartupError("HTTP service memory configuration is invalid.")

    container_image = values.get("container_image")
    if container_image is not None and (
        not isinstance(container_image, str)
        or not container_image.strip()
        or any(unicodedata.category(character) == "Cc" for character in container_image)
    ):
        raise HttpStartupError("HTTP service container configuration is invalid.")

    shutdown_timeout = values.get("shutdown_timeout_seconds", 5.0)
    if type(shutdown_timeout) not in {int, float}:
        raise HttpStartupError("HTTP service shutdown timeout is invalid.")
    shutdown_timeout_seconds = float(shutdown_timeout)
    if not math.isfinite(shutdown_timeout_seconds) or not 0 < shutdown_timeout_seconds <= 60:
        raise HttpStartupError("HTTP service shutdown timeout is invalid.")

    return _HttpRuntimeSettings(
        service=service,
        model=model,
        tier=tier,
        allowed_root=str(allowed_root_path),
        no_identity=no_identity,
        no_memory=no_memory,
        container_image=container_image,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def _serve_has_cli_policy_override(argv: list[str]) -> bool:
    return any(
        argument == option or argument.startswith(f"{option}=")
        for argument in argv
        for option in _SERVE_FORBIDDEN_CLI_OPTIONS
    )


def _run_owned_http_server(
    server,
    service: TaskService,
    *,
    shutdown_timeout: float,
    once: bool,
    on_started: Callable[[], None] | None = None,
) -> None:
    stop_requested = threading.Event()
    wrapper_entered = threading.Event()
    serve_entered = getattr(server, "serve_entered", wrapper_entered)
    server_errors: list[BaseException] = []
    cleanup_errors: list[BaseException] = []
    previous_handlers: dict[signal.Signals, object] = {}
    server_thread: threading.Thread | None = None
    thread_started = False
    listener_entered = False
    primary_error: BaseException | None = None

    def request_stop(_signum=None, _frame=None) -> None:
        stop_requested.set()

    def run_server() -> None:
        wrapper_entered.set()
        try:
            server.serve_forever(poll_interval=0.1)
        except BaseException as error:
            server_errors.append(error)
        finally:
            stop_requested.set()

    try:
        if threading.current_thread() is threading.main_thread():
            for signal_number in (signal.SIGINT, signal.SIGTERM):
                previous_handler = signal.getsignal(signal_number)
                signal.signal(signal_number, request_stop)
                previous_handlers[signal_number] = previous_handler

        server_thread = threading.Thread(
            target=run_server,
            name="forgeagent-http-server",
            daemon=False,
        )
        server_thread.start()
        thread_started = True
        listener_entered = serve_entered.wait(timeout=max(1.0, shutdown_timeout))
        if not listener_entered:
            raise HttpStartupError("HTTP listener did not enter its serve loop.")
        if on_started is not None:
            on_started()
        if once:
            stop_requested.set()
        while server_thread.is_alive() and not stop_requested.wait(0.1):
            pass
    except BaseException as error:
        primary_error = error
    finally:
        if thread_started and listener_entered:
            try:
                server.shutdown()
            except BaseException as error:
                cleanup_errors.append(error)
                logger.error("HTTP listener shutdown failed")
        try:
            service.shutdown(timeout=shutdown_timeout)
        except BaseException as error:
            cleanup_errors.append(error)
            logger.error("HTTP task service shutdown failed")
        try:
            server.server_close()
        except BaseException as error:
            cleanup_errors.append(error)
            logger.error("HTTP listener close failed")
        if thread_started and server_thread is not None:
            try:
                server_thread.join(timeout=shutdown_timeout)
            except BaseException as error:
                cleanup_errors.append(error)
                logger.error("HTTP listener thread join failed")
        for signal_number, previous_handler in reversed(previous_handlers.items()):
            try:
                signal.signal(signal_number, previous_handler)
            except BaseException as error:
                cleanup_errors.append(error)
                logger.error("HTTP signal handler restoration failed")

    if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
        raise primary_error
    for error in cleanup_errors:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise error
    for error in server_errors:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise error
    if primary_error is not None:
        if isinstance(primary_error, HttpStartupError):
            raise primary_error
        if isinstance(primary_error, Exception):
            raise HttpStartupError("HTTP service owner failed.") from primary_error
        raise primary_error
    if server_errors:
        error = server_errors[0]
        raise HttpStartupError("HTTP listener stopped unexpectedly.") from error
    if (server_thread is not None and server_thread.is_alive()) or cleanup_errors:
        raise HttpStartupError("HTTP service shutdown did not complete cleanly.")


def serve_http(
    config_path: str | Path,
    *,
    client_factory: ClientFactory,
    console: Console,
    once: bool = False,
) -> None:
    """Assemble and own the opt-in local HTTP task service."""
    settings = _load_http_runtime_settings(config_path)
    try:
        task_client_factory = _http_client_factory_with_validated_context(
            settings.model,
            client_factory,
            settings.service.context_config,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise HttpStartupError("HTTP service context policy is invalid.") from error
    audit_path = settings.service.audit_path.expanduser()
    try:
        audit_sink = JsonlAuditSink(
            audit_path,
            max_bytes=settings.service.audit_max_bytes,
            retention_files=settings.service.audit_retention_files,
        )
        headless_confirmer = HeadlessConfirmer(
            settings.service.allowlist,
            audit=audit_sink,
            root=settings.allowed_root,
        )
    except (OSError, ValueError) as error:
        raise HttpStartupError("HTTP audit or allowlist configuration is invalid.") from error

    identity = resolve_cli_identity(
        no_identity=settings.no_identity,
        allowed_root=settings.allowed_root,
        confirmer=None,
        diagnostic=make_console_identity_diagnostic(console),
    )
    skills = _load_skill_registry(
        home=str(Path.home()),
        allowed_root=settings.allowed_root,
        no_identity=settings.no_identity,
        confirmer=None,
        diagnostic=make_console_identity_diagnostic(console),
    )
    mcp: MCPManager | None = None
    service: TaskService | None = None
    try:
        mcp = build_mcp_manager()
        receipt_store = ExternalActionReceiptStore(settings.allowed_root, audit_sink=audit_sink)

        def task_factory(record: TaskRecord) -> Task | LoopRunner | CollaborationRunner:
            options = getattr(record, "options", {})
            memory_manager = _make_memory_manager(
                settings.allowed_root,
                identity=identity,
                no_memory=settings.no_memory,
                no_identity=settings.no_identity,
                audit_sink=audit_sink,
            )
            if options.get("mode") == "loop":
                loop_runner: LoopRunner | None = None

                def build_loop_task(iteration, remaining_rounds, suffix, registry):
                    del iteration
                    client = task_client_factory(settings.model)
                    task = Task(
                        client,
                        tier=settings.tier,
                        allowed_root=settings.allowed_root,
                        system_prompt=_loop_system_prompt(identity, memory_manager, suffix),
                        max_rounds=remaining_rounds,
                        mcp=mcp,
                        confirmer=headless_confirmer,
                        allow_auto_approve=False,
                        container_image=settings.container_image,
                        audit_sink=audit_sink,
                        task_id=record.task_id,
                        context_config=settings.service.context_config,
                        memory_manager=memory_manager,
                        skills=skills,
                        tool_registry=registry,
                        receipt_store=receipt_store,
                        max_submission_recovery_attempts=2,
                    )

                    class OwnedLoopTask:
                        def run(self, goal, *, cancel_event=None):
                            return task.run(goal, cancel_event=cancel_event)

                        def close(self):
                            try:
                                task.close()
                            finally:
                                close = getattr(client, "close", None)
                                if callable(close):
                                    close()

                    return OwnedLoopTask()

                common = {
                    "allowed_root": settings.allowed_root,
                    "task_builder": build_loop_task,
                    "trigger": "http",
                    "audit_sink": audit_sink,
                    "task_id": record.task_id,
                    "with_mcp": mcp is not None,
                    "skills": skills,
                    "receipt_store": receipt_store,
                }
                collaboration_mode = cast(str, options.get("collaboration_mode", "single"))

                def build_loop_collaboration(iteration, remaining_rounds, suffix, registry):
                    del iteration
                    rounds_left = remaining_rounds
                    role_models = {
                        "planner": settings.service.planner_model or settings.model,
                        "generator": settings.model,
                        "evaluator": settings.service.evaluator_model or settings.model,
                    }

                    def build_role(role, attempt, registry, prompt):
                        del attempt
                        nonlocal rounds_left
                        if rounds_left <= 0:
                            raise CollaborationRoleConfigurationError
                        client = task_client_factory(role_models[role])
                        try:
                            task = Task(
                                client,
                                tier=(
                                    settings.service.evaluator_tier
                                    if role == "evaluator"
                                    else settings.tier
                                ),
                                allowed_root=settings.allowed_root,
                                system_prompt=prompt,
                                max_rounds=rounds_left,
                                mcp=mcp if role == "generator" else None,
                                confirmer=headless_confirmer if role == "generator" else None,
                                allow_auto_approve=False,
                                container_image=settings.container_image,
                                audit_sink=audit_sink,
                                task_id=record.task_id,
                                context_config=settings.service.context_config,
                                memory_manager=memory_manager if role == "generator" else None,
                                skills=skills if role == "generator" else None,
                                tool_registry=registry,
                                receipt_store=receipt_store if role == "generator" else None,
                                max_submission_recovery_attempts=2,
                            )
                        except Exception as error:
                            close = getattr(client, "close", None)
                            if callable(close):
                                close()
                            raise CollaborationRoleConfigurationError from error

                        class OwnedRole:
                            def run(self, goal, *, cancel_event=None):
                                nonlocal rounds_left
                                outcome = task.run(goal, cancel_event=cancel_event)
                                rounds_left = max(0, rounds_left - len(outcome.rounds))
                                return outcome

                            def close(self):
                                try:
                                    task.close()
                                finally:
                                    close = getattr(client, "close", None)
                                    if callable(close):
                                        close()

                        return OwnedRole()

                    if loop_runner is None:
                        raise LoopCheckpointError("Loop collaboration is unavailable")
                    collaboration_id = loop_runner._checkpoint.collaboration_id
                    state_path = (
                        Path(settings.allowed_root)
                        / ".forgeagent"
                        / "collaborations"
                        / f"{collaboration_id}.json"
                    )
                    if state_path.exists():
                        store = CollaborationStore(
                            settings.allowed_root,
                            audit_sink=audit_sink,
                            task_id=record.task_id,
                            loop_id=loop_runner._checkpoint.loop_id,
                        )
                        state = store.load(collaboration_id)
                        collaboration = CollaborationRunner(
                            store=store,
                            state=state,
                            role_task_builder=build_role,
                            plan_confirmer=headless_plan_confirmer(
                                settings.service.triad_plan_policy
                            ),
                            generator_registry=registry,
                            task_data_suffix=suffix,
                            recover_role_failures=True,
                            execution_tier=settings.tier,
                            audit_sink=audit_sink,
                            task_id=record.task_id,
                            loop_id=loop_runner._checkpoint.loop_id,
                        )
                    else:
                        collaboration = CollaborationRunner.create(
                            mode=loop_runner._checkpoint.collaboration_mode,
                            goal=record.goal,
                            allowed_root=settings.allowed_root,
                            collaboration_id=collaboration_id,
                            role_task_builder=build_role,
                            plan_confirmer=headless_plan_confirmer(
                                settings.service.triad_plan_policy
                            ),
                            planner_model=role_models["planner"],
                            generator_model=role_models["generator"],
                            evaluator_model=role_models["evaluator"],
                            evaluator_tier=settings.service.evaluator_tier,
                            max_rejections=settings.service.max_rejections,
                            generator_registry=registry,
                            task_data_suffix=suffix,
                            recover_role_failures=True,
                            execution_tier=settings.tier,
                            audit_sink=audit_sink,
                            task_id=record.task_id,
                            loop_id=loop_runner._checkpoint.loop_id,
                        )

                    class OwnedCollaboration:
                        @property
                        def plan_digest(self):
                            return collaboration._state.plan_digest

                        def run(self, goal, *, cancel_event=None):
                            return collaboration.run(goal, cancel_event=cancel_event)

                        def close(self):
                            collaboration.close()

                    return OwnedCollaboration()

                common["collaboration_builder"] = (
                    build_loop_collaboration if collaboration_mode != "single" else None
                )
                resume_loop_id = options.get("resume_loop_id")
                if isinstance(resume_loop_id, str):
                    common["collaboration_builder"] = build_loop_collaboration
                    loop_runner = LoopRunner.resume(loop_id=resume_loop_id, **common)
                    return loop_runner
                budgets = LoopBudgets(
                    token_budget=options["token_budget"],
                    max_rounds=options["max_rounds"],
                    wall_clock_seconds=options["wall_clock_seconds"],
                    max_consecutive_failures=options["max_consecutive_failures"],
                )
                loop_runner = LoopRunner.create(
                    goal=record.goal,
                    budgets=budgets,
                    loop_id=record.task_id,
                    collaboration_mode=collaboration_mode,
                    collaboration_mode_source=(
                        "explicit" if "collaboration_mode" in options else "default"
                    ),
                    collaboration_id=(uuid4().hex if collaboration_mode != "single" else ""),
                    **common,
                )
                return loop_runner
            record_goal = getattr(record, "goal", "")
            requested = options.get("mode")
            requested_mode = (
                None
                if requested is None
                else "single"
                if requested == "task"
                else cast(str, requested)
            )
            decision = (
                resolve_collaboration_mode(
                    record_goal,
                    requested_mode,
                    allow_weaker_override=settings.service.allow_weaker_override,
                )
                if record_goal
                else resolve_collaboration_mode("ordinary request", requested_mode)
            )
            if decision.mode in {"duo", "triad"}:
                role_models = {
                    "planner": settings.service.planner_model or settings.model,
                    "generator": settings.model,
                    "evaluator": settings.service.evaluator_model or settings.model,
                }

                def build_role(role, attempt, registry, prompt):
                    del attempt
                    client = task_client_factory(role_models[role])
                    try:
                        task = Task(
                            client,
                            tier=(
                                settings.service.evaluator_tier
                                if role == "evaluator"
                                else settings.tier
                            ),
                            allowed_root=settings.allowed_root,
                            system_prompt=prompt,
                            mcp=mcp if role == "generator" else None,
                            confirmer=headless_confirmer if role == "generator" else None,
                            allow_auto_approve=False,
                            container_image=settings.container_image,
                            audit_sink=audit_sink,
                            task_id=record.task_id,
                            context_config=settings.service.context_config,
                            memory_manager=memory_manager if role == "generator" else None,
                            skills=skills if role == "generator" else None,
                            tool_registry=registry,
                        )
                    except Exception as error:
                        close = getattr(client, "close", None)
                        if callable(close):
                            close()
                        raise CollaborationRoleConfigurationError from error

                    class OwnedRole:
                        def run(self, goal, *, cancel_event=None):
                            return task.run(goal, cancel_event=cancel_event)

                        def close(self):
                            try:
                                task.close()
                            finally:
                                close = getattr(client, "close", None)
                                if callable(close):
                                    close()

                    return OwnedRole()

                return CollaborationRunner.create(
                    mode=decision.mode,
                    goal=record_goal,
                    allowed_root=settings.allowed_root,
                    role_task_builder=build_role,
                    plan_confirmer=headless_plan_confirmer(settings.service.triad_plan_policy),
                    planner_model=role_models["planner"],
                    generator_model=role_models["generator"],
                    evaluator_model=role_models["evaluator"],
                    evaluator_tier=settings.service.evaluator_tier,
                    max_rejections=settings.service.max_rejections,
                    execution_tier=settings.tier,
                    audit_sink=audit_sink,
                    task_id=record.task_id,
                )
            return Task(
                task_client_factory(settings.model),
                tier=settings.tier,
                allowed_root=settings.allowed_root,
                identity=identity,
                mcp=mcp,
                confirmer=headless_confirmer,
                allow_auto_approve=False,
                container_image=settings.container_image,
                audit_sink=audit_sink,
                task_id=record.task_id,
                context_config=settings.service.context_config,
                memory_manager=memory_manager,
                skills=skills,
                receipt_store=receipt_store,
            )

        service = TaskService(
            factory=task_factory,
            config=settings.service,
            shared_mcp_manager=mcp,
            audit_sink=audit_sink,
        )
        server = http_server.create_http_server(settings.service, service)
    except BaseException as error:
        if service is not None:
            service.shutdown(timeout=settings.shutdown_timeout_seconds)
        elif mcp is not None:
            mcp.close()
        if not isinstance(error, Exception):
            raise
        if isinstance(error, (MCPStartupError, HttpStartupError)):
            raise
        raise HttpStartupError("HTTP service could not start.") from error

    _run_owned_http_server(
        server,
        service,
        shutdown_timeout=settings.shutdown_timeout_seconds,
        once=once,
        on_started=lambda: console.print(
            f"[green]serving[/green] on {settings.service.bind_host}:{server.server_address[1]}"
        ),
    )


def _run_evaluate_command(
    args,
    *,
    client_factory: ClientFactory,
    console: Console,
    error_console: Console,
) -> int:
    return _run_evaluate_command_impl(
        args,
        client_factory=client_factory,
        console=console,
        error_console=error_console,
        validate_manifest=validate_artifact_manifest,
        evaluate=run_evaluator,
        make_record=_evaluation_record,
        append_record=append_trend,
    )


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory = build_real_client,
    audit_sink: AuditSink | None = None,
) -> int:
    """CLI entry point. Returns a process exit code.

    No subcommand -> REPL. `run <goal>` -> single execution. A missing API key surfaces
    as a clear message and a non-zero exit, never a traceback.
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code)
    console = Console()
    error_console = Console(stderr=True)
    try:
        if args.command == "models":
            print_models(console)
            return 0
        if args.command == "receipts":
            try:
                store = ExternalActionReceiptStore(str(Path.cwd().resolve()))
                if args.receipts_command == "list":
                    for receipt in store.list_pending(loop_id=args.loop_id, task_id=args.task_id):
                        console.print(
                            json.dumps(
                                receipt.model_dump(mode="json"), ensure_ascii=True, sort_keys=True
                            )
                        )
                    return 0
                decision = (
                    "confirmed"
                    if args.confirmed
                    else "abandoned"
                    if args.abandon
                    else "retry_approved"
                )
                store.resolve(args.action_id, args.revision, decision, args.evidence)
                return 0
            except (ReceiptError, OSError, ValueError):
                error_console.print("[red]receipt command error[/red]: operation rejected")
                return 2
        if args.command == "serve":
            if _serve_has_cli_policy_override(raw_argv):
                error_console.print(
                    "[red]HTTP startup error[/red]: execution policy must come from --config"
                )
                return 2
            serve_http(
                args.config,
                client_factory=client_factory,
                console=console,
                once=args.once,
            )
            return 0
        if args.command == "evaluate":
            return _run_evaluate_command(
                args,
                client_factory=client_factory,
                console=console,
                error_console=error_console,
            )
        if audit_sink is None and args.command in {None, "run", "loop"}:
            try:
                audit_sink = JsonlAuditSink(Path.home() / ".forgeagent" / "audit.jsonl")
            except OSError:
                error_console.print("[red]audit startup error[/red]: audit log is unavailable")
                return 2
        allowed_root = str(Path.cwd().resolve())
        interactive_identity = console.is_terminal and sys.stdin.isatty()
        identity_confirmer = (
            make_console_identity_confirmer(console) if interactive_identity else None
        )
        skill_confirmer = make_console_skill_confirmer(console) if interactive_identity else None
        identity_diagnostic = make_console_identity_diagnostic(console)
        if args.command == "run":
            context_config = _load_cli_context_config()
            runtime_registry = load_registry() if client_factory is build_real_client else None
            if runtime_registry is not None:
                try:
                    _validate_context_policy(args.model, runtime_registry, context_config)
                except ValueError as exc:
                    raise RegistryError(f"Invalid context configuration: {exc}") from exc
            runtime_client_factory = _client_factory_for_registry(
                runtime_registry if client_factory is build_real_client else None,
                client_factory,
            )
            images = None
            if args.image:
                try:
                    images = load_images(args.image)
                except ValueError as exc:
                    console.print(f"[red]could not load image(s)[/red]: {exc}")
                    return 2
            mcp = build_mcp_manager()
            try:
                confirmer = make_console_confirmer(console) if interactive_identity else None
                identity = resolve_cli_identity(
                    no_identity=args.no_identity,
                    allowed_root=allowed_root,
                    confirmer=identity_confirmer,
                    diagnostic=identity_diagnostic,
                )
                memory_manager = _make_memory_manager(
                    allowed_root,
                    identity=identity,
                    no_memory=args.no_memory,
                    no_identity=args.no_identity,
                    diagnostic=identity_diagnostic,
                )
                skills = _load_skill_registry(
                    home=str(Path.home()),
                    allowed_root=allowed_root,
                    no_identity=args.no_identity,
                    confirmer=skill_confirmer,
                    diagnostic=identity_diagnostic,
                )
                decision = _confirmed_collaboration_mode(
                    args.goal,
                    args.mode,
                    confirmation_available=interactive_identity,
                    read_line=input,
                    console=error_console,
                )
                if decision is None:
                    return 1 if interactive_identity else 2
                if decision.mode == "single":
                    emit_collaboration_route(
                        audit_sink,
                        decision,
                        cast(CollaborationMode | None, args.mode),
                    )
                    outcome = run_once(
                        args.goal,
                        tier=args.tier,
                        model=args.model,
                        client_factory=runtime_client_factory,
                        console=console,
                        asker=make_console_asker(console) if args.interactive else None,
                        mcp=mcp,
                        confirmer=confirmer,
                        identity=identity,
                        container_image=args.container_image,
                        images=images,
                        stream=args.stream,
                        context_config=context_config,
                        memory_manager=memory_manager,
                        skills=skills,
                    )
                else:
                    if images:
                        raise ValueError("images are unavailable in collaboration mode")
                    required_candidate_files = _load_required_candidate_files_from_environment()
                    outcome = run_collaboration_once(
                        args.goal,
                        mode=decision.mode,
                        route_decision=decision,
                        tier=args.tier,
                        model=args.model,
                        planner_model=args.planner_model,
                        evaluator_model=args.evaluator_model,
                        max_rejections=args.max_rejections,
                        client_factory=runtime_client_factory,
                        allowed_root=allowed_root,
                        console=console,
                        plan_confirmer=(
                            _console_plan_confirmer(console)
                            if interactive_identity
                            else headless_plan_confirmer("deny")
                        ),
                        asker=make_console_asker(console) if args.interactive else None,
                        mcp=mcp,
                        confirmer=confirmer,
                        identity=identity,
                        container_image=args.container_image,
                        context_config=context_config,
                        memory_manager=memory_manager,
                        skills=skills,
                        required_candidate_files=required_candidate_files,
                        audit_sink=audit_sink,
                    )
            finally:
                if mcp is not None:
                    mcp.close()
            if isinstance(outcome, CollaborationReport):
                return 0 if outcome.status == "completed" else 1
            return 0 if outcome.status.solved else 1
        if args.command == "loop":
            context_config = _load_cli_context_config()
            runtime_registry = load_registry() if client_factory is build_real_client else None
            if runtime_registry is not None:
                try:
                    _validate_context_policy(args.model, runtime_registry, context_config)
                except ValueError as exc:
                    raise RegistryError(f"Invalid context configuration: {exc}") from exc
            runtime_client_factory = _client_factory_for_registry(
                runtime_registry if client_factory is build_real_client else None,
                client_factory,
            )
            mcp = build_mcp_manager()
            try:
                confirmer = make_console_confirmer(console) if interactive_identity else None
                identity = resolve_cli_identity(
                    no_identity=args.no_identity,
                    allowed_root=allowed_root,
                    confirmer=identity_confirmer,
                    diagnostic=identity_diagnostic,
                )
                memory_manager = _make_memory_manager(
                    allowed_root,
                    identity=identity,
                    no_memory=args.no_memory,
                    no_identity=args.no_identity,
                    diagnostic=identity_diagnostic,
                )
                skills = _load_skill_registry(
                    home=str(Path.home()),
                    allowed_root=allowed_root,
                    no_identity=args.no_identity,
                    confirmer=skill_confirmer,
                    diagnostic=identity_diagnostic,
                )
                report = run_loop_once(
                    args.goal,
                    tier=args.tier,
                    model=args.model,
                    client_factory=runtime_client_factory,
                    allowed_root=allowed_root,
                    console=console,
                    mcp=mcp,
                    confirmer=confirmer,
                    identity=identity,
                    container_image=args.container_image,
                    context_config=context_config,
                    memory_manager=memory_manager,
                    skills=skills,
                    token_budget=args.token_budget,
                    max_rounds=args.max_rounds,
                    wall_clock_seconds=args.wall_clock_seconds,
                    max_consecutive_failures=args.max_consecutive_failures,
                    resume=args.resume,
                    collaboration_mode=args.collaboration_mode,
                    planner_model=args.planner_model,
                    evaluator_model=args.evaluator_model,
                    max_rejections=args.max_rejections,
                    plan_confirmer=headless_plan_confirmer("deny"),
                    audit_sink=audit_sink,
                )
            finally:
                if mcp is not None:
                    mcp.close()
            return 0 if report.status == "completed" else 1
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
        context_config = _load_cli_context_config()
        runtime_registry = load_registry() if client_factory is build_real_client else None
        if runtime_registry is not None:
            try:
                _validate_context_policy(args.model, runtime_registry, context_config)
            except ValueError as exc:
                raise RegistryError(f"Invalid context configuration: {exc}") from exc
        repl(
            tier=args.tier,
            model=args.model,
            client_factory=client_factory,
            console=console,
            container_image=args.container_image,
            stream=args.stream,
            no_identity=args.no_identity,
            no_memory=args.no_memory,
            context_config=context_config,
            registry=runtime_registry,
            use_registry_snapshot=client_factory is build_real_client,
            audit_sink=audit_sink,
        )
        return 0
    except RegistryError as exc:
        error_console.print(f"[red]config error[/red]: {exc}")
        return 2
    except ContainerRuntimeError as exc:
        error_console.print(f"[red]container error[/red]: {exc}")
        return 2
    except CollaborationRoleConfigurationError:
        error_console.print("[red]collaboration role configuration failed[/red]")
        return 2
    except MCPStartupError as exc:
        error_console.print(f"[red]MCP startup error[/red]: {exc}")
        return 2
    except (LoopCheckpointError, ValueError):
        error_console.print("[red]Loop request rejected[/red]")
        return 2
    except IdentityConfigError as exc:
        error_console.print(f"[red]identity config error[/red]: {exc}")
        return 2
    except HttpStartupError:
        error_console.print("[red]HTTP startup error[/red]: service did not start")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
