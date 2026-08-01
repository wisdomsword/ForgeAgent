"""Offline contracts for the current documentation entry point."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
INDEX = ROOT / "docs" / "README.md"
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_documentation_index_has_required_sections_and_authorities() -> None:
    text = _read(INDEX)
    for heading in (
        "## 当前权威入口",
        "## 开发流程",
        "## 里程碑与证据",
        "## 评审与治理",
        "## 运行时参考",
        "## 历史资料",
    ):
        assert heading in text
    for target in (
        "../spec.md",
        "../ACTION_PLAN.md",
        "../MILESTONE_GUIDE.md",
        "../milestones/latest",
        "agent-governance-gates.md",
    ):
        assert target in text, f"missing required documentation target: {target}"


def test_documentation_index_local_links_resolve() -> None:
    for target in LINK.findall(_read(INDEX)):
        if "://" in target or target.startswith("#"):
            continue
        resolved = (INDEX.parent / target.split("#", 1)[0]).resolve()
        assert resolved.exists(), f"broken local link in documentation index: {target}"


def test_documentation_index_tracks_latest_complete_milestone() -> None:
    latest_name = _read(ROOT / "milestones" / "latest").strip()
    assert re.fullmatch(r"milestone_\d{3}\.md", latest_name)
    latest = ROOT / "milestones" / latest_name
    assert latest.exists()
    milestone_text = _read(latest)
    assert "- 状态: 已完成并归档" in milestone_text
    assert "M45" in _read(INDEX)


def test_documentation_index_states_current_boundaries() -> None:
    text = _read(INDEX)
    for boundary in (
        "PyPI",
        "正式 tag",
        "发布自动化",
        "loopback-only",
        "条件触发",
        "不在当前路线图",
    ):
        assert boundary in text, f"missing current boundary: {boundary}"
    assert "/Users/" not in text


def test_documentation_contract_is_offline_and_release_neutral() -> None:
    source = _read(Path(__file__))
    tree = ast.parse(source)
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported.intersection({"subprocess", "requests", "urllib", "socket"})
    for forbidden in (
        "os." + "system",
        "os." + "popen",
        "sub" + "process.",
        "request" + "s.",
    ):
        assert forbidden not in source
