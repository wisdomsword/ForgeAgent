"""Static contracts for the ForgeAgent 0.1.0 release candidate."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RC_PATH = ROOT / "docs/releases/0.1.0-rc.md"


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_release_candidate_freezes_status_install_and_required_boundaries() -> None:
    assert RC_PATH.is_file()
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
    ):
        assert fragment in text


def test_release_candidate_does_not_promote_configured_or_historical_evidence() -> None:
    text = RC_PATH.read_text(encoding="utf-8")

    assert "本地 real-wheel" in text and "verified" in text
    assert "M28 installed-wheel" in text and "configured/pending" in text
    assert "M24 Pipeline 50 / Job 249" in text
    assert "historical container-only evidence" in text
    assert "M28 Linux RC smoke 已通过" not in text


def test_readme_links_release_candidate_near_current_verification() -> None:
    text = _text("README.md")
    current = text.split("## 当前验证", 1)[1].split("\n## ", 1)[0]

    assert "docs/releases/0.1.0-rc.md" in current
    assert "Release Candidate，不是正式发布" in current


def test_platform_matrix_separates_m28_gate_from_m24_historical_evidence() -> None:
    text = _text("docs/platform-support.md")

    assert "M24 Pipeline 50 / Job 249" in text
    assert "historical container-only evidence" in text
    assert "M28 installed-wheel gate" in text
    assert "configured" in text
    assert "artifacts/ci/rc-smoke.json" in text
    assert "M28 installed-wheel gate" in text.split("## M28 Release Candidate Gate", 1)[1]
