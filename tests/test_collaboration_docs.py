"""Static contracts for the M22 collaboration documentation."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_documents_collaboration_entry_points_routing_and_cost() -> None:
    text = _text("README.md")

    for fragment in (
        "forgeagent run --mode duo",
        "forgeagent run --mode triad",
        "--planner-model",
        "--evaluator-model",
        "--max-rejections",
        "/duo <goal>",
        "/triad <goal>",
        "allow_weaker_override",
        "Generator",
        "Evaluator",
        "Planner",
        "usage_available",
    ):
        assert fragment in text
    assert "显式 triad > 编程任务强制 triad" in text
    assert "Generator 的 `completed: true`" in text


def test_protocol_documents_collaboration_schema_authority_and_safe_report() -> None:
    text = _text("docs/text-protocol-spec.md")

    assert "forgeagent.collaboration.v1" in text
    assert "SubmitPlan" in text
    assert "SubmitEvaluation" in text
    assert "FileRead" in text and "FileList" in text
    assert "Generator 的 `completed: true`" in text
    assert "plan_digest" in text
    for field in (
        "plan_item_count",
        "passed_item_count",
        "failed_item_count",
        "generator_attempts",
        "evaluator_attempts",
        "rejections",
        "usage_available",
    ):
        assert f"`{field}`" in text


def test_http_docs_cover_strict_modes_headless_policy_and_projection() -> None:
    text = _text("docs/http-task-service.md")

    assert '"mode": "duo"' in text
    assert '"mode": "triad"' in text
    assert '"collaboration_mode": "triad"' in text
    assert "triad_plan_policy" in text
    assert "deny" in text and "preauthorize" in text
    assert "allow_weaker_override" in text
    assert "needs_confirmation" in text
    assert "Evaluator" in text and "read-only" in text
    assert "role model" in text.lower()
    assert "credential" in text

    documented_routes = {
        route.rstrip("`")
        for route in re.findall(r"`(/tasks(?:/\{32-hex-id\}(?:/cancel)?)?)`", text)
    }
    assert documented_routes == {
        "/tasks",
        "/tasks/{32-hex-id}",
        "/tasks/{32-hex-id}/cancel",
    }
    assert "/collaborations" not in text


def test_threat_model_covers_collaboration_role_and_state_boundaries() -> None:
    text = _text("docs/threat-model.md")

    assert "T19" in text
    for fragment in (
        "Planner",
        "Generator",
        "Evaluator",
        "plan digest",
        "headless",
        "prompt injection",
        "symlink",
        "cost",
    ):
        assert fragment.lower() in text.lower()


def test_m22_closeout_artifacts_record_final_gates() -> None:
    action_plan = _text("ACTION_PLAN.md")
    m22_row = next(line for line in action_plan.splitlines() if line.startswith("| **M22**"))
    assert "已完成验证，待归档提交" in m22_row
    assert "2069 passed" in m22_row
    assert "M22 待启动" not in action_plan

    report = _text("docs/superpowers/reports/2026-07-24-triad-mode-verify.md")
    assert "结论: PASS" in report
    assert "2069 passed, 11 skipped" in report
    assert "20/20 passed" in report
    assert "Ready for archive" in report

    milestone = _text("milestones/milestone_022.md")
    assert "# 里程碑 M22: Triad Mode" in milestone
    assert "- 状态: 已完成" in milestone
    assert "2069 passed, 11 skipped" in milestone
    assert "M23" in milestone
    assert _text("milestones/latest").strip() == "milestone_022.md"


def test_m22_adds_no_runtime_dependency() -> None:
    project = tomllib.loads(_text("pyproject.toml"))["project"]

    assert set(project["dependencies"]) == {
        "pydantic>=2.0",
        "anthropic>=0.40",
        "jinja2>=3.1",
        "rich>=13.0",
        "pyyaml>=6.0",
        "openai>=2.24,<3",
        "mcp>=1.28.1",
        "prompt-toolkit>=3.0,<4",
    }
