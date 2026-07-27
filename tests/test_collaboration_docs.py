"""Static contracts for collaboration and current project documentation."""

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
    assert "`SubmitCandidate`" in text
    assert "不需要额外 standalone `task_status`" in text


def test_readme_documents_m22_candidate_readiness_without_weakening_confirmation() -> None:
    readme = _text("README.md")

    for fragment in (
        "`calc.py` 和 `test_calc.py`",
        "非符号链接普通文件",
        "不读取文件内容",
        "不替代 Evaluator",
        "Planner 和 restricted `FileWrite`",
        "普通 CLI、Loop 和 HTTP",
    ):
        assert fragment in readme

    action_plan = _text("ACTION_PLAN.md")
    assert "M22 Candidate 文件就绪门" in action_plan
    assert "M22 TRIAD HUMAN SMOKE: PASS" in action_plan
    assert "8/8 验收项通过" in action_plan
    assert "0 rejection" in action_plan


def test_protocol_documents_collaboration_schema_authority_and_safe_report() -> None:
    text = _text("docs/text-protocol-spec.md")

    assert "forgeagent.collaboration.v1" in text
    assert "SubmitPlan" in text
    assert "SubmitEvaluation" in text
    assert "FileRead" in text and "FileList" in text
    assert "zero-argument `SubmitCandidate`" in text
    assert "without a later standalone" in text
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


def test_readme_current_verification_section_is_unique_and_structured() -> None:
    readme = _text("README.md")
    headings = re.findall(r"^##[ \t]*当前验证[ \t]*$", readme, flags=re.MULTILINE)
    assert len(headings) == 1

    current_verification = re.findall(
        r"^## 当前验证\n\n"
        r"pytest: `(?P<passed>\d+) passed, (?P<skipped>\d+) skipped`；"
        r"OpenSpec strict: `(?P<spec_passed>\d+)/(?P<spec_total>\d+)`\.$",
        readme,
        flags=re.MULTILINE,
    )
    assert len(current_verification) == 1
    passed, skipped, spec_passed, spec_total = map(int, current_verification[0])
    assert passed > 0
    assert skipped >= 0
    assert spec_passed == spec_total > 0


def test_m22_closeout_artifacts_record_final_gates() -> None:
    readme = _text("README.md")
    assert "M22 Duo/Triad 协作运行时已完成并归档" in readme
    assert "最终全量验证与归档仍在进行" not in readme
    assert "milestone_022.md" in readme
    assert "两次真实模型 Triad" in readme

    action_plan = _text("ACTION_PLAN.md")
    m22_row = next(line for line in action_plan.splitlines() if line.startswith("| **M22**"))
    assert "已完成并归档" in m22_row
    assert "2155 passed / 10 skipped" in m22_row
    assert "结构化 Submit" in m22_row
    assert "归档后复核" in action_plan
    assert "M22 结构化提交门收尾" in action_plan
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
    assert "2155 passed, 10 skipped" in milestone
    assert "SubmitCandidate" in milestone
    assert "通用 completion signal" in milestone
    assert "本里程碑不修改普通 `Step`" not in milestone
    assert "Generator clean completed" not in milestone
    assert "../openspec/changes/archive/2026-07-24-triad-mode/" in milestone
    assert "../openspec/changes/archive/2026-07-24-collaboration-contract-hotfix/" in milestone
    assert "../openspec/changes/archive/2026-07-25-fix-collaboration-role-protocol/" in milestone
    assert "../openspec/changes/triad-mode/" not in milestone
    assert "M23" in milestone
    agents = _text("AGENTS.md")
    assert "项目处于**规划阶段**" not in agents
    assert "M15-M22 已完成并归档" in agents

    technical_path = _text("TECH_PATH.md")
    assert "M15-M22 均已完成并归档" in technical_path
    assert "M22 已裁决" in technical_path
    assert "它们不是当前待决事项" in technical_path

    report = _text("docs/superpowers/reports/2026-07-24-triad-mode-verify.md")
    assert "验证实现提交: `111d60a`" in report
    assert "当前实现提交" not in report

    submission_plan = _text("docs/superpowers/plans/2026-07-25-collaboration-role-submission.md")
    assert submission_plan.count("archived-with: 2026-07-25-fix-collaboration-role-protocol") == 1

    main_spec = _text("openspec/specs/runtime-collaboration/spec.md")
    assert "TBD - created by archiving change triad-mode" not in main_spec
    if "## Requirements" in main_spec:
        assert "Duo/Triad" in main_spec.split("## Requirements", 1)[0]
    evaluator_requirement = main_spec.split("### Requirement: Evaluator 独立验收并决定协作完成", 1)[
        1
    ].split("### Requirement:", 1)[0]
    assert "Generator MUST 成功调用零载荷 `SubmitCandidate`" in evaluator_requirement
    assert "Generator 的严格 `completed` SHALL 仅表示提交验收" not in evaluator_requirement

    audit_spec = _text("openspec/specs/audit-logging/spec.md")
    assert "TBD - created by archiving change http-task-service" not in audit_spec
    assert "JSONL" in audit_spec.split("## Requirements", 1)[0]


def test_m22_milestone_links_final_human_smoke_evidence() -> None:
    milestone = _text("milestones/milestone_022.md")
    report_path = "docs/superpowers/reports/2026-07-26-m22-triad-human-smoke-final.md"
    report = _text(report_path)

    assert "- 起止: 2026-07-24 ~ 2026-07-26" in milestone
    assert "2026-07-26-m22-triad-human-smoke-final" in milestone
    assert "原两次结构化提交协议验收" in milestone
    assert "后续四次可追溯人类冒烟" in milestone
    assert "M22 TRIAD HUMAN SMOKE: PASS" in milestone
    for collaboration_id in (
        "c433416babd444efae89988cc399c1b6",
        "8c98fdc15eba4e22a5511951832b84bb",
        "bd2633c970784ea7929af75eaf2f94aa",
        "8efdd58913dc4b81a7918502faf23b82",
    ):
        assert collaboration_id in report
    assert "8/8" in report
    assert "0 rejection" in report


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
