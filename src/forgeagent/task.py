"""The Task loop: assemble the prompt, run a Step, report a structured outcome.

See ACTION_PLAN §二 (borrow agent's task.py, simplified). A Task builds the initial
conversation (system prompt + user goal), owns the runtime and executor backend so
cross-block state persists for the task's lifetime, drives one Step, and derives a
TaskOutcome from the rounds (completed / refused / needs-info / failed / exhausted).

The system prompt combines the approved runtime identity with the fixed protocol.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from .attention import Attention, attention_for_reason
from .audit import AuditEvent, AuditSink, emit_audit
from .client import ModelClient
from .context import (
    ContextConfig,
    ContextPolicy,
    SlidingWindowContextPolicy,
    validate_session_messages,
)
from .execution_evidence import (
    ExecutionEvidence,
    ExecutionEvidenceRecorder,
    ProgramArtifact,
    ProgramArtifactStore,
    ProgramArtifactStoreProtocol,
)
from .executor import ContainerBackend, ExecutorBackend, RestrictedBackend, TrustedBackend
from .external_actions import ExternalActionReceiptStore
from .identity import ApprovedIdentity, compose_system_prompt
from .mcp_manager import MCPManager
from .memory import MemoryManager, MemoryResult
from .models import GenerationParams, ImageItem, Message, Role, StreamEventKind, TextItem
from .runtime import Runtime
from .skills import SkillRegistry
from .step import (
    DEFAULT_SUBMISSION_RECOVERY_ATTEMPTS,
    MAX_SUBMISSION_RECOVERY_ATTEMPTS,
    RoundResult,
    Step,
    Termination,
)
from .tools import Asker, Confirmer, Tier, ToolRegistry


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


def _tier_for_explicit_backend(backend: ExecutorBackend | None) -> Tier | None:
    """Return the effective tier for a built-in backend supplied by the caller."""
    if isinstance(backend, TrustedBackend):
        return "trusted"
    if isinstance(backend, ContainerBackend):
        return "container"
    if isinstance(backend, RestrictedBackend):
        return "restricted"
    return None


_IDENTITY_QUERY_RE = re.compile(r"(?:你是谁|who\s+are\s+you|what\s+are\s+you)", re.IGNORECASE)


def _is_identity_query(goal: str) -> bool:
    return _IDENTITY_QUERY_RE.search(goal) is not None


def _starts_with_forgeagent(text: str) -> bool:
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    normalized = first_line.lower()
    return (
        first_line.startswith("我是 ForgeAgent")
        or normalized.startswith("i am forgeagent")
        or normalized.startswith("forgeagent")
    )


def _repair_identity_answer(
    goal: str, rounds: list[RoundResult], transcript: list[Message]
) -> None:
    """Keep an upstream host persona from replacing ForgeAgent in identity answers."""
    if not _is_identity_query(goal) or not rounds:
        return
    last_round = rounds[-1]
    if last_round.stopped_reason != Termination.ANSWERED_IN_PROSE or not last_round.body:
        return
    if _starts_with_forgeagent(last_round.body):
        return
    if re.search(r"[\u3400-\u9fff]", goal):
        answer = (
            "我是 ForgeAgent，一个轻量级的 code-as-action Agent。"
            "我可以直接回答问题，使用内置工具，或编写并执行 Python 程序完成任务；"
            "我会根据真实执行反馈继续迭代，并报告可验证的结果。"
        )
    else:
        answer = (
            "I am ForgeAgent, a lightweight code-as-action Agent. "
            "I can answer directly, use built-in tools, or write and execute Python "
            "programs to complete tasks, iterating on real execution feedback and "
            "reporting verifiable results."
        )
    last_round.text = answer
    last_round.body = answer
    if transcript and transcript[-1].role is Role.ASSISTANT:
        transcript[-1] = Message(role=Role.ASSISTANT, content=answer)


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
    attention: Attention | None = None

    @property
    def solved(self) -> bool:
        """The task reached a solved state — a verified completion or a prose answer."""
        return self.reason in (Termination.COMPLETED, Termination.ANSWERED_IN_PROSE)


class TaskOutcome(BaseModel):
    """Everything a caller needs about a finished task run."""

    status: TaskStatus
    rounds: list[RoundResult]
    memory_results: list[MemoryResult] = Field(default_factory=list)
    execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)
    session_messages: list[Message] = Field(default_factory=list, exclude=True, repr=False)


class _LazyProgramArtifactStore:
    """Create the task artifact store only when Exec first needs it."""

    def __init__(self, project_root: str) -> None:
        self._project_root = project_root
        self._store: ProgramArtifactStoreProtocol | None = None

    def persist(self, *, block_name: str | None, language: str, code: str) -> ProgramArtifact:
        if self._store is None:
            self._store = ProgramArtifactStore(self._project_root)
        return self._store.persist(block_name=block_name, language=language, code=code)

    def close(self) -> None:
        if self._store is not None:
            self._store.close()


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
        skills: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        receipt_store: ExternalActionReceiptStore | None = None,
        max_submission_recovery_attempts: int = DEFAULT_SUBMISSION_RECOVERY_ATTEMPTS,
    ):
        if not 1 <= max_submission_recovery_attempts <= MAX_SUBMISSION_RECOVERY_ATTEMPTS:
            raise ValueError(
                "max_submission_recovery_attempts must be between 1 and "
                f"{MAX_SUBMISSION_RECOVERY_ATTEMPTS}"
            )
        self._client = client
        explicit_backend_tier = _tier_for_explicit_backend(backend)
        self._tier = explicit_backend_tier or tier
        self._custom_backend_authority = backend is not None and explicit_backend_tier is None
        # Project identity and relative paths stay anchored here even when a task's
        # filesystem authority later broadens to the platform root.
        self._allowed_root = str(Path(allowed_root or Path.cwd()).resolve())
        self._evidence_recorder = ExecutionEvidenceRecorder()
        self._program_store: ProgramArtifactStoreProtocol = _LazyProgramArtifactStore(
            self._allowed_root
        )
        if explicit_backend_tier in ("restricted", "container"):
            backend_root = Path(backend._allowed_root).resolve()
            if backend_root != Path(self._allowed_root):
                raise ValueError("backend allowed_root must match Task allowed_root")
        self._host_filesystem_root = Path(self._allowed_root).anchor
        self._filesystem_root = (
            self._host_filesystem_root if self._tier == "trusted" else self._allowed_root
        )
        # Default tier is restricted (B2 / ACTION_PLAN). An explicit backend overrides
        # the tier; otherwise the tier selects the backend.
        self._backend = backend or _backend_for_tier(
            self._tier, allowed_root=self._filesystem_root, container_image=container_image
        )
        self._full_disk_backend_factory: Callable[[], ExecutorBackend] | None = None
        if backend is None and self._tier == "restricted":
            self._full_disk_backend_factory = lambda: RestrictedBackend(
                allowed_root=self._host_filesystem_root
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
        self._skills = skills
        self._tool_registry = tool_registry
        self._receipt_store = receipt_store
        self._max_submission_recovery_attempts = max_submission_recovery_attempts
        self._context_policy = context_policy or SlidingWindowContextPolicy(
            client.capability,
            params,
            context_config or ContextConfig(),
        )
        self.runtime = Runtime()

    def close(self) -> None:
        """Release backend resources (e.g. ContainerBackend's temp worker skeleton).
        Safe to call for backends without a close()."""
        self._program_store.close()
        backend_close = getattr(self._backend, "close", None)
        if callable(backend_close):
            backend_close()

    def _build_system_prompt(self) -> str:
        """Base prompt followed by the optional Skill catalog and MCP tools section."""
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
        sections = [base, self._runtime_authority_prompt()]
        catalog = self._skills.catalog_prompt() if self._skills is not None else ""
        if catalog:
            sections.append(catalog)
        if self._mcp is not None and (tools_section := self._mcp.tools_prompt()):
            sections.append(tools_section)
        return "\n\n".join(sections)

    def _runtime_authority_prompt(self) -> str:
        project_root = json.dumps(self._allowed_root)
        custom_backend = (
            "\n- executor_authority: caller-defined; tier and filesystem_scope describe "
            "built-in tools only."
            if self._custom_backend_authority
            else ""
        )
        if self._tier == "trusted":
            scope = "full_disk"
            access = "RequestFilesystemAccess is unnecessary; full-disk access is already active."
        elif self._tier == "container":
            scope = "project"
            access = "This running container cannot broaden its mount."
        elif (
            self._full_disk_backend_factory is not None
            and self._confirmer is not None
            and not getattr(self._confirmer, "is_headless", False)
            and (
                self._tool_registry is None
                or self._tool_registry.get("RequestFilesystemAccess") is not None
            )
        ):
            scope = "project"
            access = (
                "RequestFilesystemAccess can request one current-task full-disk read/write "
                "grant. Approval keeps the sandbox tier restricted."
            )
        else:
            scope = "project"
            access = "Dynamic filesystem access is unavailable for this task."
        return (
            "## Runtime Authority\n"
            "Host facts are authoritative; do not probe environment variables or MCP tools.\n"
            f'- tier: "{self._tier}"\n'
            f"- project_root: {project_root}\n"
            f'- filesystem_scope: "{scope}"\n'
            f"- filesystem_access: {access}{custom_backend}\n"
            "MCP approvals do not change Task/backend/file scope or MCP server roots."
        )

    def run(
        self,
        goal: str,
        *,
        images: list[ImageItem] | None = None,
        session_messages: Sequence[Message] | None = None,
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
        prior = validate_session_messages(session_messages or ())
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            *prior,
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
            allowed_root=self._filesystem_root,
            project_root=self._allowed_root,
            full_disk_root=self._host_filesystem_root,
            full_disk_backend_factory=self._full_disk_backend_factory,
            on_stream_text=self._on_stream_text,
            cancel_event=cancel_event,
            audit_sink=self._audit_sink,
            task_id=self._task_id,
            context_policy=self._context_policy,
            skills=self._skills,
            registry=self._tool_registry,
            receipt_store=self._receipt_store,
            evidence_recorder=self._evidence_recorder,
            program_store=self._program_store,
            max_submission_recovery_attempts=self._max_submission_recovery_attempts,
        )
        rounds = step.run(messages)
        transcript = step.session_messages
        _repair_identity_answer(goal, rounds, transcript)
        status = self._derive_status(rounds)
        if not transcript or transcript[-1].role is not Role.ASSISTANT:
            transcript.append(
                Message(
                    role=Role.ASSISTANT,
                    content=f"Task ended with status: {status.reason[:160]}.",
                )
            )
        memory_results: list[MemoryResult] = []
        last_memory_values: dict[tuple[str, str], tuple[str, str]] = {}
        if self._memory_manager is not None and status.solved:
            for round_result in rounds:
                for candidate in round_result.memory_candidates:
                    address = (candidate.scope, candidate.key)
                    value = (candidate.kind, candidate.content)
                    if last_memory_values.get(address) == value:
                        continue
                    last_memory_values[address] = value
                    memory_results.append(
                        self._memory_manager.apply(
                            candidate,
                            task_id=self._task_id,
                            source="model_candidate",
                        )
                    )
        outcome = TaskOutcome(
            status=status,
            rounds=rounds,
            memory_results=memory_results,
            execution_evidence=self._evidence_recorder.snapshot(),
            session_messages=transcript,
        )
        if self._tool_registry is not None:
            self._tool_registry.handle_task_outcome(outcome)
        emit_audit(
            self._audit_sink,
            AuditEvent(
                event_type="task.outcome",
                task_id=self._task_id,
                parameters={"completed": status.completed, "round_count": len(rounds)},
                result_status=status.reason,
            ),
        )
        if status.attention is not None:
            emit_audit(
                self._audit_sink,
                AuditEvent(
                    event_type="task.attention",
                    task_id=self._task_id,
                    parameters=status.attention.model_dump(mode="json"),
                    result_status=status.attention.state,
                ),
            )
        return outcome

    def _derive_status(self, rounds: list[RoundResult]) -> TaskStatus:
        if not rounds:
            return TaskStatus(
                completed=False,
                reason="no_rounds",
                attention=attention_for_reason("no_rounds"),
            )
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
        attention = last.attention or attention_for_reason(reason, detail)
        return TaskStatus(
            completed=completed,
            reason=reason,
            detail=detail,
            attention=attention,
        )
