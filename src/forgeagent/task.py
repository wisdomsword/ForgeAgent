"""The Task loop: assemble the prompt, run a Step, report a structured outcome.

See ACTION_PLAN §二 (borrow agent's task.py, simplified). A Task builds the initial
conversation (system prompt + user goal), owns the runtime and executor backend so
cross-block state persists for the task's lifetime, drives one Step, and derives a
TaskOutcome from the rounds (completed / refused / needs-info / failed / exhausted).

The system prompt is a plain string in v1 (Jinja2 composition is deferred — YAGNI
until there are variants to compose).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from .client import ModelClient
from .executor import ContainerBackend, ExecutorBackend, RestrictedBackend, TrustedBackend
from .mcp_manager import MCPManager
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

DEFAULT_SYSTEM_PROMPT = """\
This conversation is driven by ForgeAgent, a harness that completes tasks by running Python \
programs on your behalf and feeding you their output. You keep your own identity; ForgeAgent \
is just the name of this response format, not a persona to adopt. Complete tasks by writing \
Python code and running it through the markup below — do not answer in plain prose, even for \
simple tasks like arithmetic, since prose has no way to actually execute anything here.

To run code, wrap it in a fenced code block marked with CodeBlockStart/CodeBlockEnd HTML \
comments, then trigger it with a ToolCall comment naming the Exec tool. Example, for the task \
"compute 10 + 20 + 30 and print the result":

<!-- CodeBlockStart: {"name": "sum_block"} -->
```python
print(10 + 20 + 30)
```
<!-- CodeBlockEnd: {"name": "sum_block"} -->
<!-- ToolCall: {"name": "Exec", "arguments": {"name": "sum_block"}} -->

The Exec tool's `arguments.name` must match the CodeBlockStart/End `name`. You will receive the \
program's stdout/stderr as feedback in the next turn; use it to decide the next step.

To modify an existing block, use an Edit tool call instead of rewriting the whole block:
<!-- ToolCall: {"name": "Edit", "arguments": {"name": "sum_block", "old": "10 + 20 + 30", \
"new": "10 + 20 + 30 + 40"}} -->

Use utils.set_state(key=value) / utils.get_state(key) inside your Python code to carry values \
across blocks (state does not persist any other way).

Once you can see (from feedback) that the task is fully done, send one final response that \
starts with this YAML front matter as the very first thing, before anything else:
---
task_status:
  completed: true
  confidence: 0.9
---
"""


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


class Task:
    """Runs a single user goal to completion (or a terminal non-completion)."""

    def __init__(
        self,
        client: ModelClient,
        *,
        tier: Tier = "restricted",
        backend: ExecutorBackend | None = None,
        allowed_root: str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_rounds: int = 10,
        params: GenerationParams | None = None,
        asker: Asker | None = None,
        mcp: MCPManager | None = None,
        confirmer: Confirmer | None = None,
        container_image: str | None = None,
        on_stream_text: Callable[[str, StreamEventKind], None] | None = None,
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
        self._system_prompt = system_prompt
        self._max_rounds = max_rounds
        self._params = params
        # How the Survey tool asks the user a question; None = headless (Survey → need_info).
        self._asker = asker
        # MCP server manager (already connected by the caller) + the confirmation gate for
        # side-effecting MCP/WebFetch/FileWrite calls. None = no gated tool on the menu.
        self._mcp = mcp
        self._confirmer = confirmer
        # None = non-streaming (unchanged). Set = forwarded to Step, which consumes
        # client.stream() instead of complete() and forwards each delta here for
        # display (docs/m9-streaming-multimodal-commands.md §3.3).
        self._on_stream_text = on_stream_text
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
        if self._mcp is None:
            return self._system_prompt
        tools_section = self._mcp.tools_prompt()
        if not tools_section:
            return self._system_prompt
        return f"{self._system_prompt}\n\n{tools_section}"

    def run(self, goal: str, *, images: list[ImageItem] | None = None) -> TaskOutcome:
        """Run the task for `goal` and return its terminal outcome.

        `images` (M9 Phase 4, the REPL `/image` command and `run --image`) attaches
        image content to the goal message; the goal text always becomes a TextItem
        alongside them, so a model without `supports_images` still sees the text
        (the client-level pre-flight check rejects the request instead, see
        docs/m9-streaming-multimodal-commands.md §3.4).
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
            tier=self._tier,
            allowed_root=self._allowed_root,
            on_stream_text=self._on_stream_text,
        )
        rounds = step.run(messages)
        return TaskOutcome(status=self._derive_status(rounds), rounds=rounds)

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
