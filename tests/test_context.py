from pathlib import Path

import pytest
from pydantic import ValidationError

from forgeagent.context import (
    ContextConfig,
    estimate_message_tokens,
    estimate_request_tokens,
    estimate_text_tokens,
    load_context_config,
)
from forgeagent.models import ImageItem, Message, Role, TextItem


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
