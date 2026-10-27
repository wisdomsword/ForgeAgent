"""Private text scanning stages for the Markdown and HTML-comment protocol."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

# Front matter: a leading YAML document fenced by --- lines, emitted as the very
# first thing in a final response.
#   delimiters allow horizontal whitespace only, because they are line-oriented
#   the closing delimiter must begin a line, so a horizontal rule in the body
#     cannot terminate the front matter early
#   the YAML body is lazy, so the first closing delimiter wins
#   the trailing newline is optional and consumed, keeping the returned body free
#     of a leading blank line
_FRONT_MATTER = re.compile(
    r"""
    ^[ \t]*---[ \t]*\r?\n
    (?P<yaml>.*?)
    [ \t]*\r?\n[ \t]*---[ \t]*\r?\n?
    """,
    re.DOTALL | re.VERBOSE,
)


def _marker_comment(marker: str, group: str) -> str:
    """Fragment matching one marker comment: ``<!-- MARKER: {"json"} -->``.

    The payload is lazy so whitespace between the marker name and the braces never
    leaks into the JSON. ``group`` names that payload for the caller.
    """
    return rf"<!--\s*{marker}[ \t]*:[ \t]*(?P<{group}>\{{.*?\}})[ \t]*-->"


# A code block pairs a CodeBlockStart marker with a CodeBlockEnd marker around a
# backtick-fenced source, optionally naming a language on the opening fence line.
#   the fence run is captured and back-referenced, so a shorter fence nested in the
#     body cannot terminate the block
#   the closing fence may be indented, as Markdown allows
_CODE_BLOCK = re.compile(
    _marker_comment("CodeBlockStart", "start_meta")
    + r"\s*(?P<fence>`{3,})[ \t]*(?P<language>\w+)?[ \t]*\r?\n"
    + r"(?P<body>.*?)\r?\n[ \t]*(?P=fence)\s*"
    + _marker_comment("CodeBlockEnd", "end_meta"),
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
        yield match["start_meta"], match["language"], match["body"], match["end_meta"]


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
