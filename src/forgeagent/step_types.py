"""Private data types and text projections used by the Step orchestrator."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, Field

from .attention import Attention
from .models import AssistantMessage, TokenUsage
from .protocol import MemoryCandidate
from .tools import ToolOutcome


class Termination(StrEnum):
    """Mechanical terminal state for a Step run, not an answer-quality judgment."""

    COMPLETED = "completed"
    ANSWERED_IN_PROSE = "answered_in_prose"
    REFUSED = "refused"
    NEEDS_INFO = "needs_info"
    BLOCKED = "blocked"
    FAILED = "failed"
    TRUNCATED = "truncated"
    EMPTY_RESPONSE = "empty_response"
    MAX_ROUNDS = "max_rounds"
    CLIENT_ERROR = "client_error"
    CANCELLED = "cancelled"


class RoundResult(BaseModel):
    """The parsed response and tool outcomes produced by one model round."""

    text: str
    body: str = ""
    stop_reason: str = ""
    usage: TokenUsage | None = None
    parse_errors: list[str] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    outcomes: list[ToolOutcome] = Field(default_factory=list)
    completed: bool = False
    stopped_reason: str | None = None
    stopped_detail: str = ""
    attention: Attention | None = None


def render_history_content(reply: AssistantMessage) -> str:
    """Render native tool calls as text markers for the provider-neutral history."""
    if not reply.tool_calls:
        return reply.content
    rendered = [reply.content] if reply.content else []
    for call in reply.tool_calls:
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError:
            arguments = call.arguments
        marker = {"id": call.id, "name": call.name, "arguments": arguments}
        rendered.append(f"<!-- ToolCall: {json.dumps(marker)} -->")
    return "\n".join(rendered)
