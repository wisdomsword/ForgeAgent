"""The Step loop: the heart of the code-as-action cycle.

See ACTION_PLAN §二 (borrow agent's step.py round loop, simplified) and
docs/text-protocol-spec.md. One Step runs rounds until there is no feedback to send
back or max_rounds is hit:

    request LLM -> parse response -> execute code blocks / tool calls
    -> render results as system feedback -> feed back as next round's input

Tools: Exec (create-or-reuse a named block and run it) and Edit (old/new replacement
producing a new block version). The Edit runtime matching rules (old not found,
multiple matches without replace_all) live here — they were deferred from M2 as a
runtime concern.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

from .audit import AuditEvent, AuditSink, emit_audit
from .client import AttemptObserver, ModelClient, ProviderAttempt
from .context import (
    ContextBudgetExceeded,
    ContextConfig,
    ContextPolicy,
    SlidingWindowContextPolicy,
    render_bounded_feedback,
)
from .executor import ExecutorBackend
from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    Role,
    StreamEventKind,
    TokenUsage,
)
from .policy import CodeAnalyzer
from .protocol import (
    MemoryCandidate,
    ParseResult,
    TaskStatus,
    ToolCall,
    parse,
)
from .runtime import Runtime
from .secret_policy import mask_secrets, sensitive_env_values
from .tools import (
    Asker,
    CodeBlockStore,
    Confirmer,
    Tier,
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    _apply_edit,
    default_registry,
)

if TYPE_CHECKING:
    from .mcp_manager import MCPManager
    from .skills import SkillRegistry

# Re-exported for callers/tests that import them from step (their historical home before
# the M7 tools.py extraction): the Edit runtime matcher and the code-block store.
__all__ = ["Step", "RoundResult", "Termination", "CodeBlockStore", "ToolOutcome", "_apply_edit"]


class Termination(StrEnum):
    """Why a Step loop stopped. Kept mechanical: the loop classifies terminal STATE,
    never answer correctness (a wrong-but-well-formed answer is COMPLETED here; judging
    it right or wrong is the evaluator's job, see docs/golden-tasks-seed.md).

    COMPLETED and ANSWERED_IN_PROSE are both "solved" (see TaskStatus.solved); the
    difference is that COMPLETED was verified by execution and declared by the model,
    while ANSWERED_IN_PROSE is an unverified prose answer we accept only after nudging
    the model toward the protocol once.
    """

    COMPLETED = "completed"  # model declared task_status.completed=true
    ANSWERED_IN_PROSE = "answered_in_prose"  # prose answer, no execution (soft success)
    REFUSED = "refused"  # stop_reason refusal/content_filter, or declared status=refused
    NEEDS_INFO = "needs_info"  # model declared status=need_info, or Survey w/o asker
    FAILED = "failed"  # model declared status=failed
    TRUNCATED = "truncated"  # response cut off at the token limit (partial answer)
    EMPTY_RESPONSE = "empty_response"  # no tool activity and no prose to accept
    MAX_ROUNDS = "max_rounds"  # ran out of rounds with work still in flight
    CLIENT_ERROR = "client_error"  # transport/client failure (suffixed with :kind)
    CANCELLED = "cancelled"  # caller requested cooperative cancellation


# Provider stop_reason values, normalised. Anthropic and OpenAI-compatible clients pass
# stop_reason through verbatim (M6 decision), so their vendor-specific spellings are
# reconciled here rather than in the clients.
_REFUSAL_STOP_REASONS = frozenset({"refusal", "content_filter"})
_TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "length"})

# Declared non-completion statuses (protocol front matter) -> terminal reason.
_DECLARED_STATUS: dict[str, Termination] = {
    "refused": Termination.REFUSED,
    "need_info": Termination.NEEDS_INFO,
    "failed": Termination.FAILED,
}

# Sent once when the model answers in prose instead of executing code. A mid-conversation
# user turn is more salient than the system prompt, so this recovers the common "answered
# without running anything" deviation; if the model still answers in prose, we accept it.
_PROSE_NUDGE = (
    "You answered in prose without running any code. This harness completes a task only "
    "by executing code through the protocol — a prose answer is never executed and cannot "
    "be verified. Redo it: write a Python code block, trigger it with an Exec ToolCall, "
    "and once the output confirms the result, declare completion in the task_status front "
    "matter. If you truly cannot use the protocol, say so in task_status (status: failed)."
)


def _render_history_content(reply: AssistantMessage) -> str:
    """What goes into convo history for this reply: reply.content plus, for the
    native tool_calls channel (ToolSource.OPENAI, M6), the same text-protocol
    ToolCall markup the text channel already uses.

    `Message.content` is plain text by contract (docs/model-client-contract.md) —
    there is no vendor-native tool_calls field on it — so a native call is folded
    into the markup form rather than added as a separate structured field. Without
    this, a model using the native channel would lose its own prior tool calls from
    history on the next round (it only ever sees its own past text).
    """
    if not reply.tool_calls:
        return reply.content
    rendered = [reply.content] if reply.content else []
    for call in reply.tool_calls:
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError:
            arguments = call.arguments  # keep the raw string rather than dropping it
        marker = {"id": call.id, "name": call.name, "arguments": arguments}
        rendered.append(f"<!-- ToolCall: {json.dumps(marker)} -->")
    return "\n".join(rendered)


class RoundResult(BaseModel):
    """What happened in one round: the parsed response and per-tool outcomes."""

    text: str
    # `text` with front matter stripped — the model's own words, e.g. when it answers
    # in plain prose instead of calling Exec. Empty for refusal/client_error rounds,
    # where `text` already holds the relevant message.
    body: str = ""
    # The provider's raw stop_reason for this round (needed to spot truncation, which
    # only becomes terminal when there is nothing to feed back).
    stop_reason: str = ""
    # Token accounting for this round's call, straight from AssistantMessage.usage.
    # None for rounds with no assistant reply to account for (e.g. ClientError rounds,
    # which build a RoundResult without ever calling _handle_reply). See docs/m10 §3.2.
    usage: TokenUsage | None = None
    parse_errors: list[str] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    outcomes: list[ToolOutcome] = Field(default_factory=list)
    # True only for a model-declared completion (Termination.COMPLETED). A prose answer
    # is a soft success (Termination.ANSWERED_IN_PROSE) — solved, but not `completed`.
    completed: bool = False
    stopped_reason: str | None = None
    # When a tool signals a terminal state (e.g. Survey w/o asker → NEEDS_INFO), the
    # tool's user-facing detail (the survey question) lives here so Task's
    # `_derive_status` can surface it instead of the model's raw text. Empty otherwise.
    stopped_detail: str = ""


class Step:
    """Drives the request -> parse -> execute -> feedback loop for up to max_rounds."""

    def __init__(
        self,
        client: ModelClient,
        backend: ExecutorBackend,
        runtime: Runtime,
        *,
        max_rounds: int = 10,
        params: GenerationParams | None = None,
        analyzer: CodeAnalyzer | None = None,
        registry: ToolRegistry | None = None,
        asker: Asker | None = None,
        mcp: MCPManager | None = None,
        confirmer: Confirmer | None = None,
        allow_auto_approve: bool = True,
        tier: Tier = "restricted",
        allowed_root: str = ".",
        on_stream_text: Callable[[str, StreamEventKind], None] | None = None,
        cancel_event: threading.Event | None = None,
        audit_sink: AuditSink | None = None,
        task_id: str | None = None,
        context_policy: ContextPolicy | None = None,
        skills: SkillRegistry | None = None,
        context_config: ContextConfig | None = None,
    ):
        self._client = client
        self._backend = backend
        self._runtime = runtime
        self._max_rounds = max_rounds
        self._params = params
        # None = non-streaming (unchanged complete() path). Set = CLI display callback
        # (docs/m9-streaming-multimodal-commands.md §3.3); receives every TEXT_DELTA/
        # THINKING_DELTA as it arrives. Never sees DONE — the aggregated AssistantMessage
        # is this method's return value, not something the callback needs.
        self._on_stream_text = on_stream_text
        self._cancel_event = cancel_event
        self._audit_sink = audit_sink
        self._task_id = task_id
        self._active_llm_operation_id: str | None = None
        resolved_policy = SlidingWindowContextPolicy(
            client.capability,
            params,
            context_config or ContextConfig(),
        )
        self._context_policy = context_policy or resolved_policy
        self._feedback_result_limit = getattr(
            self._context_policy, "tool_result_limit", resolved_policy.tool_result_limit
        )
        self._feedback_round_limit = getattr(
            self._context_policy, "round_feedback_limit", resolved_policy.round_feedback_limit
        )
        self._feedback_secret_values = sensitive_env_values()
        # Static AST layer: advisory feedback before execution (not a security boundary).
        self._analyzer = analyzer or CodeAnalyzer()
        self.blocks = CodeBlockStore()
        # Tool set drives both parsing (which names are recognised) and dispatch. Default
        # is the built-in Exec/Edit/Survey registry; with an MCPManager, MCP is added too.
        self._registry = registry or default_registry(with_mcp=mcp is not None, skills=skills)
        # One context shared across the task's tool dispatches (blocks/state persist).
        self._ctx = ToolContext(
            blocks=self.blocks,
            backend=self._backend,
            runtime=self._runtime,
            analyzer=self._analyzer,
            asker=asker,
            mcp=mcp,
            confirmer=confirmer,
            allow_auto_approve=allow_auto_approve,
            tier=tier,
            allowed_root=allowed_root,
            audit_sink=audit_sink,
            task_id=task_id,
        )
        self.rounds: list[RoundResult] = []

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _stream_or_complete(
        self, request_view: list[Message]
    ) -> AssistantMessage | ClientError:
        """No callback -> plain complete() (today's path, unchanged). With a callback,
        consume client.stream(), forward TEXT_DELTA/THINKING_DELTA text to it for
        display, and return the DONE event's AssistantMessage (or a mid-stream
        ClientError) — structurally identical to what complete() would return
        (docs/m9-streaming-multimodal-commands.md §3.3)."""
        if self._on_stream_text is None:
            return self._client.complete(request_view, self._params)
        for event in self._client.stream(request_view, self._params):
            if isinstance(event, ClientError):
                return event
            if event.kind is StreamEventKind.DONE:
                assert event.message is not None  # DONE always carries a message
                return event.message
            self._on_stream_text(event.text, event.kind)
        raise RuntimeError("stream() ended without a DONE event or a ClientError")

    def _observe_provider_attempt(self, event: ProviderAttempt) -> None:
        self._emit(
            AuditEvent(
                event_type="llm.provider_attempt",
                task_id=self._task_id,
                operation_id=self._active_llm_operation_id or uuid4().hex,
                attempt=event.attempt,
                parameters={
                    "model": getattr(self._client.capability, "model_id", "unknown"),
                    **({"error_kind": event.error_kind} if event.error_kind else {}),
                },
                result_status=event.status,
            )
        )

    def run(self, messages: list[Message]) -> list[RoundResult]:
        """Run rounds until the task reaches a terminal state or max_rounds.

        `messages` is the running conversation; each round appends the assistant text
        and, when there is feedback (tool outcomes, parse errors, or a prose nudge), a
        user message carrying it. The terminal state of the last round is a
        `Termination` value on `stopped_reason` — see that enum for the taxonomy.
        """
        if self._audit_sink is None:
            return self._run_rounds(messages)

        previous_observer: AttemptObserver | None = None

        def observe(event: ProviderAttempt) -> None:
            if previous_observer is not None:
                try:
                    previous_observer(event)
                except Exception:
                    pass
            self._observe_provider_attempt(event)

        previous_observer = self._client.set_attempt_observer(observe)
        try:
            return self._run_rounds(messages)
        finally:
            self._client.set_attempt_observer(previous_observer)

    def _run_rounds(self, messages: list[Message]) -> list[RoundResult]:
        convo = list(messages)
        prose_nudged = False
        for attempt in range(1, self._max_rounds + 1):
            if self._cancelled():
                if self.rounds:
                    self.rounds[-1].completed = False
                    self.rounds[-1].stopped_reason = Termination.CANCELLED
                else:
                    self.rounds.append(RoundResult(text="", stopped_reason=Termination.CANCELLED))
                break
            try:
                request_view = self._context_policy.request_view(convo)
            except ContextBudgetExceeded as exc:
                self.rounds.append(
                    RoundResult(
                        text="",
                        stopped_reason=Termination.FAILED,
                        stopped_detail=exc.detail,
                    )
                )
                break
            operation_id = uuid4().hex
            self._active_llm_operation_id = operation_id
            started = time.monotonic()
            model_id = getattr(self._client.capability, "model_id", "unknown")
            self._emit(
                AuditEvent(
                    event_type="llm.attempt",
                    task_id=self._task_id,
                    operation_id=operation_id,
                    attempt=attempt,
                    parameters={"model": model_id},
                    result_status="started",
                )
            )
            try:
                reply = self._stream_or_complete(request_view)
            except Exception:
                self._emit(
                    AuditEvent(
                        event_type="llm.outcome",
                        task_id=self._task_id,
                        operation_id=operation_id,
                        attempt=attempt,
                        parameters={"model": model_id},
                        result_status=(
                            "interrupted" if self._on_stream_text is not None else "error"
                        ),
                        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    )
                )
                self._active_llm_operation_id = None
                raise
            if isinstance(reply, ClientError):
                outcome_status = "cancelled" if self._cancelled() else "error"
                outcome_parameters = {
                    "model": model_id,
                    "error_kind": reply.kind,
                    "provider_attempts": reply.attempts,
                }
            else:
                outcome_status = "success"
                outcome_parameters = {
                    "model": model_id,
                    "stop_reason": reply.stop_reason,
                    "usage": reply.usage.model_dump(mode="python"),
                    "cache_hit_rate": reply.usage.cache_hit_rate,
                }
            self._emit(
                AuditEvent(
                    event_type="llm.outcome",
                    task_id=self._task_id,
                    operation_id=operation_id,
                    attempt=attempt,
                    parameters=outcome_parameters,
                    result_status=outcome_status,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            )
            self._active_llm_operation_id = None
            if isinstance(reply, ClientError):
                if self._cancelled():
                    self.rounds.append(RoundResult(text="", stopped_reason=Termination.CANCELLED))
                    break
                self.rounds.append(
                    RoundResult(
                        text=reply.message,
                        stopped_reason=f"{Termination.CLIENT_ERROR}:{reply.kind}",
                    )
                )
                break

            rr = self._handle_reply(reply)
            self.rounds.append(rr)
            convo.append(Message(role=Role.ASSISTANT, content=_render_history_content(reply)))

            if self._cancelled():
                rr.completed = False
                rr.stopped_reason = Termination.CANCELLED
                break

            # A terminal state the reply itself declares (completion / refusal /
            # need_info / failed) ends the loop immediately.
            if rr.stopped_reason is not None:
                break

            try:
                feedback = self._render_feedback(rr)
            except ContextBudgetExceeded as exc:
                if self._cancelled():
                    rr.completed = False
                    rr.stopped_reason = Termination.CANCELLED
                else:
                    rr.completed = False
                    rr.stopped_reason = Termination.FAILED
                    rr.stopped_detail = exc.detail
                break
            if self._cancelled():
                rr.completed = False
                rr.stopped_reason = Termination.CANCELLED
                break
            if feedback:
                convo.append(Message(role=Role.USER, content=feedback))
                continue

            # No tool activity and no parse errors this round: the model neither ran code
            # nor reported anything. Classify what kind of dead end this is.
            if reply.stop_reason in _TRUNCATED_STOP_REASONS:
                rr.stopped_reason = Termination.TRUNCATED
                break
            if not rr.body:
                rr.stopped_reason = Termination.EMPTY_RESPONSE
                break
            # Prose with content: nudge toward the protocol once, then accept it as an
            # unverified soft completion if the model answers in prose again.
            if not prose_nudged:
                prose_nudged = True
                convo.append(Message(role=Role.USER, content=_PROSE_NUDGE))
                continue
            rr.stopped_reason = Termination.ANSWERED_IN_PROSE
            break
        else:
            if self.rounds:
                self.rounds[-1].stopped_reason = Termination.MAX_ROUNDS
        return self.rounds

    def _handle_reply(self, reply: AssistantMessage) -> RoundResult:
        if reply.stop_reason in _REFUSAL_STOP_REASONS:
            return RoundResult(
                text=reply.content,
                stop_reason=reply.stop_reason,
                stopped_reason=Termination.REFUSED,
                usage=reply.usage,
            )
        parsed: ParseResult = parse(
            reply.content,
            native_tool_calls=reply.tool_calls,
            tool_schemas=self._registry.arg_schemas(),
        )
        rr = RoundResult(
            text=reply.content,
            body=parsed.body,
            stop_reason=reply.stop_reason,
            usage=reply.usage,
            parse_errors=[f"{e.error_type}: {e.message}" for e in parsed.errors],
            memory_candidates=parsed.memory_candidates,
        )
        # Register code blocks provided in this response before running tool calls.
        for block in parsed.code_blocks:
            self.blocks.put(block.name, block.code, block.language)
        for call in parsed.tool_calls:
            rr.outcomes.append(self._dispatch(call))
            if self._cancelled():
                break
        self._apply_declared_status(
            rr,
            parsed.task_status,
            allow_completed=not parsed.tool_calls and not parsed.errors,
        )
        # A tool may signal terminal NEEDS_INFO (Survey without an asker). A declared
        # non-completed status wins if the model also declared one — the model's own
        # signal is more reliable than a tool-side default.
        if rr.stopped_reason is None:
            for o in rr.outcomes:
                if o.needs_info:
                    rr.stopped_reason = Termination.NEEDS_INFO
                    rr.stopped_detail = o.detail
                    break
        return rr

    def _apply_declared_status(
        self, rr: RoundResult, status: TaskStatus | None, *, allow_completed: bool
    ) -> None:
        """Honour a front-matter task_status declaration (see protocol.TaskStatus).

        `completed: true` is a verified completion; a `completed: false` with an explicit
        `status` (refused / need_info / failed) is the model telling us why it stopped —
        the reliable, model-declared signal we prefer over guessing intent from prose.
        A bare `completed: false` is not terminal (the model is still working).
        """
        if status is None:
            return
        if status.completed:
            if allow_completed:
                rr.completed = True
                rr.stopped_reason = Termination.COMPLETED
            return
        declared = _DECLARED_STATUS.get(status.status or "")
        if declared is not None:
            rr.stopped_reason = declared

    def _dispatch(self, call: ToolCall) -> ToolOutcome:
        # The tool is looked up by name in the registry; the parser has already validated
        # call.arguments against that tool's schema, so a missing tool here is impossible
        # for text/native calls (both go through the same registered schema table).
        tool = self._registry.get(call.name)
        if tool is None:  # defensive: only reachable if a tool schema outlives its Tool.
            self._emit(
                AuditEvent(
                    event_type="tool.operation",
                    task_id=self._task_id,
                    operation_id=call.id,
                    risk_level="high",
                    parameters={"tool": call.name},
                    result_status="failed",
                    duration_ms=0,
                )
            )
            return ToolOutcome(
                tool=call.name,
                success=False,
                detail=f"no handler registered for tool {call.name!r}",
            )
        started = time.monotonic()
        try:
            self._ctx.operation_id = call.id
            outcome = tool.run(call.arguments, self._ctx)
        except Exception:
            self._emit(
                AuditEvent(
                    event_type="tool.operation",
                    task_id=self._task_id,
                    operation_id=call.id,
                    risk_level=tool.risk_level,
                    parameters={"tool": call.name},
                    result_status="error",
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            )
            raise
        finally:
            self._ctx.operation_id = None
        self._emit(
            AuditEvent(
                event_type="tool.operation",
                task_id=self._task_id,
                operation_id=call.id,
                risk_level=tool.risk_level,
                parameters={"tool": call.name},
                result_status="success" if outcome.success else "failed",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        )
        return outcome

    def _emit(self, event: AuditEvent) -> None:
        emit_audit(self._audit_sink, event)

    def _render_feedback(self, rr: RoundResult) -> str:
        """Render parse errors and tool outcomes into a system feedback string.

        Empty string means nothing to report -> the loop ends.
        """
        return render_bounded_feedback(
            rr.parse_errors,
            rr.outcomes,
            result_limit=self._feedback_result_limit,
            round_limit=self._feedback_round_limit,
            mask=lambda text: mask_secrets(text, self._feedback_secret_values),
        )
