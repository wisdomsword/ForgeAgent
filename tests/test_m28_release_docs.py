"""Static contracts for the ForgeAgent 0.1.0 release candidate."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RC_PATH = ROOT / "docs/releases/0.1.0-rc.md"


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _markdown_table_row(text: str, first_cell: str) -> list[str]:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.startswith("|")
    ]
    matches = [row for row in rows if row and row[0] == first_cell]
    assert len(matches) == 1
    return matches[0]


def _assert_unique_release_candidate(candidates: list[Path]) -> None:
    assert candidates == [RC_PATH]


def _assert_no_m28_linux_success_claim(text: str) -> None:
    for line in text.splitlines():
        lowered = line.casefold()
        positive_context = lowered.replace("not verified", "").replace("not passed", "")
        identifies_gate = re.search(
            r"m28.*(?:linux.*(?:rc.*)?smoke|linux.*installed-wheel|"
            r"installed-wheel.*(?:gate|smoke))",
            positive_context,
        )
        claims_success = re.search(r"\b(?:passed|verified)\b|已通过", positive_context)
        has_pipeline_evidence = re.search(r"M28 Pipeline \d+ / Job \d+", line)
        assert not (identifies_gate and claims_success and not has_pipeline_evidence), line


def test_release_candidate_freezes_status_install_and_required_boundaries() -> None:
    assert RC_PATH.is_file()
    candidates = sorted(RC_PATH.parent.glob("0.1.0*rc*.md"))
    _assert_unique_release_candidate(candidates)
    with pytest.raises(AssertionError):
        _assert_unique_release_candidate([RC_PATH, RC_PATH.with_name("0.1.0-extra-rc.md")])
    text = RC_PATH.read_text(encoding="utf-8")

    assert len(re.findall(r"^# ", text, flags=re.MULTILINE)) == 1
    for fragment in (
        "0.1.0",
        "pip install dist/forgeagent-0.1.0-",
        "## 状态",
        "## 安装",
        "## 已交付能力",
        "CLI",
        "HTTP",
        "Single",
        "Duo",
        "Triad",
        "## 验证证据",
        "## 正式发布阻塞条件",
        "## 已知限制",
        "### 平台证据",
        "### 真实模型",
        "### sandbox",
        "### HTTP",
        "### 协作 v1",
        "restricted 不是 OS 级密封沙箱",
        "loopback",
        "127.0.0.1",
        "Bearer token",
        "不提供 TLS",
        "headless Triad",
        "preauthorize",
        "opt-in",
        "required Linux Docker job",
        "Golden 20/20",
        "OpenSpec strict",
        "独立审查",
        "正式发布动作",
        "没有协作专用 resume endpoint",
        "resume_loop_id",
    ):
        assert fragment in text


def test_release_candidate_records_linux_gate_without_promoting_historical_evidence() -> None:
    text = RC_PATH.read_text(encoding="utf-8")

    local_row = _markdown_table_row(
        text,
        "本地 real-wheel packaging 与 clean-wheel/CLI/HTTP/Single/Duo/Triad harness",
    )
    m28_row = _markdown_table_row(text, "M28 installed-wheel required Linux Docker gate")
    m24_row = _markdown_table_row(text, "M24 Pipeline 50 / Job 249")

    assert local_row[1] == "verified"
    assert m28_row[1] == "verified"
    assert "M28 Pipeline 57 / Job 263" in " | ".join(m28_row)
    assert "Job 249" not in " | ".join(m28_row)
    assert m24_row[1] == "historical container-only evidence"
    _assert_no_m28_linux_success_claim(text)

    contradictory = text + "\nM28 Linux installed-wheel RC smoke verified.\n"
    with pytest.raises(AssertionError):
        _assert_no_m28_linux_success_claim(contradictory)


def test_readme_links_release_candidate_near_current_verification() -> None:
    text = _text("README.md")
    current = text.split("## 当前验证", 1)[1].split("\n## ", 1)[0]

    assert "docs/releases/0.1.0-rc.md" in current
    assert "Release Candidate，不是正式发布" in current
    assert "M28 Pipeline 57 / Job 263" in current


def test_platform_matrix_separates_m28_gate_from_m24_historical_evidence() -> None:
    text = _text("docs/platform-support.md")

    m28_row = _markdown_table_row(text, "M28 installed-wheel gate on required Linux Docker job")
    m28_section = text.split("## M28 Release Candidate Gate", 1)[1].split("\n## ", 1)[0]

    assert m28_row[2] == "verified"
    assert "artifacts/ci/rc-smoke.json" in " | ".join(m28_row)
    assert "Pipeline 57 / Job 263" in " | ".join(m28_row)
    assert "M24 Pipeline 50 / Job 249 remains historical container-only evidence" in (m28_section)
    normalized_section = " ".join(m28_section.split())
    assert "must not be represented as an M28 installed-wheel smoke result" in (normalized_section)
    _assert_no_m28_linux_success_claim(text)
