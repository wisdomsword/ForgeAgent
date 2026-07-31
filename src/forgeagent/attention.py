"""Bounded attention states for callers that need to act on a task result."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .secret_policy import mask_audit_data, sensitive_env_values

MAX_ATTENTION_TEXT_CHARS = 500
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

AttentionState = Literal["running", "needs_input", "blocked", "ready"]
AttentionOwner = Literal["user", "system", "external", "provider"]


def _public_text(value: str) -> str:
    projected = mask_audit_data(value, sensitive_env_values())
    text = projected if isinstance(projected, str) else ""
    text = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} else character
        for character in text
    ).strip()
    return text[:MAX_ATTENTION_TEXT_CHARS]


class Attention(BaseModel):
    """A safe, additive projection of what needs the caller's attention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AttentionState
    reason: str
    owner: AttentionOwner
    required_action: str
    recovery: str

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
            raise ValueError("attention reason must be a stable code")
        return value

    @field_validator("required_action", "recovery")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = _public_text(value)
        if not text:
            raise ValueError("attention text must not be blank")
        return text


def attention_for_reason(reason: str | None, detail: str | None = None) -> Attention:
    """Map existing task/Loop reasons to one stable attention projection."""

    if reason is None:
        return Attention(
            state="running",
            reason="execution_in_progress",
            owner="system",
            required_action="Wait for the current execution to reach a safe boundary.",
            recovery="The task publishes a result or another attention state.",
        )
    if reason == "needs_info":
        return Attention(
            state="needs_input",
            reason="user_input_required",
            owner="user",
            required_action=detail or "Provide the requested input.",
            recovery="Submit the required input and explicitly continue the task.",
        )
    if reason == "blocked":
        return Attention(
            state="blocked",
            reason="external_dependency",
            owner="external",
            required_action=detail or "Resolve the blocking dependency.",
            recovery="Explicitly retry or resume after the dependency is available.",
        )
    if reason == "external_action_pending":
        return Attention(
            state="blocked",
            reason="external_action_pending",
            owner="user",
            required_action="Reconcile the unresolved external action.",
            recovery="Confirm or abandon the receipt before explicitly resuming.",
        )
    return Attention(
        state="ready",
        reason="result_available",
        owner="system",
        required_action="Consume the available task result.",
        recovery="The caller accepts the result or starts an explicit follow-up action.",
    )
