"""Shared mock-replay coverage for the Task 8 golden scenarios."""

from pathlib import Path

import pytest

from tests.golden.manifest import GOLDEN_SCENARIOS, GoldenEvidence

COMMON_IDS = ("G01", "G03", "G05", "G08", "G11", "G13", "G15", "G17", "G27", "G43")


@pytest.mark.parametrize("scenario_id", COMMON_IDS)
def test_common_golden_case_replays_through_manifest(scenario_id: str, tmp_path: Path):
    scenario = next(item for item in GOLDEN_SCENARIOS if item.scenario_id == scenario_id)

    evidence = scenario.run_offline(tmp_path / scenario_id)

    assert type(evidence) is GoldenEvidence
