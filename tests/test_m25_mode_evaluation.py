from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "m23_mode_evaluation.py"
M23_PROTOCOL_PATH = ROOT / "docs" / "evaluation" / "m23" / "protocol.json"
M23_FORMAL_ROOT = ROOT / "docs" / "evaluation" / "m23" / "runs" / "2026-07-27-haiku-4-5"
BASE_REF = "d7fa30526f829959102b5fb69b4778899d6b1f88"
M25_SCHEMA = "forgeagent.m25.mode-evaluation/v1"


def load_harness():
    spec = importlib.util.spec_from_file_location("m25_mode_evaluation", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments), cwd=ROOT, check=True, capture_output=True
    ).stdout


def m25_protocol_dict() -> dict[str, object]:
    value = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    source_tasks = value["tasks"]
    assert isinstance(source_tasks, list)
    tasks = []
    families = (
        "baseline",
        "baseline",
        "baseline",
        "bugfix",
        "bugfix",
        "feature",
        "feature",
        "refactor",
        "refactor",
    )
    for index, family in enumerate(families):
        task = copy.deepcopy(source_tasks[index % 3])
        task["id"] = task["id"] if index < 3 else f"contract-{family}-{index}"
        task["family"] = family
        tasks.append(task)
    value["schema"] = M25_SCHEMA
    value.pop("model_id")
    value["model_ids"] = ["claude-haiku-4-5", "gpt-5.4-mini"]
    value["repetitions"] = 5
    value["tasks"] = tasks
    return value


def test_tracked_m23_protocol_and_evidence_are_byte_identical_to_base_ref() -> None:
    expected = _git("ls-tree", "-r", "--name-only", BASE_REF, "docs/evaluation/m23")
    current = _git("ls-tree", "-r", "--name-only", "HEAD", "docs/evaluation/m23")
    assert current == expected
    for relative_path in expected.decode().splitlines():
        assert (ROOT / relative_path).read_bytes() == _git(
            "show", f"{BASE_REF}:{relative_path}"
        )


def test_formal_m23_raw_recomputes_to_checked_in_summary_and_report() -> None:
    harness = load_harness()
    protocol, protocol_sha256 = harness.load_protocol(M23_PROTOCOL_PATH)
    environment = harness.EnvironmentManifest.model_validate_json(
        (M23_FORMAL_ROOT / "environment.json").read_bytes()
    )
    records = harness.read_raw_records(
        M23_FORMAL_ROOT / "raw",
        protocol,
        protocol_sha256,
        harness.environment_sha256(environment),
    )
    recomputed = harness.aggregate_records(protocol, harness.build_schedule(protocol), records)
    checked_in = json.loads((M23_FORMAL_ROOT / "summary.json").read_text(encoding="utf-8"))
    recomputed.pop("generated_at")
    checked_in.pop("generated_at")
    assert recomputed == checked_in
    report = harness.render_report(
        protocol,
        environment.model_dump(mode="json", by_alias=True),
        recomputed,
    )
    assert report == (M23_FORMAL_ROOT / "report.md").read_text(encoding="utf-8")


def test_validate_protocol_dispatches_m23_and_m25_without_changing_m23_dump() -> None:
    harness = load_harness()
    m23_source = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    m23 = harness.validate_protocol(m23_source)
    m25 = harness.validate_protocol(m25_protocol_dict())
    assert type(m23) is harness.EvaluationProtocol
    assert type(m25) is harness.M25EvaluationProtocol
    assert m23.model_dump(mode="json", by_alias=True) == m23_source
    assert m25.model_ids == ("claude-haiku-4-5", "gpt-5.4-mini")


@pytest.mark.parametrize("schema", [None, "forgeagent.m23.mode-evaluation/v1", "unknown/v1"])
def test_unknown_schema_fails_before_model_parsing(schema: str | None) -> None:
    harness = load_harness()
    value = m25_protocol_dict()
    if schema is None:
        value.pop("schema")
    else:
        value["schema"] = schema
    with pytest.raises(ValueError, match="schema"):
        harness.validate_protocol(value)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.__setitem__("unexpected", True), "extra"),
        (
            lambda value: value.__setitem__(
                "model_ids", ["gpt-5.4-mini", "claude-haiku-4-5"]
            ),
            "model_ids",
        ),
        (
            lambda value: value.__setitem__(
                "model_ids", ["claude-haiku-4-5", "claude-haiku-4-5"]
            ),
            "model_ids",
        ),
        (lambda value: value["tasks"].__setitem__(1, copy.deepcopy(value["tasks"][0])), "unique"),
        (lambda value: value["tasks"][3].__setitem__("family", "baseline"), "3/2/2/2"),
        (lambda value: value.__setitem__("repetitions", 3), "repetitions"),
        (
            lambda value: value.__setitem__(
                "mode_orders",
                [
                    ["single", "duo", "triad"],
                    ["single", "duo", "triad"],
                    ["triad", "single", "duo"],
                ],
            ),
            "fixed Latin rotation",
        ),
    ],
)
def test_m25_protocol_rejects_contract_drift(mutate, message: str) -> None:
    harness = load_harness()
    value = m25_protocol_dict()
    mutate(value)
    with pytest.raises((ValidationError, ValueError), match=message):
        harness.validate_protocol(value)


def test_m25_protocol_rejects_colliding_file_safe_model_slugs(monkeypatch) -> None:
    harness = load_harness()
    monkeypatch.setattr(harness, "_model_slug", lambda _model_id: "same")
    with pytest.raises(ValueError, match="slugs"):
        harness.validate_protocol(m25_protocol_dict())
