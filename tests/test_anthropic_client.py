"""Unit tests for AnthropicClient + capability-gating (M2-6).

All tests use an injected transport (no real key, no network). Capability-gating and
response parsing are pure, so they are asserted directly on build_request / _parse_response.
"""

import sys
from types import SimpleNamespace

import pytest

from forgeagent.anthropic_client import (
    AnthropicClient,
    TransportError,
    _parse_response,
    classify_transport_exception,
)
from forgeagent.model_registry import get_capability
from forgeagent.models import ClientError, GenerationParams, Message, Role


def _client(model_id: str, transport=None, **kw) -> AnthropicClient:
    return AnthropicClient(
        capability=get_capability(model_id),
        api_key="test-key",
        transport=transport or (lambda req, t: _fake_reply()),
        sleep=lambda s: None,  # no real sleep in tests
        **kw,
    )


def _fake_reply(text="ok", stop_reason="end_turn", inp=3, out=5, cache_creation=0, cache_read=0):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=inp,
            output_tokens=out,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        ),
    )


def _user(text="hi") -> list[Message]:
    return [Message(role=Role.USER, content=text)]


# --- capability-gating -------------------------------------------------------


def test_haiku_drops_effort_and_thinking():
    client = _client("claude-haiku-4-5")
    req = client.build_request(_user(), GenerationParams(effort="high", thinking="on"))
    assert "output_config" not in req  # haiku supports_effort=False
    assert "thinking" not in req  # haiku supports_thinking=False


def test_fable_never_sends_explicit_thinking():
    # Fable is thinking_always_on -> explicit thinking param would 400, so never sent.
    client = _client("claude-fable-5")
    req = client.build_request(_user(), GenerationParams(thinking="on"))
    assert "thinking" not in req


def test_thinking_auto_omits_param():
    client = _client("claude-sonnet-5")
    req = client.build_request(_user(), GenerationParams(thinking="auto"))
    assert "thinking" not in req


def test_thinking_on_sonnet_sends_param():
    client = _client("claude-sonnet-5")
    req = client.build_request(_user(), GenerationParams(thinking="on"))
    assert req["thinking"] == {"type": "adaptive"}


def test_thinking_off_omits_param_best_effort():
    # "off" cannot be guaranteed; we omit rather than error.
    client = _client("claude-sonnet-5")
    req = client.build_request(_user(), GenerationParams(thinking="off"))
    assert "thinking" not in req


def test_max_output_falls_back_to_capability_ceiling():
    assert (
        _client("claude-haiku-4-5").build_request(_user(), GenerationParams())["max_tokens"]
        == 64_000
    )
    assert (
        _client("claude-sonnet-5").build_request(_user(), GenerationParams())["max_tokens"]
        == 128_000
    )


def test_positive_max_output_override_is_preserved_exactly():
    request = _client("claude-sonnet-5").build_request(
        _user(), GenerationParams(max_output_tokens=7_000)
    )

    assert request["max_tokens"] == 7_000


def test_effort_passed_through_when_supported():
    req = _client("claude-sonnet-5").build_request(_user(), GenerationParams(effort="xhigh"))
    assert req["output_config"] == {"effort": "xhigh"}
    assert "effort" not in req


def test_system_message_extracted_to_top_level():
    client = _client("claude-sonnet-5")
    msgs = [
        Message(role=Role.SYSTEM, content="be brief"),
        Message(role=Role.USER, content="hello"),
    ]
    req = client.build_request(msgs, GenerationParams())
    assert req["system"] == "be brief"
    assert req["messages"] == [{"role": "user", "content": "hello"}]


# --- response parsing --------------------------------------------------------


def test_parse_response_builds_assistant_message():
    msg = _parse_response(_fake_reply(text="hello", inp=10, out=20))
    assert msg.content == "hello"
    assert msg.usage.input_tokens == 10
    assert msg.usage.output_tokens == 20
    assert msg.stop_reason == "end_turn"


def test_parse_response_sums_cache_creation_and_read_into_cached_tokens():
    msg = _parse_response(_fake_reply(cache_creation=7, cache_read=11))
    assert msg.usage.cached_tokens == 18


def test_parse_response_normalizes_prompt_total_without_serializing_helper():
    usage = _parse_response(_fake_reply(inp=10, cache_creation=3, cache_read=2)).usage

    assert usage.total_prompt_tokens == 15
    assert "total_prompt_tokens" not in usage.model_dump()


def test_parse_response_missing_usage_leaves_prompt_total_none():
    reply = _fake_reply()
    reply.usage = None

    assert _parse_response(reply).usage.total_prompt_tokens is None


def test_parse_response_zero_usage_keeps_prompt_total_zero():
    usage = _parse_response(_fake_reply(inp=0, out=0)).usage

    assert usage.total_prompt_tokens == 0


def test_parse_response_defaults_cached_tokens_to_zero():
    msg = _parse_response(_fake_reply())
    assert msg.usage.cached_tokens == 0


def test_refusal_is_assistant_message_not_error():
    result = _client(
        "claude-fable-5", transport=lambda req, t: _fake_reply(text="", stop_reason="refusal")
    ).complete(_user())
    # refusal surfaces as a successful AssistantMessage, not a ClientError.
    assert not isinstance(result, ClientError)
    assert result.stop_reason == "refusal"


# --- retry / error mapping ---------------------------------------------------


# Stub exceptions whose __name__ matches the SDK class names the classifier keys on
# (the classifier matches by class name, so the names must be exact — no underscore).
class RateLimitError(Exception):
    pass


class AuthenticationError(Exception):
    pass


def test_classify_known_and_unknown():
    assert classify_transport_exception(RateLimitError()) == ("rate_limit", True)
    assert classify_transport_exception(AuthenticationError()) == ("auth", False)
    assert classify_transport_exception(ValueError("x")) == ("unknown", False)


def test_retryable_error_retries_then_exhausts():
    calls = {"n": 0}

    def transport(req, t):
        calls["n"] += 1
        raise TransportError("network", True, "conn reset")

    result = _client("claude-sonnet-5", transport=transport, max_attempts=3).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "network"
    assert result.attempts == 3
    assert calls["n"] == 3


def test_non_retryable_error_returns_immediately():
    calls = {"n": 0}

    def transport(req, t):
        calls["n"] += 1
        raise TransportError("auth", False, "bad key")

    result = _client("claude-sonnet-5", transport=transport, max_attempts=3).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "auth"
    assert result.attempts == 1
    assert calls["n"] == 1


def test_timeout_is_retryable_kind():
    def transport(req, t):
        raise TransportError("timeout", True, "timed out")

    result = _client("claude-sonnet-5", transport=transport, max_attempts=2).complete(_user())
    assert result.kind == "timeout"
    assert result.attempts == 2


def test_retry_then_success():
    state = {"n": 0}

    def transport(req, t):
        state["n"] += 1
        if state["n"] < 2:
            raise TransportError("network", True, "blip")
        return _fake_reply(text="recovered")

    result = _client("claude-sonnet-5", transport=transport, max_attempts=3).complete(_user())
    assert not isinstance(result, ClientError)
    assert result.content == "recovered"
    assert state["n"] == 2


def test_complete_reports_each_provider_attempt_before_retry_success():
    observed = []
    state = {"n": 0}

    def transport(req, t):
        state["n"] += 1
        if state["n"] == 1:
            raise TransportError("network", True, "blip")
        return _fake_reply(text="recovered")

    result = _client(
        "claude-sonnet-5",
        transport=transport,
        max_attempts=3,
        attempt_observer=observed.append,
    ).complete(_user())

    assert not isinstance(result, ClientError)
    assert [(event.attempt, event.status, event.error_kind) for event in observed] == [
        (1, "started", None),
        (1, "error", "network"),
        (2, "started", None),
        (2, "success", None),
    ]


def test_malformed_response_becomes_client_error_not_traceback():
    # A misconfigured base_url can make a gateway return e.g. its frontend HTML as a
    # plain string instead of a JSON error - _parse_response must not crash on that.
    def transport(req, t):
        return "<!doctype html><html>not a real response</html>"

    result = _client("claude-sonnet-5", transport=transport).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "invalid_request"
    assert result.attempts == 1


def test_stream_failure_feedback_is_stable_and_debug_detail_is_masked(monkeypatch, caplog):
    secret = "private-anthropic-stream-detail"
    monkeypatch.setenv("TEST_SECRET", secret)

    def stream_transport(_request, _timeout):
        def events():
            raise RuntimeError(secret)
            yield None

        return events()

    client = _client("claude-sonnet-5", stream_transport=stream_transport)
    with caplog.at_level("DEBUG", logger="forgeagent.transport_errors"):
        result = list(client.stream(_user()))

    assert len(result) == 1
    assert isinstance(result[0], ClientError)
    assert result[0].message == "model request failed: unknown"
    assert "model_transport_failure kind=unknown" in caplog.text
    assert secret not in caplog.text


def test_default_params_used_when_none_passed():
    client = _client("claude-sonnet-5", default_params=GenerationParams(effort="low"))
    captured = {}

    def transport(req, t):
        captured.update(req)
        return _fake_reply()

    client._transport = transport
    client.complete(_user())  # no params -> uses default_params
    assert captured["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("model_id", ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"])
def test_complete_happy_path_across_models(model_id):
    result = _client(model_id).complete(_user())
    assert not isinstance(result, ClientError)
    assert result.content == "ok"


def test_default_sdk_transport_reuses_one_client_for_complete_and_stream(monkeypatch):
    calls = {"construct": 0, "close": 0, "complete": 0, "stream": 0}

    class FakeSDK:
        def __init__(self, **kwargs):
            calls["construct"] += 1
            self.messages = self

        def close(self):
            calls["close"] += 1

        def create(self, *, stream=False, **kwargs):
            if stream:
                calls["stream"] += 1
                return [
                    SimpleNamespace(type="message_start", message=SimpleNamespace(usage=None)),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text="stream"),
                    ),
                    SimpleNamespace(
                        type="message_delta",
                        delta=SimpleNamespace(stop_reason="end_turn"),
                        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                    ),
                    SimpleNamespace(type="message_stop"),
                ]
            calls["complete"] += 1
            return _fake_reply(text="complete")

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeSDK))
    monkeypatch.setattr(
        "forgeagent.anthropic_client.resolve_effective_model_id",
        lambda model_id, **kwargs: model_id,
    )
    client = AnthropicClient(capability=get_capability("claude-sonnet-5"), api_key="test-key")

    result = client.complete(_user())
    events = list(client.stream(_user()))
    client.close()
    client.close()

    assert result.content == "complete"
    assert events[-1].message.content == "stream"
    assert calls == {"construct": 1, "close": 1, "complete": 1, "stream": 1}


def test_closed_default_sdk_client_rejects_requests_without_reopening(monkeypatch):
    calls = {"construct": 0, "close": 0, "request": 0}

    class FakeSDK:
        def __init__(self, **kwargs):
            calls["construct"] += 1
            self.messages = self

        def close(self):
            calls["close"] += 1

        def create(self, **kwargs):
            calls["request"] += 1
            return _fake_reply()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeSDK))
    monkeypatch.setattr(
        "forgeagent.anthropic_client.resolve_effective_model_id",
        lambda model_id, **kwargs: model_id,
    )
    client = AnthropicClient(capability=get_capability("claude-sonnet-5"), api_key="test-key")
    assert not isinstance(client.complete(_user()), ClientError)
    client.close()

    result = client.complete(_user())
    stream_result = list(client.stream(_user()))

    assert isinstance(result, ClientError)
    assert result.kind == "invalid_request"
    assert stream_result and isinstance(stream_result[0], ClientError)
    assert calls == {"construct": 1, "close": 1, "request": 1}


def test_sdk_close_failure_is_swallowed_and_does_not_leak_exception(monkeypatch, caplog):
    class FakeSDK:
        def __init__(self, **kwargs):
            self.messages = self

        def close(self):
            raise RuntimeError("secret-key-must-not-appear")

        def create(self, **kwargs):
            return _fake_reply()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeSDK))
    monkeypatch.setattr(
        "forgeagent.anthropic_client.resolve_effective_model_id",
        lambda model_id, **kwargs: model_id,
    )
    client = AnthropicClient(capability=get_capability("claude-sonnet-5"), api_key="test-key")
    client.complete(_user())

    with caplog.at_level("WARNING"):
        client.close()

    assert caplog.messages == ["provider_sdk_close_failed provider=anthropic"]
    assert "secret-key-must-not-appear" not in caplog.text
    client.close()


def test_injected_transports_are_not_closed():
    calls = {"complete": 0, "stream": 0, "close": 0}

    class InjectedTransport:
        def __call__(self, req, timeout):
            calls["complete"] += 1
            return _fake_reply()

        def close(self):
            calls["close"] += 1

    class InjectedStreamTransport:
        def __call__(self, req, timeout):
            calls["stream"] += 1
            return []

        def close(self):
            calls["close"] += 1

    transport = InjectedTransport()
    stream_transport = InjectedStreamTransport()
    client = _client("claude-sonnet-5", transport=transport, stream_transport=stream_transport)
    client.complete(_user())
    list(client.stream(_user()))
    client.close()

    assert calls == {"complete": 1, "stream": 1, "close": 0}
