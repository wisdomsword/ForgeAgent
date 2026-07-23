from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from forgeagent.models import Message


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "m19-skills-human-smoke.py"
    spec = importlib.util.spec_from_file_location("m19_skills_human_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixture_isolated_user_and_project_skills(tmp_path):
    smoke = _load_smoke_module()

    fixture = smoke.create_fixture(tmp_path)

    assert "USER_SKILL" in fixture.user_skill.read_text()
    assert "PROJECT_SKILL_V1" in fixture.project_skill.read_text()
    assert fixture.home.is_relative_to(tmp_path)
    assert fixture.project.is_relative_to(tmp_path)


def test_client_reads_skill_then_accepts_expected_feedback():
    smoke = _load_smoke_module()
    state = smoke.SmokeState()
    client = smoke.DeterministicSkillClient("PROJECT_SKILL_V1", state)

    first = client.complete([Message(role="user", content="review")])
    second = client.complete([Message(role="system", content="[Skill None]\nPROJECT_SKILL_V1")])

    assert '"name": "Skill"' in first.content
    assert "PASS progressive loading: PROJECT_SKILL_V1" in second.content
    assert state.observed_markers == ["PROJECT_SKILL_V1"]


def test_factory_upgrades_disk_once_but_keeps_first_expected_snapshot(tmp_path):
    smoke = _load_smoke_module()
    fixture = smoke.create_fixture(tmp_path)
    state = smoke.SmokeState()
    factory = smoke.SmokeClientFactory(fixture, state)

    first = factory("mock")
    second = factory("mock")

    assert first.expected_marker == "PROJECT_SKILL_V1"
    assert second.expected_marker == "PROJECT_SKILL_V2"
    assert "PROJECT_SKILL_V2" in fixture.project_skill.read_text()


def test_check_matrix_fails_closed_until_human_checks_pass():
    smoke = _load_smoke_module()
    state = smoke.SmokeState(observed_markers=["PROJECT_SKILL_V1", "PROJECT_SKILL_V2"])

    checks = smoke.evaluate_checks(
        state,
        trust_matches=True,
        completion_ok=False,
        history_ok=False,
    )

    assert checks["progressive V1"] is True
    assert checks["reload V2"] is True
    assert checks["Skill trust V2"] is True
    assert checks["slash completion"] is False
    assert checks["arrow history"] is False
