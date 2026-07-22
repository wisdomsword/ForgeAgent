from pathlib import Path

import pytest
from pydantic import ValidationError

from forgeagent.context import (
    ContextBudgetExceeded,
    ContextConfig,
    SlidingWindowContextPolicy,
    estimate_message_tokens,
    estimate_request_tokens,
    estimate_text_tokens,
    load_context_config,
)
from forgeagent.models import GenerationParams, ImageItem, Message, ModelCapability, Role, TextItem


def _image() -> ImageItem:
    return ImageItem(media_type="image/png", data="not-counted-as-text")


def test_context_config_missing_mapping_uses_bounded_defaults():
    config = load_context_config(data={"groups": []})

    assert config.utilization_ratio == 0.8
    assert config.image_token_reserve == 4096
    assert config.tool_result_max_tokens is None
    assert config.round_feedback_max_tokens is None


def test_context_config_is_frozen_and_rejects_invalid_explicit_limits():
    config = ContextConfig()

    with pytest.raises(ValidationError):
        config.utilization_ratio = 0.5
    with pytest.raises(ValidationError, match="round feedback limit"):
        ContextConfig(tool_result_max_tokens=100, round_feedback_max_tokens=99)


@pytest.mark.parametrize(
    "context",
    [
        {"utilization_ratio": 0},
        {"utilization_ratio": 1.1},
        {"utilization_ratio": "0.8"},
        {"image_token_reserve": 0},
        {"image_token_reserve": "100"},
        {"tool_result_max_tokens": 0},
        {"round_feedback_max_tokens": 0},
    ],
)
def test_context_config_rejects_invalid_context_values(context: dict[str, object]):
    with pytest.raises(ValidationError):
        load_context_config(data={"context": context})


def test_context_config_rejects_non_mapping_context():
    with pytest.raises(ValueError, match="context"):
        load_context_config(data={"context": []})


def test_load_context_config_reads_only_top_level_context_mapping(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "utilization_ratio: 0.1\ncontext:\n  utilization_ratio: 0.5\n  image_token_reserve: 99\n"
    )

    assert load_context_config(path) == ContextConfig(utilization_ratio=0.5, image_token_reserve=99)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("abcde", 2),
        ("a b", 1),
        ("!?.,", 2),
        ("你好", 3),
        ("x=1\n", 2),
        ('{"x":1}', 4),
        ("😀", 2),
        ("", 0),
    ],
)
def test_estimate_text_tokens_uses_ceil_by_character_category(text: str, expected: int):
    assert estimate_text_tokens(text) == expected


def test_estimator_uses_ceil_and_image_reserve():
    config = ContextConfig(image_token_reserve=100)
    message = Message(role=Role.USER, content=[TextItem(text="abcde"), _image()])

    assert estimate_text_tokens("abcde") == 2
    assert estimate_message_tokens(message, config) == 2 + 100 + 4


def test_estimate_message_tokens_counts_empty_text_and_each_image():
    config = ContextConfig(image_token_reserve=7)
    text_message = Message(role=Role.SYSTEM, content="")
    multimodal_message = Message(
        role=Role.USER,
        content=[TextItem(text="你"), _image(), _image()],
    )

    assert estimate_message_tokens(text_message, config) == 4
    assert estimate_message_tokens(multimodal_message, config) == 2 + 7 + 7 + 4


def test_estimate_request_tokens_adds_request_framing_and_ignores_role():
    config = ContextConfig(image_token_reserve=10)
    system = Message(role=Role.SYSTEM, content="abc")
    user = Message(role=Role.USER, content="abc")

    assert estimate_message_tokens(system, config) == estimate_message_tokens(user, config) == 5
    assert estimate_request_tokens([system, user], config) == 12


def _capability(context_window: int, max_output_tokens: int) -> ModelCapability:
    return ModelCapability(
        model_id="context-test",
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )


def _conversation_with_three_rounds() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="goal"),
        Message(role=Role.ASSISTANT, content="first assistant"),
        Message(role=Role.USER, content="first feedback"),
        Message(role=Role.ASSISTANT, content="second assistant"),
        Message(role=Role.USER, content="second feedback"),
        Message(role=Role.ASSISTANT, content="third assistant"),
        Message(role=Role.USER, content="third feedback"),
    ]


def _small_policy_that_fits_two_rounds() -> SlidingWindowContextPolicy:
    return SlidingWindowContextPolicy(_capability(70, 10), None, ContextConfig(utilization_ratio=1))


def test_policy_reserves_effective_output_and_resolves_adaptive_limits():
    policy = SlidingWindowContextPolicy(
        _capability(1000, 200),
        GenerationParams(max_output_tokens=100),
        ContextConfig(),
    )

    assert policy.input_budget == 700
    assert policy.round_feedback_limit == 70
    assert policy.tool_result_limit == 17
    with pytest.raises(AttributeError):
        policy.input_budget = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("config", "expected_round_limit", "expected_result_limit"),
    [
        (ContextConfig(round_feedback_max_tokens=90), 90, 22),
        (ContextConfig(tool_result_max_tokens=20), 70, 20),
    ],
)
def test_policy_resolves_each_explicit_limit_independently(
    config: ContextConfig, expected_round_limit: int, expected_result_limit: int
):
    policy = SlidingWindowContextPolicy(
        _capability(1000, 200), GenerationParams(max_output_tokens=100), config
    )

    assert policy.round_feedback_limit == expected_round_limit
    assert policy.tool_result_limit == expected_result_limit


@pytest.mark.parametrize(
    ("capability", "config", "match"),
    [
        (_capability(100, 100), ContextConfig(utilization_ratio=1), "input budget"),
        (_capability(20, 1), ContextConfig(utilization_ratio=1), "tool result"),
        (
            _capability(1000, 200),
            ContextConfig(tool_result_max_tokens=80),
            "round feedback",
        ),
    ],
)
def test_policy_rejects_non_positive_or_inconsistent_resolved_limits(
    capability: ModelCapability, config: ContextConfig, match: str
):
    with pytest.raises(ValueError, match=match):
        SlidingWindowContextPolicy(capability, None, config)


def test_policy_drops_oldest_complete_round_without_mutating_input():
    conversation = _conversation_with_three_rounds()
    snapshot = [message.model_copy(deep=True) for message in conversation]

    view = _small_policy_that_fits_two_rounds().request_view(conversation)

    assert view == [conversation[0], conversation[1], *conversation[-4:]]
    assert conversation == snapshot
    assert view is not conversation


def test_policy_preserves_conversation_exactly_below_budget():
    conversation = _conversation_with_three_rounds()
    policy = SlidingWindowContextPolicy(
        _capability(200, 10), None, ContextConfig(utilization_ratio=1)
    )

    view = policy.request_view(conversation)

    assert view == conversation
    assert view is not conversation
    assert all(returned is original for returned, original in zip(view, conversation, strict=True))


def test_policy_never_splits_tool_call_and_feedback_round():
    conversation = [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="goal"),
        Message(role=Role.ASSISTANT, content="<!-- ToolCall: {\"name\": \"Exec\"} -->"),
        Message(role=Role.USER, content="tool feedback"),
        Message(role=Role.ASSISTANT, content="latest assistant"),
        Message(role=Role.USER, content="latest feedback"),
    ]
    policy = SlidingWindowContextPolicy(
        _capability(50, 10), None, ContextConfig(utilization_ratio=1)
    )

    view = policy.request_view(conversation)

    assert view == [conversation[0], conversation[1], *conversation[-2:]]


def test_policy_rejects_prefix_that_exceeds_budget_with_bounded_detail():
    policy = SlidingWindowContextPolicy(
        _capability(70, 10), None, ContextConfig(utilization_ratio=1)
    )
    conversation = [
        Message(role=Role.SYSTEM, content="x" * 300),
        Message(role=Role.USER, content="goal"),
    ]

    with pytest.raises(ContextBudgetExceeded) as raised:
        policy.request_view(conversation)

    assert "prefix" in raised.value.detail
    assert len(raised.value.detail) <= 160


def test_policy_rejects_prefix_and_latest_round_that_exceed_budget():
    policy = SlidingWindowContextPolicy(
        _capability(38, 10),
        None,
        ContextConfig(utilization_ratio=1, round_feedback_max_tokens=4, tool_result_max_tokens=1),
    )
    conversation = [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="goal"),
        Message(role=Role.ASSISTANT, content="latest assistant"),
        Message(role=Role.USER, content="latest feedback"),
    ]

    with pytest.raises(ContextBudgetExceeded) as raised:
        policy.request_view(conversation)

    assert "latest round" in raised.value.detail


def test_policy_rejects_invalid_prefix_shape_with_bounded_detail():
    policy = SlidingWindowContextPolicy(
        _capability(100, 10), None, ContextConfig(utilization_ratio=1)
    )

    with pytest.raises(ContextBudgetExceeded) as raised:
        policy.request_view([Message(role=Role.USER, content="goal")])

    assert "prefix" in raised.value.detail
    assert len(raised.value.detail) <= 160
