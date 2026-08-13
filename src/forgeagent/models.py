"""Core data models for the model-client contract.

See docs/model-client-contract.md. These are the vendor-agnostic types the upper
layers (Task/Step loop) depend on; each concrete client translates them to/from
its backend. All types are plain pydantic models with no vendor coupling.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, FiniteFloat

PositiveInt = Annotated[int, Field(gt=0)]
PositiveFiniteFloat = Annotated[FiniteFloat, Field(gt=0)]


class Role(StrEnum):
    """Message roles. Message content is text or a text+image item list (M9);
    audio/video input is deferred (docs/m9-streaming-multimodal-commands.md §九)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class TextItem(BaseModel):
    """One text part of a multimodal message."""

    type: Literal["text"] = "text"
    text: str


class ImageItem(BaseModel):
    """One image part of a multimodal message, as base64-encoded bytes.

    Vendor-neutral: each client translates this to its own wire shape (Anthropic
    content blocks vs OpenAI data-URI). Loading/validation (magic-number sniffing,
    per-image and per-request caps) lives in image_input.py.
    """

    type: Literal["image"] = "image"
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str


ContentItem = Annotated[TextItem | ImageItem, Field(discriminator="type")]


class Message(BaseModel):
    """A single conversation message.

    content stays a plain string on the main path; only messages that actually
    carry images use the list form (docs/m9 §3.4), so every pre-M9 construction
    site keeps working unchanged.
    """

    role: Role
    content: str | list[ContentItem]


class GenerationParams(BaseModel):
    """Per-call generation intent. The upper layer expresses intent with these
    unified fields; each client translates them per its own capability
    (see ModelCapability and docs/model-client-contract.md capability-gating)."""

    max_output_tokens: PositiveInt | None = None
    temperature: FiniteFloat | None = None
    # Tri-state intent: "on" = prefer thinking, "off" = prefer no thinking (NOT a
    # hard guarantee — some models can't disable it), "auto" = use model default.
    thinking: Literal["on", "off", "auto"] = "auto"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    timeout_seconds: PositiveFiniteFloat = 120.0


class TokenUsage(BaseModel):
    """Token accounting for one call. Field names align with the Anthropic usage
    shape; OpenAI-compatible clients map their fields into this in their own code."""

    input_tokens: int = 0
    output_tokens: int = 0
    # Cache-related input tokens (Anthropic: cache_creation + cache_read combined;
    # OpenAI-compatible: prompt_tokens_details.cached_tokens). See docs/m10 §3.1.
    cached_tokens: int = 0
    # Billed reasoning/thinking output tokens. OpenAI-compatible: max of
    # usage.completion_tokens_details.reasoning_tokens and the non-standard top-level
    # usage.reasoning_tokens — some providers put a fake zero in the standard nested
    # location and the real value at top level, or vice versa (docs/m9 §8 S2).
    # Anthropic: always 0 (thinking is billed inside output_tokens, never split out).
    reasoning_tokens: int = 0
    total_prompt_tokens: int | None = Field(default=None, exclude=True, repr=False)
    cache_rate_unavailable: bool = Field(default=False, exclude=True, repr=False)

    @property
    def cache_hit_rate(self) -> float | None:
        """Return a valid cached-prompt ratio without normalizing bad provider data."""
        total = self.total_prompt_tokens
        if (
            self.cache_rate_unavailable
            or total is None
            or total <= 0
            or self.cached_tokens < 0
            or self.cached_tokens > total
        ):
            return None
        return self.cached_tokens / total

    def accumulate_cache_rate(self, usage: TokenUsage) -> None:
        """Add one successful call's prompt denominator to this mutable accumulator."""
        denominator = usage.total_prompt_tokens
        if denominator is None:
            self.cache_rate_unavailable = True
            self.total_prompt_tokens = None
            return
        if usage.cached_tokens < 0 or usage.cached_tokens > denominator:
            self.cache_rate_unavailable = True
        if self.total_prompt_tokens is None:
            if not self.cache_rate_unavailable:
                self.total_prompt_tokens = denominator
            return
        self.total_prompt_tokens += denominator


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
    kind: Literal["network", "auth", "rate_limit", "invalid_request", "timeout", "unknown"]
    attempts: int = Field(ge=1)


class ModelCapability(BaseModel):
    """Static capability declaration per model. Drives capability-gating so callers
    never branch on model name. Values sourced from docs/model-capability-matrix.md."""

    model_id: str
    context_window: PositiveInt
    max_output_tokens: PositiveInt
    supports_thinking: bool
    thinking_always_on: bool
    supports_effort: bool
    # Whether the model accepts image input (ImageItem). Clients refuse a request
    # carrying images for a model without this (ClientError, never a silent drop).
    supports_images: bool = False
    # Which concrete ModelClient this model is served by; cli.py dispatches on this
    # instead of branching on model_id/vendor strings.
    client_kind: Literal["anthropic", "openai_compatible"]
    # Some OpenAI-compatible models (the GPT-5 family) reject the legacy `max_tokens`
    # Chat Completions param and require `max_completion_tokens` instead. Anthropic
    # models always use "max_tokens" (AnthropicClient ignores this field).
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


# --- Streaming (M9) ---------------------------------------------------------


class StreamEventKind(StrEnum):
    """Kinds of events yielded by ModelClient.stream()."""

    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    DONE = "done"


class StreamEvent(BaseModel):
    """One streaming event. TEXT_DELTA/THINKING_DELTA carry incremental text;
    DONE is the terminal event and carries the complete AssistantMessage —
    structurally identical to what complete() would return for the same request."""

    kind: StreamEventKind
    text: str = ""
    message: AssistantMessage | None = None
