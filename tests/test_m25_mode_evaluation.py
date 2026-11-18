from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "m23_mode_evaluation.py"
M23_PROTOCOL_PATH = ROOT / "docs" / "evaluation" / "m23" / "protocol.json"
M23_FORMAL_ROOT = ROOT / "docs" / "evaluation" / "m23" / "runs" / "2026-07-27-haiku-4-5"
M25_PROTOCOL_PATH = ROOT / "docs" / "evaluation" / "m25" / "protocol.json"
M25_PLAN_PATH = (
    ROOT / "docs" / "superpowers" / "plans" / "2026-07-27-m25-programming-mode-evaluation.md"
)
M25_SCHEMA = "forgeagent.m25.mode-evaluation/v1"


def load_harness():
    spec = importlib.util.spec_from_file_location("m25_mode_evaluation", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_tracked_m23_protocol_and_evidence_match_portable_frozen_manifest() -> None:
    frozen = (ROOT / "tests/data/m23-frozen-evidence.json").read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == (
        "78e24f2af30a749b104a8f4dc91997fba94de0f8570ede272a896737a9cfe88b"
    )
    expected = json.loads(frozen)["evidence_sha256"]
    # These two deliberately ignored local runs are outside the published audit.
    local_runs = {
        "2026-07-27-haiku-4-5-invalid-37d969e",
        "2026-07-27-haiku-4-5-invalid-600e283",
    }
    current = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "docs/evaluation/m23").rglob("*")
        if path.is_file() and not local_runs.intersection(path.parts)
    }
    assert len(expected) == 62
    assert current == expected


def test_m25_plan_registers_dynamic_preflight_module_before_execution() -> None:
    plan = M25_PLAN_PATH.read_text(encoding="utf-8")
    assert (
        "module=importlib.util.module_from_spec(spec); "
        "sys.modules[spec.name]=module; spec.loader.exec_module(module)"
    ) in plan


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
            lambda value: value.__setitem__("model_ids", ["gpt-5.4-mini", "claude-haiku-4-5"]),
            "model_ids",
        ),
        (
            lambda value: value.__setitem__("model_ids", ["claude-haiku-4-5", "claude-haiku-4-5"]),
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


def test_m25_fixture_candidate_files_fit_collaboration_contract() -> None:
    from forgeagent.collaboration import normalize_required_candidate_files

    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    for task in protocol.tasks:
        assert (
            normalize_required_candidate_files(task.required_candidate_files)
            == task.required_candidate_files
        )


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
        sum(s.task_id == task.id and s.model_id == model and s.mode == mode for s in schedule) == 5
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
        "provider_route_sha256": harness.route_hash_for_model(environment, spec.model_id),
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
    record = _m25_record_dict(harness, protocol, schedule[0], environment, environment_sha256)
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
    record = _m25_record_dict(harness, protocol, schedule[0], environment, environment_sha256)
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


def test_checked_in_m25_protocol_fixes_models_tasks_families_and_baselines() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    m23 = json.loads(M23_PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert protocol.schema_ == M25_SCHEMA
    assert protocol.model_ids == ("claude-haiku-4-5", "gpt-5.4-mini")
    assert protocol.repetitions == 5
    assert len(protocol.tasks) == 9
    assert digest == harness.canonical_sha256(protocol.model_dump(mode="json", by_alias=True))
    for index in range(3):
        actual = protocol.tasks[index].model_dump(mode="json")
        assert actual.pop("family") == "baseline"
        assert actual == m23["tasks"][index]
    assert [(task.id, task.family) for task in protocol.tasks[3:]] == [
        ("fix-ttl-expiration-boundary", "bugfix"),
        ("fix-invoice-discount-composition", "bugfix"),
        ("add-topological-batches", "feature"),
        ("add-jsonl-dead-letter-output", "feature"),
        ("refactor-notification-routing", "refactor"),
        ("refactor-config-precedence", "refactor"),
    ]


def _write_reference_solution(task_id: str, workspace: Path) -> None:
    if task_id == "fix-ttl-expiration-boundary":
        path = workspace / "cache.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "self._clock() <= expires_at", "self._clock() < expires_at"
            ),
            encoding="utf-8",
        )
        return

    if task_id == "fix-invoice-discount-composition":
        (workspace / "invoice.py").write_text(
            """from decimal import Decimal
from discounts import apply_discounts


def invoice_total(lines, adjustments):
    subtotal = sum(Decimal(str(price)) * quantity for price, quantity in lines)
    return apply_discounts(subtotal, adjustments)
""",
            encoding="utf-8",
        )
        (workspace / "discounts.py").write_text(
            """from decimal import Decimal, ROUND_HALF_UP


def apply_discounts(subtotal, adjustments):
    total = Decimal(subtotal)
    for kind, value in adjustments:
        amount = Decimal(str(value))
        if kind == "percent":
            total -= total * amount
        elif kind == "fixed":
            total -= amount
        else:
            raise ValueError("unknown adjustment kind")
    return max(total, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
""",
            encoding="utf-8",
        )
        return

    if task_id == "add-topological-batches":
        (workspace / "dependency_graph.py").write_text(
            """class CycleError(ValueError):
    pass


class DependencyGraph:
    def __init__(self):
        self._dependencies = {}

    def add_node(self, node):
        self._dependencies.setdefault(node, set())

    def add_dependency(self, node, dependency):
        self.add_node(node)
        self.add_node(dependency)
        self._dependencies[node].add(dependency)

    def topological_batches(self):
        remaining = {node: set(dependencies) for node, dependencies in self._dependencies.items()}
        batches = []
        while remaining:
            ready = tuple(sorted(node for node, deps in remaining.items() if not deps))
            if not ready:
                raise CycleError("dependency cycle")
            batches.append(ready)
            for node in ready:
                del remaining[node]
            for dependencies in remaining.values():
                dependencies.difference_update(ready)
        return batches
""",
            encoding="utf-8",
        )
        return

    if task_id == "add-jsonl-dead-letter-output":
        (workspace / "event_processor.py").write_text(
            """import json


def normalize_event(event):
    return {"id": str(event["id"]), "kind": str(event["kind"]).lower()}


def process_jsonl(lines):
    accepted = []
    rejected = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            accepted.append(normalize_event(json.loads(line)))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            rejected.append({"line": line_number, "error": type(error).__name__})
    return accepted, rejected
""",
            encoding="utf-8",
        )
        (workspace / "cli.py").write_text(
            """import argparse
import json
from pathlib import Path

from event_processor import process_jsonl


def _write_jsonl(path, rows):
    Path(path).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\\n" for row in rows),
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--dead-letter", required=True)
    args = parser.parse_args(argv)
    accepted, rejected = process_jsonl(
        Path(args.input).read_text(encoding="utf-8").splitlines()
    )
    _write_jsonl(args.output, accepted)
    _write_jsonl(args.dead_letter, rejected)
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
            encoding="utf-8",
        )
        (workspace / "output.jsonl").write_text('{"id": "1", "kind": "open"}\n', encoding="utf-8")
        (workspace / "dead-letter.jsonl").write_text(
            '{"error": "JSONDecodeError", "line": 2}\n{"error": "KeyError", "line": 3}\n',
            encoding="utf-8",
        )
        return

    if task_id == "refactor-notification-routing":
        (workspace / "routing.py").write_text(
            """def route_notification(user, event):
    preferred = user.get("preferred_channel", "email")
    if event.get("urgent") and user.get("phone"):
        return "sms", user["phone"]
    if preferred == "push" and user.get("device"):
        return "push", user["device"]
    return "email", user["email"]
""",
            encoding="utf-8",
        )
        (workspace / "notifications.py").write_text(
            """from routing import route_notification


def send_notification(user, event):
    channel, address = route_notification(user, event)
    return {"channel": channel, "address": address, "message": event["message"]}
""",
            encoding="utf-8",
        )
        return

    if task_id == "refactor-config-precedence":
        (workspace / "config_sources.py").write_text(
            """def environment_values(environment):
    return {
        key[4:].lower(): value
        for key, value in environment.items()
        if key.startswith("APP_") and value is not None
    }


def explicit_values(values):
    return {key: value for key, value in values.items() if value is not None}
""",
            encoding="utf-8",
        )
        (workspace / "config_merge.py").write_text(
            """def merge_layers(*layers):
    result = {}
    for layer in layers:
        result.update(layer)
    return result
""",
            encoding="utf-8",
        )
        (workspace / "config.py").write_text(
            """from config_merge import merge_layers
from config_sources import environment_values, explicit_values


def load_config(defaults, file_values, environment, command_line):
    return merge_layers(
        dict(defaults),
        explicit_values(file_values),
        environment_values(environment),
        explicit_values(command_line),
    )
""",
            encoding="utf-8",
        )
        return

    raise AssertionError(f"unknown task: {task_id}")


PROGRAMMING_TASK_IDS = (
    "fix-ttl-expiration-boundary",
    "fix-invoice-discount-composition",
    "add-topological-batches",
    "add-jsonl-dead-letter-output",
    "refactor-notification-routing",
    "refactor-config-precedence",
)


@pytest.mark.parametrize("task_id", PROGRAMMING_TASK_IDS)
def test_real_programming_fixture_fails_initially_and_reference_passes(task_id, tmp_path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    task = next(task for task in protocol.tasks if task.id == task_id)
    initial = tmp_path / "initial"
    initial.mkdir()
    harness.prepare_workspace(task, initial)
    assert any(check.status != "passed" for check in harness.run_checks(task, initial))
    reference = tmp_path / "reference"
    reference.mkdir()
    harness.prepare_workspace(task, reference)
    immutable_before = {path: (reference / path).read_bytes() for path in task.immutable_files}
    _write_reference_solution(task_id, reference)
    assert all(check.status == "passed" for check in harness.run_checks(task, reference))
    assert all(artifact.status == "ok" for artifact in harness.hash_artifacts(task, reference))
    assert immutable_before == {
        path: (reference / path).read_bytes() for path in task.immutable_files
    }


WEAK_MUTATIONS = {
    "fix-ttl-expiration-boundary": ("cache.py", "< expires_at", "<= expires_at"),
    "fix-invoice-discount-composition": (
        "discounts.py",
        "for kind, value in adjustments:",
        "for kind, value in sorted(adjustments):",
    ),
    "add-topological-batches": (
        "dependency_graph.py",
        "tuple(sorted(",
        "tuple(",
    ),
    "add-jsonl-dead-letter-output": (
        "cli.py",
        "return 1 if rejected else 0",
        "return 0",
    ),
    "refactor-notification-routing": (
        "notifications.py",
        "from routing import route_notification",
        "# route remains local",
    ),
    "refactor-config-precedence": (
        "config.py",
        "environment_values(environment)",
        "explicit_values(file_values)",
    ),
}


@pytest.mark.parametrize("task_id", PROGRAMMING_TASK_IDS)
def test_programming_fixture_check_strength_and_fixture_integrity(task_id, tmp_path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    task = next(task for task in protocol.tasks if task.id == task_id)

    weak = tmp_path / "weak"
    weak.mkdir()
    harness.prepare_workspace(task, weak)
    _write_reference_solution(task_id, weak)
    relative_path, original, replacement = WEAK_MUTATIONS[task_id]
    target = weak / relative_path
    source = target.read_text(encoding="utf-8")
    assert original in source
    target.write_text(source.replace(original, replacement, 1), encoding="utf-8")
    assert any(check.status != "passed" for check in harness.run_checks(task, weak))

    tampered = tmp_path / "tampered"
    tampered.mkdir()
    harness.prepare_workspace(task, tampered)
    _write_reference_solution(task_id, tampered)
    immutable = tampered / task.immutable_files[0]
    immutable.write_bytes(immutable.read_bytes() + b"\n")
    checks = {check.id: check for check in harness.run_checks(task, tampered)}
    assert checks["fixture-integrity"].status == "failed"


def test_m25_preflight_probes_two_routes_and_persists_only_safe_hashes(
    tmp_path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    built_model_ids = []
    clients = []

    def client_builder(model_id, *, registry):
        built_model_ids.append(model_id)
        client = SimpleNamespace(
            capability=SimpleNamespace(model_id=model_id, max_output_tokens=8192),
            closed=False,
        )
        client.close = lambda: setattr(client, "closed", True)
        clients.append(client)
        return client

    client_kinds = {
        "claude-haiku-4-5": "anthropic",
        "gpt-5.4-mini": "openai",
    }
    monkeypatch.setattr(
        harness,
        "resolve_model",
        lambda model_id, _registry: SimpleNamespace(
            capability=SimpleNamespace(client_kind=client_kinds[model_id]),
            api_key="SECRET_MUST_NOT_PERSIST",
            base_url=f"https://provider.invalid/{model_id}",
        ),
    )
    monkeypatch.setattr(
        harness,
        "_git_value",
        lambda _root, *arguments: "a" * 40 if arguments[0] == "rev-parse" else "",
    )
    context = harness.preflight(
        protocol,
        digest,
        tmp_path / "output",
        allowed_output_root=tmp_path,
        registry_loader=lambda: object(),
        client_builder=client_builder,
    )
    assert built_model_ids == ["claude-haiku-4-5", "gpt-5.4-mini"]
    assert [route.model_id for route in context.environment.model_routes] == built_model_ids
    assert all(client.closed for client in clients)
    persisted = (tmp_path / "output" / "environment.json").read_text(encoding="utf-8")
    assert "SECRET" not in persisted
    assert "https://" not in persisted
    assert context.environment.tracked_dirty is False


def test_m25_preflight_rejects_tracked_dirty_before_writing_environment(
    tmp_path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)

    class FakeClient:
        capability = SimpleNamespace(max_output_tokens=8192)

        def __init__(self, model_id):
            self.capability = SimpleNamespace(model_id=model_id, max_output_tokens=8192)

        def close(self):
            pass

    monkeypatch.setattr(
        harness,
        "resolve_model",
        lambda model_id, _registry: SimpleNamespace(
            capability=SimpleNamespace(client_kind="fake"), base_url=None
        ),
    )
    monkeypatch.setattr(
        harness,
        "_git_value",
        lambda _root, *arguments: "a" * 40 if arguments[0] == "rev-parse" else " M tracked.py",
    )
    with pytest.raises(ValueError, match="tracked.*clean"):
        harness.preflight(
            protocol,
            digest,
            tmp_path / "output",
            allowed_output_root=tmp_path,
            registry_loader=lambda: object(),
            client_builder=lambda model_id, registry: FakeClient(model_id),
        )
    assert not (tmp_path / "output" / "environment.json").exists()


@pytest.mark.parametrize("failure", ["model_id", "output_limit", "route"])
def test_m25_preflight_closes_all_probes_when_second_route_is_invalid(
    tmp_path, monkeypatch, failure
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    clients = []

    def client_builder(model_id, *, registry):
        capability = SimpleNamespace(
            model_id=("wrong-model" if failure == "model_id" and clients else model_id),
            max_output_tokens=(1024 if failure == "output_limit" and clients else 8192),
        )
        client = SimpleNamespace(capability=capability, closed=False)
        client.close = lambda: setattr(client, "closed", True)
        clients.append(client)
        return client

    def resolve(model_id, registry):
        if failure == "route" and model_id == "gpt-5.4-mini":
            raise ValueError("model route is ambiguous")
        return SimpleNamespace(capability=SimpleNamespace(client_kind="fake"), base_url=None)

    monkeypatch.setattr(harness, "resolve_model", resolve)
    monkeypatch.setattr(
        harness,
        "_git_value",
        lambda _root, *arguments: "a" * 40 if arguments[0] == "rev-parse" else "",
    )
    with pytest.raises(ValueError):
        harness.preflight(
            protocol,
            digest,
            tmp_path / "output",
            allowed_output_root=tmp_path,
            registry_loader=lambda: object(),
            client_builder=client_builder,
        )
    assert len(clients) == 2
    assert all(client.closed for client in clients)
    assert not (tmp_path / "output" / "environment.json").exists()


def test_m25_preflight_rejects_mismatched_existing_environment(tmp_path, monkeypatch) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    routes = {
        model_id: ("fake", character * 64)
        for model_id, character in zip(protocol.model_ids, ("b", "c"), strict=True)
    }
    monkeypatch.setattr(
        harness,
        "_git_value",
        lambda _root, *arguments: "a" * 40 if arguments[0] == "rev-parse" else "",
    )
    manifest = harness.environment_manifest(
        protocol,
        digest,
        repo_root=ROOT,
        model_routes=routes,
    )
    output = tmp_path / "output"
    output.mkdir()
    changed = manifest.model_copy(
        update={"protocol_sha256": "0" * 64, "generated_at": "unchanged-by-hash"}
    )
    (output / "environment.json").write_text(
        json.dumps(changed.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )

    def client_builder(model_id, *, registry):
        client = SimpleNamespace(
            capability=SimpleNamespace(model_id=model_id, max_output_tokens=8192)
        )
        client.close = lambda: None
        return client

    monkeypatch.setattr(
        harness,
        "resolve_model",
        lambda model_id, registry: SimpleNamespace(
            capability=SimpleNamespace(client_kind="fake"), base_url=None
        ),
    )
    with pytest.raises(ValueError, match="existing environment"):
        harness.preflight(
            protocol,
            digest,
            output,
            allowed_output_root=tmp_path,
            registry_loader=lambda: object(),
            client_builder=client_builder,
        )


@pytest.mark.parametrize("mode", ["single", "duo", "triad"])
@pytest.mark.parametrize("model_id", ["claude-haiku-4-5", "gpt-5.4-mini"])
def test_m25_execution_routes_every_role_through_run_model(
    tmp_path, monkeypatch, mode, model_id
) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    task_spec = protocol.tasks[0]
    run_spec = next(
        spec
        for spec in harness.build_schedule(protocol)
        if spec.mode == mode and spec.model_id == model_id
    )
    clients = []
    tasks = []
    create_kwargs = {}

    def build_client(requested_model, *, registry):
        client = SimpleNamespace(model=requested_model, closed=False)
        client.close = lambda: setattr(client, "closed", True)
        clients.append(client)
        return client

    class FakeTask:
        def __init__(self, client, **kwargs):
            self.client = client
            self.kwargs = kwargs
            self.closed = False
            tasks.append(self)

        def run(self, goal, *, cancel_event=None):
            return SimpleNamespace(status=SimpleNamespace(completed=True, reason="completed"))

        def close(self):
            self.closed = True

    class FakeRunner:
        @classmethod
        def create(cls, **kwargs):
            create_kwargs.update(kwargs)
            return cls()

        def run(self, goal):
            roles = (
                ("generator", "evaluator")
                if mode == "duo"
                else (
                    "planner",
                    "generator",
                    "evaluator",
                )
            )
            for role in roles:
                owned = create_kwargs["role_task_builder"](role, 1, object(), role)
                owned.run(goal)
                owned.close()
            return SimpleNamespace(
                status="completed",
                stop_reason="completed",
                generator_attempts=1,
                evaluator_attempts=1,
                rejections=0,
            )

        def close(self):
            pass

    monkeypatch.setattr(harness, "build_real_client", build_client)
    monkeypatch.setattr(harness, "Task", FakeTask)
    monkeypatch.setattr(harness, "CollaborationRunner", FakeRunner)
    if mode == "single":
        harness.run_single(
            protocol,
            task_spec,
            run_spec,
            tmp_path,
            object(),
            harness.CollectingAuditSink(),
        )
    else:
        harness.run_collaboration(
            protocol,
            task_spec,
            run_spec,
            tmp_path,
            object(),
            harness.CollectingAuditSink(),
        )
        assert create_kwargs["planner_model"] == model_id
        assert create_kwargs["generator_model"] == model_id
        assert create_kwargs["evaluator_model"] == model_id
    assert clients and all(client.model == model_id for client in clients)
    assert all(task.kwargs["task_id"].startswith("m25-") for task in tasks)
    assert all(task.closed for task in tasks)
    assert all(client.closed for client in clients)


def test_m25_raw_record_binds_model_family_and_route_hash() -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    spec = harness.build_schedule(protocol)[0]
    record = harness.build_raw_record(
        run_spec=spec,
        mode_result=harness.ModeResult(
            runtime_completed=False,
            runtime_status="failed",
            runtime_reason="test",
            first_acceptance_passed=None,
            rejection_count=None,
            correction_count=None,
        ),
        checks=(),
        artifacts=(),
        audit_metrics=harness.project_audit_metrics([]),
        protocol_sha256="a" * 64,
        environment_sha256="b" * 64,
        provider_route_sha256="c" * 64,
        started_at="2026-07-27T00:00:00.000Z",
        finished_at="2026-07-27T00:00:01.000Z",
        end_to_end_latency_seconds=1.0,
    )
    assert type(record) is harness.M25RawRecord
    assert record.run_id.startswith("001-")
    assert record.task_family == spec.task_family
    assert record.model_id == spec.model_id
    assert record.provider_route_sha256 == "c" * 64


def test_m25_raw_solved_requires_all_artifacts() -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(M25_PROTOCOL_PATH)
    spec = harness.build_schedule(protocol)[0]
    common = {
        "run_spec": spec,
        "mode_result": harness.ModeResult(
            runtime_completed=True,
            runtime_status="completed",
            runtime_reason="completed",
            first_acceptance_passed=None,
            rejection_count=None,
            correction_count=None,
        ),
        "checks": (
            harness.CheckRecord(
                id="check",
                status="passed",
                exit_code=0,
                stdout_sha256="0" * 64,
                stderr_sha256="0" * 64,
            ),
        ),
        "audit_metrics": harness.project_audit_metrics([]),
        "protocol_sha256": "a" * 64,
        "environment_sha256": "b" * 64,
        "provider_route_sha256": "c" * 64,
        "started_at": "2026-07-27T00:00:00.000Z",
        "finished_at": "2026-07-27T00:00:01.000Z",
        "end_to_end_latency_seconds": 1.0,
    }
    missing = harness.build_raw_record(
        **common,
        artifacts=(harness.ArtifactResult(path="result.txt", status="missing"),),
    )
    complete = harness.build_raw_record(
        **common,
        artifacts=(
            harness.ArtifactResult(path="result.txt", status="ok", size=1, sha256="d" * 64),
        ),
    )
    assert missing.solved is False
    assert complete.solved is True


def make_m25_raw_record(harness, spec, protocol_sha256, *, solved=True):
    logical_calls = 2 if spec.sequence % 10 == 0 else 1
    missing_calls = logical_calls - 1
    return harness.M25RawRecord(
        run_id=harness._run_id_for_spec(spec),
        sequence=spec.sequence,
        task_id=spec.task_id,
        task_family=spec.task_family,
        model_id=spec.model_id,
        provider_route_sha256=("b" * 64 if spec.model_id == "claude-haiku-4-5" else "c" * 64),
        mode=spec.mode,
        repeat=spec.repeat,
        protocol_sha256=protocol_sha256,
        environment_sha256="9" * 64,
        run_spec_sha256=harness.run_spec_hash(spec, protocol_sha256),
        terminal=True,
        started_at="2026-07-27T00:00:00.000Z",
        finished_at="2026-07-27T00:00:01.000Z",
        runtime_completed=solved,
        runtime_status="completed" if solved else "failed",
        runtime_reason="completed" if solved else "test",
        checks=(),
        artifacts=(),
        solved=solved,
        first_acceptance_passed=(None if spec.mode == "single" else solved),
        rejection_count=(None if spec.mode == "single" else spec.sequence % 3),
        correction_count=(None if spec.mode == "single" else spec.sequence % 2),
        tokens=harness.TokenTotals(
            input_tokens=spec.sequence,
            output_tokens=2,
            cached_tokens=0,
            reasoning_tokens=1,
        ),
        logical_model_calls=logical_calls,
        provider_attempts=logical_calls + 1,
        usage_present_calls=1,
        usage_missing_calls=missing_calls,
        usage_missing_rate=missing_calls / logical_calls,
        end_to_end_latency_seconds=spec.sequence / 100,
        error_category=None,
    )


def make_complete_m25_records(harness, protocol, protocol_sha256):
    tasks = {task.id: task for task in protocol.tasks}
    records = []
    for spec in harness.build_schedule(protocol):
        task = tasks[spec.task_id]
        records.append(
            make_m25_raw_record(
                harness,
                spec,
                protocol_sha256,
                solved=spec.sequence % 7 != 0,
            ).model_copy(
                update={
                    "checks": tuple(
                        harness.CheckRecord(
                            id=check.id,
                            status="passed",
                            exit_code=0,
                            stdout_sha256="0" * 64,
                            stderr_sha256="0" * 64,
                        )
                        for check in task.checks
                    ),
                    "artifacts": tuple(
                        harness.ArtifactResult(
                            path=path,
                            status="ok",
                            size=1,
                            sha256="d" * 64,
                        )
                        for path in task.artifacts
                    ),
                }
            )
        )
    return tuple(records)


def test_m25_aggregate_uses_exact_model_family_task_and_call_denominators() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_m25_records(harness, protocol, digest)
    summary = harness.aggregate_records(protocol, schedule, records)
    assert summary["completeness"] == {
        "expected_runs": 270,
        "observed_runs": 270,
        "complete": True,
    }
    assert summary["models"]["claude-haiku-4-5"]["modes"]["single"]["scheduled_runs"] == 45
    assert summary["models"]["gpt-5.4-mini"]["modes"]["triad"]["scheduled_runs"] == 45
    assert (
        summary["families"]["baseline"]["models"]["claude-haiku-4-5"]["modes"]["duo"][
            "scheduled_runs"
        ]
        == 15
    )
    assert (
        summary["families"]["bugfix"]["models"]["gpt-5.4-mini"]["modes"]["single"]["scheduled_runs"]
        == 10
    )
    assert summary["tasks"]["csv-region-summary"]["family"] == "baseline"
    selected = summary["tasks"]["csv-region-summary"]["models"]["claude-haiku-4-5"]["modes"][
        "single"
    ]
    assert selected["scheduled_runs"] == 5
    assert summary["models"]["claude-haiku-4-5"]["modes"]["single"]["first_acceptance_rate"] is None
    selected_records = [
        record
        for record in records
        if record.model_id == "claude-haiku-4-5" and record.mode == "single"
    ]
    logical_calls = sum(record.logical_model_calls for record in selected_records)
    missing_calls = sum(record.usage_missing_calls for record in selected_records)
    selected_model = summary["models"]["claude-haiku-4-5"]["modes"]["single"]
    assert selected_model["usage_missing_rate"] == {
        "numerator": missing_calls,
        "denominator": logical_calls,
        "value": missing_calls / logical_calls,
    }
    assert selected_model["tokens"]["input_tokens"]["sum"] == sum(
        record.tokens.input_tokens
        for record in selected_records
        if record.tokens.input_tokens is not None
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda records: records[:-1],
        lambda records: (*records[:-1], records[0], records[0]),
        lambda records: (
            records[0].model_copy(update={"model_id": "gpt-5.4-mini"}),
            *records[1:],
        ),
        lambda records: (
            records[0].model_copy(update={"task_family": "feature"}),
            *records[1:],
        ),
        lambda records: (
            records[0].model_copy(update={"run_id": "wrong"}),
            *records[1:],
        ),
        lambda records: (
            records[0].model_copy(update={"run_spec_sha256": "0" * 64}),
            *records[1:],
        ),
        lambda records: (
            records[0].model_copy(update={"terminal": False}),
            *records[1:],
        ),
    ],
)
def test_m25_aggregate_rejects_incomplete_duplicate_or_mixed_records(mutation) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_m25_records(harness, protocol, digest)
    with pytest.raises(ValueError):
        harness.aggregate_records(protocol, schedule, mutation(records))


def test_m25_report_keeps_models_and_modes_descriptive_without_ranking() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    records = make_complete_m25_records(harness, protocol, digest)
    summary = harness.aggregate_records(protocol, harness.build_schedule(protocol), records)
    environment = _m25_environment(harness, protocol).model_dump(mode="json", by_alias=True)
    report = harness.render_report(protocol, environment, summary)
    assert "## Model: claude-haiku-4-5" in report
    assert "## Model: gpt-5.4-mini" in report
    assert "## Task Families" in report
    assert "## Tasks" in report
    assert "First acceptance: N/A" in report
    assert "## Failures And Usage Gaps" in report
    assert "## Limitations" in report

    def keys(value):
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    forbidden_keys = {"rank", "ranking", "winner", "best_mode", "superior"}
    assert keys(summary).isdisjoint(forbidden_keys)
    assert "automatically rank" not in report.lower()
    assert "recommend one mode" not in report.lower()


def _write_m25_batch(harness, output, protocol, digest, records):
    environment = _m25_environment(harness, protocol).model_copy(update={"protocol_sha256": digest})
    environment_sha = harness.environment_sha256(environment)
    output.mkdir()
    (output / "environment.json").write_text(
        json.dumps(environment.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    for record in records:
        bound = record.model_copy(update={"environment_sha256": environment_sha})
        harness.write_raw_record(output / "raw" / f"{bound.run_id}.json", bound)
    return environment, environment_sha


def test_m25_read_raw_records_binds_filenames_routes_and_environment(tmp_path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    records = make_complete_m25_records(harness, protocol, digest)
    output = tmp_path / "complete"
    environment, environment_sha = _write_m25_batch(harness, output, protocol, digest, records)
    loaded = harness.read_raw_records(
        output / "raw",
        protocol,
        digest,
        environment_sha,
        environment=environment,
    )
    assert len(loaded) == 270
    first = output / "raw" / f"{records[0].run_id}.json"
    first.rename(output / "raw" / "wrong-name.json")
    with pytest.raises(ValueError, match="filenames"):
        harness.read_raw_records(
            output / "raw",
            protocol,
            digest,
            environment_sha,
            environment=environment,
        )


def test_m25_aggregate_failure_preserves_existing_outputs(tmp_path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    records = make_complete_m25_records(harness, protocol, digest)
    output = tmp_path / "incomplete"
    _write_m25_batch(harness, output, protocol, digest, records[:-1])
    summary_bytes = b"existing-summary"
    report_bytes = b"existing-report"
    (output / "summary.json").write_bytes(summary_bytes)
    (output / "report.md").write_bytes(report_bytes)
    with pytest.raises(ValueError, match="complete 270"):
        harness.aggregate_command(M25_PROTOCOL_PATH, output, allowed_output_root=tmp_path)
    assert (output / "summary.json").read_bytes() == summary_bytes
    assert (output / "report.md").read_bytes() == report_bytes


def test_m25_environment_raw_and_summary_have_safe_recursive_projection() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(M25_PROTOCOL_PATH)
    environment = _m25_environment(harness, protocol).model_copy(update={"protocol_sha256": digest})
    record = make_complete_m25_records(harness, protocol, digest)[0].model_copy(
        update={
            "checks": (
                harness.CheckRecord(
                    id="safe-check",
                    status="passed",
                    exit_code=0,
                    duration_ms=1,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_sha256="0" * 64,
                    stderr_sha256="0" * 64,
                ),
            )
        }
    )
    summary = harness.aggregate_records(
        protocol,
        harness.build_schedule(protocol),
        make_complete_m25_records(harness, protocol, digest),
    )
    values = [
        environment.model_dump(mode="json", by_alias=True),
        record.model_dump(mode="json", by_alias=True),
        summary,
    ]
    forbidden_key = re.compile(
        r"goal|prompt|messages|reply|body|text|api_key|credential|base_url|absolute_path",
        re.IGNORECASE,
    )
    forbidden_values = (
        "SECRET_SENTINEL",
        "https://provider.invalid/private",
        "/private/workspace/sentinel",
    )

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert forbidden_key.search(key) is None
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, str):
            yield value

    strings = [string for value in values for string in walk(value)]
    assert all(sentinel not in string for sentinel in forbidden_values for string in strings)
    assert set(record.checks[0].model_dump()) == {
        "id",
        "status",
        "exit_code",
        "duration_ms",
        "stdout_bytes",
        "stderr_bytes",
        "stdout_sha256",
        "stderr_sha256",
    }


def test_m25_public_docs_and_milestone_publish_verified_evidence() -> None:
    evidence_root = ROOT / "docs" / "evaluation" / "m25"
    run_root = evidence_root / "runs" / "2026-07-27-haiku-4-5-gpt-5-4-mini"
    milestone = ROOT / "milestones" / "milestone_025.md"
    public_paths = (
        ROOT / "docs/history/readme-milestones.md",
        ROOT / "ACTION_PLAN.md",
        evidence_root / "README.md",
        milestone,
    )
    required_refs = (
        "docs/evaluation/m25/protocol.json",
        "docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md",
        "scripts/m25_independent_recompute.py",
    )
    for path in public_paths:
        text = path.read_text(encoding="utf-8")
        for reference in required_refs:
            assert reference in text

    combined = "\n".join(path.read_text(encoding="utf-8") for path in public_paths)
    for required in (
        "270/270",
        "claude-haiku-4-5",
        "gpt-5.4-mini",
        "INDEPENDENT_RECOMPUTE_OK runs=270",
        "M23",
        "本机",
        "日期",
        "provider",
        "权重",
        "不自动排名",
    ):
        assert required in combined

    assert (run_root / "summary.json").is_file()
    assert (run_root / "report.md").is_file()
    assert "待 Comet verify/归档" not in combined
    assert "下一步由 Comet verify" not in combined
    assert "2026-07-28-m25-programming-mode-evaluation" in combined
    latest_name = (ROOT / "milestones" / "latest").read_text(encoding="utf-8").strip()
    assert latest_name.startswith("milestone_") and latest_name.endswith(".md")
    assert int(latest_name.removeprefix("milestone_").removesuffix(".md")) >= 25
    assert (ROOT / "milestones" / latest_name).is_file()
    tasks = (
        ROOT
        / "openspec"
        / "changes"
        / "archive"
        / "2026-07-28-m25-programming-mode-evaluation"
        / "tasks.md"
    ).read_text(encoding="utf-8")
    assert "- [ ]" not in tasks
    plan = M25_PLAN_PATH.read_text(encoding="utf-8")
    assert plan.count("archived-with: 2026-07-28-m25-programming-mode-evaluation") == 1
