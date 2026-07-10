"""Unit tests for OpenAICompatibleClient + capability-gating (M6).

All tests use an injected transport (no real key, no network) — mirrors
test_anthropic_client.py's pattern. Capability-gating and response parsing are pure,
so they are asserted directly on build_request / _parse_response.
"""

from types import SimpleNamespace

from forgeagent.model_registry import get_capability
from forgeagent.models import ClientError, GenerationParams, Message, Role
from forgeagent.openai_compatible_client import OpenAICompatibleClient, _parse_response


def _client(model_id: str, transport=None, **kw) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        capability=get_capability(model_id),
        api_key="test-key",
        transport=transport or (lambda req, t: _fake_reply()),
        sleep=lambda s: None,  # no real sleep in tests
        **kw,
    )


def _fake_reply(text="ok", finish_reason="stop", inp=3, out=5, tool_calls=None):
    message = SimpleNamespace(content=text, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=inp, completion_tokens=out),
    )


def _user(text="hi") -> list[Message]:
    return [Message(role=Role.USER, content=text)]


# --- capability-gating -------------------------------------------------------


def test_system_message_stays_inline_in_messages_array():
    # Unlike Anthropic, OpenAI-compatible keeps system in the messages array.
    client = _client("gpt-5.5")
    msgs = [
        Message(role=Role.SYSTEM, content="be brief"),
        Message(role=Role.USER, content="hello"),
    ]
    req = client.build_request(msgs, GenerationParams())
    assert req["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]
    assert "system" not in req


def test_gpt_family_uses_max_completion_tokens():
    req = _client("gpt-5.5").build_request(_user(), GenerationParams())
    assert "max_completion_tokens" in req
    assert "max_tokens" not in req
    assert req["max_completion_tokens"] == 128_000


def test_deepseek_uses_legacy_max_tokens():
    req = _client("deepseek-v4-flash").build_request(_user(), GenerationParams())
    assert req["max_tokens"] == 384_000
    assert "max_completion_tokens" not in req


def test_max_output_falls_back_to_capability_ceiling():
    req = _client("gpt-5.4-mini").build_request(_user(), GenerationParams(max_output_tokens=None))
    assert req["max_completion_tokens"] == 128_000
    req2 = _client("gpt-5.4-mini").build_request(_user(), GenerationParams(max_output_tokens=1_000))
    assert req2["max_completion_tokens"] == 1_000


def test_effort_passed_through_as_reasoning_effort_when_supported():
    req = _client("gpt-5.4-mini").build_request(_user(), GenerationParams(effort="low"))
    assert req["reasoning_effort"] == "low"
    assert "effort" not in req


def test_thinking_on_sends_glm_native_shape_when_supported():
    client = _client("glm-5.2")
    req = client.build_request(_user(), GenerationParams(thinking="on"))
    assert req["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "thinking" not in req


def test_thinking_auto_omits_param():
    req = _client("glm-5.2").build_request(_user(), GenerationParams(thinking="auto"))
    assert "thinking" not in req
    assert "extra_body" not in req


def test_model_without_effort_support_drops_reasoning_effort():
    # deepseek-v4-flash's ModelCapability supports_effort=True in the registry, so use
    # a model that doesn't to prove the drop rule; none of the registered
    # openai_compatible models have supports_effort=False today, so assert the
    # generic gating logic directly via a hand-built capability instead.
    from forgeagent.models import ModelCapability

    cap = ModelCapability(
        model_id="no-effort-model",
        context_window=100_000,
        max_output_tokens=8_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="openai_compatible",
    )
    client = OpenAICompatibleClient(
        capability=cap,
        api_key="test-key",
        transport=lambda req, t: _fake_reply(),
        sleep=lambda s: None,
    )
    req = client.build_request(_user(), GenerationParams(effort="high", thinking="on"))
    assert "reasoning_effort" not in req
    assert "thinking" not in req
    assert "extra_body" not in req


# --- response parsing --------------------------------------------------------


def test_parse_response_builds_assistant_message():
    msg = _parse_response(_fake_reply(text="hello", inp=10, out=20))
    assert msg.content == "hello"
    assert msg.usage.input_tokens == 10
    assert msg.usage.output_tokens == 20
    assert msg.stop_reason == "stop"


def test_finish_reason_passed_through_verbatim():
    msg = _parse_response(_fake_reply(finish_reason="content_filter"))
    assert msg.stop_reason == "content_filter"


def test_null_content_becomes_empty_string():
    # native tool_calls replies can have content=None with tool_calls populated.
    msg = _parse_response(_fake_reply(text=None, finish_reason="tool_calls"))
    assert msg.content == ""


# --- retry / error mapping ---------------------------------------------------


class RateLimitError(Exception):
    pass


def test_retryable_error_retries_then_exhausts():
    calls = {"n": 0}

    def transport(req, t):
        calls["n"] += 1
        from forgeagent.transport_errors import TransportError

        raise TransportError("network", True, "conn reset")

    result = _client("gpt-5.4-mini", transport=transport, max_attempts=3).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "network"
    assert result.attempts == 3
    assert calls["n"] == 3


def test_non_retryable_error_returns_immediately():
    def transport(req, t):
        from forgeagent.transport_errors import TransportError

        raise TransportError("auth", False, "bad key")

    result = _client("gpt-5.4-mini", transport=transport, max_attempts=3).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "auth"
    assert result.attempts == 1


def test_malformed_response_becomes_client_error_not_traceback():
    # A misconfigured base_url (e.g. missing "/v1") can make a gateway return its
    # frontend HTML as a plain string instead of a JSON error - _parse_response must
    # not crash on that with an unhandled AttributeError.
    def transport(req, t):
        return "<!doctype html><html>not a real response</html>"

    result = _client("gpt-5.4-mini", transport=transport).complete(_user())
    assert isinstance(result, ClientError)
    assert result.kind == "invalid_request"
    assert result.attempts == 1


def test_default_params_used_when_none_passed():
    client = _client("gpt-5.4-mini", default_params=GenerationParams(effort="low"))
    captured = {}

    def transport(req, t):
        captured.update(req)
        return _fake_reply()

    client._transport = transport
    client.complete(_user())  # no params -> uses default_params
    assert captured["reasoning_effort"] == "low"


def test_complete_happy_path_across_models():
    for model_id in ("gpt-5.5", "gpt-5.4-mini", "glm-5.2", "deepseek-v4-flash"):
        result = _client(model_id).complete(_user())
        assert not isinstance(result, ClientError)
        assert result.content == "ok"
