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

import hashlib
import http.client
import json
import logging
import os
import stat
import threading
import time
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel

from .attention import Attention
from .audit import AuditEvent, AuditSink, emit_audit
from .executor import ExecResult, ExecutorBackend
from .external_actions import (
    ExternalActionReceiptStore,
    ReceiptError,
    canonical_request_digest,
    public_receipt_evidence_code,
    public_receipt_label,
)
from .policy import CodeAnalyzer
from .protocol import (
    EditArgs,
    ExecArgs,
    FileListArgs,
    FileReadArgs,
    FileWriteArgs,
    MCPArgs,
    MCPDescribeArgs,
    RequestFilesystemAccessArgs,
    SkillArgs,
    SurveyArgs,
    WebFetchArgs,
)
from .runtime import Runtime
from .secret_policy import mask_secrets, sensitive_env_values
from .skills import SkillRegistry
from .ssrf_guard import SSRFGuardError, guarded_urlopen

if TYPE_CHECKING:
    from .mcp_manager import MCPManager

# WebFetch download/preview caps (docs/m10 §五 decision 6). The download cap bounds
# memory for the response body; the preview cap keeps ToolOutcome.detail well under
# the feedback tail-truncation limit so the full body never needs to ride in-context —
# it is saved to disk instead (§3.4 hybrid return design).
_MAX_FETCH_BYTES = 1_048_576
_FETCH_PREVIEW_CHARS = 2048
_EXT_BY_CONTENT_TYPE = {"text/html": ".html", "application/json": ".json", "text/plain": ".txt"}

_logger = logging.getLogger(__name__)

_FILE_READ_CONTINUATION = "Read another path with FileRead, or process this file with Exec."
_FILE_LIST_CONTINUATION = "Narrow the directory path and call FileList again."
_EXEC_CONTINUATION = "Narrow the output or split the work into smaller executions and retry."
_MCP_CONTINUATION = "This tool has no cursor; narrow the query and call it again for more results."
_MCP_DESCRIBE_CONTINUATION = (
    "Choose another tool from the MCP catalog and call MCPDescribe again with its server and tool."
)
_MCP_RECEIPT_UNAVAILABLE = "MCP receipt unavailable"
_MCP_RESULT_UNKNOWN = "MCP result unknown; reconcile the external action before retrying"
_MCP_DESCRIPTION_CHARS = 2000
_MCP_SCHEMA_CHARS = 6000
_SURVEY_CONTINUATION = "This tool has no cursor; ask a new question if you need more results."
_WEBFETCH_RETRY_CONTINUATION = (
    "This tool has no cursor; narrow the request and call WebFetch again."
)


def _mcp_detail_text(value: str) -> str:
    projected = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} else character
        for character in value
    )
    return " ".join(projected.split())


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
    attention: Attention | None = None
    # True only when a successful tool call is itself the task's completion boundary.
    completes_task: bool = False
    continuation: str | None = None
    truncation_mode: Literal["head", "tail"] = "tail"


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
    # Current filesystem authority boundary. It matches the executor backend root.
    allowed_root: str = "."
    # Relative file-tool paths remain project-relative even when authority broadens.
    project_root: str | None = None
    full_disk_root: str | None = None
    full_disk_backend_factory: Callable[[], ExecutorBackend] | None = None
    filesystem_access_decision: Literal["pending", "approved", "denied"] = "pending"
    audit_sink: AuditSink | None = None
    task_id: str | None = None
    operation_id: str | None = None
    # MCP autoApprove is a CLI/REPL compatibility path. HTTP contexts disable it so
    # their explicit headless allowlist is the only non-interactive pre-approval.
    allow_auto_approve: bool = True
    cancel_event: threading.Event | None = None
    receipt_store: ExternalActionReceiptStore | None = None


class Tool(ABC):
    """A registered tool: a protocol name, an argument schema, and a run behaviour."""

    name: str
    args_model: type[BaseModel]
    risk_level: Literal["low", "medium", "high"] = "high"

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        """Execute the tool with validated `args` against `ctx`; return an outcome.

        Never raises for tool-level failures — those become ToolOutcome(success=False)
        so the Step loop can feed them back to the model.
        """


def _audit_confirmation(
    ctx: ToolContext,
    *,
    tool: str,
    decision: str,
    parameters: dict[str, object] | None = None,
    duration_ms: int = 0,
) -> None:
    emit_audit(
        ctx.audit_sink,
        AuditEvent(
            event_type="confirmation.decision",
            task_id=ctx.task_id,
            operation_id=ctx.operation_id or uuid4().hex,
            risk_level="high",
            parameters={"tool": tool, **(parameters or {})},
            result_status=decision,
            duration_ms=duration_ms,
        ),
    )


def _confirm(
    ctx: ToolContext,
    args: BaseModel,
    *,
    tool: str,
    parameters: dict[str, object],
) -> bool:
    if ctx.confirmer is None:
        _audit_confirmation(ctx, tool=tool, decision="denied", parameters=parameters)
        return False
    started = time.monotonic()
    try:
        contextual_confirm = getattr(ctx.confirmer, "confirm_with_context", None)
        if callable(contextual_confirm):
            extra_context = {}
            if getattr(ctx.confirmer, "is_headless", False):
                extra_context["allowed_root"] = ctx.allowed_root
            approved = bool(
                contextual_confirm(
                    args,
                    task_id=ctx.task_id,
                    operation_id=ctx.operation_id or uuid4().hex,
                    **extra_context,
                )
            )
            return approved
        approved = bool(ctx.confirmer(args))
    except Exception:
        _audit_confirmation(
            ctx,
            tool=tool,
            decision="error",
            parameters=parameters,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        raise
    _audit_confirmation(
        ctx,
        tool=tool,
        decision="approved" if approved else "denied",
        parameters=parameters,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
    )
    return approved


def _denial_detail(ctx: ToolContext, default: str) -> str:
    if getattr(ctx.confirmer, "is_headless", False):
        return "rejected: operation is not in the headless allowlist"
    return default


def _audit_receipt_transition(
    ctx: ToolContext, receipt: object, source_operation_id: str | None
) -> None:
    """Emit only a bounded receipt projection; store state remains authoritative."""
    action_id = getattr(receipt, "action_id", "")
    emit_audit(
        ctx.audit_sink,
        AuditEvent(
            event_type="external_action.receipt",
            task_id=ctx.task_id,
            operation_id=action_id,
            risk_level="high",
            parameters={
                "action_id": action_id,
                "phase": getattr(receipt, "phase", "unknown"),
                "resolution": getattr(receipt, "resolution", "open"),
                "dispatch_certainty": getattr(receipt, "dispatch_certainty", None),
                "remote_ok": getattr(receipt, "remote_ok", None),
                "server_label": public_receipt_label(getattr(receipt, "server_label", "")),
                "tool_label": public_receipt_label(getattr(receipt, "tool_label", "")),
                "evidence_code": public_receipt_evidence_code(getattr(receipt, "evidence_ref", "")),
                **(
                    {"source_operation_id": str(source_operation_id)[:128]}
                    if source_operation_id
                    else {}
                ),
            },
            result_status=getattr(receipt, "phase", "unknown"),
        ),
    )


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
                tool="Exec",
                block_name=name,
                success=False,
                detail=f"block {name!r} not found and no code provided",
            )
        # Static AST layer (advisory): analyze before execution, surface as feedback.
        # This never blocks — real enforcement is the execution backend.
        static_feedback = ctx.analyzer.feedback(ctx.analyzer.analyze(block.code))
        result = ctx.backend.execute(block.code, ctx.runtime)
        return ToolOutcome(
            tool="Exec",
            block_name=name,
            success=result.success,
            detail=result.error or "",
            exec_result=result,
            static_feedback=static_feedback,
            continuation=_EXEC_CONTINUATION,
        )


class EditTool(Tool):
    """Old/new string replacement on an existing block, producing a new version."""

    name = "Edit"
    args_model = EditArgs
    risk_level = "medium"

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, EditArgs)
        block = ctx.blocks.get(args.name)
        if block is None:
            return ToolOutcome(
                tool="Edit",
                block_name=args.name,
                success=False,
                detail=f"Edit failed: block {args.name!r} does not exist",
            )
        new_code, error = _apply_edit(block.code, args)
        if error:
            return ToolOutcome(tool="Edit", block_name=args.name, success=False, detail=error)
        updated = ctx.blocks.put(args.name, new_code, block.language)
        return ToolOutcome(
            tool="Edit",
            block_name=args.name,
            success=True,
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
    risk_level = "low"

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, SurveyArgs)
        if ctx.asker is None:
            return ToolOutcome(
                tool="Survey",
                success=False,
                needs_info=True,
                detail=args.question,
                continuation=_SURVEY_CONTINUATION,
                truncation_mode="head",
            )
        answer = ctx.asker(args)
        if answer is None:
            return ToolOutcome(
                tool="Survey",
                success=False,
                needs_info=True,
                detail=args.question,
                continuation=_SURVEY_CONTINUATION,
                truncation_mode="head",
            )
        # The answer text becomes the tool's feedback line for the next round.
        return ToolOutcome(
            tool="Survey",
            success=True,
            detail=answer,
            continuation=_SURVEY_CONTINUATION,
            truncation_mode="head",
        )


class RequestFilesystemAccessTool(Tool):
    """Request one full-disk grant without changing the sandbox tier."""

    name = "RequestFilesystemAccess"
    args_model = RequestFilesystemAccessArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, RequestFilesystemAccessArgs)
        if ctx.tier == "trusted":
            return ToolOutcome(
                tool=self.name,
                success=True,
                detail="Full-disk filesystem access is already active in trusted mode.",
            )
        if ctx.tier == "container":
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="Dynamic filesystem access is unavailable in container mode.",
            )
        if ctx.filesystem_access_decision == "approved":
            return ToolOutcome(
                tool=self.name,
                success=True,
                detail=(
                    "Full-disk filesystem access is active for this task; "
                    "the sandbox remains restricted."
                ),
            )
        if ctx.filesystem_access_decision == "denied":
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="Full-disk filesystem access was not granted for this task.",
            )
        if ctx.full_disk_root is None or ctx.full_disk_backend_factory is None:
            ctx.filesystem_access_decision = "denied"
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="Dynamic filesystem access is unavailable for this task.",
            )
        try:
            approved = _confirm(
                ctx,
                args,
                tool=self.name,
                parameters={"scope": "full_disk", "tier": "restricted"},
            )
        except Exception:
            ctx.filesystem_access_decision = "denied"
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="Full-disk filesystem access confirmation failed.",
            )
        if not approved:
            ctx.filesystem_access_decision = "denied"
            detail = (
                "rejected: no interactive confirmation channel available"
                if ctx.confirmer is None
                else _denial_detail(ctx, "Full-disk filesystem access was not approved")
            )
            return ToolOutcome(tool=self.name, success=False, detail=detail)
        try:
            backend = ctx.full_disk_backend_factory()
        except Exception:
            ctx.filesystem_access_decision = "denied"
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="Full-disk filesystem access could not be activated.",
            )
        ctx.backend = backend
        ctx.allowed_root = ctx.full_disk_root
        ctx.filesystem_access_decision = "approved"
        return ToolOutcome(
            tool=self.name,
            success=True,
            detail=(
                "Full-disk filesystem access is active for this task; "
                "the sandbox remains restricted. Continue the original operation once."
            ),
        )


class SkillTool(Tool):
    """Read a validated skill section from the immutable registry snapshot."""

    name = "Skill"
    args_model = SkillArgs
    risk_level = "low"

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, SkillArgs)
        detail = self._skills.read(args.name, args.section)
        if detail is None:
            return ToolOutcome(tool=self.name, success=False, detail="Skill is unavailable")
        return ToolOutcome(
            tool=self.name,
            success=True,
            detail=detail,
            continuation=(
                "Skill result truncated; read steps, failure_branches, completion_criteria, or "
                "exit_conditions by name."
            ),
            truncation_mode="head",
        )


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
        labeler = getattr(ctx.mcp, "public_tool_label", None)
        if callable(labeler):
            label = labeler(args.server, args.tool)
        else:
            secret_values = sensitive_env_values()
            label = (
                f"{mask_secrets(args.server, secret_values)}:"
                f"{mask_secrets(args.tool, secret_values)}"
            )
        if ctx.mcp is None:
            return ToolOutcome(
                tool="MCP",
                block_name=label,
                success=False,
                detail="no MCP servers are configured",
                continuation=_MCP_CONTINUATION,
                truncation_mode="head",
            )
        parameters = {"server": args.server, "operation": args.tool}
        auto_approved = bool(
            ctx.allow_auto_approve and ctx.mcp.is_auto_approved(args.server, args.tool)
        )
        if auto_approved:
            _audit_confirmation(ctx, tool="MCP", decision="preapproved", parameters=parameters)
        elif not _confirm(ctx, args, tool="MCP", parameters=parameters):
            if ctx.confirmer is None:
                return ToolOutcome(
                    tool="MCP",
                    block_name=label,
                    success=False,
                    detail="rejected: no interactive confirmation channel available",
                    continuation=_MCP_CONTINUATION,
                    truncation_mode="head",
                )
            return ToolOutcome(
                tool="MCP",
                block_name=label,
                success=False,
                detail=_denial_detail(ctx, f"MCP call {label} was not approved by the user"),
                continuation=_MCP_CONTINUATION,
                truncation_mode="head",
            )
        receipt = None
        # Legacy direct ToolContext callers without a task/store have no durable scope;
        # retain their compatibility path. Task-scoped protected calls fail closed.
        protected = not auto_approved and not (ctx.receipt_store is None and ctx.task_id is None)
        if protected:
            store = ctx.receipt_store
            if store is None:
                return ToolOutcome(
                    tool="MCP",
                    block_name=label,
                    success=False,
                    detail=_MCP_RECEIPT_UNAVAILABLE,
                    continuation=_MCP_CONTINUATION,
                    truncation_mode="head",
                )
            try:
                receipt = store.create_prepared(
                    task_id=ctx.task_id,
                    server_label=label.split(":", 1)[0],
                    tool_label=label.split(":", 1)[1] if ":" in label else label,
                    request_digest=canonical_request_digest(args.arguments),
                )
                _audit_receipt_transition(ctx, receipt, ctx.operation_id)
                receipt = store.mark_dispatched(receipt.action_id, receipt.revision)
                _audit_receipt_transition(ctx, receipt, ctx.operation_id)
            except (ReceiptError, ValueError, TypeError):
                return ToolOutcome(
                    tool="MCP",
                    block_name=label,
                    success=False,
                    detail=_MCP_RECEIPT_UNAVAILABLE,
                    continuation=_MCP_CONTINUATION,
                    truncation_mode="head",
                )
        try:
            result = ctx.mcp.call_tool(args.server, args.tool, args.arguments)
        except Exception:
            result = {"ok": False, "text": "MCP call failed", "dispatch_certainty": "unknown"}
        certainty = result.get("dispatch_certainty", "confirmed")
        if receipt is not None:
            try:
                if certainty == "unknown":
                    store = ctx.receipt_store
                    assert store is not None
                    updated = store.mark_unknown(
                        receipt.action_id, receipt.revision, "result_unknown"
                    )
                    _audit_receipt_transition(ctx, updated, ctx.operation_id)
                else:
                    store = ctx.receipt_store
                    assert store is not None
                    updated = store.mark_confirmed(
                        receipt.action_id,
                        receipt.revision,
                        "not_dispatched" if certainty == "not_dispatched" else "confirmed",
                        bool(result.get("ok")),
                        "no_dispatch" if certainty == "not_dispatched" else "protocol_response",
                    )
                    _audit_receipt_transition(ctx, updated, ctx.operation_id)
            except (ReceiptError, ValueError, TypeError):
                return ToolOutcome(
                    tool="MCP",
                    block_name=label,
                    success=False,
                    detail=_MCP_RECEIPT_UNAVAILABLE,
                    continuation=_MCP_CONTINUATION,
                    truncation_mode="head",
                )
        detail = _MCP_RESULT_UNKNOWN if certainty == "unknown" else result.get("text", "")
        return ToolOutcome(
            tool="MCP",
            block_name=label,
            success=bool(result.get("ok")),
            detail=detail,
            continuation=_MCP_CONTINUATION,
            truncation_mode="head",
        )


class MCPDescribeTool(Tool):
    """Read one available MCP tool's bounded public discovery metadata."""

    name = "MCPDescribe"
    args_model = MCPDescribeArgs
    risk_level = "low"

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, MCPDescribeArgs)
        if ctx.mcp is None:
            return ToolOutcome(
                tool=self.name,
                success=False,
                detail="MCP tool is unavailable",
                continuation=_MCP_DESCRIBE_CONTINUATION,
                truncation_mode="head",
            )
        info = ctx.mcp.describe_tool(args.server, args.tool)
        labeler = getattr(ctx.mcp, "public_tool_label", None)
        if callable(labeler):
            label = labeler(args.server, args.tool)
        else:
            secret_values = sensitive_env_values()
            label = (
                f"{mask_secrets(args.server, secret_values)}:"
                f"{mask_secrets(args.tool, secret_values)}"
            )
        if info is None:
            return ToolOutcome(
                tool=self.name,
                block_name=label,
                success=False,
                detail="MCP tool is unavailable",
                continuation=_MCP_DESCRIBE_CONTINUATION,
                truncation_mode="head",
            )
        try:
            schema = json.dumps(
                info.input_schema,
                ensure_ascii=True,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (RecursionError, TypeError, ValueError):
            schema = "{}"
        if len(schema) > _MCP_SCHEMA_CHARS:
            schema = "{}"
        description = _mcp_detail_text(mask_secrets(info.description, sensitive_env_values()))[
            :_MCP_DESCRIPTION_CHARS
        ]
        checker = getattr(ctx.mcp, "is_auto_approved", None)
        permission = (
            "auto-approved"
            if callable(checker) and checker(args.server, args.tool)
            else "confirmation required"
        )
        return ToolOutcome(
            tool=self.name,
            block_name=label,
            success=True,
            detail=(
                f"permission: {permission}\ndescription: {description}\ninput_schema: {schema}"
            ),
            continuation=_MCP_DESCRIBE_CONTINUATION,
            truncation_mode="head",
        )


class WebFetchTool(Tool):
    """GET a single http(s) URL through the SSRF guard; save the body to disk and
    return a small preview (docs/m10-usage-observability-and-tools.md §3.3/§3.4).

    Hybrid return: the full (possibly truncated) body is written under
    `ctx.allowed_root` so the model can read/process it with Exec/FileRead in a later
    round; `detail` carries only a preview so an untrusted page never rides fully into
    the model's context. This is the only outbound network path under
    restricted/container tiers (Exec cannot open sockets there), so the confirmer gate
    here is a real security boundary, not just UX (see FileWriteTool for the contrast).
    """

    name = "WebFetch"
    args_model = WebFetchArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, WebFetchArgs)
        if ctx.tier in ("restricted", "container"):
            if not _confirm(ctx, args, tool="WebFetch", parameters={"url": args.url}):
                if ctx.confirmer is None:
                    return ToolOutcome(
                        tool="WebFetch",
                        success=False,
                        detail="rejected: no interactive confirmation channel available",
                        continuation=_WEBFETCH_RETRY_CONTINUATION,
                        truncation_mode="head",
                    )
                return ToolOutcome(
                    tool="WebFetch",
                    success=False,
                    detail=_denial_detail(ctx, "WebFetch was not approved by the user"),
                    continuation=_WEBFETCH_RETRY_CONTINUATION,
                    truncation_mode="head",
                )
        try:
            url_validator = getattr(ctx.confirmer, "allows_web_url", None)
            if callable(url_validator) and ctx.tier in ("restricted", "container"):
                response = guarded_urlopen(args.url, url_validator=url_validator)
            else:
                response = guarded_urlopen(args.url)
            with response:
                content_type = response.headers.get_content_type()
                raw = response.read(_MAX_FETCH_BYTES + 1)
        except SSRFGuardError:
            return ToolOutcome(
                tool="WebFetch",
                success=False,
                detail="WebFetch blocked by network policy",
                continuation=_WEBFETCH_RETRY_CONTINUATION,
                truncation_mode="head",
            )
        except (OSError, http.client.HTTPException, ValueError):
            return ToolOutcome(
                tool="WebFetch",
                success=False,
                detail="WebFetch request failed",
                continuation=_WEBFETCH_RETRY_CONTINUATION,
                truncation_mode="head",
            )
        truncated = len(raw) > _MAX_FETCH_BYTES
        if truncated:
            raw = raw[:_MAX_FETCH_BYTES]
        masked = mask_secrets(raw.decode("utf-8", errors="replace"), sensitive_env_values())
        truncated_note = " (truncated at 1MB)" if truncated else ""
        try:
            digest = hashlib.sha256(args.url.encode()).hexdigest()[:12]
            ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".fetch")
            filename = f"webfetch_{digest}{ext}"
            dest = _validate_context_path(filename, ctx)
            dest.write_text(masked, encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return ToolOutcome(
                tool="WebFetch",
                success=False,
                detail="WebFetch response save failed",
                continuation=_WEBFETCH_RETRY_CONTINUATION,
                truncation_mode="head",
            )
        preview = masked[:_FETCH_PREVIEW_CHARS]
        preview_note = " (preview truncated)" if len(masked) > _FETCH_PREVIEW_CHARS else ""
        detail = (
            f"saved to {dest.name} ({len(masked.encode('utf-8'))} bytes, "
            f"{content_type}){truncated_note}\n"
            f"preview{preview_note}:\n{preview}"
        )
        continuation = (
            f"截断响应已保存至 {dest.name}；可使用 FileRead 读取"
            if truncated
            else f"完整响应已保存至 {dest.name}；可使用 FileRead 读取"
        )
        return ToolOutcome(
            tool="WebFetch",
            success=True,
            detail=detail,
            continuation=continuation,
            truncation_mode="head",
        )


def _validate_path(path: str, allowed_root: str) -> Path:
    """Resolve `path` (relative to allowed_root if not absolute) and require the
    realpath to be allowed_root itself or nested under it. Mirrors the predicate in
    _sandbox_worker.py's audit hook; implemented independently here since File tools
    run in the main process, not inside the sandboxed executor (docs/m10 §3.5)."""
    try:
        base = os.path.realpath(allowed_root)
        candidate = path if os.path.isabs(path) else os.path.join(allowed_root, path)
        resolved = os.path.realpath(candidate)
    except ValueError:
        raise ValueError("invalid file path") from None
    try:
        common = os.path.commonpath((base, resolved))
    except ValueError:
        raise PermissionError("path outside allowed root") from None
    if os.path.normcase(common) != os.path.normcase(base):
        raise PermissionError("path outside allowed root")
    return Path(resolved)


def _validate_context_path(path: str, ctx: ToolContext) -> Path:
    if os.path.isabs(path) or ctx.project_root is None:
        return _validate_path(path, ctx.allowed_root)
    return _validate_path(path, ctx.project_root)


def _display_path(path: Path, ctx: ToolContext) -> str:
    display_root = Path(os.path.realpath(ctx.project_root or ctx.allowed_root))
    try:
        return path.relative_to(display_root).as_posix()
    except ValueError:
        return path.name


def _root_binding_matches(root: Path, root_stat: os.stat_result) -> bool:
    try:
        current = os.stat(root, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(current.st_mode)
        and current.st_dev == root_stat.st_dev
        and current.st_ino == root_stat.st_ino
    )


def _write_file_safely(
    path: Path,
    root: Path,
    root_fd: int,
    root_stat: os.stat_result,
    content: str,
) -> str:
    """Write through directory descriptors so path components cannot be rebound."""
    relative = path.relative_to(root)
    if not relative.parts:
        raise OSError("file target required")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise OSError("safe file open is unavailable")

    current_fd = os.dup(root_fd)
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | directory_flag | no_follow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd

        if not _root_binding_matches(root, root_stat):
            raise OSError("project root binding changed")
        file_fd = os.open(
            relative.parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK | no_follow | getattr(os, "O_CLOEXEC", 0),
            0o666,
            dir_fd=current_fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OSError("file target is not regular")
            os.ftruncate(file_fd, 0)
            with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
                file_fd = -1
                handle.write(content)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
        if not _root_binding_matches(root, root_stat):
            raise OSError("project root binding changed")
    finally:
        os.close(current_fd)
    return relative.as_posix()


class FileReadTool(Tool):
    """Read a file under `ctx.allowed_root`, masking secrets before returning it.

    No confirmer gate by default (read is lower-risk than write); when a confirmer is
    configured for a non-trusted tier, this logs only the validated, masked project path.
    """

    name = "FileRead"
    args_model = FileReadArgs
    risk_level = "low"

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, FileReadArgs)
        try:
            resolved = _validate_context_path(args.path, ctx)
            if ctx.confirmer is not None and ctx.tier != "trusted":
                _logger.info(
                    "FileRead: %s",
                    mask_secrets(_display_path(resolved, ctx), sensitive_env_values()),
                )
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError, ValueError):
            return ToolOutcome(
                tool="FileRead",
                success=False,
                detail="FileRead failed",
                continuation=_FILE_READ_CONTINUATION,
                truncation_mode="head",
            )
        masked = mask_secrets(content, sensitive_env_values())
        return ToolOutcome(
            tool="FileRead",
            success=True,
            detail=masked,
            continuation=_FILE_READ_CONTINUATION,
            truncation_mode="head",
        )


class FileWriteTool(Tool):
    """Create or overwrite a file under `ctx.allowed_root` with unmasked content.

    SECURITY NOTE: this confirmer gate is UX-only, not a security boundary — model
    code run via ExecTool can already write anywhere under allowed_root without ever
    hitting this confirmer (Exec's writes are gated only by the executor backend's own
    audit hook, which already permits writes anywhere inside allowed_root). Contrast
    WebFetchTool, whose confirmer gate is a real boundary (see its docstring).
    """

    name = "FileWrite"
    args_model = FileWriteArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, FileWriteArgs)
        if ctx.tier in ("restricted", "container"):
            try:
                audit_candidate = args.path
                if not os.path.isabs(audit_candidate):
                    audit_candidate = os.path.join(
                        ctx.project_root or ctx.allowed_root, audit_candidate
                    )
                audit_path = _display_path(Path(os.path.realpath(audit_candidate)), ctx)
            except (OSError, ValueError):
                audit_path = "invalid"
            if not _confirm(
                ctx,
                args,
                tool="FileWrite",
                parameters={"path": audit_path, "content_length": len(args.content)},
            ):
                if ctx.confirmer is None:
                    return ToolOutcome(
                        tool="FileWrite",
                        success=False,
                        detail="rejected: no interactive confirmation channel available",
                    )
                return ToolOutcome(
                    tool="FileWrite",
                    success=False,
                    detail=_denial_detail(ctx, "FileWrite was not approved by the user"),
                )
        root_fd = -1
        try:
            root = Path(os.path.realpath(ctx.allowed_root))
            no_follow = getattr(os, "O_NOFOLLOW", None)
            directory_flag = getattr(os, "O_DIRECTORY", None)
            if no_follow is None or directory_flag is None:
                raise OSError("safe file open is unavailable")
            root_fd = os.open(
                root,
                os.O_RDONLY | directory_flag | no_follow | getattr(os, "O_CLOEXEC", 0),
            )
            root_stat = os.fstat(root_fd)
            resolved = _validate_context_path(args.path, ctx)
            _write_file_safely(resolved, root, root_fd, root_stat, args.content)
            display_path = _display_path(resolved, ctx)
        except PermissionError:
            return ToolOutcome(
                tool="FileWrite",
                success=False,
                detail="FileWrite path is outside project root",
            )
        except (OSError, ValueError):
            return ToolOutcome(tool="FileWrite", success=False, detail="FileWrite failed")
        finally:
            if root_fd >= 0:
                os.close(root_fd)
        return ToolOutcome(tool="FileWrite", success=True, detail=f"wrote {display_path}")


class FileListTool(Tool):
    """List entries directly under a directory, as paths relative to allowed_root.

    Returns relative paths only (never absolute) so the model is never told the host's
    real directory structure (docs/m10 §五 decision 9).
    """

    name = "FileList"
    args_model = FileListArgs
    risk_level = "low"

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, FileListArgs)
        try:
            resolved = _validate_context_path(args.path, ctx)
            entries = sorted(_display_path(path, ctx) for path in resolved.iterdir())
        except (PermissionError, OSError, ValueError):
            return ToolOutcome(
                tool="FileList",
                success=False,
                detail="FileList failed",
                continuation=_FILE_LIST_CONTINUATION,
                truncation_mode="head",
            )
        return ToolOutcome(
            tool="FileList",
            success=True,
            detail="\n".join(entries),
            continuation=_FILE_LIST_CONTINUATION,
            truncation_mode="head",
        )


class ToolRegistry:
    """Holds the registered tools; the single source of truth for both parsing
    (arg_schemas) and dispatch (get)."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._required_completion_tool: str | None = None

    def register(self, tool: Tool) -> None:
        """Register a tool by its declared name (later registration overrides)."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def required_completion_tool(self) -> str | None:
        return self._required_completion_tool

    def require_completion(self, tool_name: str) -> None:
        if tool_name not in self._tools:
            raise ValueError("required completion tool must be registered")
        current = self._required_completion_tool
        if current is not None and current != tool_name:
            raise ValueError(f"completion tool {current!r} is already required")
        self._required_completion_tool = tool_name

    def arg_schemas(self) -> dict[str, type[BaseModel]]:
        """name -> argument schema, for the protocol parser to validate against."""
        return {name: tool.args_model for name, tool in self._tools.items()}


def default_registry(
    *, with_mcp: bool = False, skills: SkillRegistry | None = None
) -> ToolRegistry:
    """The built-in tool set: Exec + Edit + Survey + WebFetch + FileRead/Write/List,
    plus MCP when `with_mcp` is set.

    Survey is always registered (so the model may always ask); it degrades gracefully
    to NEEDS_INFO when no asker is wired (headless). MCP is registered only when an
    MCPManager is configured (with_mcp=True) — it stays off the menu by default so the
    model is never told about a tool with no server behind it.
    """
    registry = ToolRegistry()
    registry.register(ExecTool())
    registry.register(EditTool())
    registry.register(SurveyTool())
    registry.register(RequestFilesystemAccessTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    if skills is not None and skills.catalog_prompt():
        registry.register(SkillTool(skills))
    if with_mcp:
        registry.register(MCPDescribeTool())
        registry.register(MCPTool())
    return registry
