"""Context configuration and deterministic token estimation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import GenerationParams, Message, ModelCapability, Role, TextItem

_DEFAULT_CONFIG_PATH = Path.home() / ".forgeagent" / "config.yaml"
_MAX_CONTEXT_ERROR_DETAIL_LENGTH = 160


class ContextBudgetExceeded(ValueError):
    """Raised when an intact local conversation view cannot fit the request budget."""

    def __init__(self, detail: str):
        self.detail = detail[:_MAX_CONTEXT_ERROR_DETAIL_LENGTH]
        super().__init__(self.detail)


class ContextPolicy(Protocol):
    """Build a bounded, non-destructive message view for one model request."""

    def request_view(self, messages: Sequence[Message]) -> list[Message]:
        """Return the messages that fit this policy's request budget."""


class SlidingWindowContextPolicy:
    """Keep the fixed prefix and the newest complete conversation rounds."""

    def __init__(
        self,
        capability: ModelCapability,
        params: GenerationParams | None,
        config: ContextConfig,
    ):
        effective_output = (
            params.max_output_tokens
            if params is not None and params.max_output_tokens is not None
            else capability.max_output_tokens
        )
        input_budget = math.floor(capability.context_window * config.utilization_ratio)
        input_budget -= effective_output
        if input_budget <= 0:
            raise ValueError("input budget must be positive")

        round_feedback_limit = (
            config.round_feedback_max_tokens
            if config.round_feedback_max_tokens is not None
            else math.floor(input_budget * 0.10)
        )
        tool_result_limit = (
            config.tool_result_max_tokens
            if config.tool_result_max_tokens is not None
            else math.floor(round_feedback_limit * 0.25)
        )
        if round_feedback_limit <= 0:
            raise ValueError("round feedback limit must be positive")
        if tool_result_limit <= 0:
            raise ValueError("tool result limit must be positive")
        if round_feedback_limit < tool_result_limit:
            raise ValueError("round feedback limit must be >= tool result limit")

        self._config = config
        self._input_budget = input_budget
        self._round_feedback_limit = round_feedback_limit
        self._tool_result_limit = tool_result_limit

    @property
    def input_budget(self) -> int:
        """The maximum estimated input tokens for one model request."""
        return self._input_budget

    @property
    def round_feedback_limit(self) -> int:
        """The maximum estimated feedback tokens for one completed round."""
        return self._round_feedback_limit

    @property
    def tool_result_limit(self) -> int:
        """The maximum estimated detail tokens for one tool result."""
        return self._tool_result_limit

    def request_view(self, messages: Sequence[Message]) -> list[Message]:
        """Return the newest complete rounds that fit, without changing messages."""
        prefix, rounds = self._validated_prefix_and_rounds(messages)
        if estimate_request_tokens(prefix, self._config) > self._input_budget:
            raise ContextBudgetExceeded("context prefix exceeds input budget")

        chosen_newest_first: list[tuple[Message, Message]] = []
        for round_messages in reversed(rounds):
            candidate_rounds = [round_messages, *chosen_newest_first]
            candidate = [*prefix, *(message for pair in candidate_rounds for message in pair)]
            if estimate_request_tokens(candidate, self._config) <= self._input_budget:
                chosen_newest_first = candidate_rounds
                continue
            if not chosen_newest_first:
                raise ContextBudgetExceeded("context prefix and latest round exceed input budget")
            break

        return [*prefix, *(message for pair in chosen_newest_first for message in pair)]

    @staticmethod
    def _validated_prefix_and_rounds(
        messages: Sequence[Message],
    ) -> tuple[list[Message], list[tuple[Message, Message]]]:
        if (
            len(messages) < 2
            or messages[0].role is not Role.SYSTEM
            or messages[1].role is not Role.USER
        ):
            raise ContextBudgetExceeded(
                "conversation prefix must contain system prompt and initial goal"
            )

        history = messages[2:]
        if len(history) % 2:
            raise ContextBudgetExceeded("conversation history contains an incomplete round")

        rounds: list[tuple[Message, Message]] = []
        for index in range(0, len(history), 2):
            assistant, feedback = history[index : index + 2]
            if assistant.role is not Role.ASSISTANT or feedback.role is not Role.USER:
                raise ContextBudgetExceeded(
                    "conversation history must contain assistant and feedback rounds"
                )
            rounds.append((assistant, feedback))
        return list(messages[:2]), rounds


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
