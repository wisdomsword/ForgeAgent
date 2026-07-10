"""Unit tests for ModelClient ABC and MockClient (M2-4)."""

import pytest

from forgeagent.client import MockClient, MockScriptExhausted, ModelClient
from forgeagent.models import (
    AssistantMessage,
    ClientError,
    Message,
    Role,
    TokenUsage,
)


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason="end_turn")


def _user(text: str) -> list[Message]:
    return [Message(role=Role.USER, content=text)]


def test_mock_client_is_a_model_client():
    assert isinstance(MockClient(script=[]), ModelClient)


def test_mock_client_returns_script_in_order():
    client = MockClient(script=[_reply("first"), _reply("second")])
    assert client.complete(_user("a")).content == "first"
    assert client.complete(_user("b")).content == "second"
    assert client.calls_made == 2


def test_mock_client_can_return_client_error():
    err = ClientError(message="boom", kind="network", attempts=3)
    client = MockClient(script=[err])
    result = client.complete(_user("a"))
    assert isinstance(result, ClientError)
    assert result.kind == "network"


def test_mock_client_raises_when_script_exhausted():
    client = MockClient(script=[_reply("only")])
    client.complete(_user("a"))
    with pytest.raises(MockScriptExhausted):
        client.complete(_user("b"))


def test_mock_client_default_capability():
    cap = MockClient(script=[]).capability
    assert cap.model_id == "mock"


def test_mock_client_complete_never_raises_for_scripted_error():
    # A scripted ClientError is returned, not raised — mirrors the contract that
    # complete() never raises for known backend errors.
    client = MockClient(script=[ClientError(message="x", kind="auth", attempts=1)])
    result = client.complete(_user("a"))
    assert isinstance(result, ClientError)
