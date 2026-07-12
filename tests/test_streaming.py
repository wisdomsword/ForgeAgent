"""Tests for M9 Phase 1 streaming: StreamEvent, default degrade-to-complete stream(),
and the real-streaming overrides in AnthropicClient / OpenAICompatibleClient.

All fake SDK events/chunks are SimpleNamespace shapes matching the spike S1/S2
recordings in docs/m9-streaming-multimodal-commands.md §8.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from forgeagent.anthropic_client import AnthropicClient
from forgeagent.anthropic_client import _parse_response as anthropic_parse
from forgeagent.client import MockClient
from forgeagent.models import (
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
from forgeagent.openai_compatible_client import OpenAICompatibleClient
from forgeagent.openai_compatible_client import _parse_response as openai_parse

USER = [Message(role=Role.USER, content="hi")]


def _capability(client_kind: str = "anthropic") -> ModelCapability:
    return ModelCapability(
        model_id="test-model",
        context_window=100_000,
        max_output_tokens=4_096,
        supports_thinking=True,
        thinking_always_on=False,
        supports_effort=False,
        client_kind=client_kind,
    )


def _anthropic_client(events: list[Any] | Exception) -> AnthropicClient:
    def stream_transport(request: dict, timeout: float):
        if isinstance(events, Exception):
            raise events
        yield from events

    return AnthropicClient(
        capability=_capability(),
        api_key="test-key",
        transport=lambda request, timeout: None,
        stream_transport=stream_transport,
        sleep=lambda seconds: None,
    )


def _openai_client(chunks: list[Any]) -> OpenAICompatibleClient:
    def stream_transport(request: dict, timeout: float):
        yield from chunks

    return OpenAICompatibleClient(
        capability=_capability("openai_compatible"),
        api_key="test-key",
        transport=lambda request, timeout: None,
        stream_transport=stream_transport,
        sleep=lambda seconds: None,
    )


# --- Default stream(): degrade-to-complete ----------------------------------


class TestDefaultStream:
    def test_success_yields_full_text_delta_then_done(self):
        reply = AssistantMessage(
            content="hello world",
            usage=TokenUsage(input_tokens=3, output_tokens=5),
            stop_reason="end_turn",
        )
        client = MockClient(script=[reply])
        events = list(client.stream(USER))
        assert [e.kind for e in events] == [
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.DONE,
        ]
        assert events[0].text == "hello world"
        assert events[1].message == reply

    def test_client_error_is_yielded_then_iteration_ends(self):
        error = ClientError(message="boom", kind="network", attempts=3)
        client = MockClient(script=[error])
        events = list(client.stream(USER))
        assert events == [error]

    def test_stream_matches_complete_for_same_script(self):
        reply = AssistantMessage(
            content="same",
            usage=TokenUsage(input_tokens=1, output_tokens=2, cached_tokens=1),
            stop_reason="end_turn",
        )
        completed = MockClient(script=[reply]).complete(USER)
        streamed = list(MockClient(script=[reply]).stream(USER))[-1].message
        assert streamed == completed


# --- AnthropicClient.stream() ------------------------------------------------


def _anthropic_events() -> list[Any]:
    # Shape per spike S1: message_start carries placeholder input/output counts
    # (only the cache fields are real); message_delta carries the authoritative usage.
    return [
        SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=0,
                    output_tokens=1,
                    cache_creation_input_tokens=7,
                    cache_read_input_tokens=3,
                )
            ),
        ),
        SimpleNamespace(type="content_block_start"),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="pondering"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="signature_delta", signature="sig=="),
        ),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start"),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="Hello"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text=" world"),
        ),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(input_tokens=42, output_tokens=17),
        ),
        SimpleNamespace(type="message_stop"),
    ]


class TestAnthropicStream:
    def test_event_mapping_and_done_message(self):
        events = list(_anthropic_client(_anthropic_events()).stream(USER))
        kinds = [e.kind for e in events]
        assert kinds == [
            StreamEventKind.THINKING_DELTA,
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.DONE,
        ]
        assert events[0].text == "pondering"
        assert [e.text for e in events[1:3]] == ["Hello", " world"]
        # signature_delta never surfaces as any event
        assert all("sig==" not in e.text for e in events if isinstance(e, StreamEvent))
        done = events[-1].message
        assert done.content == "Hello world"
        assert done.stop_reason == "end_turn"
        # usage from message_delta, not polluted by message_start placeholders
        assert done.usage.input_tokens == 42
        assert done.usage.output_tokens == 17
        assert done.usage.cached_tokens == 10
        assert done.usage.reasoning_tokens == 0

    def test_mid_stream_failure_yields_single_client_error_no_done(self):
        good = _anthropic_events()

        def failing():
            yield good[0]
            yield good[6]  # one text_delta
            raise ConnectionResetError("wire cut")

        client = AnthropicClient(
            capability=_capability(),
            api_key="k",
            transport=lambda r, t: None,
            stream_transport=lambda r, t: failing(),
            sleep=lambda s: None,
        )
        events = list(client.stream(USER))
        # partial delta was already emitted, then a single ClientError; no DONE
        errors = [e for e in events if isinstance(e, ClientError)]
        assert len(errors) == 1
        assert errors[0].kind == "unknown"
        assert errors[0].attempts == 1  # not retried after first byte
        assert not any(
            isinstance(e, StreamEvent) and e.kind is StreamEventKind.DONE for e in events
        )

    def test_silent_truncation_without_message_stop_yields_client_error_no_done(self):
        # The transport generator can end early with no exception at all (e.g. the
        # underlying connection is dropped and the SDK's iterator simply stops) --
        # this must be treated the same as the exception path above: discard the
        # partial text_delta, never fabricate a DONE with an empty stop_reason (T11c).
        good = _anthropic_events()

        def truncated():
            yield good[0]
            yield good[6]  # one text_delta
            # generator ends here -- no message_delta/message_stop, no exception

        client = AnthropicClient(
            capability=_capability(),
            api_key="k",
            transport=lambda r, t: None,
            stream_transport=lambda r, t: truncated(),
            sleep=lambda s: None,
        )
        events = list(client.stream(USER))
        assert [e.kind for e in events if isinstance(e, StreamEvent)] == [
            StreamEventKind.TEXT_DELTA,
        ]
        errors = [e for e in events if isinstance(e, ClientError)]
        assert len(errors) == 1
        assert not any(
            isinstance(e, StreamEvent) and e.kind is StreamEventKind.DONE for e in events
        )


# --- OpenAICompatibleClient.stream() ------------------------------------------


def _chunk(
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
    usage: Any = None,
    choices: bool = True,
) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    if reasoning_content is not None:
        delta.reasoning_content = reasoning_content
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)] if choices else [],
        usage=usage,
    )


def _usage(reasoning_nested: int | None = None, reasoning_top: int | None = None):
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=20,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4),
    )
    if reasoning_nested is not None:
        usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=reasoning_nested)
    if reasoning_top is not None:
        usage.reasoning_tokens = reasoning_top
    return usage


class TestOpenAIStream:
    def test_text_and_reasoning_deltas_and_final_usage(self):
        chunks = [
            _chunk(reasoning_content="think"),
            _chunk(content="Hi"),
            _chunk(content=" there", finish_reason="stop"),
            _chunk(choices=False, usage=_usage(reasoning_nested=0, reasoning_top=121)),
        ]
        events = list(_openai_client(chunks).stream(USER))
        assert [e.kind for e in events] == [
            StreamEventKind.THINKING_DELTA,
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.DONE,
        ]
        done = events[-1].message
        assert done.content == "Hi there"
        assert done.stop_reason == "stop"
        assert done.usage.input_tokens == 10
        assert done.usage.output_tokens == 20
        assert done.usage.cached_tokens == 4
        # dual-location trap: nested fake zero, top-level real value (glm-5.2 shape)
        assert done.usage.reasoning_tokens == 121

    def test_reasoning_tokens_nested_real_value_no_top_level(self):
        # gpt-5.4-mini shape: real value in the standard nested location only
        chunks = [
            _chunk(content="ok", finish_reason="stop"),
            _chunk(choices=False, usage=_usage(reasoning_nested=69)),
        ]
        done = list(_openai_client(chunks).stream(USER))[-1].message
        assert done.usage.reasoning_tokens == 69

    def test_missing_usage_is_all_zero(self):
        chunks = [_chunk(content="x", finish_reason="stop")]
        done = list(_openai_client(chunks).stream(USER))[-1].message
        assert done.usage == TokenUsage()

    def test_tool_calls_trigger_silent_aggregation_fallback(self):
        fragment1 = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(name="do_thing", arguments='{"a"'),
        )
        fragment2 = SimpleNamespace(
            index=0,
            id=None,
            function=SimpleNamespace(name=None, arguments=": 1}"),
        )
        chunks = [
            _chunk(content="before"),
            _chunk(tool_calls=[fragment1]),
            _chunk(content="after", tool_calls=[fragment2], finish_reason="tool_calls"),
            _chunk(choices=False, usage=_usage()),
        ]
        events = list(_openai_client(chunks).stream(USER))
        # only the pre-tool_calls delta was yielded; then silence until DONE
        assert [e.kind for e in events] == [
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.DONE,
        ]
        assert events[0].text == "before"
        done = events[-1].message
        assert done.content == "beforeafter"  # full aggregate still in DONE
        assert done.stop_reason == "tool_calls"
        assert len(done.tool_calls) == 1
        call = done.tool_calls[0]
        assert (call.id, call.name, call.arguments) == ("call_1", "do_thing", '{"a": 1}')

    def test_mid_stream_failure_yields_single_client_error_no_done(self):
        def failing(request: dict, timeout: float):
            yield _chunk(content="par")
            yield _chunk(content="tial")
            raise ConnectionResetError("wire cut")

        client = OpenAICompatibleClient(
            capability=_capability("openai_compatible"),
            api_key="k",
            transport=lambda r, t: None,
            stream_transport=failing,
            sleep=lambda s: None,
        )
        events = list(client.stream(USER))
        errors = [e for e in events if isinstance(e, ClientError)]
        assert len(errors) == 1
        assert errors[0].attempts == 1
        assert not any(
            isinstance(e, StreamEvent) and e.kind is StreamEventKind.DONE for e in events
        )

    def test_silent_truncation_without_finish_reason_yields_client_error_no_done(self):
        # No exception at all -- the transport generator just ends early (dropped
        # connection). Must not fabricate a DONE with an empty stop_reason (T11c).
        def truncated(request: dict, timeout: float):
            yield _chunk(content="par")
            yield _chunk(content="tial")
            # generator ends here -- no finish_reason chunk, no exception

        client = OpenAICompatibleClient(
            capability=_capability("openai_compatible"),
            api_key="k",
            transport=lambda r, t: None,
            stream_transport=truncated,
            sleep=lambda s: None,
        )
        events = list(client.stream(USER))
        assert [e.kind for e in events if isinstance(e, StreamEvent)] == [
            StreamEventKind.TEXT_DELTA,
            StreamEventKind.TEXT_DELTA,
        ]
        errors = [e for e in events if isinstance(e, ClientError)]
        assert len(errors) == 1
        assert not any(
            isinstance(e, StreamEvent) and e.kind is StreamEventKind.DONE for e in events
        )

    def test_request_carries_include_usage(self):
        seen: dict = {}

        def stream_transport(request: dict, timeout: float):
            seen.update(request)
            yield _chunk(content="x", finish_reason="stop")

        client = OpenAICompatibleClient(
            capability=_capability("openai_compatible"),
            api_key="k",
            transport=lambda r, t: None,
            stream_transport=stream_transport,
            sleep=lambda s: None,
        )
        list(client.stream(USER, GenerationParams()))
        assert seen["stream_options"] == {"include_usage": True}


# --- _parse_response reasoning_tokens mapping ---------------------------------


class TestParseResponseReasoningTokens:
    def _response(self, usage: Any) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=usage,
        )

    def test_nested_only(self):
        parsed = openai_parse(self._response(_usage(reasoning_nested=69)))
        assert parsed.usage.reasoning_tokens == 69

    def test_dual_location_takes_max(self):
        parsed = openai_parse(self._response(_usage(reasoning_nested=0, reasoning_top=121)))
        assert parsed.usage.reasoning_tokens == 121

    def test_absent_is_zero(self):
        parsed = openai_parse(self._response(_usage()))
        assert parsed.usage.reasoning_tokens == 0

    def test_anthropic_parse_defaults_to_zero(self):
        raw = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hi")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
            stop_reason="end_turn",
        )
        assert anthropic_parse(raw).usage.reasoning_tokens == 0


# --- complete()/stream() invariant --------------------------------------------


def test_stream_done_message_identical_to_complete():
    reply = AssistantMessage(
        content="invariant",
        usage=TokenUsage(input_tokens=5, output_tokens=6, reasoning_tokens=2),
        stop_reason="end_turn",
    )
    complete_result = MockClient(script=[reply]).complete(USER)
    stream_events = list(MockClient(script=[reply]).stream(USER))
    done = [e for e in stream_events if e.kind is StreamEventKind.DONE]
    assert len(done) == 1
    assert done[0].message.model_dump() == complete_result.model_dump()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
