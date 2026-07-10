"""Core data models for the model-client contract.

See docs/model-client-contract.md. These are the vendor-agnostic types the upper
layers (Task/Step loop) depend on; each concrete client translates them to/from
its backend. All types are plain pydantic models with no vendor coupling.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Message roles. v1 is text-only; multimodal content is deferred (M8)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """A single conversation message. content is plain text in v1."""

    role: Role
    content: str


class GenerationParams(BaseModel):
    """Per-call generation intent. The upper layer expresses intent with these
    unified fields; each client translates them per its own capability
    (see ModelCapability and docs/model-client-contract.md capability-gating)."""

    max_output_tokens: int | None = None
    temperature: float | None = None
    # Tri-state intent: "on" = prefer thinking, "off" = prefer no thinking (NOT a
    # hard guarantee — some models can't disable it), "auto" = use model default.
    thinking: Literal["on", "off", "auto"] = "auto"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    timeout_seconds: float = 120.0


class TokenUsage(BaseModel):
    """Token accounting for one call. Field names align with the Anthropic usage
    shape; OpenAI-compatible clients map their fields into this in their own code."""

    input_tokens: int = 0
    output_tokens: int = 0


class NativeToolCall(BaseModel):
    """One vendor-native tool call from an OpenAI-compatible response.

    `arguments` is kept as the raw JSON-encoded string the SDK returns (not parsed
    here) — parsing into ExecArgs/EditArgs is protocol.py's job (see ToolSource.OPENAI
    in text-protocol-spec.md), so this model stays free of tool-schema knowledge.
    """

    id: str
    name: str
    arguments: str


class AssistantMessage(Message):
    """A successful model response.

    A safety-classifier refusal is a normal 200 response with
    stop_reason == "refusal" (see docs/model-capability-matrix.md), so a refusal
    is an AssistantMessage — never a ClientError.
    """

    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    usage: TokenUsage
    stop_reason: str
    # Populated only by OpenAICompatibleClient when the response carries native
    # tool_calls (ToolSource.OPENAI dual-channel, M6). Empty for AnthropicClient and
    # for text-protocol-only replies.
    tool_calls: list[NativeToolCall] = Field(default_factory=list)


class ClientError(BaseModel):
    """A failed call. kind expresses the error nature; whether retries were already
    exhausted is conveyed by attempts (not a misleading `retryable` boolean).

    refusal is intentionally absent from kind — it is a successful response
    (AssistantMessage.stop_reason), handled by the task layer.
    """

    message: str
    kind: Literal[
        "network", "auth", "rate_limit", "invalid_request", "timeout", "unknown"
    ]
    attempts: int = Field(ge=1)


class ModelCapability(BaseModel):
    """Static capability declaration per model. Drives capability-gating so callers
    never branch on model name. Values sourced from docs/model-capability-matrix.md."""

    model_id: str
    context_window: int
    max_output_tokens: int
    supports_thinking: bool
    thinking_always_on: bool
    supports_effort: bool
    # Which concrete ModelClient this model is served by; cli.py dispatches on this
    # instead of branching on model_id/vendor strings.
    client_kind: Literal["anthropic", "openai_compatible"]
    # Some OpenAI-compatible models (the GPT-5 family) reject the legacy `max_tokens`
    # Chat Completions param and require `max_completion_tokens` instead. Anthropic
    # models always use "max_tokens" (AnthropicClient ignores this field).
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


