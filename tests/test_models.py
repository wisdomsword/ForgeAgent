"""Unit tests for core data models (M2-2)."""

import math

import pytest
from pydantic import ValidationError

from forgeagent.models import (
    AssistantMessage,
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    Role,
    TokenUsage,
)


def test_generation_params_defaults():
    p = GenerationParams()
    assert p.max_output_tokens is None
    assert p.temperature is None
    assert p.thinking == "auto"  # safest default: omit thinking param
    assert p.effort is None
    assert p.timeout_seconds == 120.0


@pytest.mark.parametrize("value", [0, -1])
def test_generation_params_rejects_non_positive_output_limit(value):
    with pytest.raises(ValidationError):
        GenerationParams(max_output_tokens=value)


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_generation_params_rejects_non_finite_or_non_positive_timeout(value):
    with pytest.raises(ValidationError):
        GenerationParams(timeout_seconds=value)


def test_generation_params_thinking_tristate():
    for value in ("on", "off", "auto"):
        assert GenerationParams(thinking=value).thinking == value
    with pytest.raises(ValidationError):
        GenerationParams(thinking="maybe")


def test_generation_params_effort_range():
    for value in ("low", "medium", "high", "xhigh", "max"):
        assert GenerationParams(effort=value).effort == value
    with pytest.raises(ValidationError):
        GenerationParams(effort="turbo")


def test_client_error_kind_enum_and_refusal_excluded():
    for kind in ("network", "auth", "rate_limit", "invalid_request", "timeout", "unknown"):
        assert ClientError(message="x", kind=kind, attempts=1).kind == kind
    # refusal must NOT be a valid ClientError kind — it is a successful response.
    with pytest.raises(ValidationError):
        ClientError(message="x", kind="refusal", attempts=1)


def test_client_error_attempts_min():
    assert ClientError(message="x", kind="network", attempts=3).attempts == 3
    with pytest.raises(ValidationError):
        ClientError(message="x", kind="network", attempts=0)


def test_assistant_message_carries_usage_and_stop_reason():
    msg = AssistantMessage(
        content="done",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    assert msg.role is Role.ASSISTANT
    assert msg.usage.output_tokens == 5
    # refusal surfaces here, not as a ClientError.
    refusal = AssistantMessage(content="", usage=TokenUsage(), stop_reason="refusal")
    assert refusal.stop_reason == "refusal"


def test_message_roles():
    assert Message(role=Role.SYSTEM, content="s").role is Role.SYSTEM
    assert Message(role=Role.USER, content="u").role is Role.USER


def test_model_capability_fields():
    cap = ModelCapability(
        model_id="claude-haiku-4-5",
        context_window=200_000,
        max_output_tokens=64_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )
    assert cap.max_output_tokens == 64_000
    assert cap.supports_effort is False
    assert cap.client_kind == "anthropic"
    assert cap.max_tokens_param == "max_tokens"


@pytest.mark.parametrize("field", ["context_window", "max_output_tokens"])
@pytest.mark.parametrize("value", [0, -1])
def test_model_capability_rejects_non_positive_limits(field, value):
    values = {
        "model_id": "model",
        "context_window": 1,
        "max_output_tokens": 1,
        "supports_thinking": False,
        "thinking_always_on": False,
        "supports_effort": False,
        "client_kind": "anthropic",
        field: value,
    }
    with pytest.raises(ValidationError):
        ModelCapability(**values)


def test_model_capability_max_tokens_param_defaults_and_override():
    cap = ModelCapability(
        model_id="gpt-5.5",
        context_window=1_050_000,
        max_output_tokens=128_000,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=True,
        client_kind="openai_compatible",
        max_tokens_param="max_completion_tokens",
    )
    assert cap.max_tokens_param == "max_completion_tokens"
