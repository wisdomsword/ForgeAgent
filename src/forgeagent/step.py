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
from enum import StrEnum

from pydantic import BaseModel, Field

from .client import ModelClient
from .executor import ExecResult, ExecutorBackend
from .models import AssistantMessage, ClientError, GenerationParams, Message, Role
from .policy import CodeAnalyzer
from .protocol import (
    EditArgs,
    ExecArgs,
    ParseResult,
    TaskStatus,
    ToolCall,
    parse,
)
from .runtime import Runtime


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
    NEEDS_INFO = "needs_info"  # model declared status=need_info
    FAILED = "failed"  # model declared status=failed
    TRUNCATED = "truncated"  # response cut off at the token limit (partial answer)
    EMPTY_RESPONSE = "empty_response"  # no tool activity and no prose to accept
    MAX_ROUNDS = "max_rounds"  # ran out of rounds with work still in flight
    CLIENT_ERROR = "client_error"  # transport/client failure (suffixed with :kind)


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

# Feedback is fed straight into the next round's user message; a block that prints a
# lot (or a long traceback) would otherwise blow up the context on its own. Keep the
# tail — the end of a printout/traceback is almost always the informative part.
_FEEDBACK_TAIL_LIMIT = 4096


def _truncate_tail(text: str, limit: int = _FEEDBACK_TAIL_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"[... truncated {len(text) - limit} chars ...]\n{text[-limit:]}"


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


class StoredBlock(BaseModel):
    """A named code block with version history (Edit bumps the version)."""

    name: str
    code: str
    language: str = "python"
    version: int = 1


class CodeBlockStore:
    """Holds the current version of each named block plus a flat history."""

    def __init__(self) -> None:
        self._blocks: dict[str, StoredBlock] = {}
        self.history: list[StoredBlock] = []

    def put(self, name: str, code: str, language: str = "python") -> StoredBlock:
        """Create or update a block by name; updating bumps its version."""
        existing = self._blocks.get(name)
        version = existing.version + 1 if existing else 1
        block = StoredBlock(name=name, code=code, language=language, version=version)
        self._blocks[name] = block
        self.history.append(block)
        return block

    def get(self, name: str) -> StoredBlock | None:
        return self._blocks.get(name)


class ToolOutcome(BaseModel):
    """Result of one tool call, for feedback rendering."""

    tool: str
    block_name: str | None = None
    success: bool
    detail: str = ""
    exec_result: ExecResult | None = None
    # Static-analysis feedback for this block (advisory, does not block execution).
    static_feedback: str = ""


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
    parse_errors: list[str] = Field(default_factory=list)
    outcomes: list[ToolOutcome] = Field(default_factory=list)
    # True only for a model-declared completion (Termination.COMPLETED). A prose answer
    # is a soft success (Termination.ANSWERED_IN_PROSE) — solved, but not `completed`.
    completed: bool = False
    stopped_reason: str | None = None


def _apply_edit(current_code: str, args: EditArgs) -> tuple[str | None, str | None]:
    """Apply an Edit's old/new replacement. Returns (new_code, error).

    Runtime matching rules (deferred from M2): old not found -> error; multiple
    matches without replace_all -> error asking for replace_all or more context.
    """
    if args.old not in current_code:
        return None, f"Edit failed: 'old' string not found in block {args.name!r}"
    count = current_code.count(args.old)
    if count > 1 and not args.replace_all:
        return None, (
            f"Edit failed: {count} matches for 'old' in block {args.name!r}; "
            f"set replace_all=true or provide more specific context"
        )
    new_code = current_code.replace(args.old, args.new, -1 if args.replace_all else 1)
    return new_code, None


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
    ):
        self._client = client
        self._backend = backend
        self._runtime = runtime
        self._max_rounds = max_rounds
        self._params = params
        # Static AST layer: advisory feedback before execution (not a security boundary).
        self._analyzer = analyzer or CodeAnalyzer()
        self.blocks = CodeBlockStore()
        self.rounds: list[RoundResult] = []

    def run(self, messages: list[Message]) -> list[RoundResult]:
        """Run rounds until the task reaches a terminal state or max_rounds.

        `messages` is the running conversation; each round appends the assistant text
        and, when there is feedback (tool outcomes, parse errors, or a prose nudge), a
        user message carrying it. The terminal state of the last round is a
        `Termination` value on `stopped_reason` — see that enum for the taxonomy.
        """
        convo = list(messages)
        prose_nudged = False
        for _ in range(self._max_rounds):
            reply = self._client.complete(convo, self._params)
            if isinstance(reply, ClientError):
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

            # A terminal state the reply itself declares (completion / refusal /
            # need_info / failed) ends the loop immediately.
            if rr.stopped_reason is not None:
                break

            feedback = self._render_feedback(rr)
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
            )
        parsed: ParseResult = parse(reply.content, native_tool_calls=reply.tool_calls)
        rr = RoundResult(
            text=reply.content,
            body=parsed.body,
            stop_reason=reply.stop_reason,
            parse_errors=[f"{e.error_type}: {e.message}" for e in parsed.errors],
        )
        # Register code blocks provided in this response before running tool calls.
        for block in parsed.code_blocks:
            self.blocks.put(block.name, block.code, block.language)
        for call in parsed.tool_calls:
            rr.outcomes.append(self._dispatch(call))
        self._apply_declared_status(rr, parsed.task_status)
        return rr

    def _apply_declared_status(self, rr: RoundResult, status: TaskStatus | None) -> None:
        """Honour a front-matter task_status declaration (see protocol.TaskStatus).

        `completed: true` is a verified completion; a `completed: false` with an explicit
        `status` (refused / need_info / failed) is the model telling us why it stopped —
        the reliable, model-declared signal we prefer over guessing intent from prose.
        A bare `completed: false` is not terminal (the model is still working).
        """
        if status is None:
            return
        if status.completed:
            rr.completed = True
            rr.stopped_reason = Termination.COMPLETED
            return
        declared = _DECLARED_STATUS.get(status.status or "")
        if declared is not None:
            rr.stopped_reason = declared

    def _dispatch(self, call: ToolCall) -> ToolOutcome:
        # call.arguments: ExecArgs | EditArgs (protocol.ToolCall) — exhaustive, no
        # "unknown tool" fallthrough is reachable.
        if isinstance(call.arguments, ExecArgs):
            return self._exec(call.arguments)
        return self._edit(call.arguments)

    def _exec(self, args: ExecArgs) -> ToolOutcome:
        # Inline code creates/updates the named block; otherwise reuse an existing one.
        if args.code is not None:
            name = args.name or f"exec_{len(self.blocks.history)}"
            self.blocks.put(name, args.code, args.language)
        else:
            name = args.name  # guaranteed present by the parser (name or code required)
        block = self.blocks.get(name)
        if block is None:
            return ToolOutcome(
                tool="Exec", block_name=name, success=False,
                detail=f"block {name!r} not found and no code provided",
            )
        # Static AST layer (advisory): analyze before execution, surface as feedback.
        # This never blocks — real enforcement is the execution backend.
        static_feedback = self._analyzer.feedback(self._analyzer.analyze(block.code))
        result = self._backend.execute(block.code, self._runtime)
        return ToolOutcome(
            tool="Exec", block_name=name, success=result.success,
            detail=result.error or "", exec_result=result, static_feedback=static_feedback,
        )

    def _edit(self, args: EditArgs) -> ToolOutcome:
        block = self.blocks.get(args.name)
        if block is None:
            return ToolOutcome(
                tool="Edit", block_name=args.name, success=False,
                detail=f"Edit failed: block {args.name!r} does not exist",
            )
        new_code, error = _apply_edit(block.code, args)
        if error:
            return ToolOutcome(tool="Edit", block_name=args.name, success=False, detail=error)
        updated = self.blocks.put(args.name, new_code, block.language)
        return ToolOutcome(
            tool="Edit", block_name=args.name, success=True,
            detail=f"block updated to version {updated.version}",
        )

    def _render_feedback(self, rr: RoundResult) -> str:
        """Render parse errors and tool outcomes into a system feedback string.

        Empty string means nothing to report -> the loop ends.
        """
        lines: list[str] = []
        for err in rr.parse_errors:
            lines.append(f"[parse error] {err}")
        for o in rr.outcomes:
            if o.success and o.exec_result is not None:
                out = _truncate_tail(o.exec_result.stdout.strip())
                lines.append(f"[{o.tool} {o.block_name}] ok" + (f": {out}" if out else ""))
            elif o.success:
                lines.append(f"[{o.tool} {o.block_name}] {o.detail}")
            else:
                detail = _truncate_tail(o.detail)
                lines.append(f"[{o.tool} {o.block_name}] FAILED: {detail}")
            # Advisory static feedback rides alongside the execution outcome.
            if o.static_feedback:
                lines.append(o.static_feedback)
            # A restricted-tier block may set_state a value that can't cross the process
            # boundary as JSON (e.g. a DataFrame) — say so, rather than let the model
            # retry against a silently-empty state key with no explanation.
            if o.exec_result and o.exec_result.dropped_state_keys:
                keys = ", ".join(o.exec_result.dropped_state_keys)
                lines.append(
                    f"[{o.tool} {o.block_name}] note: state key(s) {keys} could not be "
                    "carried to the next block (not JSON-serializable) and are unset there"
                )
        return "\n".join(lines)
