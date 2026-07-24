"""Deterministic bilingual collaboration mode routing tests."""

from __future__ import annotations

import pytest

from forgeagent.collaboration import resolve_collaboration_mode


@pytest.mark.parametrize(
    "goal",
    [
        "Create a Python script to parse records",
        "修复这个代码项目中的测试",
        "Update package.json",
        "构建 src/main.go",
    ],
)
def test_programming_requests_route_to_triad(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "triad"


@pytest.mark.parametrize(
    "goal", ["Explain Python decorators", "Review this report", "解释这个函数的作用"]
)
def test_explanations_and_review_prose_do_not_false_positive(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "single"


def test_explicit_modes_and_weaker_override_conflict_are_deterministic():
    assert resolve_collaboration_mode("Create code", "triad").mode == "triad"
    blocked = resolve_collaboration_mode("Create code", "single")
    assert blocked.mode == "triad"
    assert blocked.override_required is True
    assert (
        resolve_collaboration_mode("Create code", "duo", allow_weaker_override=True).mode == "duo"
    )
