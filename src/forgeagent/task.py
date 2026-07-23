"""The Task loop: assemble the prompt, run a Step, report a structured outcome.

See ACTION_PLAN §二 (borrow agent's task.py, simplified). A Task builds the initial
conversation (system prompt + user goal), owns the runtime and executor backend so
cross-block state persists for the task's lifetime, drives one Step, and derives a
TaskOutcome from the rounds (completed / refused / needs-info / failed / exhausted).

The system prompt combines the approved runtime identity with the fixed protocol.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from .audit import AuditSink
from .client import ModelClient
from .context import ContextConfig, ContextPolicy, SlidingWindowContextPolicy
from .executor import ContainerBackend, ExecutorBackend, RestrictedBackend, TrustedBackend
from .identity import ApprovedIdentity, compose_system_prompt
from .mcp_manager import MCPManager
from .memory import MemoryManager, MemoryResult
from .models import GenerationParams, ImageItem, Message, Role, StreamEventKind, TextItem
from .runtime import Runtime
from .step import RoundResult, Step, Termination
from .tools import Asker, Confirmer, Tier


def _backend_for_tier(
    tier: Tier, *, allowed_root: str | None = None, container_image: str | None = None
) -> ExecutorBackend:
    """Map a sandbox tier to its executor backend (B2). `restricted` is the default.

    `allowed_root=None` defers to each backend's own default (cwd, resolved) — callers
    that need the exact resolved value (to also hand it to ToolContext, §3.7) should
    resolve it themselves first and pass it through, as Task.__init__ does.
    """
    if tier == "trusted":
        return TrustedBackend()
    if tier == "container":
        return ContainerBackend(
            allowed_root=allowed_root, image=container_image or "python:3.11-slim"
        )
    return RestrictedBackend(allowed_root=allowed_root)


class TaskStatus(BaseModel):
    """Terminal status of a task run.

    `completed` is a verified, model-declared completion. `solved` is broader: it also
    covers an unverified prose answer (Termination.ANSWERED_IN_PROSE), so callers and
    the golden evaluator can score "task solved, format irregular" apart from "task not
    solved" without conflating either with "answer factually wrong" (which is judged
    separately, on the answer content — not here).
    """

    completed: bool
    # A Termination value (or "client_error:<kind>"); "no_rounds"/"unknown" as fallbacks.
    reason: str
    detail: str | None = None

    @property
    def solved(self) -> bool:
        """The task reached a solved state — a verified completion or a prose answer."""
        return self.reason in (Termination.COMPLETED, Termination.ANSWERED_IN_PROSE)


class TaskOutcome(BaseModel):
    """Everything a caller needs about a finished task run."""

    status: TaskStatus
    rounds: list[RoundResult]
    memory_results: list[MemoryResult] = Field(default_factory=list)


class Task:
    """Runs a single user goal to completion (or a terminal non-completion)."""

    def __init__(
        self,
        client: ModelClient,
        *,
        tier: Tier = "restricted",
        backend: ExecutorBackend | None = None,
        allowed_root: str | None = None,
        system_prompt: str | None = None,
        identity: ApprovedIdentity | None = None,
        max_rounds: int = 10,
        params: GenerationParams | None = None,
        asker: Asker | None = None,
        mcp: MCPManager | None = None,
        confirmer: Confirmer | None = None,
        allow_auto_approve: bool = True,
        container_image: str | None = None,
        on_stream_text: Callable[[str, StreamEventKind], None] | None = None,
        audit_sink: AuditSink | None = None,
        task_id: str | None = None,
        context_config: ContextConfig | None = None,
        context_policy: ContextPolicy | None = None,
        memory_manager: MemoryManager | None = None,
    ):
        self._client = client
        self._tier = tier
        # Resolved once here so backend and ToolContext (File tools/WebFetch, §3.7) share
        # the exact same root — mirrors RestrictedBackend/ContainerBackend's own default.
        self._allowed_root = str(Path(allowed_root or Path.cwd()).resolve())
        # Default tier is restricted (B2 / ACTION_PLAN). An explicit backend overrides
        # the tier; otherwise the tier selects the backend.
        self._backend = backend or _backend_for_tier(
            tier, allowed_root=self._allowed_root, container_image=container_image
        )
        # Explicit system_prompt wins outright. Identity is only consulted when it is None;
        # neither given means compose from a zero-content identity without loading files.
        self._system_prompt = system_prompt
        self._identity = identity
        self._max_rounds = max_rounds
        self._params = params
        # How the Survey tool asks the user a question; None = headless (Survey → need_info).
        self._asker = asker
        # MCP server manager (already connected by the caller) + the confirmation gate for
        # side-effecting MCP/WebFetch/FileWrite calls. None = no gated tool on the menu.
        self._mcp = mcp
        self._confirmer = confirmer
        self._allow_auto_approve = allow_auto_approve
        # None = non-streaming (unchanged). Set = forwarded to Step, which consumes
        # client.stream() instead of complete() and forwards each delta here for
        # display (docs/m9-streaming-multimodal-commands.md §3.3).
        self._on_stream_text = on_stream_text
        self._audit_sink = audit_sink
        self._task_id = task_id
        self._memory_manager = memory_manager
        self._context_policy = context_policy or SlidingWindowContextPolicy(
            client.capability,
            params,
            context_config or ContextConfig(),
        )
        self.runtime = Runtime()

    def close(self) -> None:
        """Release backend resources (e.g. ContainerBackend's temp worker skeleton).
        Safe to call for backends without a close()."""
        backend_close = getattr(self._backend, "close", None)
        if callable(backend_close):
            backend_close()

    def _build_system_prompt(self) -> str:
        """Base prompt plus, when MCP servers are connected, the MCP tools section — so
        the model knows which servers/tools exist (eager discovery, docs/m7 §3.4)."""
        if self._system_prompt is not None:
            base = self._system_prompt
        else:
            identity = self._identity or ApprovedIdentity(
                soul=None, user=None, project_agents=None, memory=None
            )
            if self._memory_manager is not None:
                identity = ApprovedIdentity(
                    soul=identity.soul,
                    user=identity.user,
                    project_agents=identity.project_agents,
                    memory=self._memory_manager.render() or None,
                )
            base = compose_system_prompt(identity)
        if self._mcp is None:
            return base
        tools_section = self._mcp.tools_prompt()
        if not tools_section:
            return base
        return f"{base}\n\n{tools_section}"

    def run(
        self,
        goal: str,
        *,
        images: list[ImageItem] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> TaskOutcome:
        """Run the task for `goal` and return its terminal outcome.

        `images` (M9 Phase 4, the REPL `/image` command and `run --image`) attaches
        image content to the goal message; the goal text always becomes a TextItem
        alongside them, so a model without `supports_images` still sees the text
        (the client-level pre-flight check rejects the request instead, see
        docs/m9-streaming-multimodal-commands.md §3.4).

        `cancel_event` is cooperative: it stops work between model and tool calls but
        does not interrupt a model, network, or tool call already in flight.
        """
        goal_content: str | list = goal
        if images:
            goal_content = [TextItem(text=goal), *images]
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            Message(role=Role.USER, content=goal_content),
        ]
        step = Step(
            self._client,
            self._backend,
            self.runtime,
            max_rounds=self._max_rounds,
            params=self._params,
            asker=self._asker,
            mcp=self._mcp,
            confirmer=self._confirmer,
            allow_auto_approve=self._allow_auto_approve,
            tier=self._tier,
            allowed_root=self._allowed_root,
            on_stream_text=self._on_stream_text,
            cancel_event=cancel_event,
            audit_sink=self._audit_sink,
            task_id=self._task_id,
            context_policy=self._context_policy,
        )
        rounds = step.run(messages)
        status = self._derive_status(rounds)
        memory_results: list[MemoryResult] = []
        if self._memory_manager is not None and status.solved:
            for round_result in rounds:
                for candidate in round_result.memory_candidates:
                    memory_results.append(
                        self._memory_manager.apply(candidate, task_id=self._task_id)
                    )
        return TaskOutcome(status=status, rounds=rounds, memory_results=memory_results)

    def _derive_status(self, rounds: list[RoundResult]) -> TaskStatus:
        if not rounds:
            return TaskStatus(completed=False, reason="no_rounds")
        last = rounds[-1]
        reason = str(last.stopped_reason or "unknown")
        completed = reason == Termination.COMPLETED
        # For a prose answer the payload is the model's own words (front matter stripped);
        # for a tool-signalled terminal state (e.g. Survey → need_info) it's the tool's
        # detail (the survey question); otherwise it's whatever text the round carried.
        if reason == Termination.ANSWERED_IN_PROSE:
            detail = last.body or None
        elif completed:
            detail = None
        elif last.stopped_detail:
            detail = last.stopped_detail
        else:
            detail = last.text or None
        return TaskStatus(completed=completed, reason=reason, detail=detail)
