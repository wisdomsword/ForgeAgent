"""HTTP service and model-client assembly for the CLI compatibility facade."""

from __future__ import annotations

import logging
import math
import signal
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from rich.console import Console

from . import http_server
from ._cli_parser import DEFAULT_MODEL
from .anthropic_client import AnthropicClient
from .audit import JsonlAuditSink
from .client import ModelClient
from .collaboration import (
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    CollaborationStore,
    headless_plan_confirmer,
    resolve_collaboration_mode,
)
from .context import ContextConfig, SlidingWindowContextPolicy
from .external_actions import ExternalActionReceiptStore
from .headless import HeadlessConfirmer
from .http_config import HttpServiceConfig
from .http_task_service import TaskRecord, TaskService
from .loop import LoopBudgets, LoopCheckpointError, LoopRunner
from .mcp_manager import MCPManager
from .model_registry import Registry, get_capability, load_registry, resolve_model
from .openai_compatible_client import OpenAICompatibleClient
from .task import Task
from .tools import Tier

logger = logging.getLogger(__name__)
ClientFactory = Callable[[str], ModelClient]


class HttpStartupError(RuntimeError):
    """The opt-in HTTP service could not be configured, bound, or started."""


@dataclass(frozen=True)
class HttpRuntimeSettings:
    service: HttpServiceConfig
    model: str
    tier: Tier
    allowed_root: str
    no_identity: bool
    no_memory: bool
    container_image: str | None
    shutdown_timeout_seconds: float


@dataclass(frozen=True)
class HttpBindings:
    """Facade-owned dependencies resolved for each HTTP service invocation."""

    task_service_type: type[TaskService]
    task_type: type[Task]
    loop_runner_type: type[LoopRunner]
    collaboration_runner_type: type[CollaborationRunner]
    collaboration_store_type: type[CollaborationStore]
    receipt_store_type: type[ExternalActionReceiptStore]
    audit_sink_type: type[JsonlAuditSink]
    headless_confirmer_type: type[HeadlessConfirmer]
    build_mcp_manager: Callable[[], MCPManager | None]
    load_registry: Callable[[], Registry]
    validate_context_policy: Callable[[str, Registry, ContextConfig], None]
    validate_client_context_policy: Callable[[ModelClient, ContextConfig], None]
    resolve_cli_identity: Callable[..., Any]
    make_console_identity_diagnostic: Callable[..., Any]
    load_skill_registry: Callable[..., Any]
    make_memory_manager: Callable[..., Any]
    loop_system_prompt: Callable[..., str]
    mcp_startup_error_type: type[Exception]


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
        *(item.name for item in fields(HttpServiceConfig) if item.name != "context_config"),
        "context",
    }
)
SERVE_FORBIDDEN_CLI_OPTIONS = (
    "--tier",
    "--container-image",
    "--model",
    "--stream",
    "--no-identity",
    "--no-memory",
)

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
    """Assemble a real model client from the declared registry route."""
    resolved = resolve_model(model, registry if registry is not None else load_registry(), env=env)
    client_class = _CLIENT_CLASSES[resolved.capability.client_kind]
    return client_class(
        capability=resolved.capability,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
    )


def client_factory_for_registry(
    registry: Registry | None,
    fallback: ClientFactory,
    real_client_factory: Callable[..., ModelClient] = build_real_client,
) -> ClientFactory:
    if registry is None:
        return fallback

    def build_from_snapshot(model: str) -> ModelClient:
        return real_client_factory(model, registry=registry)

    return build_from_snapshot


def validate_context_policy(model: str, registry: Registry, context_config: ContextConfig) -> None:
    """Resolve the selected model and its context limits before publishing a snapshot."""
    SlidingWindowContextPolicy(get_capability(model, registry), None, context_config)


def validate_client_context_policy(client: ModelClient, context_config: ContextConfig) -> None:
    """Validate an injected client's actual capability before constructing its Task."""
    SlidingWindowContextPolicy(client.capability, None, context_config)


def _http_client_factory_with_validated_context(
    model: str,
    client_factory: ClientFactory,
    context_config: ContextConfig,
    *,
    bindings: HttpBindings,
    real_client_factory: Callable[..., ModelClient],
) -> ClientFactory:
    if client_factory is real_client_factory:
        registry = bindings.load_registry()
        bindings.validate_context_policy(model, registry, context_config)
        return client_factory_for_registry(registry, client_factory, real_client_factory)

    probe = client_factory(model)
    try:
        bindings.validate_client_context_policy(probe, context_config)
    finally:
        close = getattr(probe, "close", None)
        if callable(close):
            close()
    return client_factory


def load_http_runtime_settings(path: str | Path) -> HttpRuntimeSettings:
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

    return HttpRuntimeSettings(
        service=service,
        model=model,
        tier=tier,
        allowed_root=str(allowed_root_path),
        no_identity=no_identity,
        no_memory=no_memory,
        container_image=container_image,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def serve_has_cli_policy_override(argv: list[str]) -> bool:
    return any(
        argument == option or argument.startswith(f"{option}=")
        for argument in argv
        for option in SERVE_FORBIDDEN_CLI_OPTIONS
    )


def run_owned_http_server(
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
    real_client_factory: Callable[..., ModelClient],
    bindings: HttpBindings,
    console: Console,
    once: bool = False,
) -> None:
    """Assemble and own the opt-in local HTTP task service."""
    settings = load_http_runtime_settings(config_path)
    try:
        task_client_factory = _http_client_factory_with_validated_context(
            settings.model,
            client_factory,
            settings.service.context_config,
            bindings=bindings,
            real_client_factory=real_client_factory,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise HttpStartupError("HTTP service context policy is invalid.") from error
    audit_path = settings.service.audit_path.expanduser()
    try:
        audit_sink = bindings.audit_sink_type(
            audit_path,
            max_bytes=settings.service.audit_max_bytes,
            retention_files=settings.service.audit_retention_files,
        )
        headless_confirmer = bindings.headless_confirmer_type(
            settings.service.allowlist,
            audit=audit_sink,
            root=settings.allowed_root,
        )
    except (OSError, ValueError) as error:
        raise HttpStartupError("HTTP audit or allowlist configuration is invalid.") from error

    identity_diagnostic = bindings.make_console_identity_diagnostic(console)
    identity = bindings.resolve_cli_identity(
        no_identity=settings.no_identity,
        allowed_root=settings.allowed_root,
        confirmer=None,
        diagnostic=identity_diagnostic,
    )
    skills = bindings.load_skill_registry(
        home=str(Path.home()),
        allowed_root=settings.allowed_root,
        no_identity=settings.no_identity,
        confirmer=None,
        diagnostic=bindings.make_console_identity_diagnostic(console),
    )
    mcp: MCPManager | None = None
    service: TaskService | None = None
    try:
        mcp = bindings.build_mcp_manager()
        receipt_store = bindings.receipt_store_type(settings.allowed_root, audit_sink=audit_sink)

        def task_factory(record: TaskRecord) -> Task | LoopRunner | CollaborationRunner:
            options = getattr(record, "options", {})
            memory_manager = bindings.make_memory_manager(
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
                    task = bindings.task_type(
                        client,
                        tier=settings.tier,
                        allowed_root=settings.allowed_root,
                        system_prompt=bindings.loop_system_prompt(identity, memory_manager, suffix),
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
                            task = bindings.task_type(
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
                        store = bindings.collaboration_store_type(
                            settings.allowed_root,
                            audit_sink=audit_sink,
                            task_id=record.task_id,
                            loop_id=loop_runner._checkpoint.loop_id,
                        )
                        state = store.load(collaboration_id)
                        collaboration = bindings.collaboration_runner_type(
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
                        collaboration = bindings.collaboration_runner_type.create(
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
                    loop_runner = bindings.loop_runner_type.resume(loop_id=resume_loop_id, **common)
                    return loop_runner
                budgets = LoopBudgets(
                    token_budget=options["token_budget"],
                    max_rounds=options["max_rounds"],
                    wall_clock_seconds=options["wall_clock_seconds"],
                    max_consecutive_failures=options["max_consecutive_failures"],
                )
                loop_runner = bindings.loop_runner_type.create(
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
                        task = bindings.task_type(
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

                return bindings.collaboration_runner_type.create(
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
            return bindings.task_type(
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

        service = bindings.task_service_type(
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
        if isinstance(error, (bindings.mcp_startup_error_type, HttpStartupError)):
            raise
        raise HttpStartupError("HTTP service could not start.") from error

    run_owned_http_server(
        server,
        service,
        shutdown_timeout=settings.shutdown_timeout_seconds,
        once=once,
        on_started=lambda: console.print(
            f"[green]serving[/green] on {settings.service.bind_host}:{server.server_address[1]}"
        ),
    )
