"""Context configuration and deterministic token estimation."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import GenerationParams, Message, ModelCapability, Role, TextItem

if TYPE_CHECKING:
    from .tools import ToolOutcome

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


@dataclass(frozen=True)
class _FeedbackItem:
    header: str
    detail: str
    continuation: str | None
    mode: Literal["head", "tail"]


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


def render_bounded_feedback(
    parse_errors: Sequence[str],
    outcomes: Sequence[ToolOutcome],
    *,
    result_limit: int,
    round_limit: int,
    mask: Callable[[str], str],
) -> str:
    """Render ordered feedback within per-result and per-round token limits."""
    if result_limit <= 0:
        raise ValueError("result limit must be positive")
    if round_limit <= 0:
        raise ValueError("round limit must be positive")
    if round_limit < result_limit:
        raise ValueError("round limit must be >= result limit")

    items = [
        _FeedbackItem(
            header="[parse error] ",
            detail=error,
            continuation=None,
            mode="tail",
        )
        for error in parse_errors
    ]
    items.extend(_feedback_item(outcome, mask) for outcome in outcomes)
    if not items:
        return ""

    demands = [min(estimate_text_tokens(item.detail), result_limit) for item in items]
    truncated: set[int] = set()
    allocations: list[int] = []
    for _ in range(len(items) + 1):
        minimum_metadata = _render_metadata(items, truncated, reserve_digits=False)
        if estimate_text_tokens(minimum_metadata) > round_limit:
            raise ContextBudgetExceeded("feedback metadata exceeds context budget")

        reserved_metadata = _render_metadata(items, truncated, reserve_digits=True)
        available = max(0, round_limit - estimate_text_tokens(reserved_metadata))
        allocations = _waterfill(demands, available)
        expanded = truncated | {
            index
            for index, item in enumerate(items)
            if estimate_text_tokens(item.detail) > allocations[index]
        }
        if expanded == truncated:
            break
        truncated = expanded
    else:  # pragma: no cover - the set grows at most once per item
        raise RuntimeError("feedback limiter did not converge")

    rendered = "\n".join(
        _render_feedback_item(item, allocations[index], index in truncated)
        for index, item in enumerate(items)
    )
    if estimate_text_tokens(rendered) > round_limit:  # defensive invariant
        raise ContextBudgetExceeded("feedback metadata exceeds context budget")
    return rendered


def _feedback_item(outcome: ToolOutcome, mask: Callable[[str], str]) -> _FeedbackItem:
    label = f"[{outcome.tool} {outcome.block_name}]"
    if outcome.success and outcome.exec_result is not None:
        primary = outcome.exec_result.stdout.strip()
        header = f"{label} ok" + (": " if primary else "")
    elif outcome.success:
        primary = outcome.detail
        header = f"{label} "
    else:
        primary = outcome.detail
        header = f"{label} FAILED: "

    detail = primary
    if outcome.static_feedback:
        detail += f"\n{outcome.static_feedback}"
    if outcome.exec_result and outcome.exec_result.dropped_state_keys:
        keys = ", ".join(outcome.exec_result.dropped_state_keys)
        detail += (
            f"\n{label} note: state key(s) {keys} could not be carried to the next "
            "block (not JSON-serializable) and are unset there"
        )
    continuation = mask(outcome.continuation) if outcome.continuation else None
    return _FeedbackItem(
        header=header,
        detail=detail,
        continuation=continuation,
        mode=outcome.truncation_mode,
    )


def _waterfill(demands: Sequence[int], budget: int) -> list[int]:
    allocations = [0] * len(demands)
    remaining = budget
    active = [index for index, demand in enumerate(demands) if demand]
    while remaining and active:
        share, remainder = divmod(remaining, len(active))
        spent = 0
        for position, index in enumerate(active):
            grant = share + (position < remainder)
            granted = min(grant, demands[index] - allocations[index])
            allocations[index] += granted
            spent += granted
        if spent == 0:
            break
        remaining -= spent
        active = [index for index in active if allocations[index] < demands[index]]
    return allocations


def _render_metadata(
    items: Sequence[_FeedbackItem], truncated: set[int], *, reserve_digits: bool
) -> str:
    return "\n".join(
        (
            _render_feedback_item(
                item,
                0,
                True,
                marker_shown=len(item.detail) if reserve_digits else 0,
            )
            if index in truncated
            else item.header
        )
        for index, item in enumerate(items)
    )


def _render_feedback_item(
    item: _FeedbackItem,
    detail_budget: int,
    truncated: bool,
    *,
    marker_shown: int | None = None,
) -> str:
    if not truncated:
        return f"{item.header}{item.detail}"

    fragment = _largest_fragment(item.detail, detail_budget, item.mode)
    shown = len(fragment) if marker_shown is None else marker_shown
    range_description = "first" if item.mode == "head" else "last"
    marker = (
        f"[truncated: original {len(item.detail)} chars; showing {range_description} {shown} chars]"
    )
    continuation = f"\n[continuation] {item.continuation}" if item.continuation else ""
    if item.mode == "head":
        return f"{item.header}{fragment}\n{marker}{continuation}"
    return f"{item.header}{marker}{continuation}\n{fragment}"


def _largest_fragment(detail: str, budget: int, mode: Literal["head", "tail"]) -> str:
    low = 0
    high = len(detail)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = detail[:middle] if mode == "head" else detail[-middle:]
        if estimate_text_tokens(candidate) <= budget:
            low = middle
        else:
            high = middle - 1
    if low == 0:
        return ""
    return detail[:low] if mode == "head" else detail[-low:]
