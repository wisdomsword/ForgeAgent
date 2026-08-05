"""Interactive REPL runtime behind the command-line compatibility facade."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import yaml
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.text import Text

from .audit import AuditSink
from .client import ModelClient
from .collaboration import (
    CollaborationReport,
    emit_collaboration_route,
    headless_plan_confirmer,
    resolve_collaboration_mode,
)
from .context import ContextConfig, ResolvedFeedbackLimits, resolve_feedback_limits
from .identity import IdentityConfigError, IdentityConfirmer, IdentityTrustRequest
from .mcp_manager import MCPServerDiagnostic
from .model_registry import Registry, RegistryError
from .models import ImageItem, Message, Role, TokenUsage
from .protocol import (
    FileWriteArgs,
    MCPArgs,
    RequestFilesystemAccessArgs,
    WebFetchArgs,
)
from .secret_policy import REDACTED, is_secret_name, mask_secrets, sensitive_env_values
from .skills import SkillRegistry
from .tools import Tier

ClientFactory = Callable[[str], ModelClient]


def _project_collaboration_report(goal: str, report: CollaborationReport) -> list[Message]:
    """Return the bounded public pair that may cross a REPL task boundary."""
    lines = [
        "collaboration_result",
        f"mode={report.mode}",
        f"status={report.status}",
        f"stop_reason={report.stop_reason or 'active'}",
        f"phase={report.phase}",
        (
            "counters="
            f"plan={report.plan_item_count},passed={report.passed_item_count},"
            f"failed={report.failed_item_count},generator={report.generator_attempts},"
            f"evaluator={report.evaluator_attempts},rejections={report.rejections},"
            f"rounds={report.rounds},usage_available={report.usage_available}"
        ),
    ]
    secret_values = sensitive_env_values()
    for evidence in report.evidence:
        lines.append(f"evidence={mask_secrets(evidence[:160], secret_values)}")
    for record in report.execution_evidence.records[:16]:
        lines.append(f"execution={record.tool}:{record.status}")
    if report.execution_evidence.truncated:
        lines.append(f"execution_omitted={report.execution_evidence.omitted_count}")
    content = "\n".join(lines)
    return [
        Message(role=Role.USER, content=goal),
        Message(role=Role.ASSISTANT, content=content[:4096]),
    ]


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
    " _____ ___  ____   ____ _____      _    ____ _____ _   _ _____",
    "|  ___/ _ \\|  _ \\ / ___| ____|    / \\  / ___| ____| \\ | |_   _|",
    "| |_ | | | | |_) | |  _|  _|     / _ \\| |  _|  _| |  \\| | | |",
    "|  _|| |_| |  _ <| |_| | |___   / ___ \\ |_| | |___| |\\  | | |",
    "|_|   \\___/|_| \\_\\\\____|_____| /_/   \\_\\____|_____|_| \\_| |_|",
)


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


def confirmation_summary(args: BaseModel, secret_values: set[str]) -> str:
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
    if isinstance(args, RequestFilesystemAccessArgs):
        safe_path = mask_secrets(args.path, secret_values)
        return f"FullDiskAccess current task read/write: {safe_path}; sandbox restricted"
    return type(args).__name__


def confirmation_single_line(value: str) -> str:
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


def make_interactive_reader(
    command_usage: dict[str, str],
    *,
    prompt_session_type: Callable[..., Any] = PromptSession,
) -> Callable[[str], str]:
    """Build a terminal reader with slash completion and session-only history."""
    completer = WordCompleter(
        list(command_usage),
        meta_dict=command_usage,
        sentence=True,
        match_middle=False,
    )
    session = prompt_session_type(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True,
    )
    return session.prompt


def interactive_repl(console: Console, *, default_reader: bool) -> bool:
    return default_reader and console.is_terminal and sys.stdin.isatty()


def startup_mark_available(console: Console) -> bool:
    return (
        console.is_terminal
        and os.environ.get("TERM") != "dumb"
        and not any(name in os.environ for name in ("CI", "GITHUB_ACTIONS", "BUILD_NUMBER"))
    )


def startup_ui_available(console: Console) -> bool:
    return (
        startup_mark_available(console)
        and console.color_system is not None
        and not console.no_color
        and "NO_COLOR" not in os.environ
    )


class StartupDisplay:
    def __init__(
        self,
        console: Console,
        *,
        live_type: Callable[..., Any] = Live,
        monotonic: Callable[[], float] = time.monotonic,
        mark_available: Callable[[Console], bool] = startup_mark_available,
        ui_available: Callable[[Console], bool] = startup_ui_available,
    ) -> None:
        self._console = console
        self._live_type = live_type
        self._monotonic = monotonic
        self._mark_available = mark_available
        self._ui_available = ui_available
        self._stage: str | None = None
        self._live: Any | None = None
        self._static_mark_rendered = False

    def _logo_text(self) -> str:
        return (
            "ForgeAgent"
            if self._console.width < max(map(len, _STARTUP_LOGO))
            else "\n".join(_STARTUP_LOGO)
        )

    def logo_renderable(self) -> Text:
        colour = _STARTUP_COLOURS[int(self._monotonic() * 8) % len(_STARTUP_COLOURS)]
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
        if self._ui_available(self._console):
            self._start_live()
        elif self._mark_available(self._console) and not self._static_mark_rendered:
            self._console.print(self.static_logo_renderable())
            self._static_mark_rendered = True

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def pause(self) -> None:
        self.stop()

    def resume(self) -> None:
        if self._stage is not None:
            self._start_live()

    def stop(self, *, persist: bool = False) -> None:
        live = self._live
        if live is None:
            return
        try:
            live.stop()
            if persist and not self._static_mark_rendered:
                self._console.print(self.static_logo_renderable())
                self._static_mark_rendered = True
        finally:
            self._live = None

    def _start_live(self) -> None:
        if self._live is not None or not self._ui_available(self._console):
            return
        self._live = self._live_type(
            console=self._console,
            refresh_per_second=8,
            transient=True,
            get_renderable=self.renderable,
        )
        self._live.start()


@contextmanager
def startup_confirmation(display: StartupDisplay):
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


def with_startup_display_pause(
    confirmer: IdentityConfirmer | None, display: StartupDisplay
) -> IdentityConfirmer | None:
    if confirmer is None:
        return None

    def confirm(request: IdentityTrustRequest) -> bool:
        with startup_confirmation(display):
            return confirmer(request)

    return confirm


def render_startup_summary(
    console: Console,
    *,
    model: str,
    tier: Tier,
    root: str,
    diagnostics: Sequence[MCPServerDiagnostic],
    feedback_limits: ResolvedFeedbackLimits | None = None,
) -> None:
    enabled = [item for item in diagnostics if item.enabled]
    available = sum(item.status == "available" for item in enabled)
    summary_fields = ["Ready", f"model {model}", f"sandbox {tier}", f"project {root}"]
    if enabled:
        summary_fields.insert(1, f"MCP {available}/{len(enabled)}")
    if feedback_limits is not None:
        summary_fields.append(
            f"feedback round {feedback_limits.effective_round_feedback_limit} / "
            f"tool {feedback_limits.effective_tool_result_limit}"
        )
    console.print(Text(" | ".join(summary_fields)), soft_wrap=True)
    if feedback_limits is not None and (
        feedback_limits.round_configured_below_adaptive
        or feedback_limits.tool_configured_below_adaptive
    ):
        fields: list[str] = []
        if feedback_limits.round_configured_below_adaptive:
            fields.append(
                f"round configured {feedback_limits.configured_round_feedback_limit} "
                f"< adaptive {feedback_limits.adaptive_round_feedback_limit}"
            )
        if feedback_limits.tool_configured_below_adaptive:
            fields.append(
                f"tool configured {feedback_limits.configured_tool_result_limit} "
                f"< adaptive {feedback_limits.adaptive_tool_result_limit}"
            )
        console.print(Text("feedback limit warning | " + " | ".join(fields)), soft_wrap=True)
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


def resolve_repl_feedback_limits(
    model: str,
    registry: Registry | None,
    context_config: ContextConfig,
    client_factory: ClientFactory,
    use_registry_snapshot: bool,
    validate_context_policy: Callable[[str, Registry, ContextConfig], ResolvedFeedbackLimits],
) -> ResolvedFeedbackLimits | None:
    """Resolve limits for interactive display without changing task execution state."""
    if use_registry_snapshot and registry is not None:
        return validate_context_policy(model, registry, context_config)
    probe = client_factory(model)
    try:
        return resolve_feedback_limits(probe.capability, None, context_config)
    finally:
        close = getattr(probe, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class ReplBindings:
    """Facade-owned collaborators resolved for each REPL invocation."""

    build_real_client: Callable[..., ModelClient]
    build_mcp_manager: Callable[[], Any]
    confirmed_collaboration_mode: Callable[..., Any]
    console_plan_confirmer: Callable[..., Callable[[str], bool]]
    handle_help_command: Callable[..., None]
    handle_image_command: Callable[..., tuple[list[ImageItem] | None, str | None]]
    handle_mcp_slash: Callable[..., None]
    handle_memory_command: Callable[..., None]
    handle_model_command: Callable[..., str]
    handle_remember_command: Callable[..., None]
    handle_search_command: Callable[..., None]
    interactive_repl: Callable[..., bool]
    load_context_config: Callable[[], ContextConfig]
    load_skill_registry: Callable[..., SkillRegistry]
    make_console_asker: Callable[..., Any]
    make_console_confirmer: Callable[..., Any]
    make_console_identity_confirmer: Callable[..., Any]
    make_console_identity_diagnostic: Callable[..., Any]
    make_console_skill_confirmer: Callable[..., Any]
    make_interactive_reader: Callable[[], Callable[[str], str]]
    make_memory_manager: Callable[..., Any]
    print_command_menu: Callable[[Console], None]
    reload_registry: Callable[[], Registry]
    render_startup_summary: Callable[..., None]
    resolve_cli_identity: Callable[..., Any]
    run_collaboration_once: Callable[..., Any]
    run_once: Callable[..., Any]
    resolve_repl_feedback_limits: Callable[..., ResolvedFeedbackLimits | None]
    startup_display_type: Callable[[Console], Any]
    validate_context_policy: Callable[[str, Registry, ContextConfig], ResolvedFeedbackLimits]
    with_startup_display_pause: Callable[..., Any]


def repl(
    *,
    tier: Tier,
    model: str,
    client_factory: ClientFactory,
    bindings: ReplBindings,
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
    """Run the interactive goal loop with facade-provided collaborators."""
    console = console or Console()
    default_reader = read_line is None
    if default_reader:
        read_line = (
            bindings.make_interactive_reader()
            if console.is_terminal and sys.stdin.isatty()
            else input
        )
    interactive = bindings.interactive_repl(console, default_reader=default_reader)
    display = bindings.startup_display_type(console)
    current_context = context_config or ContextConfig()
    current_registry = registry
    if use_registry_snapshot is None:
        use_registry_snapshot = client_factory is bindings.build_real_client
    if use_registry_snapshot and current_registry is not None:
        try:
            bindings.validate_context_policy(model, current_registry, current_context)
        except ValueError as exc:
            raise RegistryError(f"Invalid context configuration: {exc}") from exc

    feedback_limits: ResolvedFeedbackLimits | None = None

    def task_client_factory(selected_model: str) -> ModelClient:
        if use_registry_snapshot and current_registry is not None:
            return bindings.build_real_client(selected_model, registry=current_registry)
        return client_factory(selected_model)

    mcp = None
    try:
        if interactive:
            display.start("Loading identity")
        asker = bindings.make_console_asker(console, read_line)
        if confirmation_available is None:
            confirmation_available = console.is_terminal and sys.stdin.isatty()
        confirmer = (
            bindings.make_console_confirmer(console, read_line) if confirmation_available else None
        )
        identity_confirmer = (
            bindings.make_console_identity_confirmer(console, read_line)
            if confirmation_available
            else None
        )
        identity_confirmer = bindings.with_startup_display_pause(identity_confirmer, display)
        allowed_root = str(Path.cwd().resolve())
        identity_diagnostic = bindings.make_console_identity_diagnostic(console)
        skill_confirmer = (
            bindings.make_console_skill_confirmer(console, read_line)
            if confirmation_available
            else None
        )
        skill_confirmer = bindings.with_startup_display_pause(skill_confirmer, display)
        identity = bindings.resolve_cli_identity(
            no_identity=no_identity,
            allowed_root=allowed_root,
            confirmer=identity_confirmer,
            diagnostic=identity_diagnostic,
        )
        display.set_stage("Loading memory")
        memory_manager = bindings.make_memory_manager(
            allowed_root,
            identity=identity,
            no_memory=no_memory,
            no_identity=no_identity,
            diagnostic=identity_diagnostic,
        )
        display.set_stage("Loading skills")
        current_skills = skills or bindings.load_skill_registry(
            home=str(Path.home()),
            allowed_root=allowed_root,
            no_identity=no_identity,
            confirmer=skill_confirmer,
            diagnostic=identity_diagnostic,
        )
        display.set_stage("Connecting MCP services")
        mcp = bindings.build_mcp_manager()
        display.stop(persist=True)
        if interactive:
            feedback_limits = bindings.resolve_repl_feedback_limits(
                model,
                current_registry,
                current_context,
                client_factory,
                use_registry_snapshot,
                bindings.validate_context_policy,
            )
            bindings.render_startup_summary(
                console,
                model=model,
                tier=tier,
                root=allowed_root,
                diagnostics=mcp.diagnostics() if mcp is not None else (),
                feedback_limits=feedback_limits,
            )
        usage_total = TokenUsage()
        session_messages: list[Message] = []
        staged_images: list[ImageItem] | None = None

        def run_single(goal: str, *, images: list[ImageItem] | None = None) -> Any:
            nonlocal session_messages
            outcome = bindings.run_once(
                goal,
                tier=tier,
                model=model,
                client_factory=task_client_factory,
                console=console,
                asker=asker,
                mcp=mcp,
                confirmer=confirmer,
                identity=identity,
                container_image=container_image,
                usage_total=usage_total,
                images=images,
                session_messages=list(session_messages),
                stream=stream,
                context_config=current_context,
                memory_manager=memory_manager,
                skills=current_skills,
                audit_sink=audit_sink,
            )
            session_messages = list(getattr(outcome, "session_messages", ()))
            return outcome

        def run_collaboration(goal: str, decision: Any) -> Any:
            nonlocal session_messages
            report = bindings.run_collaboration_once(
                goal,
                mode=decision.mode,
                route_decision=decision,
                tier=tier,
                model=model,
                planner_model=None,
                evaluator_model=None,
                max_rejections=2,
                client_factory=task_client_factory,
                allowed_root=allowed_root,
                console=console,
                plan_confirmer=(
                    bindings.console_plan_confirmer(console, read_line)
                    if confirmation_available
                    else headless_plan_confirmer("deny")
                ),
                asker=asker,
                mcp=mcp,
                confirmer=confirmer,
                identity=identity,
                container_image=container_image,
                context_config=current_context,
                memory_manager=memory_manager,
                skills=current_skills,
                audit_sink=audit_sink,
                session_messages=list(session_messages),
            )
            session_messages.extend(_project_collaboration_report(goal, report))
            return report

        while True:
            try:
                prompt = "forge> " if interactive else ""
                goal = read_line(prompt).strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                console.print()
                break
            if not goal or goal in {"quit", "exit"}:
                break
            if goal == "/":
                bindings.print_command_menu(console)
                continue
            if goal in {"/new", "/reset"}:
                session_messages.clear()
                staged_images = None
                console.print("[green]session reset[/green]")
                continue
            if goal == "/model" or goal.startswith("/model "):
                previous_model = model
                candidate_model = bindings.handle_model_command(
                    goal,
                    model,
                    console,
                    current_registry,
                    current_context,
                    use_registry_snapshot or current_registry is None,
                )
                if candidate_model != previous_model:
                    candidate_limits = feedback_limits
                    if interactive:
                        try:
                            candidate_limits = bindings.resolve_repl_feedback_limits(
                                candidate_model,
                                current_registry,
                                current_context,
                                client_factory,
                                use_registry_snapshot,
                                bindings.validate_context_policy,
                            )
                        except (RegistryError, ValueError) as exc:
                            console.print(
                                "[red]model switch failed[/red]: invalid context configuration: "
                                f"{exc}"
                            )
                            continue
                    model = candidate_model
                    feedback_limits = candidate_limits
                    if interactive:
                        bindings.render_startup_summary(
                            console,
                            model=model,
                            tier=tier,
                            root=allowed_root,
                            diagnostics=mcp.diagnostics() if mcp is not None else (),
                            feedback_limits=feedback_limits,
                        )
                continue
            if goal == "/search" or goal.startswith("/search "):
                bindings.handle_search_command(goal, console)
                continue
            if goal == "/image" or goal.startswith("/image "):
                images, inline_goal = bindings.handle_image_command(goal, console)
                if images is None:
                    continue
                if inline_goal is None:
                    staged_images = images
                    continue
                goal = inline_goal
                staged_images = None
                run_single(goal, images=images)
                continue
            if goal == "/mcp" or goal.startswith("/mcp "):
                bindings.handle_mcp_slash(goal, mcp, console)
                continue
            if goal == "/memory":
                bindings.handle_memory_command(memory_manager, console)
                continue
            if goal == "/remember" or goal.startswith("/remember "):
                bindings.handle_remember_command(goal, memory_manager, console)
                continue
            if goal == "/reload":
                try:
                    candidate_registry = bindings.reload_registry()
                    candidate_context = bindings.load_context_config()
                    if use_registry_snapshot and not interactive:
                        bindings.validate_context_policy(
                            model, candidate_registry, candidate_context
                        )
                    candidate_limits = feedback_limits
                    if interactive:
                        candidate_limits = bindings.resolve_repl_feedback_limits(
                            model,
                            candidate_registry,
                            candidate_context,
                            client_factory,
                            use_registry_snapshot,
                            bindings.validate_context_policy,
                        )
                    candidate_identity = bindings.resolve_cli_identity(
                        no_identity=no_identity,
                        allowed_root=allowed_root,
                        confirmer=identity_confirmer,
                        diagnostic=identity_diagnostic,
                    )
                    candidate_memory_manager = bindings.make_memory_manager(
                        allowed_root,
                        identity=candidate_identity,
                        no_memory=no_memory,
                        no_identity=no_identity,
                        diagnostic=identity_diagnostic,
                    )
                    candidate_memory_manager.copy_session_from(memory_manager)
                    candidate_skills = bindings.load_skill_registry(
                        home=str(Path.home()),
                        allowed_root=allowed_root,
                        no_identity=no_identity,
                        confirmer=skill_confirmer,
                        diagnostic=identity_diagnostic,
                    )
                except (
                    IdentityConfigError,
                    OSError,
                    RegistryError,
                    ValueError,
                    yaml.YAMLError,
                ) as exc:
                    console.print(f"[red]reload failed[/red]: {exc}")
                    continue
                current_registry = candidate_registry
                current_context = candidate_context
                identity = candidate_identity
                memory_manager = candidate_memory_manager
                current_skills = candidate_skills
                feedback_limits = candidate_limits
                console.print(f"[green]reloaded[/green]: {len(current_registry.models)} models")
                if not no_identity:
                    console.print("[green]identity reloaded[/green]")
                if interactive:
                    bindings.render_startup_summary(
                        console,
                        model=model,
                        tier=tier,
                        root=allowed_root,
                        diagnostics=mcp.diagnostics() if mcp is not None else (),
                        feedback_limits=feedback_limits,
                    )
                continue
            if goal == "/help" or goal.startswith("/help "):
                bindings.handle_help_command(goal, console)
                continue
            if (
                goal == "/single"
                or goal.startswith("/single ")
                or goal == "/duo"
                or goal.startswith("/duo ")
                or goal == "/triad"
                or goal.startswith("/triad ")
            ):
                command, _, collaboration_goal = goal.partition(" ")
                if not collaboration_goal.strip():
                    console.print(f"usage: {command} <goal>", style="dim", markup=False)
                    continue
                collaboration_goal = collaboration_goal.strip()
                decision = bindings.confirmed_collaboration_mode(
                    collaboration_goal,
                    command[1:],
                    confirmation_available=confirmation_available,
                    read_line=read_line,
                    console=console,
                )
                if decision is None:
                    continue
                if decision.mode == "single":
                    emit_collaboration_route(audit_sink, decision, "single")
                    run_single(collaboration_goal)
                    continue
                run_collaboration(collaboration_goal, decision)
                continue
            if goal.startswith("/"):
                console.print(f"[red]unknown command[/red] {goal!r}")
                bindings.print_command_menu(console)
                continue
            decision = resolve_collaboration_mode(goal, None)
            if decision.mode == "single":
                emit_collaboration_route(audit_sink, decision, None)
                run_single(goal, images=staged_images)
            else:
                run_collaboration(goal, decision)
            staged_images = None
    finally:
        display.stop()
        if mcp is not None:
            mcp.close()
