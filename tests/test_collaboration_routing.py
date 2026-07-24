"""Deterministic bilingual collaboration mode routing tests."""

from __future__ import annotations

import pytest

from forgeagent.collaboration import resolve_collaboration_mode


@pytest.mark.parametrize(
    ("action", "artifact"),
    [
        ("Add", "a unit test"),
        ("Remove", "obsolete code"),
        ("Delete", "obsolete code"),
        ("Rename", "parser.py"),
        ("Write", "a script"),
        ("Create", "a module"),
        ("Modify", "Main.java"),
        ("Edit", "package.json"),
        ("Update", "Cargo.toml"),
        ("Implement", "an API"),
        ("Fix", "the tests"),
        ("Refactor", "this class"),
        ("Test", "the package"),
        ("Build", "the project"),
    ],
)
def test_direct_english_change_action_and_artifact_categories_route_to_triad(
    action: str, artifact: str
):
    assert resolve_collaboration_mode(f"{action} {artifact}", None).mode == "triad"


@pytest.mark.parametrize(
    ("action", "artifact"),
    [
        ("添加", "单元测试"),
        ("移除", "旧代码"),
        ("删除", "旧代码"),
        ("重命名", "Main.java"),
        ("编写", "脚本"),
        ("创建", "模块"),
        ("修改", "Main.java"),
        ("编辑", "package.json"),
        ("更新", "Cargo.toml"),
        ("实现", "接口"),
        ("修复", "测试"),
        ("重构", "这个类"),
        ("测试", "软件包"),
        ("构建", "项目"),
    ],
)
def test_direct_chinese_change_action_and_artifact_categories_route_to_triad(
    action: str, artifact: str
):
    assert resolve_collaboration_mode(f"{action}{artifact}", None).mode == "triad"


@pytest.mark.parametrize(
    "filename",
    [
        "main.py",
        "main.ts",
        "view.tsx",
        "main.js",
        "view.jsx",
        "lib.rs",
        "main.go",
        "Main.java",
        "Main.kt",
        "app.rb",
        "index.php",
        "App.swift",
        "main.c",
        "main.cc",
        "main.cpp",
        "main.h",
        "main.hpp",
        "Program.cs",
        "build.sh",
        "setup.bash",
        "env.zsh",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "build.gradle",
        "settings.gradle",
        "pom.xml",
        "Makefile",
    ],
)
def test_common_source_test_and_build_files_route_with_a_direct_action(filename: str):
    assert resolve_collaboration_mode(f"Please modify {filename}", None).mode == "triad"


@pytest.mark.parametrize(
    "goal",
    [
        "Can you add a unit test?",
        "Could you delete obsolete code?",
        "I need you to update Cargo.toml",
        "I want you to modify Main.java",
        "请添加单元测试",
        "帮我删除旧代码",
        "麻烦你修改 Main.java",
    ],
)
def test_polite_direct_request_prefixes_still_route_to_triad(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "triad"


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
        'Write the phrase "create code" in the report',
        "Add the example 'modify Main.java' to the report",
        "写下“创建代码”这句话",
        "Write `create code` in the report",
        'Explain the example "review it; then create code"',
        "Explain `review it; then create code`",
        "解释示例“先审查；然后创建代码”",
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
        "Add examples showing how to create code",
        "Please review how to update Cargo.toml",
        "请审查如何修改 Main.java",
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
        "Explain the code first, then add a unit test",
        "请先说明现状，然后修改 Main.java",
        "不要修改 Main.java；然后添加单元测试",
    ],
)
def test_later_affirmative_programming_clause_still_routes_to_triad(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "triad"


@pytest.mark.parametrize(
    "goal",
    [
        "编写可再现测试代码",
        "解释现状，再修改 Main.java",
        "请再修改 Main.java",
    ],
)
def test_chinese_sequence_marker_does_not_split_ordinary_words(goal: str):
    assert resolve_collaboration_mode(goal, None).mode == "triad"
