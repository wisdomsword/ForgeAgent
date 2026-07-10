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
from pydantic import BaseModel, Field, ValidationError

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


class ExecArgs(BaseModel):
    """Exec tool arguments. Provide at least one of name/code; v1 language is python."""

    name: str | None = None
    code: str | None = None
    language: Literal["python"] = "python"


class EditArgs(BaseModel):
    """Edit tool arguments: old/new string replacement on an existing block."""

    name: str
    old: str = Field(min_length=1)
    new: str
    replace_all: bool = False


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
    """A parsed tool call. v1 recognises only Exec and Edit."""

    id: str
    name: Literal["Exec", "Edit"]
    arguments: ExecArgs | EditArgs
    source: ToolCallSource = ToolCallSource.TEXT


# --- task status (front matter) ---------------------------------------------


class TaskStatus(BaseModel):
    """Optional task-completion signal declared in front matter."""

    completed: bool
    confidence: float | None = None
    status: Literal["refused", "need_info", "failed"] | None = None
    reason: str | None = None
    suggestion: str | None = None


class ParseResult(BaseModel):
    """Everything extracted from one model response."""

    task_status: TaskStatus | None = None
    code_blocks: list[CodeBlock] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    errors: list[ParseError] = Field(default_factory=list)
    # The response text with the front matter stripped off — a model that answers in
    # plain prose instead of calling Exec leaves its answer here, so callers can still
    # show it even though there is no tool outcome to report.
    body: str = ""


# --- parsing -----------------------------------------------------------------

_ARGS_BY_NAME: dict[str, type[BaseModel]] = {"Exec": ExecArgs, "Edit": EditArgs}


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
) -> None:
    """Validate one tool call's name+arguments and append it to result (or an error).

    Shared by both channels (text markers and native tool_calls) so Exec/Edit schema
    validation happens exactly once, regardless of where the call came from.
    """
    if name not in _ARGS_BY_NAME:
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.INVALID_FORMAT,
                message=f"Unknown or missing tool name {name!r} (v1 supports Exec/Edit)",
                raw=raw,
            )
        )
        return
    try:
        args = _ARGS_BY_NAME[name].model_validate(raw_arguments)
        # Exec requires at least one of name/code.
        if name == "Exec" and not args.name and not args.code:
            raise ValueError("Exec requires at least one of 'name' or 'code'")
        result.tool_calls.append(ToolCall(id=call_id, name=name, arguments=args, source=source))
    except (ValidationError, ValueError) as exc:
        result.errors.append(
            ParseError(
                error_type=ParseErrorType.VALIDATION_ERROR,
                message=f"Invalid arguments for {name}: {exc}",
                raw=raw,
            )
        )


def _parse_tool_calls(text: str, result: ParseResult) -> None:
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
            data.get("name"), call_id, data.get("arguments", {}), ToolCallSource.TEXT, raw, result
        )


def _parse_native_tool_calls(native_calls: list[NativeToolCall], result: ParseResult) -> None:
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
            call.name, call.id, arguments, ToolCallSource.OPENAI, call.arguments, result
        )


def parse(text: str, native_tool_calls: list[NativeToolCall] | None = None) -> ParseResult:
    """Parse one model response into code blocks, tool calls, and task status.

    `native_tool_calls` (ToolSource.OPENAI dual-channel, M6) is optional and comes
    from `AssistantMessage.tool_calls` — pass it through when the client populated it.
    Both channels can be present in the same response; results are merged into one
    `tool_calls` list, distinguished only by `ToolCall.source`.

    Errors are collected (not raised) so the caller can feed them back to the model.
    """
    result = ParseResult()
    body = _parse_front_matter(text, result)
    result.body = body.strip()
    _parse_code_blocks(body, result)
    _parse_tool_calls(body, result)
    if native_tool_calls:
        _parse_native_tool_calls(native_tool_calls, result)
    return result
