"""Context configuration and deterministic token estimation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Message, TextItem

_DEFAULT_CONFIG_PATH = Path.home() / ".forgeagent" / "config.yaml"


class ContextConfig(BaseModel):
    """Validated limits used by context policies."""

    utilization_ratio: float = Field(default=0.8, gt=0, le=1, strict=True)
    image_token_reserve: int = Field(default=4096, gt=0, strict=True)
    tool_result_max_tokens: int | None = Field(default=None, gt=0, strict=True)
    round_feedback_max_tokens: int | None = Field(default=None, gt=0, strict=True)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def validate_explicit_limits(self) -> Self:
        if (
            self.tool_result_max_tokens is not None
            and self.round_feedback_max_tokens is not None
            and self.round_feedback_max_tokens < self.tool_result_max_tokens
        ):
            raise ValueError("round feedback limit must be >= tool result limit")
        return self


def load_context_config(
    path: Path | None = None,
    *,
    data: Mapping[str, object] | None = None,
) -> ContextConfig:
    """Load and validate only the top-level ``context`` configuration mapping."""
    if data is None:
        config_path = _DEFAULT_CONFIG_PATH if path is None else path
        if config_path.exists():
            loaded = yaml.safe_load(config_path.read_text()) or {}
        else:
            loaded = {}
    else:
        loaded = data

    if not isinstance(loaded, Mapping):
        raise ValueError("configuration root must be a mapping")
    context = loaded.get("context", {})
    if not isinstance(context, Mapping):
        raise ValueError("context must be a mapping")
    return ContextConfig.model_validate(context)


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens conservatively from ASCII and UTF-8 character categories."""
    ascii_words_or_space = 0
    ascii_punctuation = 0
    non_ascii_bytes = 0
    for character in text:
        if character.isascii():
            if character.isalnum() or character.isspace():
                ascii_words_or_space += 1
            else:
                ascii_punctuation += 1
        else:
            non_ascii_bytes += len(character.encode("utf-8"))
    return (
        math.ceil(ascii_words_or_space / 4)
        + math.ceil(ascii_punctuation / 2)
        + math.ceil(non_ascii_bytes / 2)
    )


def estimate_message_tokens(message: Message, config: ContextConfig) -> int:
    """Estimate message content plus its fixed request framing."""
    if isinstance(message.content, str):
        content_tokens = estimate_text_tokens(message.content)
    else:
        content_tokens = sum(
            estimate_text_tokens(item.text)
            if isinstance(item, TextItem)
            else config.image_token_reserve
            for item in message.content
        )
    return content_tokens + 4


def estimate_request_tokens(messages: Sequence[Message], config: ContextConfig) -> int:
    """Estimate all request messages plus the request framing."""
    return sum(estimate_message_tokens(message, config) for message in messages) + 2
