"""Deterministic bilingual collaboration mode routing tests."""

from __future__ import annotations

import pytest

from forgeagent.collaboration import resolve_collaboration_mode


@pytest.mark.parametrize(
    "goal",
    [
        "Create a Python script to parse records",
        "Create a file named 'foo.py'",
        'Modify "src/main.py"',
        "Edit `package.json`",
        "Write code",
        "Implement an API",
        "Fix the tests",
        "Refactor this class",
        "Test the package",
        "Build the project",
        "修复这个代码项目中的测试",
        "写一个脚本",
        "创建一个程序",
        "实现这个接口",
        "重构这个类",
        "测试这个包",
        "构建这个项目",
        '修改 "src/main.py"',
        "不要解释作用，只修改 src/main.py",
        "Do not summarize it; edit package.json",
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


@pytest.mark.parametrize(
    "goal",
    [
        "Explain foo.py",
        "Review src/main.py",
        "Read package.json and summarize it",
        "不要修改 src/main.py，只解释作用",
        "Do not edit package.json; summarize it",
    ],
)
def test_recognized_filename_requires_an_affirmative_programming_action(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "single"


def test_explicit_modes_and_weaker_override_conflict_are_deterministic():
    assert resolve_collaboration_mode("Create code", "triad").mode == "triad"
    blocked = resolve_collaboration_mode("Create code", "single")
    assert blocked.mode == "triad"
    assert blocked.override_required is True
    assert (
        resolve_collaboration_mode("Create code", "duo", allow_weaker_override=True).mode == "duo"
    )


@pytest.mark.parametrize(
    "goal",
    [
        "Explain test strategy",
        "Review the code policy",
        "contest rules",
        "Do not create code; explain the policy",
        'Explain the phrase "create code"',
        "不要创建代码，只解释策略",
        "无需修复测试，请说明原因",
        "解释“创建代码”这句话",
    ],
)
def test_programming_routing_excludes_boundaries_negation_and_quotations(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "single"


@pytest.mark.parametrize(
    "goal",
    [
        "Explain how to create code",
        "Review instructions to modify package.json",
        "Tell me why we should refactor this class",
        "Explain how to write tests",
        "解释如何创建代码",
        "审查修改 package.json 的说明",
        "告诉我为什么应该重构这个类",
        "说明如何编写测试",
    ],
)
def test_explanation_read_and_review_framing_stays_single(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "single"


@pytest.mark.parametrize(
    "goal",
    [
        "Explain how to create code; then create the script",
        "Review instructions to modify package.json, then update package.json",
        "Review how to modify this class then refactor this class",
        "解释如何创建代码，然后创建代码",
        "审查修改 package.json 的说明；然后更新 package.json",
        "审查如何修改这个类然后重构这个类",
    ],
)
def test_later_affirmative_programming_clause_still_routes_to_triad(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "triad"
