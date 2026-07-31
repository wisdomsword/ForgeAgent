"""Attention-state contract and safe public projection tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forgeagent.attention import Attention, attention_for_reason


@pytest.mark.parametrize(
    ("reason", "state", "public_reason", "owner"),
    [
        (None, "running", "execution_in_progress", "system"),
        ("completed", "ready", "result_available", "system"),
        ("needs_info", "needs_input", "user_input_required", "user"),
        ("blocked", "blocked", "external_dependency", "external"),
        ("external_action_pending", "blocked", "external_action_pending", "user"),
    ],
)
def test_attention_for_reason_maps_stable_states(
    reason: str | None,
    state: str,
    public_reason: str,
    owner: str,
) -> None:
    attention = attention_for_reason(reason)

    assert attention.state == state
    assert attention.reason == public_reason
    assert attention.owner == owner
    assert attention.required_action
    assert attention.recovery


def test_attention_masks_secrets_paths_controls_and_bounds_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "attention-secret-value"
    monkeypatch.setenv("ATTENTION_TOKEN", secret)
    detail = f"answer {secret}\nfrom /Users/example/private.txt " + "x" * 1000

    attention = attention_for_reason("needs_info", detail)

    assert secret not in attention.required_action
    assert "/Users/example/private.txt" not in attention.required_action
    assert "\n" not in attention.required_action
    assert len(attention.required_action) <= 500


def test_attention_rejects_unknown_fields_and_invalid_codes() -> None:
    with pytest.raises(ValidationError):
        Attention(
            state="ready",
            reason="result_available",
            owner="system",
            required_action="consume result",
            recovery="result consumed",
            unexpected="nope",
        )

    with pytest.raises(ValidationError):
        Attention(
            state="ready",
            reason="Not a stable code",
            owner="system",
            required_action="consume result",
            recovery="result consumed",
        )
