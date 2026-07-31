"""Text protocol parser: CodeBlock / ToolCall HTML-comment markup.

See docs/text-protocol-spec.md. The protocol is plain Markdown + HTML comments, so
it works with any model that emits Markdown (no vendor function-calling dependency).
v1 defines only the Exec and Edit tools (no SubTask/MCP/Survey).

Parsing is recoverable: malformed JSON, missing fields, and name mismatches produce
structured ParseError entries rather than crashing, so the errors can be fed back to
the model for correction.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .models import NativeToolCall

# --- markup patterns ---------------------------------------------------------

# Front matter: leading YAML block delimited by --- lines.
_FRONT_MATTER = re.compile(r"^\s*---\s*\n(.*?)\n---\s*", re.DOTALL)

# Code block: CodeBlockStart JSON, then a variable-length backtick fence (>=3),
# then CodeBlockEnd JSON. The backreference (?P=ticks) requires the closing fence
# to match the opening fence length, so code containing ``` does not close early.
_CODE_BLOCK = re.compile(
    r"<!--\s*CodeBlockStart:\s*(\{.*?\})\s*-->\s*"
    r"(?P<ticks>`{3,})(\w+)?\s*\n(.*?)\n(?P=ticks)\s*"
    r"<!--\s*CodeBlockEnd:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

# Tool call: a single HTML comment carrying a JSON object.
_TOOL_CALL = re.compile(r"<!--\s*ToolCall:\s*(\{.*?\})\s*-->", re.DOTALL)
_MEMORY = re.compile(r"<!--\s*Memory:\s*(.*?)\s*-->", re.DOTALL)


class ParseErrorType(StrEnum):
    JSON_DECODE_ERROR = "json_decode_error"
    INVALID_FORMAT = "invalid_format"
    VALIDATION_ERROR = "validation_error"


class ParseError(BaseModel):
    """A structured parse error, suitable for feeding back to the model."""

    error_type: ParseErrorType
    message: str
    raw: str = ""


# --- tool argument schemas ---------------------------------------------------


class SurveyArgs(BaseModel):
    """Survey tool arguments: ask the user a question mid-task.

    Inline `question` (not a code-block reference) — Survey is "part of the conversation,
    not a data structure" (docs/m7-tools-mcp-survey.md §3.5). `options` is optional and
    lets the model pose a multiple-choice question, which pairs well with the CLI's
    confirmation menu; omit it for free-text questions.
    """

    question: str = Field(min_length=1)
    options: list[str] | None = None


class SkillArgs(BaseModel):
    """Read one validated section of a discovered skill."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    section: Literal[
        "full", "steps", "failure_branches", "completion_criteria", "exit_conditions"
    ] = "full"


class MCPArgs(BaseModel):
    """MCP tool arguments: call a `tool` on a named `server` with `arguments`.

    A single `MCP` tool routed by `{server, tool}` (not one flat name per MCP tool) — so
    two servers exposing the same tool name never collide, and routing stays a structured
    protocol choice rather than a name the model must memorise (docs/m7 §3.4, decision 5).
    `arguments` is a free-form dict validated by the target MCP tool's own schema, not here.
    """

    server: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPDescribeArgs(BaseModel):
    """Read one discovered MCP tool's public metadata without calling the server."""

    server: str = Field(min_length=1)
    tool: str = Field(min_length=1)


class ExecArgs(BaseModel):
    """Exec tool arguments. Provide at least one of name/code; v1 language is python."""

    name: str | None = None
    code: str | None = None
    language: Literal["python"] = "python"

    @model_validator(mode="after")
    def _require_name_or_code(self) -> ExecArgs:
        # Exec's own cross-field rule lives on Exec (not in the parser) so the parser can
        # validate any tool's schema uniformly — a failing rule raises ValidationError,
        # which the parser already turns into a structured ParseError.
        if not self.name and not self.code:
            raise ValueError("Exec requires at least one of 'name' or 'code'")
        return self


class EditArgs(BaseModel):
    """Edit tool arguments: old/new string replacement on an existing block."""

    name: str
    old: str = Field(min_length=1)
    new: str
    replace_all: bool = False


class WebFetchArgs(BaseModel):
    """WebFetch tool arguments: GET-only fetch of a single http(s) URL.

    No method/headers fields by design (docs/m10 §五 decision 10) — a generic HTTP
    client belongs to MCP, not WebFetch; GET-only keeps the SSRF guard's read-only
    threat model intact.
    """

    url: str


class FileReadArgs(BaseModel):
    """FileRead tool arguments: path is relative to ctx.allowed_root unless absolute."""

    path: str


class FileWriteArgs(BaseModel):
    """FileWrite tool arguments: overwrites (or creates) the file at path."""

    path: str
    content: str


class FileListArgs(BaseModel):
    """FileList tool arguments: lists entries directly under path (default: root)."""

    path: str = "."


class CodeBlock(BaseModel):
    """A parsed code block."""

    name: str = Field(min_length=1)
    language: str
    code: str
    path: str | None = None


class ToolCallSource(StrEnum):
    """Where a ToolCall's raw data came from — the text protocol markers, or a
    vendor's native tool_calls channel (ToolSource.OPENAI, M6). Downstream dispatch
    (step.py) never branches on this; it exists only for feedback/debugging."""

    TEXT = "text"
    OPENAI = "openai"


class ToolCall(BaseModel):
    """A parsed tool call. `name` is validated against the registered tool set passed to
    parse() (a plain str, not a Literal, so registering a tool is enough to make it
    parseable); `arguments` is the validated instance of that tool's schema."""

    id: str
    name: str
    arguments: BaseModel
    source: ToolCallSource = ToolCallSource.TEXT


class MemoryCandidate(BaseModel):
    """One explicit, structured fact proposed for the runtime memory store."""

    scope: Literal["session", "project"]
    kind: Literal["fact", "preference", "decision", "procedure"]
    key: str = Field(min_length=1)
    content: str = Field(min_length=1)


# --- task status (front matter) ---------------------------------------------


class TaskStatus(BaseModel):
    """Optional task-completion signal declared in front matter."""

    completed: bool
    confidence: float | None = None
    status: Literal["refused", "need_info", "blocked", "failed"] | None = None
    reason: str | None = None
    suggestion: str | None = None


class ParseResult(BaseModel):
    """Everything extracted from one model response."""

    task_status: TaskStatus | None = None
    code_blocks: list[CodeBlock] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    errors: list[ParseError] = Field(default_factory=list)
    # The response text with the front matter stripped off — a model that answers in
    # plain prose instead of calling Exec leaves its answer here, so callers can still
    # show it even though there is no tool outcome to report.
    body: str = ""


def _merge_tool_calls(result: ParseResult) -> None:
    """Keep one explicit call ID and fail closed when channels disagree."""
    by_id: dict[str, ToolCall] = {}
    order: list[str] = []
    conflicted: set[str] = set()
    for call in result.tool_calls:
        if call.id not in by_id:
            by_id[call.id] = call
            order.append(call.id)
            continue
        previous = by_id[call.id]
        if previous.name == call.name and previous.arguments.model_dump(
            mode="python"
        ) == call.arguments.model_dump(mode="python"):
            continue
        conflicted.add(call.id)
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.INVALID_FORMAT,
                message=f"Conflicting tool call id {call.id!r}; dispatch suppressed",
                raw="",
            )
        )
    result.tool_calls = [by_id[call_id] for call_id in order if call_id not in conflicted]


# --- parsing -----------------------------------------------------------------

# Default tool schema table (the pre-M7 built-in set). parse() accepts a `tool_schemas`
# override so a ToolRegistry can extend the recognised tools (MCP/Survey) without editing
# this module — see docs/m7-tools-mcp-survey.md §3.2.
_DEFAULT_ARGS_BY_NAME: dict[str, type[BaseModel]] = {"Exec": ExecArgs, "Edit": EditArgs}


def _parse_front_matter(text: str, result: ParseResult) -> str:
    """Extract and parse leading YAML front matter; return the body after it.

    A malformed front matter is recorded as an error but does not stop body parsing.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return text
    body = text[match.end() :]
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.INVALID_FORMAT,
                message=f"Invalid YAML front matter: {exc}",
                raw=match.group(1),
            )
        )
        return body
    if isinstance(data, dict) and "task_status" in data:
        try:
            result.task_status = TaskStatus.model_validate(data["task_status"])
        except ValidationError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.VALIDATION_ERROR,
                    message=f"Invalid task_status: {exc}",
                    raw=str(data.get("task_status")),
                )
            )
    return body


def _parse_code_blocks(text: str, result: ParseResult) -> None:
    for match in _CODE_BLOCK.finditer(text):
        start_json, _ticks, lang, code, end_json = match.groups()
        try:
            start_meta = json.loads(start_json)
            end_meta = json.loads(end_json)
        except json.JSONDecodeError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.JSON_DECODE_ERROR,
                    message=f"Invalid JSON in code block markup: {exc}",
                    raw=match.group(0)[:200],
                )
            )
            continue
        start_name, end_name = start_meta.get("name"), end_meta.get("name")
        if not start_name or start_name != end_name:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.INVALID_FORMAT,
                    message=f"CodeBlockStart/End name mismatch: {start_name!r} vs {end_name!r}",
                    raw=match.group(0)[:200],
                )
            )
            continue
        try:
            result.code_blocks.append(
                CodeBlock(
                    name=start_name,
                    language=lang or "python",
                    code=code,
                    path=start_meta.get("path"),
                )
            )
        except ValidationError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.VALIDATION_ERROR,
                    message=f"Invalid code block: {exc}",
                    raw=start_json,
                )
            )


def _build_tool_call(
    name: Any,
    call_id: str,
    raw_arguments: Any,
    source: ToolCallSource,
    raw: str,
    result: ParseResult,
    tool_schemas: dict[str, type[BaseModel]],
) -> None:
    """Validate one tool call's name+arguments and append it to result (or an error).

    Shared by both channels (text markers and native tool_calls) so schema validation
    happens exactly once, regardless of where the call came from. `tool_schemas` is the
    registered tool set (name -> arg schema); a name outside it is a structured error.
    """
    if name not in tool_schemas:
        known = "/".join(tool_schemas) or "(none)"
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.INVALID_FORMAT,
                message=f"Unknown or missing tool name {name!r} (registered tools: {known})",
                raw=raw,
            )
        )
        return
    try:
        args = tool_schemas[name].model_validate(raw_arguments)
        result.tool_calls.append(ToolCall(id=call_id, name=name, arguments=args, source=source))
    except (ValidationError, ValueError) as exc:
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.VALIDATION_ERROR,
                message=f"Invalid arguments for {name}: {exc}",
                raw=raw,
            )
        )


def _parse_tool_calls(
    text: str, result: ParseResult, tool_schemas: dict[str, type[BaseModel]]
) -> None:
    for match in _TOOL_CALL.finditer(text):
        raw = match.group(1)
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.JSON_DECODE_ERROR,
                    message=f"Invalid JSON in ToolCall: {exc}",
                    raw=raw,
                )
            )
            continue
        call_id = data.get("id") or uuid4().hex
        _build_tool_call(
            data.get("name"),
            call_id,
            data.get("arguments", {}),
            ToolCallSource.TEXT,
            raw,
            result,
            tool_schemas,
        )


def _parse_memory_candidates(text: str, result: ParseResult) -> str:
    """Extract explicit Memory markers and return display text without them."""
    for match in _MEMORY.finditer(text):
        raw = match.group(1)
        try:
            result.memory_candidates.append(MemoryCandidate.model_validate(json.loads(raw)))
        except json.JSONDecodeError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.JSON_DECODE_ERROR,
                    message=f"Invalid JSON in Memory marker: {exc}",
                    raw=raw,
                )
            )
        except ValidationError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.VALIDATION_ERROR,
                    message=f"Invalid Memory candidate: {exc}",
                    raw=raw,
                )
            )
    return _MEMORY.sub("", text)


def _parse_native_tool_calls(
    native_calls: list[NativeToolCall],
    result: ParseResult,
    tool_schemas: dict[str, type[BaseModel]],
) -> None:
    """Parse ToolSource.OPENAI native tool_calls (M6) — the dual-channel counterpart
    to _parse_tool_calls. `arguments` is a JSON-encoded string on the wire (verified
    identical shape across OpenAI/GLM/DeepSeek); malformed JSON or a failing schema
    produces a structured ParseError, same as the text channel, never a crash.
    """
    for call in native_calls:
        try:
            arguments: Any = json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            result.errors.append(
                ParseError(
                    error_type=ParseErrorType.JSON_DECODE_ERROR,
                    message=f"Invalid JSON in native tool_call arguments: {exc}",
                    raw=call.arguments,
                )
            )
            continue
        _build_tool_call(
            call.name,
            call.id,
            arguments,
            ToolCallSource.OPENAI,
            call.arguments,
            result,
            tool_schemas,
        )


def parse(
    text: str,
    native_tool_calls: list[NativeToolCall] | None = None,
    tool_schemas: dict[str, type[BaseModel]] | None = None,
) -> ParseResult:
    """Parse one model response into code blocks, tool calls, and task status.

    `native_tool_calls` (ToolSource.OPENAI dual-channel, M6) is optional and comes
    from `AssistantMessage.tool_calls` — pass it through when the client populated it.
    Both channels can be present in the same response; results are merged into one
    `tool_calls` list, distinguished only by `ToolCall.source`.

    `tool_schemas` (name -> arg schema) is the registered tool set to validate against;
    it defaults to the built-in Exec/Edit set, so `parse(text)` behaves as before M7.
    A ToolRegistry passes `registry.arg_schemas()` to make its tools (MCP/Survey) known.

    Errors are collected (not raised) so the caller can feed them back to the model.
    """
    schemas = _DEFAULT_ARGS_BY_NAME if tool_schemas is None else tool_schemas
    result = ParseResult()
    body = _parse_front_matter(text, result)
    body = _parse_memory_candidates(body, result)
    result.body = body.strip()
    _parse_code_blocks(body, result)
    _parse_tool_calls(body, result, schemas)
    if native_tool_calls:
        _parse_native_tool_calls(native_tool_calls, result, schemas)
    _merge_tool_calls(result)
    return result
