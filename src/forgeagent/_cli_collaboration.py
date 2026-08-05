"""Collaboration-mode assembly for the command-line compatibility facade."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rich.console import Console

from .audit import AuditSink
from .client import ModelClient
from .collaboration import (
    CollaborationMode,
    CollaborationReport,
    CollaborationRole,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    ModeDecision,
    emit_collaboration_route,
    resolve_collaboration_mode,
)
from .context import ContextConfig
from .identity import ApprovedIdentity
from .mcp_manager import MCPManager
from .memory import MemoryManager
from .models import Message
from .skills import SkillRegistry
from .task import Task
from .tools import Asker, Confirmer, Tier

ClientFactory = Callable[[str], ModelClient]
ExecutionEvidenceRenderer = Callable[..., None]


@dataclass(frozen=True)
class CollaborationBindings:
    """Facade-owned dependencies whose current values must honor monkeypatching."""

    runner_type: type[CollaborationRunner]
    task_type: type[Task]
    validate_context_policy: Callable[[ModelClient, ContextConfig], None]
    render_execution_evidence: ExecutionEvidenceRenderer


def render_collaboration_report(
    report: CollaborationReport,
    console: Console,
    *,
    project_root: str | Path | None = None,
    render_execution_evidence: ExecutionEvidenceRenderer,
) -> None:
    console.print(f"collaboration id: {report.collaboration_id}")
    console.print(f"mode: {report.mode}")
    console.print(f"status: {report.status}")
    console.print(f"stop reason: {report.stop_reason or 'active'}")
    console.print(f"phase: {report.phase}")
    console.print(
        "counters: "
        f"plan={report.plan_item_count} passed={report.passed_item_count} "
        f"failed={report.failed_item_count} generator={report.generator_attempts} "
        f"evaluator={report.evaluator_attempts} rejections={report.rejections} "
        f"rounds={report.rounds} usage_available={report.usage_available}"
    )
    for item in report.evidence:
        console.print(f"evidence: {item}", markup=False)
    render_execution_evidence(
        report.execution_evidence,
        console,
        project_root=project_root,
    )


def console_plan_confirmer(
    console: Console, read_line: Callable[[str], str] = input
) -> Callable[[str], bool]:
    def confirm(summary: str) -> bool:
        console.print("[bold yellow]approve collaboration plan[/bold yellow]")
        console.print(summary, markup=False)
        try:
            answer = read_line("approve plan? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return confirm


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
    bindings: CollaborationBindings,
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
    session_messages: Sequence[Message] | None = None,
) -> CollaborationReport:
    if mode not in {"duo", "triad"}:
        raise ValueError("collaboration mode must be duo or triad")
    root = str(Path.cwd().resolve()) if allowed_root is None else allowed_root
    output = console or Console()
    audited_requested_mode = (
        cast(CollaborationMode, mode)
        if route_decision is None or route_decision.reason == "explicit"
        else None
    )
    emit_collaboration_route(
        audit_sink,
        route_decision or ModeDecision(mode=cast(CollaborationMode, mode), reason="explicit"),
        audited_requested_mode,
        task_id=task_id,
    )
    resolved_context = context_config or ContextConfig()
    role_models = {
        "planner": planner_model or model,
        "generator": model,
        "evaluator": evaluator_model or model,
    }

    for selected_model in dict.fromkeys(
        role_models[role]
        for role in (("planner",) if mode == "triad" else ()) + ("generator", "evaluator")
    ):
        probe = None
        try:
            probe = client_factory(selected_model)
            bindings.validate_context_policy(probe, resolved_context)
        except Exception as error:
            raise CollaborationRoleConfigurationError from error
        finally:
            close = getattr(probe, "close", None)
            if callable(close):
                close()

    outer_session_messages = None if session_messages is None else list(session_messages)

    def build_role_task(role: CollaborationRole, attempt: int, registry, system_prompt: str):
        del attempt
        client = None
        task = None
        try:
            client = client_factory(role_models[role])
            bindings.validate_context_policy(client, resolved_context)
            task = bindings.task_type(
                client,
                tier="restricted" if role == "evaluator" else tier,
                allowed_root=root,
                system_prompt=system_prompt,
                max_rounds=10,
                asker=asker if role == "generator" else None,
                mcp=mcp if role == "generator" else None,
                confirmer=confirmer if role == "generator" else None,
                identity=identity,
                container_image=container_image,
                context_config=resolved_context,
                memory_manager=memory_manager if role == "generator" else None,
                skills=skills if role == "generator" else None,
                tool_registry=registry,
                receipt_store=None,
                audit_sink=audit_sink,
                task_id=task_id,
            )
        except BaseException as error:
            if task is not None:
                task.close()
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            if not isinstance(error, Exception):
                raise
            raise CollaborationRoleConfigurationError from error

        class OwnedRoleTask:
            def __init__(self) -> None:
                self._closed = False

            def run(self, task_goal: str, *, cancel_event=None):
                run_kwargs = {"cancel_event": cancel_event}
                if outer_session_messages is not None:
                    run_kwargs["session_messages"] = list(outer_session_messages)
                return task.run(task_goal, **run_kwargs)

            def close(self) -> None:
                if self._closed:
                    return
                self._closed = True
                try:
                    task.close()
                finally:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()

        return OwnedRoleTask()

    runner = bindings.runner_type.create(
        mode=mode,
        goal=goal,
        allowed_root=root,
        role_task_builder=build_role_task,
        plan_confirmer=plan_confirmer,
        planner_model=role_models["planner"],
        generator_model=role_models["generator"],
        evaluator_model=role_models["evaluator"],
        evaluator_tier="restricted",
        max_rejections=max_rejections,
        execution_tier=tier,
        audit_sink=audit_sink,
        task_id=task_id,
        required_candidate_files=required_candidate_files,
    )
    try:
        report = runner.run(goal)
    finally:
        runner.close()
    render_collaboration_report(
        report,
        output,
        project_root=root,
        render_execution_evidence=bindings.render_execution_evidence,
    )
    return report


def confirmed_collaboration_mode(
    goal: str,
    requested_mode: str | None,
    *,
    confirmation_available: bool,
    read_line: Callable[[str], str],
    console: Console,
):
    del confirmation_available, read_line, console
    return resolve_collaboration_mode(goal, cast(CollaborationMode | None, requested_mode))
