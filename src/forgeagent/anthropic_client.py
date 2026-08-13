"""Anthropic native client with capability-gating.

See docs/model-client-contract.md. The network layer is injectable (a `transport`
callable) so capability-gating and response parsing are pure and unit-testable
without a real key or network. The default transport wraps the Anthropic SDK.

Capability-gating (the contract's core): the caller never branches on model name.
Each client translates GenerationParams intent per its own `capability`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from threading import Lock
from typing import Any

from .client import AttemptObserver, ModelClient, ProviderAttempt
from .model_discovery import resolve_effective_model_id
from .models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    Role,
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

__all__ = [
    "AnthropicClient",
    "TransportError",
    "classify_transport_exception",
]

_logger = logging.getLogger(__name__)

# request dict + timeout -> raw response object (duck-typed: .content/.stop_reason/.usage)
Transport = Callable[[dict, float], Any]
# request dict + timeout -> iterable of raw SDK stream events (duck-typed)
StreamTransport = Callable[[dict, float], Iterable[Any]]


def _render_content(content: str | list) -> str | list[dict]:
    """Translate Message.content to Anthropic's wire shape.

    A plain string passes through unchanged (pre-M9 path). A ContentItem list becomes
    Anthropic content blocks; images use the base64 source shape (verified against the
    real API, docs/m9-streaming-multimodal-commands.md §八 S3).
    """
    if isinstance(content, str):
        return content
    blocks: list[dict] = []
    for item in content:
        if item.type == "text":
            blocks.append({"type": "text", "text": item.text})
        else:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.media_type,
                        "data": item.data,
                    },
                }
            )
    return blocks


def _contains_image(messages: list[Message]) -> bool:
    return any(
        isinstance(msg.content, list) and any(item.type == "image" for item in msg.content)
        for msg in messages
    )


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
            turns.append({"role": msg.role.value, "content": _render_content(msg.content)})
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
                    _logger.warning("provider_sdk_close_failed provider=anthropic")

    def _sdk_client_for_request(self) -> Any:
        with self._sdk_lock:
            if self._closed:
                raise TransportError("invalid_request", False, "model client is closed")
            client = self._sdk_client
            if client is None:
                import anthropic

                client = anthropic.Anthropic(api_key=self._api_key, base_url=self._base_url)
                self._sdk_client = client
            return client

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
            "max_tokens": (
                params.max_output_tokens
                if params.max_output_tokens is not None
                else cap.max_output_tokens
            ),
        }
        if system is not None:
            request["system"] = system
        if params.temperature is not None:
            request["temperature"] = params.temperature

        # thinking: only send an explicit param to request it ("on") on a model that
        # supports it and is not always-on. "auto" and "off" both omit the param
        # (auto = model default; off is best-effort and cannot be guaranteed).
        if params.thinking == "on" and cap.supports_thinking and not cap.thinking_always_on:
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
        """Real streaming: translate SDK events into StreamEvents, ending with DONE.

        Retry semantics (docs/m9 §3.1): only pre-first-byte failures are retried
        (same classification as complete()); once any delta has been yielded, a
        mid-stream failure is not retried — the partial text is discarded and a
        single ClientError ends the iteration, so truncated protocol markup never
        reaches the parser.
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
        attempt = 0
        while True:
            attempt += 1
            self._notify_attempt(ProviderAttempt(attempt=attempt, status="started"))
            started = False
            saw_message_stop = False
            text_parts: list[str] = []
            usage = TokenUsage()
            stop_reason = ""
            try:
                for event in self._stream_transport(request, effective.timeout_seconds):
                    event_type = getattr(event, "type", None)
                    if event_type == "message_start":
                        # message_start's input/output counts are placeholders (spike
                        # S1) — only the cache fields are read here; real totals come
                        # from message_delta.
                        start_usage = getattr(getattr(event, "message", None), "usage", None)
                        usage.cached_tokens = (
                            getattr(start_usage, "cache_creation_input_tokens", 0) or 0
                        ) + (getattr(start_usage, "cache_read_input_tokens", 0) or 0)
                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            started = True
                            text = delta.text
                            text_parts.append(text)
                            yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, text=text)
                        elif delta_type == "thinking_delta":
                            started = True
                            yield StreamEvent(
                                kind=StreamEventKind.THINKING_DELTA, text=delta.thinking
                            )
                        # signature_delta (and any future delta kind) is skipped.
                    elif event_type == "message_delta":
                        # Authoritative usage: full input/output totals live here.
                        delta_usage = getattr(event, "usage", None)
                        usage.input_tokens = getattr(delta_usage, "input_tokens", 0) or 0
                        usage.output_tokens = getattr(delta_usage, "output_tokens", 0) or 0
                        if delta_usage is not None:
                            usage.total_prompt_tokens = usage.input_tokens + usage.cached_tokens
                        stop_reason = (
                            getattr(getattr(event, "delta", None), "stop_reason", "") or ""
                        )
                    elif event_type == "message_stop":
                        saw_message_stop = True
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
            if not saw_message_stop:
                # The transport generator ended (no exception) before the terminal
                # message_stop event — a silent mid-stream truncation. Discard the
                # partial text just like the exception path above, rather than
                # yielding a DONE with a fabricated stop_reason (T11c).
                self._notify_attempt(
                    ProviderAttempt(attempt=attempt, status="interrupted", error_kind="unknown")
                )
                yield ClientError(
                    message="stream ended before message_stop", kind="unknown", attempts=attempt
                )
                return
            self._notify_attempt(ProviderAttempt(attempt=attempt, status="success"))
            yield StreamEvent(
                kind=StreamEventKind.DONE,
                message=AssistantMessage(
                    content="".join(text_parts), usage=usage, stop_reason=stop_reason
                ),
            )
            return

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
            if resolved_model_id is None:
                resolved_model_id = resolve_effective_model_id(
                    request["model"], base_url=self._base_url, api_key=self._api_key
                )
            client = self._sdk_client_for_request()
            try:
                return client.messages.create(
                    timeout=timeout_seconds, **{**request, "model": resolved_model_id}
                )
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return transport

    def _make_sdk_stream_transport(self) -> StreamTransport:
        """Build the default streaming transport (SDK create(stream=True)).

        Mirrors _make_sdk_transport: lazy SDK import, per-base_url model-id
        resolution, connect-time exceptions classified into TransportError.
        Exceptions raised *during* iteration propagate raw — stream() classifies
        them without retrying (mid-stream failures are never retried).
        """
        resolved_model_id: str | None = None

        def stream_transport(request: dict, timeout_seconds: float) -> Iterable[Any]:
            nonlocal resolved_model_id
            if resolved_model_id is None:
                resolved_model_id = resolve_effective_model_id(
                    request["model"], base_url=self._base_url, api_key=self._api_key
                )
            client = self._sdk_client_for_request()
            try:
                return client.messages.create(
                    timeout=timeout_seconds,
                    stream=True,
                    **{**request, "model": resolved_model_id},
                )
            except Exception as exc:  # noqa: BLE001 - classified then re-raised
                kind, retryable = classify_transport_exception(exc)
                raise TransportError(kind, retryable, str(exc)) from exc

        return stream_transport


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
    if usage is not None:
        token_usage.total_prompt_tokens = token_usage.input_tokens + token_usage.cached_tokens
    return AssistantMessage(
        content="".join(text_parts),
        usage=token_usage,
        stop_reason=getattr(raw, "stop_reason", "") or "",
    )
