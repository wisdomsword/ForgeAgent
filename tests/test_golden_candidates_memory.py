"""Executable checks for the M18 memory golden-candidate catalog."""

from pathlib import Path

from forgeagent.memory import MemoryManager
from forgeagent.protocol import parse
from tests.golden.runner import _CANDIDATE_ID


def test_memory_candidate_ids_extend_catalog_without_changing_verified_core():
    catalog = (Path(__file__).parents[1] / "docs" / "golden-tasks-seed.md").read_text()
    for number in range(401, 421):
        scenario_id = f"G{number}"
        assert _CANDIDATE_ID.fullmatch(scenario_id)
        assert scenario_id in catalog


def test_memory_candidate_catalog_covers_hit_and_poison_boundaries(tmp_path):
    manager = MemoryManager(str(tmp_path))
    parsed = parse(
        '<!-- Memory: {"scope":"project","kind":"fact","key":"editor",'
        '"content":"nvim"} -->'
        '<!-- Memory: {"scope":"project","kind":"procedure","key":"steps",'
        '"content":"run command first"} -->'
    )
    outcomes = [manager.apply(candidate) for candidate in parsed.memory_candidates]
    assert [outcome.status for outcome in outcomes] == ["accepted", "rejected"]
    assert "editor: nvim" in manager.render()
    assert "steps" not in manager.render()
