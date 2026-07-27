from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
import subprocess
import sys
from collections import Counter
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


def test_m25_schedule_has_fixed_270_run_order_and_global_position_balance() -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    schedule = harness.build_schedule(protocol)
    assert len(schedule) == 270
    assert len({(s.task_id, s.model_id, s.repeat, s.mode) for s in schedule}) == 270
    assert Counter(s.model_id for s in schedule) == {
        "claude-haiku-4-5": 135,
        "gpt-5.4-mini": 135,
    }
    assert Counter(s.mode for s in schedule) == {
        "single": 90,
        "duo": 90,
        "triad": 90,
    }
    assert all(
        sum(
            s.task_id == task.id and s.model_id == model and s.mode == mode
            for s in schedule
        )
        == 5
        for task in protocol.tasks
        for model in protocol.model_ids
        for mode in protocol.modes
    )
    positions = Counter((s.mode, (s.sequence - 1) % 3) for s in schedule)
    assert positions == Counter(
        {(mode, position): 30 for mode in protocol.modes for position in range(3)}
    )
    assert [(s.sequence, s.model_id, s.repeat, s.mode) for s in schedule[:6]] == [
        (1, "claude-haiku-4-5", 1, "single"),
        (2, "claude-haiku-4-5", 1, "duo"),
        (3, "claude-haiku-4-5", 1, "triad"),
        (4, "gpt-5.4-mini", 1, "duo"),
        (5, "gpt-5.4-mini", 1, "triad"),
        (6, "gpt-5.4-mini", 1, "single"),
    ]
    assert [(s.sequence, s.model_id, s.repeat, s.mode) for s in schedule[-6:]] == [
        (265, "claude-haiku-4-5", 5, "triad"),
        (266, "claude-haiku-4-5", 5, "single"),
        (267, "claude-haiku-4-5", 5, "duo"),
        (268, "gpt-5.4-mini", 5, "single"),
        (269, "gpt-5.4-mini", 5, "duo"),
        (270, "gpt-5.4-mini", 5, "triad"),
    ]


def test_m25_run_identity_binds_model_family_sequence_and_protocol() -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    first = harness.build_schedule(protocol)[0]
    digest = "a" * 64
    assert harness.run_id_for(protocol, first) == (
        "001-csv-region-summary-claude-haiku-4-5-r1-single"
    )
    changed = dataclasses.replace(first, model_id="gpt-5.4-mini")
    assert harness.run_spec_hash(first, digest) != harness.run_spec_hash(changed, digest)


def _m25_environment(harness, protocol):
    return harness.M25EnvironmentManifest(
        generated_at="2026-07-27T00:00:00.000Z",
        git_commit="a" * 40,
        tracked_dirty=False,
        python_version="3.13.0",
        python_executable_name="python",
        platform="test",
        package_version="0.1.0",
        model_routes=(
            harness.M25ModelRoute(
                model_id="claude-haiku-4-5",
                client_kind="anthropic",
                provider_route_sha256="b" * 64,
            ),
            harness.M25ModelRoute(
                model_id="gpt-5.4-mini",
                client_kind="openai",
                provider_route_sha256="c" * 64,
            ),
        ),
        builtin_models_sha256="d" * 64,
        builtin_config_sha256="e" * 64,
        protocol_sha256="f" * 64,
        generation=protocol.generation,
        execution=protocol.execution,
    )


def _m25_record_dict(harness, protocol, spec, environment, environment_sha256):
    protocol_sha256 = "f" * 64
    return {
        "schema": "forgeagent.m25.mode-evaluation.run/v1",
        "run_id": harness.run_id_for(protocol, spec),
        "sequence": spec.sequence,
        "task_id": spec.task_id,
        "task_family": spec.task_family,
        "model_id": spec.model_id,
        "provider_route_sha256": harness.route_hash_for_model(
            environment, spec.model_id
        ),
        "mode": spec.mode,
        "repeat": spec.repeat,
        "protocol_sha256": protocol_sha256,
        "environment_sha256": environment_sha256,
        "run_spec_sha256": harness.run_spec_hash(spec, protocol_sha256),
        "terminal": True,
        "started_at": "2026-07-27T00:00:00.000Z",
        "finished_at": "2026-07-27T00:00:01.000Z",
        "runtime_completed": False,
        "runtime_status": "failed",
        "runtime_reason": "test",
        "checks": [],
        "artifacts": [],
        "solved": False,
        "first_acceptance_passed": None,
        "rejection_count": None,
        "correction_count": None,
        "tokens": {
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
        },
        "logical_model_calls": 0,
        "provider_attempts": 0,
        "usage_present_calls": 0,
        "usage_missing_calls": 0,
        "usage_missing_rate": None,
        "end_to_end_latency_seconds": 1.0,
        "error_category": None,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("task_family", "feature"),
        lambda value: value.__setitem__("model_id", "gpt-5.4-mini"),
        lambda value: value.__setitem__("provider_route_sha256", "0" * 64),
        lambda value: value.__setitem__("run_id", "wrong-run"),
        lambda value: value.__setitem__("run_spec_sha256", "0" * 64),
        lambda value: value.__setitem__("schema", "forgeagent.m23.mode-evaluation.run/v1"),
    ],
)
def test_m25_resume_rejects_conflicting_terminal_records(tmp_path, mutation) -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    schedule = harness.build_schedule(protocol)
    environment = _m25_environment(harness, protocol)
    environment_sha256 = "9" * 64
    record = _m25_record_dict(
        harness, protocol, schedule[0], environment, environment_sha256
    )
    mutation(record)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    filename = harness.run_id_for(protocol, schedule[0]) + ".json"
    (raw_dir / filename).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="existing raw record"):
        harness.pending_run_specs(
            tmp_path,
            schedule,
            "f" * 64,
            environment_sha256,
            environment=environment,
        )


def test_m25_resume_skips_exact_terminal_and_rejects_unexpected_filename(tmp_path) -> None:
    harness = load_harness()
    protocol = harness.validate_protocol(m25_protocol_dict())
    schedule = harness.build_schedule(protocol)
    environment = _m25_environment(harness, protocol)
    environment_sha256 = "9" * 64
    record = _m25_record_dict(
        harness, protocol, schedule[0], environment, environment_sha256
    )
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    filename = harness.run_id_for(protocol, schedule[0]) + ".json"
    (raw_dir / filename).write_text(json.dumps(record), encoding="utf-8")
    pending = harness.pending_run_specs(
        tmp_path,
        schedule,
        "f" * 64,
        environment_sha256,
        environment=environment,
    )
    assert pending == schedule[1:]
    (raw_dir / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected run record"):
        harness.pending_run_specs(
            tmp_path,
            schedule,
            "f" * 64,
            environment_sha256,
            environment=environment,
        )
