"""OpenAI-compatible client (Chat Completions schema) with capability-gating.

See docs/model-client-contract.md and docs/m6-openai-compatible-client.md. One class
serves any OpenAI-compatible endpoint (OpenAI itself, or a Chat-Completions-compatible
gateway such as LLM) — vendor distinction lives entirely in `base_url` +
`model_registry.py`'s capability registry, never in an if/else on model or vendor
name here.

Mirrors anthropic_client.py's pattern: injectable `transport` for key-free unit tests,
lazy SDK import inside the default transport, duck-typed response parsing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .client import ModelClient
from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    NativeToolCall,
    TokenUsage,
)
from .transport_errors import TransportError, classify_transport_exception, run_with_retries

__all__ = ["OpenAICompatibleClient"]

# request dict + timeout -> raw response object (duck-typed: .choices[0].message/.usage)
Transport = Callable[[dict, float], Any]


def _render_content(content: str | list) -> str | list[dict]:
    """Translate Message.content to the OpenAI-compatible wire shape.

    A plain string passes through unchanged (pre-M9 path). A ContentItem list becomes
    the `image_url` data-URI shape (verified against the real API,
    docs/m9-streaming-multimodal-commands.md §八 S3).
    """
    if isinstance(content, str):
        return content
    parts: list[dict] = []
    for item in content:
        if item.type == "text":
            parts.append({"type": "text", "text": item.text})
        else:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{item.media_type};base64,{item.data}"},
                }
            )
    return parts


def _contains_image(messages: list[Message]) -> bool:
    return any(
        isinstance(msg.content, list) and any(item.type == "image" for item in msg.content)
        for msg in messages
    )


class OpenAICompatibleClient(ModelClient):
    """Client for any OpenAI Chat Completions-compatible endpoint.

    `base_url` must already include the `/v1` path segment where the vendor requires
    it (the OpenAI SDK does not append it automatically, unlike the Anthropic SDK) —
    this is a user configuration convention, not something this client normalizes.
    """

    def __init__(
        self,
        capability: ModelCapability,
        *,
        api_key: str,
        default_params: GenerationParams | None = None,
        max_attempts: int = 3,
        backoff_base_seconds: float = 1.0,
        backoff_factor: float = 2.0,
        base_url: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._capability = capability
        self._api_key = api_key
        self._default_params = default_params or GenerationParams()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_factor = backoff_factor
        self._base_url = base_url
        self._transport = transport or self._make_sdk_transport()
        self._sleep = sleep

    @property
    def capability(self) -> ModelCapability:
        return self._capability

    def build_request(self, messages: list[Message], params: GenerationParams) -> dict:
        """Translate intent to a Chat Completions request dict via capability-gating.

        Unlike Anthropic, `system`-role messages stay inline in `messages` (no
        top-level split). Token-limit key and reasoning params are picked per
        `self._capability`, mirroring anthropic_client.AnthropicClient.build_request.
        """
        cap = self._capability
        turns = [
            {"role": msg.role.value, "content": _render_content(msg.content)}
            for msg in messages
        ]
        request: dict[str, Any] = {"model": cap.model_id, "messages": turns}
        request[cap.max_tokens_param] = params.max_output_tokens or cap.max_output_tokens
        if params.temperature is not None:
            request["temperature"] = params.temperature

        # thinking: only send an explicit param to request it ("on") on a model that
        # supports it and is not always-on, mirroring AnthropicClient's rule. `thinking`
        # is not part of the OpenAI Chat Completions schema, so it must travel inside
        # `extra_body` (verified against the installed SDK's create() signature) rather
        # than as a bare top-level kwarg. Wire shape (GLM/DeepSeek): {"type": "enabled"}.
        if params.thinking == "on" and cap.supports_thinking and not cap.thinking_always_on:
            request["extra_body"] = {"thinking": {"type": "enabled"}}

        # effort: OpenAI-compatible protocol's param name is "reasoning_effort", not
        # Anthropic's "effort" (verified against gpt-5.4-mini/gpt-5.5 directly).
        # Dropped entirely when unsupported (sending it errors on such models).
        if params.effort is not None and cap.supports_effort:
            request["reasoning_effort"] = params.effort

        return request

    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError:
        if _contains_image(messages) and not self._capability.supports_images:
            return ClientError(
                message=(
                    f"model {self._capability.model_id!r} does not support image input"
                ),
                kind="invalid_request",
                attempts=1,
            )
        effective = params if params is not None else self._default_params
        request = self.build_request(messages, effective)
        return run_with_retries(
            transport=self._transport,
            request=request,
            timeout_seconds=effective.timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_base_seconds=self._backoff_base,
            backoff_factor=self._backoff_factor,
            sleep=self._sleep,
            parse_response=_parse_response,
        )

    def _make_sdk_transport(self) -> Transport:
        """Build the default transport that calls the OpenAI SDK.

        Imported lazily so the module (and tests using an injected transport) do not
        require the SDK to be installed or constructable.
        """

        def transport(request: dict, timeout_seconds: float) -> Any:
            import openai

            client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
            try:
                return client.chat.completions.create(timeout=timeout_seconds, **request)
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return transport


def _parse_response(raw: Any) -> AssistantMessage:
    """Parse a raw Chat Completions response (duck-typed) into an AssistantMessage.

    `finish_reason` is passed through verbatim as `stop_reason` (OpenAI's values
    "stop"/"length"/"content_filter"/"tool_calls" differ from Anthropic's, but the
    field is free-form text — see docs/m6-openai-compatible-client.md §三).

    `message.tool_calls` (ToolSource.OPENAI dual-channel, M6), when present, becomes
    `AssistantMessage.tool_calls` — verified identical wire shape across OpenAI/GLM/
    DeepSeek: {id, type:"function", function:{name, arguments}}.
    """
    choice = raw.choices[0]
    message = choice.message
    content = getattr(message, "content", None) or ""
    usage = getattr(raw, "usage", None)
    token_usage = TokenUsage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        # Nested under prompt_tokens_details, which may be absent entirely on
        # providers that don't report prompt caching.
        cached_tokens=getattr(
            getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0
        )
        or 0,
    )
    native_calls = [
        NativeToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
        for call in getattr(message, "tool_calls", None) or []
    ]
    return AssistantMessage(
        content=content,
        usage=token_usage,
        stop_reason=getattr(choice, "finish_reason", "") or "",
        tool_calls=native_calls,
    )
