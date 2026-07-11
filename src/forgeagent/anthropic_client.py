"""Anthropic native client with capability-gating.

See docs/model-client-contract.md. The network layer is injectable (a `transport`
callable) so capability-gating and response parsing are pure and unit-testable
without a real key or network. The default transport wraps the Anthropic SDK.

Capability-gating (the contract's core): the caller never branches on model name.
Each client translates GenerationParams intent per its own `capability`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .client import ModelClient
from .model_discovery import resolve_effective_model_id
from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    Role,
    TokenUsage,
)
from .transport_errors import TransportError, classify_transport_exception, run_with_retries

__all__ = [
    "AnthropicClient",
    "TransportError",
    "classify_transport_exception",
]

# request dict + timeout -> raw response object (duck-typed: .content/.stop_reason/.usage)
Transport = Callable[[dict, float], Any]


def _split_system(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """Anthropic takes `system` as a top-level param, not a messages entry.

    Concatenate all SYSTEM messages into one top-level string; keep user/assistant
    turns in the messages array. The upper layer stays vendor-agnostic (always a flat
    list[Message]); this split is absorbed here.
    """
    system_parts: list[str] = []
    turns: list[dict] = []
    for msg in messages:
        if msg.role is Role.SYSTEM:
            system_parts.append(msg.content)
        else:
            turns.append({"role": msg.role.value, "content": msg.content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, turns


class AnthropicClient(ModelClient):
    """Anthropic-backed client. Pass a `transport` for tests; the default wraps the SDK."""

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
        """Translate intent to an Anthropic request dict via capability-gating.

        Rules (docs/model-client-contract.md): thinking is only sent when the model
        supports it and the intent is "on" and it is not always-on; effort is dropped
        when unsupported; max_output_tokens falls back to the model's ceiling.
        """
        cap = self._capability
        system, turns = _split_system(messages)
        request: dict[str, Any] = {
            "model": cap.model_id,
            "messages": turns,
            "max_tokens": params.max_output_tokens or cap.max_output_tokens,
        }
        if system is not None:
            request["system"] = system
        if params.temperature is not None:
            request["temperature"] = params.temperature

        # thinking: only send an explicit param to request it ("on") on a model that
        # supports it and is not always-on. "auto" and "off" both omit the param
        # (auto = model default; off is best-effort and cannot be guaranteed).
        if (
            params.thinking == "on"
            and cap.supports_thinking
            and not cap.thinking_always_on
        ):
            request["thinking"] = {"type": "adaptive"}

        # effort: dropped entirely when unsupported (sending it errors on such models).
        # Wire shape: nested under `output_config` (verified against installed SDK's
        # OutputConfigParam), not a bare top-level `effort` kwarg.
        if params.effort is not None and cap.supports_effort:
            request["output_config"] = {"effort": params.effort}

        return request

    def complete(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> AssistantMessage | ClientError:
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
        """Build the default transport that calls the Anthropic SDK.

        Imported lazily so the module (and tests using an injected transport) do not
        require the SDK client to be constructable. The request's `model` (a logical
        id like "claude-haiku-4-5") is resolved against what this base_url actually
        serves once per client instance and cached on disk per base_url — some proxies
        only serve a dated snapshot of a model and reject the bare alias.
        """
        resolved_model_id: str | None = None

        def transport(request: dict, timeout_seconds: float) -> Any:
            nonlocal resolved_model_id
            import anthropic

            if resolved_model_id is None:
                resolved_model_id = resolve_effective_model_id(
                    request["model"], base_url=self._base_url, api_key=self._api_key
                )
            client = anthropic.Anthropic(api_key=self._api_key, base_url=self._base_url)
            try:
                return client.messages.create(
                    timeout=timeout_seconds, **{**request, "model": resolved_model_id}
                )
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return transport


def _parse_response(raw: Any) -> AssistantMessage:
    """Parse a raw Anthropic response (duck-typed) into an AssistantMessage.

    A safety refusal arrives as a normal response with stop_reason == "refusal";
    it is returned as an AssistantMessage, never a ClientError.
    """
    _MISSING = object()
    content = getattr(raw, "content", _MISSING)
    if content is _MISSING:
        # A response object always has a content list (even if empty) - its absence
        # means `raw` isn't the shape we expect at all (e.g. a plain string from a
        # misconfigured base_url returning HTML), so fail loudly instead of silently
        # parsing it into a valid-looking, empty AssistantMessage.
        raise AttributeError(f"expected an Anthropic response object, got {type(raw).__name__}")
    text_parts: list[str] = []
    for block in content or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
    usage = getattr(raw, "usage", None)
    token_usage = TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        # Anthropic reports cache-write and cache-read tokens as two separate usage
        # fields; sum them into the one cached_tokens field.
        cached_tokens=(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0),
    )
    return AssistantMessage(
        content="".join(text_parts),
        usage=token_usage,
        stop_reason=getattr(raw, "stop_reason", "") or "",
    )
