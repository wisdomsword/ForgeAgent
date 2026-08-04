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

import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

from prompt_toolkit import PromptSession
from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.text import Text

from . import _cli_collaboration, _cli_http, _cli_parser, _cli_repl
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
)
from .context import ContextConfig, load_context_config
from .execution_evidence import (
    ExecutionEvidence,
    public_execution_evidence,
    resolve_local_artifact_path,
)
from .executor import ContainerRuntimeError
from .external_actions import ExternalActionReceiptStore, ReceiptError
from .headless import HeadlessConfirmer
from .http_action_approvals import HttpActionApprovalStore
from .http_task_service import TaskService
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
from .mcp_manager import MCPManager, load_mcp_config
from .memory import MemoryManager
from .model_registry import (
    Registry,
    RegistryError,
    list_models,
    load_registry,
    reload_registry,
)
from .models import ImageItem, StreamEventKind, TokenUsage
from .protocol import MemoryCandidate, SurveyArgs
from .secret_policy import mask_secrets, sensitive_env_values
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


HttpStartupError = _cli_http.HttpStartupError
_HttpRuntimeSettings = _cli_http.HttpRuntimeSettings


# Injectable client factory: (model) -> ModelClient. Default builds a real client from
# the environment; tests pass a factory returning a MockClient.
ClientFactory = Callable[[str], ModelClient]


def build_real_client(
    model: str,
    env: dict[str, str] | None = None,
    *,
    registry: Registry | None = None,
) -> ModelClient:
    """Build a client using the facade's current registry binding."""
    resolved_registry = registry if registry is not None else load_registry()
    return _cli_http.build_real_client(model, env, registry=resolved_registry)


_validate_context_policy = _cli_http.validate_context_policy
_validate_client_context_policy = _cli_http.validate_client_context_policy


def _client_factory_for_registry(
    registry: Registry | None, fallback: ClientFactory
) -> ClientFactory:
    return _cli_http.client_factory_for_registry(registry, fallback, build_real_client)


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


def render_outcome(
    outcome: TaskOutcome, console: Console, *, plain_body_already_rendered: bool = False
) -> None:
    """Print task status, tool results, and any plain body not already streamed."""
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
        if not plain_body_already_rendered and not rnd.outcomes and rnd.body:
            # The model answered in plain text without calling Exec — still show it,
            # since it's the only place the actual answer lives.
            console.print(rnd.body)
    render_execution_evidence(outcome.execution_evidence, console, project_root=Path.cwd())
    for result in outcome.memory_results:
        colour = "green" if result.status in {"accepted", "replaced"} else "yellow"
        detail = f" ({result.reason})" if result.reason else ""
        console.print(
            f"[{colour}]memory {result.status}[/{colour}]: {result.scope}/{result.key}{detail}"
        )


def render_execution_evidence(
    evidence: ExecutionEvidence,
    console: Console,
    *,
    project_root: str | Path | None = None,
) -> None:
    """Render one bounded terminal summary of the task's execution attempts."""
    projected = public_execution_evidence(
        evidence,
        secret_values=sensitive_env_values(),
        include_local_paths=True,
    )
    if not projected.records:
        if projected.omitted_count:
            console.print(f"execution evidence: omitted={projected.omitted_count}", markup=False)
        else:
            console.print("execution evidence: no tools or programs executed", markup=False)
        return

    console.print("execution evidence:", markup=False)
    for record in projected.records:
        console.print(f"    {record.sequence} {record.tool} {record.status}", markup=False)
        if record.block is not None:
            console.print(f"      block: {record.block}", markup=False)
        if record.iteration is not None or record.role is not None or record.attempt is not None:
            origin = f"iteration={record.iteration} role={record.role} attempt={record.attempt}"
            console.print(f"      origin: {origin}", markup=False)
        if record.artifact is None:
            continue
        path = record.artifact.local_path
        if path is None and project_root is not None:
            path = resolve_local_artifact_path(project_root, record.artifact.reference)
        console.print(
            f"      program: {path}" if path is not None else "      program unavailable",
            markup=False,
        )
    if projected.omitted_count:
        console.print(f"    omitted={projected.omitted_count}", markup=False)


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


def _confirmation_summary(args: BaseModel) -> str:
    return _cli_repl.confirmation_summary(args, sensitive_env_values())


_confirmation_single_line = _cli_repl.confirmation_single_line


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
    audit_sink: AuditSink | None = None,
    task_id: str | None = None,
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
    task: Task | None = None
    live: Live | None = None
    try:
        resolved_context_config = context_config or ContextConfig()
        try:
            _validate_client_context_policy(client, resolved_context_config)
        except ValueError as exc:
            raise RegistryError(f"Invalid context configuration: {exc}") from exc

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
                audit_sink=audit_sink,
                task_id=task_id or uuid4().hex,
            )
        except ValueError as exc:
            raise RegistryError(f"Invalid context configuration: {exc}") from exc

        if live is not None:
            with live:
                outcome = task.run(goal, images=images)
        else:
            outcome = task.run(goal, images=images)
    finally:
        try:
            if task is not None:
                task.close()
        finally:
            client.close()
    render_outcome(outcome, console, plain_body_already_rendered=live is not None)
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
    outcome = manager.apply(candidate, source="user_command")
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
    return _cli_repl.make_interactive_reader(
        _SLASH_COMMAND_USAGE,
        prompt_session_type=PromptSession,
    )


_interactive_repl = _cli_repl.interactive_repl
_startup_mark_available = _cli_repl.startup_mark_available
_startup_ui_available = _cli_repl.startup_ui_available
_startup_confirmation = _cli_repl.startup_confirmation
_with_startup_display_pause = _cli_repl.with_startup_display_pause
_render_startup_summary = _cli_repl.render_startup_summary


class _StartupDisplay(_cli_repl.StartupDisplay):
    def __init__(self, console: Console) -> None:
        super().__init__(
            console,
            live_type=Live,
            monotonic=lambda: time.monotonic(),
            mark_available=_startup_mark_available,
            ui_available=_startup_ui_available,
        )


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


# Deterministic live goals with no file I/O, safe for the restricted tier.
SMOKE_GOALS = [
    "Compute the sum of the integers 10, 20 and 30 and print the result.",
    "Print the 6th Fibonacci number.",
]

# Fable and OpenAI-compatible models remain opt-in because they require separate access.
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
        try:
            console.print(f"[bold]smoke[/bold] model={model} tier={tier}")
            for goal in SMOKE_GOALS:
                task = Task(client, tier=tier)
                try:
                    outcome = task.run(goal)
                finally:
                    task.close()
                ok = outcome.status.solved
                all_ok = all_ok and ok
                marker = (
                    "[green]PASS[/green]" if ok else f"[red]FAIL[/red] ({outcome.status.reason})"
                )
                console.print(f"  {marker}  {goal}")
        finally:
            client.close()
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
    return _cli_parser.load_cli_context_config(
        os.environ.get(_CONTEXT_CONFIG_ENVIRONMENT),
        context_loader=load_context_config,
        json_loader=json.loads,
    )


def _load_required_candidate_files_from_environment() -> tuple[str, ...]:
    return _cli_parser.load_required_candidate_files(
        os.environ.get(_CANDIDATE_FILES_ENVIRONMENT),
        json_loader=json.loads,
        normalizer=normalize_required_candidate_files,
    )


_load_http_runtime_settings = _cli_http.load_http_runtime_settings
_serve_has_cli_policy_override = _cli_http.serve_has_cli_policy_override


_run_owned_http_server = _cli_http.run_owned_http_server


def serve_http(
    config_path: str | Path,
    *,
    client_factory: ClientFactory,
    console: Console,
    once: bool = False,
) -> None:
    """Assemble and own the opt-in local HTTP task service."""
    return _cli_http.serve_http(
        config_path,
        client_factory=client_factory,
        real_client_factory=build_real_client,
        bindings=_cli_http.HttpBindings(
            task_service_type=TaskService,
            task_type=Task,
            loop_runner_type=LoopRunner,
            collaboration_runner_type=CollaborationRunner,
            collaboration_store_type=CollaborationStore,
            approval_store_type=HttpActionApprovalStore,
            receipt_store_type=ExternalActionReceiptStore,
            audit_sink_type=JsonlAuditSink,
            headless_confirmer_type=HeadlessConfirmer,
            build_mcp_manager=build_mcp_manager,
            load_registry=load_registry,
            validate_context_policy=_validate_context_policy,
            validate_client_context_policy=_validate_client_context_policy,
            resolve_cli_identity=resolve_cli_identity,
            make_console_identity_diagnostic=make_console_identity_diagnostic,
            load_skill_registry=_load_skill_registry,
            make_memory_manager=_make_memory_manager,
            loop_system_prompt=_loop_system_prompt,
            mcp_startup_error_type=MCPStartupError,
        ),
        console=console,
        once=once,
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
                        audit_sink=audit_sink,
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
