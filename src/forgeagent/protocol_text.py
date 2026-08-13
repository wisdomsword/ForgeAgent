"""Private text scanning stages for the Markdown and HTML-comment protocol."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

# Front matter: leading YAML block delimited by --- lines.
_FRONT_MATTER = re.compile(r"^\s*---\s*\n(.*?)\n---\s*", re.DOTALL)

# Code block: CodeBlockStart JSON, then a variable-length backtick fence (>=3),
# then CodeBlockEnd JSON. The matching fence preserves embedded shorter fences.
_CODE_BLOCK = re.compile(
    r"<!--\s*CodeBlockStart:\s*(\{.*?\})\s*-->\s*"
    r"(?P<ticks>`{3,})(\w+)?\s*\n(.*?)\n(?P=ticks)\s*"
    r"<!--\s*CodeBlockEnd:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

# Tool calls are scanned as complete comments before JSON is considered. This prevents
# an unterminated marker from consuming a later complete ToolCall.
_HTML_COMMENT = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
_TOOL_CALL_PREFIX = re.compile(r"^\s*ToolCall:\s*(?P<payload>.*)\Z", re.DOTALL)
_MEMORY = re.compile(r"<!--\s*Memory:\s*(.*?)\s*-->", re.DOTALL)
_MARKDOWN_FENCE = re.compile(
    r"^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=fence)[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_TODO_WRITE_ENVELOPE = re.compile(
    r"^[ \t]*todo_write[ \t]*\r?\n[ \t]*Params:[ \t]*(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_JSON_OBJECT_AT_LINE_START = re.compile(r"^[ \t]*(?=\{)", re.MULTILINE)


def split_front_matter(text: str) -> tuple[str | None, str]:
    """Return leading front-matter YAML, if any, and the remaining response body."""
    match = _FRONT_MATTER.match(text)
    if match is None:
        return None, text
    return match.group(1), text[match.end() :]


def iter_code_block_parts(text: str) -> Iterator[tuple[str, str | None, str, str]]:
    """Yield CodeBlock metadata JSON, optional language, body, and end metadata JSON."""
    for match in _CODE_BLOCK.finditer(text):
        start_json, _ticks, language, code, end_json = match.groups()
        yield start_json, language, code, end_json


def iter_tool_call_payloads(text: str) -> Iterator[str]:
    """Yield payloads from complete ToolCall comment boundaries, in source order."""
    for match in _HTML_COMMENT.finditer(text):
        marker = _TOOL_CALL_PREFIX.match(match.group("body"))
        if marker is not None:
            yield marker.group("payload").strip()


def extract_memory_payloads(text: str) -> tuple[list[str], str]:
    """Return Memory marker payloads and display text with those markers removed."""
    return [match.group(1) for match in _MEMORY.finditer(text)], _MEMORY.sub("", text)


def has_unsupported_external_tool_syntax(text: str) -> bool:
    """Detect executable external-agent envelopes in visible non-fenced prose."""
    visible_text = _MARKDOWN_FENCE.sub("", text)
    if _TODO_WRITE_ENVELOPE.search(visible_text) is not None:
        return True
    decoder = json.JSONDecoder()
    for match in _JSON_OBJECT_AT_LINE_START.finditer(visible_text):
        try:
            value, end = decoder.raw_decode(visible_text[match.end() :])
        except json.JSONDecodeError:
            continue
        command = value.get("cmd") if isinstance(value, dict) else None
        if (
            isinstance(command, str)
            and command.strip()
            and not visible_text[match.end() + end :].strip()
        ):
            return True
    return False
