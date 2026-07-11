"""Pluggable tool registry: the dispatch layer the Step loop runs tools through.

See docs/m7-tools-mcp-survey.md §3.1. Before M7 the two tools (Exec/Edit) were
hardcoded into step.py's dispatch and protocol.py's schema table. This module makes
tools a registered set: a `Tool` declares its name + argument schema + `run`, a
`ToolRegistry` holds them, `arg_schemas()` feeds the parser, and `get()` feeds Step's
dispatch. Adding a tool (MCP/Survey in later phases) means registering a `Tool`, not
editing dispatch or the parser.

Exec/Edit here are a straight port of the logic that lived in step.py (M3), so the
refactor is behaviour-preserving.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from .executor import ExecResult, ExecutorBackend
from .policy import CodeAnalyzer
from .protocol import EditArgs, ExecArgs, MCPArgs, SurveyArgs
from .runtime import Runtime

if TYPE_CHECKING:
    from .mcp_manager import MCPManager

# Sandbox tier. Lives here (not task.py) so ToolContext.tier can reference it without
# a circular import: task.py already imports from tools.py (see docs/m10 §3.7).
Tier = Literal["trusted", "restricted", "container"]

# Asker: how a Survey question is answered. Returns the answer text, or None when
# there is no interactive channel (headless/one-shot run). See §3.5.
Asker = Callable[[SurveyArgs], "str | None"]

# Confirmer: the human gate for a side-effecting tool call (MCP / WebFetch / FileWrite).
# Returns True to allow. Typed as BaseModel (not a Union of every Args class) so adding
# a new confirmable tool never requires editing this alias. See §3.4/§3.6.
Confirmer = Callable[[BaseModel], bool]


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
    # True when the tool wants to terminate the Step loop with NEEDS_INFO — used by
    # Survey when no answer is available (headless / no asker). Step reads this flag
    # and, if set, ends the loop with `Termination.NEEDS_INFO` using `detail` as the
    # user-facing question. See docs/m7-tools-mcp-survey.md §3.5.
    needs_info: bool = False


@dataclass
class ToolContext:
    """Everything one tool dispatch can reach. Exec/Edit use blocks/backend/runtime/
    analyzer; Survey uses asker; MCP (later phase) adds its own capabilities as fields.

    A plain dataclass (not a pydantic model) because it carries live, non-serializable
    runtime objects (the executor backend, the runtime state holder, the asker callable).
    A capability that is absent (e.g. no asker in a headless run) is None; the owning
    tool self-checks and returns a structured outcome rather than crashing.
    """

    blocks: CodeBlockStore
    backend: ExecutorBackend
    runtime: Runtime
    analyzer: CodeAnalyzer
    asker: Asker | None = None
    mcp: MCPManager | None = None
    confirmer: Confirmer | None = None
    # Sandbox tier: WebFetch/FileWrite use this to decide whether the confirmer gate is
    # mandatory (restricted/container) or skipped (trusted). See docs/m10 §3.7.
    tier: Tier = "restricted"
    # project-root lock for File tools (and WebFetch's save-to-disk path). Must be the
    # same resolved value passed to the executor backend's allowed_root — see §3.7.
    allowed_root: str = "."


class Tool(ABC):
    """A registered tool: a protocol name, an argument schema, and a run behaviour."""

    name: str
    args_model: type[BaseModel]

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        """Execute the tool with validated `args` against `ctx`; return an outcome.

        Never raises for tool-level failures — those become ToolOutcome(success=False)
        so the Step loop can feed them back to the model.
        """


def _apply_edit(current_code: str, args: EditArgs) -> tuple[str | None, str | None]:
    """Apply an Edit's old/new replacement. Returns (new_code, error).

    Runtime matching rules: old not found -> error; multiple matches without
    replace_all -> error asking for replace_all or more context.
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


class ExecTool(Tool):
    """Create-or-reuse a named block and run it through the executor backend."""

    name = "Exec"
    args_model = ExecArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, ExecArgs)
        # Inline code creates/updates the named block; otherwise reuse an existing one.
        if args.code is not None:
            name = args.name or f"exec_{len(ctx.blocks.history)}"
            ctx.blocks.put(name, args.code, args.language)
        else:
            name = args.name  # guaranteed present by the parser (name or code required)
        block = ctx.blocks.get(name)
        if block is None:
            return ToolOutcome(
                tool="Exec", block_name=name, success=False,
                detail=f"block {name!r} not found and no code provided",
            )
        # Static AST layer (advisory): analyze before execution, surface as feedback.
        # This never blocks — real enforcement is the execution backend.
        static_feedback = ctx.analyzer.feedback(ctx.analyzer.analyze(block.code))
        result = ctx.backend.execute(block.code, ctx.runtime)
        return ToolOutcome(
            tool="Exec", block_name=name, success=result.success,
            detail=result.error or "", exec_result=result, static_feedback=static_feedback,
        )


class EditTool(Tool):
    """Old/new string replacement on an existing block, producing a new version."""

    name = "Edit"
    args_model = EditArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, EditArgs)
        block = ctx.blocks.get(args.name)
        if block is None:
            return ToolOutcome(
                tool="Edit", block_name=args.name, success=False,
                detail=f"Edit failed: block {args.name!r} does not exist",
            )
        new_code, error = _apply_edit(block.code, args)
        if error:
            return ToolOutcome(tool="Edit", block_name=args.name, success=False, detail=error)
        updated = ctx.blocks.put(args.name, new_code, block.language)
        return ToolOutcome(
            tool="Edit", block_name=args.name, success=True,
            detail=f"block updated to version {updated.version}",
        )


class SurveyTool(Tool):
    """Ask the user a question mid-task and feed the answer back in the next round.

    Delegates to `ctx.asker`; when there is no asker (headless / one-shot with no TTY)
    or the asker returns None (user declined / no interactive channel), the tool marks
    the outcome `needs_info=True` so Step ends the loop with NEEDS_INFO — the task's
    detail becomes the question, so callers can see what the model was asking for.
    """

    name = "Survey"
    args_model = SurveyArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, SurveyArgs)
        if ctx.asker is None:
            return ToolOutcome(
                tool="Survey", success=False, needs_info=True, detail=args.question,
            )
        answer = ctx.asker(args)
        if answer is None:
            return ToolOutcome(
                tool="Survey", success=False, needs_info=True, detail=args.question,
            )
        # The answer text becomes the tool's feedback line for the next round.
        return ToolOutcome(tool="Survey", success=True, detail=answer)


class MCPTool(Tool):
    """Call a tool on an external MCP server, routed by {server, tool}.

    The server runs in the MAIN process, outside the restricted sandbox, so a
    side-effecting call passes the confirmation gate first: a call whose (server, tool)
    is on the server's autoApprove allowlist runs directly; otherwise `ctx.confirmer`
    must return True, else the call is refused with a structured outcome (never silently
    executed, never a crash). See docs/m7-tools-mcp-survey.md §3.4 / threat-model T8a.
    """

    name = "MCP"
    args_model = MCPArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, MCPArgs)
        label = f"{args.server}:{args.tool}"
        if ctx.mcp is None:
            return ToolOutcome(
                tool="MCP", block_name=label, success=False,
                detail="no MCP servers are configured",
            )
        if not ctx.mcp.is_auto_approved(args.server, args.tool):
            if ctx.confirmer is None or not ctx.confirmer(args):
                return ToolOutcome(
                    tool="MCP", block_name=label, success=False,
                    detail=f"MCP call {label} was not approved by the user",
                )
        result = ctx.mcp.call_tool(args.server, args.tool, args.arguments)
        return ToolOutcome(
            tool="MCP", block_name=label, success=bool(result.get("ok")),
            detail=result.get("text", ""),
        )


class ToolRegistry:
    """Holds the registered tools; the single source of truth for both parsing
    (arg_schemas) and dispatch (get)."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool by its declared name (later registration overrides)."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def arg_schemas(self) -> dict[str, type[BaseModel]]:
        """name -> argument schema, for the protocol parser to validate against."""
        return {name: tool.args_model for name, tool in self._tools.items()}


def default_registry(*, with_mcp: bool = False) -> ToolRegistry:
    """The built-in tool set: Exec + Edit + Survey, plus MCP when `with_mcp` is set.

    Survey is always registered (so the model may always ask); it degrades gracefully
    to NEEDS_INFO when no asker is wired (headless). MCP is registered only when an
    MCPManager is configured (with_mcp=True) — it stays off the menu by default so the
    model is never told about a tool with no server behind it.
    """
    registry = ToolRegistry()
    registry.register(ExecTool())
    registry.register(EditTool())
    registry.register(SurveyTool())
    if with_mcp:
        registry.register(MCPTool())
    return registry
