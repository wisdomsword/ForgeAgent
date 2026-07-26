from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parents[1]
PROTOCOL_PATH = ROOT / "docs" / "evaluation" / "m23" / "protocol.json"


def load_harness():
    path = ROOT / "scripts" / "m23_mode_evaluation.py"
    spec = importlib.util.spec_from_file_location("m23_mode_evaluation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def protocol_dict() -> dict[str, object]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_checked_in_protocol_builds_balanced_27_run_schedule() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)

    assert digest == harness.canonical_sha256(protocol.model_dump(mode="json", by_alias=True))
    assert len(schedule) == 27
    assert [item.mode for item in schedule[:9]] == [
        "single",
        "duo",
        "triad",
        "duo",
        "triad",
        "single",
        "triad",
        "single",
        "duo",
    ]
    assert {(item.task_id, item.repeat, item.mode) for item in schedule} == {
        (task.id, repeat, mode)
        for task in protocol.tasks
        for repeat in range(1, 4)
        for mode in ("single", "duo", "triad")
    }
    assert all(sum(item.mode == mode for item in schedule) == 9 for mode in protocol.modes)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("generation"), "generation"),
        (lambda value: value.__setitem__("repetitions", 2), "at least 3"),
        (lambda value: value.__setitem__("modes", ["single", "duo"]), "modes"),
        (
            lambda value: value.__setitem__("mode_orders", [["single", "duo", "triad"]] * 3),
            "mode_orders",
        ),
        (lambda value: value.__setitem__("unknown", True), "extra"),
        (
            lambda value: value["tasks"].append(copy.deepcopy(value["tasks"][0])),
            "task id",
        ),
    ],
)
def test_protocol_rejects_incomplete_or_ambiguous_contract(mutate, message: str) -> None:
    harness = load_harness()
    value = protocol_dict()
    mutate(value)
    with pytest.raises((ValidationError, ValueError), match=message):
        harness.validate_protocol(value)


@pytest.mark.parametrize("bad_path", ["/tmp/escape", "../escape", "a/../../escape", "bad\0name"])
def test_protocol_rejects_fixture_and_artifact_path_escape(bad_path: str) -> None:
    harness = load_harness()
    value = protocol_dict()
    value["tasks"][0]["initial_files"] = {bad_path: "x"}
    with pytest.raises((ValidationError, ValueError), match="relative path"):
        harness.validate_protocol(value)
