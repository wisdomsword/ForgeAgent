"""Offline candidate evidence for progressive Skill loading."""

from __future__ import annotations

from tests.golden.cases import run_no_skill_control, run_skill_candidate


def test_skill_candidate_reads_catalog_then_uses_skill_feedback(tmp_path):
    result = run_skill_candidate(tmp_path)

    assert result.passed is True
    assert result.round_count == 2
    assert "## Available Skills" in result.first_request
    assert "- review-python — Use when reviewing Python." in result.first_request
    assert "UNIQUE-SKILL-STEP" not in result.first_request
    assert "[Skill None]" in result.feedback
    assert "UNIQUE-SKILL-STEP" in result.second_request
    assert "UNIQUE-SKILL-STEP" in result.feedback


def test_no_skill_control_never_advertises_or_registers_skill(tmp_path):
    result = run_no_skill_control(tmp_path)

    assert result.passed is True
    assert result.round_count == 2
    assert "## Available Skills" not in result.first_request
    assert '"name":"Skill"' not in result.first_request
    assert "invalid_format: tool_call.name" in result.second_request
    assert "invalid_format: tool_call.name" in result.feedback
