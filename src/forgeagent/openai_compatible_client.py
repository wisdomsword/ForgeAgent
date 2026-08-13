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

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from threading import Lock
from typing import Any

from .client import AttemptObserver, ModelClient, ProviderAttempt
from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    NativeToolCall,
    StreamEvent,
    StreamEventKind,
    TokenUsage,
)
from .transport_errors import (
    TransportError,
    classify_transport_exception,
    client_error_message,
    log_transport_failure,
    run_with_retries,
)

__all__ = ["OpenAICompatibleClient"]

_logger = logging.getLogger(__name__)

# request dict + timeout -> raw response object (duck-typed: .choices[0].message/.usage)
Transport = Callable[[dict, float], Any]
# request dict + timeout -> iterable of raw SDK stream chunks (duck-typed)
StreamTransport = Callable[[dict, float], Iterable[Any]]


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
        stream_transport: StreamTransport | None = None,
        attempt_observer: AttemptObserver | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._capability = capability
        self._api_key = api_key
        self._default_params = default_params or GenerationParams()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_factor = backoff_factor
        self._base_url = base_url
        self._sdk_client: Any | None = None
        self._sdk_lock = Lock()
        self._closed = False
        self._transport = transport or self._make_sdk_transport()
        self._stream_transport = stream_transport or self._make_sdk_stream_transport()
        self._sleep = sleep
        self._attempt_observer = attempt_observer

    @property
    def capability(self) -> ModelCapability:
        return self._capability

    def close(self) -> None:
        with self._sdk_lock:
            if self._closed:
                return
            self._closed = True
            client = self._sdk_client
            self._sdk_client = None
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - cleanup must not mask task result
                    _logger.warning("provider_sdk_close_failed provider=openai_compatible")

    def _sdk_client_for_request(self) -> Any:
        with self._sdk_lock:
            if self._closed:
                raise TransportError("invalid_request", False, "model client is closed")
            client = self._sdk_client
            if client is None:
                import openai

                client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
                self._sdk_client = client
            return client

    def build_request(self, messages: list[Message], params: GenerationParams) -> dict:
        """Translate intent to a Chat Completions request dict via capability-gating.

        Unlike Anthropic, `system`-role messages stay inline in `messages` (no
        top-level split). Token-limit key and reasoning params are picked per
        `self._capability`, mirroring anthropic_client.AnthropicClient.build_request.
        """
        cap = self._capability
        turns = [
            {"role": msg.role.value, "content": _render_content(msg.content)} for msg in messages
        ]
        request: dict[str, Any] = {"model": cap.model_id, "messages": turns}
        request[cap.max_tokens_param] = (
            params.max_output_tokens
            if params.max_output_tokens is not None
            else cap.max_output_tokens
        )
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
        if self._closed:
            return ClientError(message="model client is closed", kind="invalid_request", attempts=1)
        if _contains_image(messages) and not self._capability.supports_images:
            return ClientError(
                message=(f"model {self._capability.model_id!r} does not support image input"),
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
            attempt_observer=self._attempt_observer,
        )

    def stream(
        self, messages: list[Message], params: GenerationParams | None = None
    ) -> Iterator[StreamEvent | ClientError]:
        """Real streaming: translate Chat Completions chunks into StreamEvents.

        Once any chunk carries `tool_calls`, further text/thinking deltas stop being
        yielded (still accumulated for the final DONE message) — tool-call fragments
        arrive interleaved with text on some providers and forwarding partial JSON
        argument fragments as text would corrupt the transcript. Same mid-stream-no-
        retry contract as AnthropicClient.stream() (docs/m9 §3.1).
        """
        if self._closed:
            yield ClientError(message="model client is closed", kind="invalid_request", attempts=1)
            return
        if _contains_image(messages) and not self._capability.supports_images:
            yield ClientError(
                message=(f"model {self._capability.model_id!r} does not support image input"),
                kind="invalid_request",
                attempts=1,
            )
            return
        effective = params if params is not None else self._default_params
        request = self.build_request(messages, effective)
        request["stream_options"] = {"include_usage": True}
        attempt = 0
        while True:
            attempt += 1
            self._notify_attempt(ProviderAttempt(attempt=attempt, status="started"))
            started = False
            aggregating_tool_calls = False
            text_parts: list[str] = []
            tool_call_fragments: dict[int, dict[str, str]] = {}
            usage = TokenUsage()
            stop_reason = ""
            try:
                for chunk in self._stream_transport(request, effective.timeout_seconds):
                    choice = chunk.choices[0] if chunk.choices else None
                    delta = getattr(choice, "delta", None) if choice is not None else None
                    if delta is not None:
                        raw_tool_calls = getattr(delta, "tool_calls", None)
                        if raw_tool_calls:
                            aggregating_tool_calls = True
                            for fragment in raw_tool_calls:
                                slot = tool_call_fragments.setdefault(
                                    fragment.index, {"id": "", "name": "", "arguments": ""}
                                )
                                if fragment.id:
                                    slot["id"] = fragment.id
                                function = getattr(fragment, "function", None)
                                if function is not None:
                                    if getattr(function, "name", None):
                                        slot["name"] += function.name
                                    if getattr(function, "arguments", None):
                                        slot["arguments"] += function.arguments
                        text = getattr(delta, "content", None)
                        if text:
                            text_parts.append(text)
                            if not aggregating_tool_calls:
                                started = True
                                yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, text=text)
                        thinking = getattr(delta, "reasoning_content", None)
                        if thinking:
                            if not aggregating_tool_calls:
                                started = True
                                yield StreamEvent(
                                    kind=StreamEventKind.THINKING_DELTA, text=thinking
                                )
                    finish_reason = getattr(choice, "finish_reason", None) if choice else None
                    if finish_reason:
                        stop_reason = finish_reason
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = TokenUsage(
                            input_tokens=getattr(chunk_usage, "prompt_tokens", 0) or 0,
                            output_tokens=getattr(chunk_usage, "completion_tokens", 0) or 0,
                            cached_tokens=getattr(
                                getattr(chunk_usage, "prompt_tokens_details", None),
                                "cached_tokens",
                                0,
                            )
                            or 0,
                            reasoning_tokens=_extract_reasoning_tokens(chunk_usage),
                            total_prompt_tokens=getattr(chunk_usage, "prompt_tokens", 0) or 0,
                        )
            except TransportError as exc:
                log_transport_failure(exc.kind, exc)
                self._notify_attempt(
                    ProviderAttempt(
                        attempt=attempt,
                        status="error" if not started else "interrupted",
                        error_kind=exc.kind,
                    )
                )
                if not started and exc.retryable and attempt < self._max_attempts:
                    self._sleep(self._backoff_base * self._backoff_factor ** (attempt - 1))
                    continue
                yield ClientError(
                    message=client_error_message(exc.kind), kind=exc.kind, attempts=attempt
                )
                return
            except Exception as exc:  # noqa: BLE001 - mid-stream failure, never retried
                kind, _retryable = classify_transport_exception(exc)
                log_transport_failure(kind, exc)
                self._notify_attempt(
                    ProviderAttempt(attempt=attempt, status="interrupted", error_kind=kind)
                )
                yield ClientError(message=client_error_message(kind), kind=kind, attempts=attempt)
                return
            if not stop_reason:
                # The transport generator ended (no exception) before any chunk carried
                # a finish_reason — a silent mid-stream truncation. Discard the partial
                # text just like the exception path above, rather than yielding a DONE
                # with an empty stop_reason (T11c).
                self._notify_attempt(
                    ProviderAttempt(attempt=attempt, status="interrupted", error_kind="unknown")
                )
                yield ClientError(
                    message="stream ended before finish_reason", kind="unknown", attempts=attempt
                )
                return
            native_calls = [
                NativeToolCall(
                    id=fragment["id"], name=fragment["name"], arguments=fragment["arguments"]
                )
                for _, fragment in sorted(tool_call_fragments.items())
            ]
            self._notify_attempt(ProviderAttempt(attempt=attempt, status="success"))
            yield StreamEvent(
                kind=StreamEventKind.DONE,
                message=AssistantMessage(
                    content="".join(text_parts),
                    usage=usage,
                    stop_reason=stop_reason,
                    tool_calls=native_calls,
                ),
            )
            return

    def _make_sdk_transport(self) -> Transport:
        """Build the default transport that calls the OpenAI SDK.

        Imported lazily so the module (and tests using an injected transport) do not
        require the SDK to be installed or constructable.
        """

        def transport(request: dict, timeout_seconds: float) -> Any:
            client = self._sdk_client_for_request()
            try:
                return client.chat.completions.create(timeout=timeout_seconds, **request)
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return transport

    def _make_sdk_stream_transport(self) -> StreamTransport:
        """Build the default streaming transport (SDK create(stream=True)).

        Mirrors _make_sdk_transport: lazy SDK import, connect-time exceptions
        classified into TransportError. Exceptions raised *during* iteration
        propagate raw — stream() classifies them without retrying.
        """

        def stream_transport(request: dict, timeout_seconds: float) -> Iterable[Any]:
            client = self._sdk_client_for_request()
            try:
                return client.chat.completions.create(
                    timeout=timeout_seconds, stream=True, **request
                )
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return stream_transport


def _extract_reasoning_tokens(usage: Any) -> int:
    """Max of the standard nested location and a non-standard top-level location.

    Different vendors put the real billed-reasoning-token value in different spots
    and a fake zero in the other (docs/m9 §8 S2): glm-5.2 reports the real value at
    the top level and a fake zero nested; gpt-5.4-mini reports the real value nested
    and has no top-level field at all. Taking the max is correct for both shapes.
    """
    nested = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0)
    top_level = getattr(usage, "reasoning_tokens", 0)
    return max(nested or 0, top_level or 0)


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
        cached_tokens=getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
        or 0,
        reasoning_tokens=_extract_reasoning_tokens(usage),
        total_prompt_tokens=(getattr(usage, "prompt_tokens", 0) or 0)
        if usage is not None
        else None,
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
