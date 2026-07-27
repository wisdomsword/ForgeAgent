from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from forgeagent.audit import AuditEvent

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


def test_protocol_requires_immutable_files_to_reference_initial_fixtures() -> None:
    harness = load_harness()
    value = protocol_dict()
    value["tasks"][0]["immutable_files"] = ["missing.csv"]
    with pytest.raises((ValidationError, ValueError), match="immutable"):
        harness.validate_protocol(value)


EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def make_raw_record(
    harness,
    spec,
    protocol_sha256: str,
    *,
    environment_sha256: str = "b" * 64,
    solved: bool = True,
):
    applicable = spec.mode != "single"
    return harness.RawRecord(
        run_id=f"{spec.sequence:02d}-{spec.task_id}-r{spec.repeat}-{spec.mode}",
        sequence=spec.sequence,
        task_id=spec.task_id,
        mode=spec.mode,
        repeat=spec.repeat,
        protocol_sha256=protocol_sha256,
        environment_sha256=environment_sha256,
        run_spec_sha256=harness.run_spec_hash(spec, protocol_sha256),
        started_at="2026-07-27T00:00:00.000Z",
        finished_at="2026-07-27T00:00:01.000Z",
        runtime_completed=True,
        runtime_status="completed",
        runtime_reason="completed",
        checks=(
            harness.CheckRecord(
                id="artifact",
                status="passed",
                exit_code=0,
                stdout_sha256=EMPTY_SHA256,
                stderr_sha256=EMPTY_SHA256,
            ),
        ),
        artifacts=(),
        solved=solved,
        first_acceptance_passed=True if applicable else None,
        rejection_count=0 if applicable else None,
        correction_count=0 if applicable else None,
        tokens=harness.TokenTotals(
            input_tokens=10,
            output_tokens=4,
            cached_tokens=2,
            reasoning_tokens=1,
        ),
        logical_model_calls=1,
        provider_attempts=1,
        usage_present_calls=1,
        usage_missing_calls=0,
        usage_missing_rate=0.0,
        end_to_end_latency_seconds=1.0,
        error_category=None,
    )


def test_audit_projection_counts_calls_attempts_tokens_and_missing_usage() -> None:
    harness = load_harness()
    events = [
        AuditEvent(event_type="llm.provider_attempt", result_status="started", attempt=1),
        AuditEvent(event_type="llm.provider_attempt", result_status="success", attempt=1),
        AuditEvent(
            event_type="llm.outcome",
            result_status="success",
            parameters={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "cached_tokens": 2,
                    "reasoning_tokens": 1,
                }
            },
        ),
        AuditEvent(event_type="llm.outcome", result_status="error", parameters={}),
    ]
    metrics = harness.project_audit_metrics(events)
    assert metrics.logical_model_calls == 2
    assert metrics.provider_attempts == 1
    assert metrics.usage_present_calls == 1
    assert metrics.usage_missing_calls == 1
    assert metrics.usage_missing_rate == 0.5
    assert metrics.tokens.model_dump() == {
        "input_tokens": 10,
        "output_tokens": 4,
        "cached_tokens": 2,
        "reasoning_tokens": 1,
    }


def test_no_calls_has_zero_calls_null_missing_rate_and_known_zero_tokens() -> None:
    harness = load_harness()
    metrics = harness.project_audit_metrics([])
    assert metrics.logical_model_calls == 0
    assert metrics.usage_missing_rate is None
    assert metrics.tokens.input_tokens == 0


def test_all_missing_usage_keeps_unknown_tokens_null() -> None:
    harness = load_harness()
    metrics = harness.project_audit_metrics(
        [AuditEvent(event_type="llm.outcome", result_status="error", parameters={})]
    )
    assert metrics.logical_model_calls == metrics.usage_missing_calls == 1
    assert metrics.tokens.input_tokens is None
    assert metrics.tokens.output_tokens is None


@pytest.mark.parametrize(
    "usage",
    [
        True,
        {},
        {"input_tokens": 1, "output_tokens": 2, "cached_tokens": 0},
        {
            "input_tokens": True,
            "output_tokens": 2,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
        },
        {
            "input_tokens": -1,
            "output_tokens": 2,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
        },
    ],
)
def test_invalid_usage_is_counted_as_missing(usage: object) -> None:
    harness = load_harness()
    metrics = harness.project_audit_metrics(
        [AuditEvent(event_type="llm.outcome", parameters={"usage": usage})]
    )
    assert metrics.usage_present_calls == 0
    assert metrics.usage_missing_calls == 1
    assert metrics.tokens.input_tokens is None


def test_single_acceptance_loop_fields_are_null() -> None:
    harness = load_harness()
    result = harness.ModeResult(
        runtime_completed=True,
        runtime_status="completed",
        runtime_reason="completed",
        first_acceptance_passed=None,
        rejection_count=None,
        correction_count=None,
    )
    assert result.first_acceptance_passed is None
    assert result.rejection_count is None
    assert result.correction_count is None


def test_internal_completion_with_failed_external_check_is_not_solved() -> None:
    harness = load_harness()
    record = harness.build_raw_record(
        run_spec=harness.RunSpec(1, "task", 1, "duo"),
        mode_result=harness.ModeResult(
            runtime_completed=True,
            runtime_status="completed",
            runtime_reason="completed",
            first_acceptance_passed=True,
            rejection_count=0,
            correction_count=0,
        ),
        checks=(
            harness.CheckRecord(
                id="artifact",
                status="failed",
                exit_code=1,
                stdout_sha256=EMPTY_SHA256,
                stderr_sha256=EMPTY_SHA256,
            ),
        ),
        artifacts=(),
        audit_metrics=harness.project_audit_metrics([]),
        protocol_sha256="a" * 64,
        environment_sha256="b" * 64,
        started_at="2026-07-27T00:00:00.000Z",
        finished_at="2026-07-27T00:00:01.000Z",
        end_to_end_latency_seconds=1.0,
    )
    assert record.runtime_completed is True
    assert record.solved is False


def test_prepare_workspace_requires_an_existing_empty_directory(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "occupied").write_text("user data", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        harness.prepare_workspace(protocol.tasks[0], workspace)


def test_hash_artifacts_classifies_missing_directory_and_symlink(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task = protocol.tasks[0]
    (tmp_path / "summarize.py").mkdir()
    (tmp_path / "summary.json").symlink_to(tmp_path / "outside")
    results = {item.path: item for item in harness.hash_artifacts(task, tmp_path)}
    assert results["summarize.py"].status == "not_regular"
    assert results["summary.json"].status == "symlink"
    assert results["summarize.py"].sha256 is None


def test_external_check_projects_only_output_size_and_hash(tmp_path: Path) -> None:
    harness = load_harness()
    task = harness.TaskSpec(
        id="local-check",
        goal="Run a local check.",
        initial_files={"fixture.txt": "fixed\n"},
        immutable_files=("fixture.txt",),
        required_candidate_files=("result.txt",),
        artifacts=("result.txt",),
        checks=(
            harness.CheckSpec(
                id="local-output",
                command=(
                    "{python}",
                    "-c",
                    "import sys; print('visible-output'); print('visible-error', file=sys.stderr)",
                ),
                timeout_seconds=30,
            ),
        ),
    )
    records = harness.run_checks(task, tmp_path)
    dumped = records[0].model_dump(mode="json")
    assert records[0].status == "passed"
    assert records[0].stdout_bytes == len(b"visible-output\n")
    assert records[0].stderr_bytes == len(b"visible-error\n")
    assert "stdout" not in dumped and "stderr" not in dumped


def test_checked_in_csv_check_runs_candidate_without_nested_process_spawn(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task = protocol.tasks[0]
    harness.prepare_workspace(task, tmp_path)
    (tmp_path / "summarize.py").write_text(
        """import csv
import json
import sys

totals = {}
with open(sys.argv[1], newline='', encoding='utf-8') as source:
    for row in csv.DictReader(source):
        totals[row['region']] = totals.get(row['region'], 0) + int(row['amount'])
with open(sys.argv[2], 'w', encoding='utf-8') as destination:
    json.dump(dict(sorted(totals.items())), destination)
""",
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        json.dumps({"North": 15, "South": 10, "West": 8}), encoding="utf-8"
    )

    checks = harness.run_checks(task, tmp_path)

    assert [check.id for check in checks] == ["csv-summary", "fixture-integrity"]
    assert all(check.status == "passed" for check in checks)


def test_checked_in_event_check_runs_candidate_without_nested_process_spawn(
    tmp_path: Path,
) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task = protocol.tasks[2]
    harness.prepare_workspace(task, tmp_path)
    (tmp_path / "normalize_events.py").write_text(
        """import json
import sys

with open(sys.argv[1], encoding='utf-8') as source:
    events = json.load(source)
latest = {}
for event in events:
    if event['id'] not in latest or event['timestamp'] > latest[event['id']]['timestamp']:
        latest[event['id']] = event
result = sorted(latest.values(), key=lambda event: (event['timestamp'], event['id']))
with open(sys.argv[2], 'w', encoding='utf-8') as destination:
    json.dump(result, destination)
""",
        encoding="utf-8",
    )
    expected = [
        {"id": "b", "timestamp": "2026-01-01T12:00:00Z", "kind": "create"},
        {"id": "c", "timestamp": "2026-01-01T12:00:00Z", "kind": "create"},
        {"id": "a", "timestamp": "2026-01-03T09:00:00Z", "kind": "close"},
    ]
    (tmp_path / "normalized.json").write_text(json.dumps(expected), encoding="utf-8")

    checks = harness.run_checks(task, tmp_path)

    assert [check.id for check in checks] == ["normalized-events", "fixture-integrity"]
    assert all(check.status == "passed" for check in checks)


def test_fixture_integrity_fails_even_when_modified_test_file_passes(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task = protocol.tasks[1]
    harness.prepare_workspace(task, tmp_path)
    (tmp_path / "test_range_compression.py").write_text(
        "def test_fabricated_pass():\n    assert True\n", encoding="utf-8"
    )

    checks = {check.id: check for check in harness.run_checks(task, tmp_path)}

    assert checks["range-pytest"].status == "passed"
    assert checks["fixture-integrity"].status == "failed"


def test_write_raw_record_is_atomic_and_never_leaves_temp_file(tmp_path: Path) -> None:
    harness = load_harness()
    record = make_raw_record(
        harness,
        harness.RunSpec(sequence=1, task_id="csv-region-summary", repeat=1, mode="single"),
        protocol_sha256="a" * 64,
    )
    target = tmp_path / "raw" / "01-task-r1-single.json"
    harness.write_raw_record(target, record)
    assert json.loads(target.read_text()) == record.model_dump(mode="json", by_alias=True)
    assert list(target.parent.glob(".*.tmp")) == []


def test_raw_record_contains_no_sensitive_or_conversation_keys() -> None:
    harness = load_harness()
    record = make_raw_record(
        harness,
        harness.RunSpec(1, "csv-region-summary", 1, "single"),
        protocol_sha256="a" * 64,
    )
    forbidden = {
        "goal",
        "prompt",
        "messages",
        "reply",
        "body",
        "text",
        "api_key",
        "base_url",
        "environment",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    assert keys(record.model_dump(mode="json", by_alias=True)).isdisjoint(forbidden)


def test_environment_manifest_has_a_fixed_safe_surface() -> None:
    harness = load_harness()
    protocol, protocol_sha256 = harness.load_protocol(PROTOCOL_PATH)
    manifest = harness.environment_manifest(
        protocol,
        protocol_sha256,
        repo_root=ROOT,
        provider_route_sha256="c" * 64,
    )
    dumped = manifest.model_dump(mode="json", by_alias=True)
    assert set(dumped) == {
        "schema",
        "generated_at",
        "git_commit",
        "tracked_dirty",
        "python_version",
        "python_executable_name",
        "platform",
        "package_version",
        "model_id",
        "provider_route_sha256",
        "builtin_models_sha256",
        "builtin_config_sha256",
        "protocol_sha256",
        "generation",
        "execution",
    }
    assert harness.environment_sha256(manifest) == harness.environment_sha256(
        manifest.model_copy(update={"generated_at": "2099-01-01T00:00:00.000Z"})
    )


def test_run_single_uses_fixed_params_and_closes_task_and_client(
    tmp_path: Path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task_spec = protocol.tasks[0]
    run_spec = harness.RunSpec(1, task_spec.id, 1, "single")
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def close(self) -> None:
            calls.append(("client.close", self))

    class FakeTask:
        def __init__(self, client, **kwargs) -> None:
            calls.append(("task.init", (client, kwargs)))

        def run(self, goal: str):
            calls.append(("task.run", goal))
            return SimpleNamespace(status=SimpleNamespace(completed=True, reason="completed"))

        def close(self) -> None:
            calls.append(("task.close", self))

    monkeypatch.setattr(harness, "Task", FakeTask)
    monkeypatch.setattr(harness, "build_real_client", lambda model, registry: FakeClient())
    result = harness.run_single(
        protocol, task_spec, run_spec, tmp_path, object(), harness.CollectingAuditSink()
    )

    init_kwargs = next(value[1] for name, value in calls if name == "task.init")
    assert init_kwargs["tier"] == "restricted"
    assert init_kwargs["allowed_root"] == str(tmp_path)
    assert init_kwargs["params"].model_dump() == protocol.generation.model_dump()
    assert result.first_acceptance_passed is None
    assert [name for name, _ in calls[-2:]] == ["task.close", "client.close"]


@pytest.mark.parametrize(
    ("mode", "roles"),
    [("duo", ("generator", "evaluator")), ("triad", ("planner", "generator", "evaluator"))],
)
def test_run_collaboration_uses_fresh_owned_role_tasks(
    tmp_path: Path, monkeypatch, mode: str, roles: tuple[str, ...]
) -> None:
    harness = load_harness()
    protocol, _ = harness.load_protocol(PROTOCOL_PATH)
    task_spec = protocol.tasks[0]
    run_spec = harness.RunSpec(1, task_spec.id, 1, mode)
    clients: list[SimpleNamespace] = []
    tasks: list[SimpleNamespace] = []
    create_kwargs: dict[str, object] = {}

    def build_client(model: str, *, registry):
        client = SimpleNamespace(model=model, closed=False)
        client.close = lambda: setattr(client, "closed", True)
        clients.append(client)
        return client

    class FakeTask:
        def __init__(self, client, **kwargs) -> None:
            self.client = client
            self.kwargs = kwargs
            self.closed = False
            tasks.append(self)

        def run(self, goal: str, *, cancel_event=None):
            return SimpleNamespace(status=SimpleNamespace(completed=True, reason="completed"))

        def close(self) -> None:
            self.closed = True

    class FakeRunner:
        @classmethod
        def create(cls, **kwargs):
            create_kwargs.update(kwargs)
            return cls()

        def run(self, goal: str):
            for role in roles:
                owned = create_kwargs["role_task_builder"](role, 1, object(), f"{role} system")
                owned.run("role input")
                owned.close()
            return SimpleNamespace(
                status="completed",
                stop_reason="completed",
                generator_attempts=1,
                evaluator_attempts=1,
                rejections=0,
            )

        def close(self) -> None:
            create_kwargs["runner_closed"] = True

    monkeypatch.setattr(harness, "Task", FakeTask)
    monkeypatch.setattr(harness, "CollaborationRunner", FakeRunner)
    monkeypatch.setattr(harness, "build_real_client", build_client)
    result = harness.run_collaboration(
        protocol, task_spec, run_spec, tmp_path, object(), harness.CollectingAuditSink()
    )

    assert create_kwargs["mode"] == mode
    assert len(create_kwargs["collaboration_id"]) == 32
    assert set(create_kwargs["collaboration_id"]) <= set("0123456789abcdef")
    assert "evaluator_checks" not in create_kwargs
    assert create_kwargs["required_candidate_files"] == task_spec.required_candidate_files
    assert all(
        task.kwargs["params"].model_dump() == protocol.generation.model_dump() for task in tasks
    )
    assert all(task.kwargs["allowed_root"] == str(tmp_path) for task in tasks)
    assert all(task.closed for task in tasks)
    assert all(client.closed for client in clients)
    assert len({id(client) for client in clients}) == len(roles)
    assert result.first_acceptance_passed is True
    assert create_kwargs["runner_closed"] is True


def test_execute_run_collapses_exception_without_persisting_message(
    tmp_path: Path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, protocol_sha256 = harness.load_protocol(PROTOCOL_PATH)
    task_spec = protocol.tasks[0]
    run_spec = harness.RunSpec(1, task_spec.id, 1, "single")

    def fail_runner(*_args, **_kwargs):
        raise RuntimeError("LEAK_ME_INTERNAL_DETAIL")

    monkeypatch.setattr(harness, "run_single", fail_runner)
    monkeypatch.setattr(harness, "run_checks", lambda *_args: ())
    monkeypatch.setattr(harness, "hash_artifacts", lambda *_args: ())
    record = harness.execute_run(
        protocol,
        protocol_sha256,
        "b" * 64,
        task_spec,
        run_spec,
        tmp_path,
        object(),
    )
    dumped = json.dumps(record.model_dump(mode="json", by_alias=True))
    assert record.runtime_completed is False
    assert record.error_category == "internal_error"
    assert "LEAK_ME" not in dumped
    assert record.end_to_end_latency_seconds >= 0


def make_complete_records(harness, schedule, protocol_sha256: str):
    return tuple(
        make_raw_record(harness, spec, protocol_sha256, solved=spec.sequence % 4 != 0)
        for spec in schedule
    )


def test_aggregate_uses_exact_denominators_and_single_na() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    summary = harness.aggregate_records(protocol, schedule, records)

    for mode in ("single", "duo", "triad"):
        assert summary["modes"][mode]["scheduled_runs"] == 9
        assert summary["modes"][mode]["task_completion_rate"]["denominator"] == 9
    assert summary["modes"]["single"]["first_acceptance_rate"] is None
    assert summary["modes"]["single"]["rejections"] is None
    assert summary["modes"]["single"]["corrections"] is None
    assert summary["modes"]["duo"]["first_acceptance_rate"]["denominator"] == 9
    assert summary["modes"]["triad"]["first_acceptance_rate"]["denominator"] == 9
    assert all(
        summary["tasks"][task.id][mode]["scheduled_runs"] == 3
        for task in protocol.tasks
        for mode in protocol.modes
    )


def test_aggregate_rejects_missing_duplicate_or_mixed_records() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    with pytest.raises(ValueError, match="complete 27"):
        harness.aggregate_records(protocol, schedule, records[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        harness.aggregate_records(protocol, schedule, (*records[:-1], records[0], records[0]))
    mixed = records[0].model_copy(update={"protocol_sha256": "f" * 64})
    with pytest.raises(ValueError, match="protocol"):
        harness.aggregate_records(protocol, schedule, (mixed, *records[1:]))


def test_usage_missing_rate_is_call_weighted_and_runtime_is_not_completion() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = list(make_complete_records(harness, schedule, digest))
    first = records[0]
    records[0] = first.model_copy(
        update={
            "solved": False,
            "logical_model_calls": 10,
            "usage_present_calls": 0,
            "usage_missing_calls": 10,
            "usage_missing_rate": 1.0,
            "tokens": harness.TokenTotals(
                input_tokens=None,
                output_tokens=None,
                cached_tokens=None,
                reasoning_tokens=None,
            ),
        }
    )
    summary = harness.aggregate_records(protocol, schedule, records)
    single = summary["modes"]["single"]
    assert single["usage_missing_rate"] == {
        "numerator": 10,
        "denominator": 18,
        "value": 10 / 18,
    }
    assert single["task_completion_rate"]["numerator"] < sum(
        record.runtime_completed for record in records if record.mode == "single"
    )
    assert single["tokens"]["input_tokens"]["sum"] == 80


def test_report_is_descriptive_and_contains_no_ranking_contract() -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    records = make_complete_records(harness, schedule, digest)
    summary = harness.aggregate_records(protocol, schedule, records)
    report = harness.render_report(
        protocol,
        {"schema": "forgeagent.m23.environment/v1", "model_id": protocol.model_id},
        summary,
    )
    lowered = report.lower()
    assert "不自动宣称 triad 优于 single" in lowered
    assert "小样本" in report
    assert "N/A" in report
    for forbidden in ("winner", "rank", "recommendation", "superiority"):
        assert forbidden not in lowered
        assert forbidden not in json.dumps(summary).lower()


def test_parser_exposes_only_fixed_run_and_aggregate_inputs() -> None:
    harness = load_harness()
    parser = harness.build_parser()
    run_args = parser.parse_args(["run", "--protocol", str(PROTOCOL_PATH), "--output", "/tmp/m23"])
    assert run_args.command == "run"
    aggregate_args = parser.parse_args(
        ["aggregate", "--protocol", str(PROTOCOL_PATH), "--output", "/tmp/m23"]
    )
    assert aggregate_args.command == "aggregate"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "--model",
                "other",
                "--protocol",
                str(PROTOCOL_PATH),
                "--output",
                "/tmp/m23",
            ]
        )


def test_preflight_fails_before_schedule_when_model_or_output_mismatches(
    tmp_path: Path,
) -> None:
    harness = load_harness()
    calls: list[str] = []
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)

    def failing_builder(model_id: str, *, registry):
        calls.append(model_id)
        raise ValueError("model capability mismatch")

    with pytest.raises(ValueError, match="model capability"):
        harness.preflight(
            protocol,
            digest,
            tmp_path / "output",
            allowed_output_root=tmp_path,
            registry_loader=harness.load_registry,
            client_builder=failing_builder,
        )
    assert calls == ["claude-haiku-4-5"]


def test_preflight_rejects_output_symlink_before_client_build(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    output.symlink_to(outside, target_is_directory=True)
    calls: list[str] = []

    with pytest.raises(ValueError, match="symlink"):
        harness.preflight(
            protocol,
            digest,
            output,
            allowed_output_root=tmp_path,
            registry_loader=harness.load_registry,
            client_builder=lambda model_id, registry: calls.append(model_id),
        )
    assert calls == []


def test_output_path_rejects_dotdot_escape_and_symlink_ancestor(tmp_path: Path) -> None:
    harness = load_harness()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="outside"):
        harness._validate_output_path(allowed / ".." / "escaped", allowed)

    (allowed / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|outside"):
        harness._validate_output_path(allowed / "linked" / "run", allowed)


def test_aggregate_rejects_symlink_ancestor_before_reading_evidence(tmp_path: Path) -> None:
    harness = load_harness()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink|outside"):
        harness.aggregate_command(
            PROTOCOL_PATH,
            allowed / "linked" / "run",
            allowed_output_root=allowed,
        )


def test_resume_skips_only_exact_matching_raw_record(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    first = make_raw_record(harness, schedule[0], digest)
    target = tmp_path / "raw" / f"{first.run_id}.json"
    harness.write_raw_record(target, first)

    pending = harness.pending_run_specs(tmp_path, schedule, digest, "b" * 64)
    assert [spec.sequence for spec in pending] == list(range(2, 28))

    value = json.loads(target.read_text(encoding="utf-8"))
    value["run_spec_sha256"] = "f" * 64
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="run spec"):
        harness.pending_run_specs(tmp_path, schedule, digest, "b" * 64)


def test_resume_rejects_run_id_that_disagrees_with_fixed_filename(tmp_path: Path) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    first = make_raw_record(harness, schedule[0], digest)
    target = tmp_path / "raw" / f"{first.run_id}.json"
    harness.write_raw_record(target, first.model_copy(update={"run_id": "wrong-id"}))
    with pytest.raises(ValueError, match="run id"):
        harness.pending_run_specs(tmp_path, schedule, digest, "b" * 64)


def test_aggregate_rejects_environment_manifest_bound_to_another_protocol(
    tmp_path: Path,
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    manifest = harness.environment_manifest(
        protocol,
        digest,
        repo_root=ROOT,
        provider_route_sha256="c" * 64,
    ).model_copy(update={"protocol_sha256": "f" * 64})
    environment_digest = harness.environment_sha256(manifest)
    (tmp_path / "raw").mkdir()
    (tmp_path / "environment.json").write_text(
        json.dumps(manifest.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    for record in make_complete_records(harness, harness.build_schedule(protocol), digest):
        bound = record.model_copy(update={"environment_sha256": environment_digest})
        harness.write_raw_record(tmp_path / "raw" / f"{bound.run_id}.json", bound)
    with pytest.raises(ValueError, match="environment.*protocol"):
        harness.aggregate_command(PROTOCOL_PATH, tmp_path, allowed_output_root=tmp_path)


def test_successful_preflight_closes_probe_and_writes_only_safe_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    client = SimpleNamespace(
        capability=SimpleNamespace(
            model_id=protocol.model_id, max_output_tokens=8192, client_kind="anthropic"
        ),
        closed=False,
    )
    client.close = lambda: setattr(client, "closed", True)
    monkeypatch.setattr(
        harness,
        "resolve_model",
        lambda *_args, **_kwargs: SimpleNamespace(
            capability=client.capability,
            api_key="SECRET_KEY_MUST_NOT_PERSIST",
            base_url="https://provider.invalid/secret-route",
        ),
    )
    context = harness.preflight(
        protocol,
        digest,
        tmp_path / "output",
        allowed_output_root=tmp_path,
        registry_loader=lambda: object(),
        client_builder=lambda *_args, **_kwargs: client,
    )
    persisted = (tmp_path / "output" / "environment.json").read_text()
    assert client.closed is True
    assert context.environment.protocol_sha256 == digest
    assert "SECRET_KEY" not in persisted
    assert "provider.invalid" not in persisted


def test_keyboard_interrupt_preserves_existing_raw_record(tmp_path: Path, monkeypatch) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    schedule = harness.build_schedule(protocol)
    output = tmp_path / "runs"
    first = make_raw_record(harness, schedule[0], digest)
    target = output / "raw" / f"{first.run_id}.json"
    harness.write_raw_record(target, first)
    original = target.read_bytes()
    monkeypatch.setattr(
        harness,
        "preflight",
        lambda *_args, **_kwargs: SimpleNamespace(registry=object(), environment_sha256="b" * 64),
    )
    monkeypatch.setattr(
        harness,
        "execute_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        harness.run_command(PROTOCOL_PATH, output, allowed_output_root=tmp_path)
    assert target.read_bytes() == original


def test_run_command_writes_all_terminal_records_then_aggregates(
    tmp_path: Path, monkeypatch
) -> None:
    harness = load_harness()
    protocol, digest = harness.load_protocol(PROTOCOL_PATH)
    aggregate_calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        harness,
        "preflight",
        lambda *_args, **_kwargs: SimpleNamespace(registry=object(), environment_sha256="b" * 64),
    )

    def fake_execute(
        _protocol,
        _protocol_sha256,
        _environment_sha256,
        _task,
        run_spec,
        _workspace,
        _registry,
    ):
        return make_raw_record(harness, run_spec, digest, solved=run_spec.sequence != 1)

    monkeypatch.setattr(harness, "execute_run", fake_execute)

    def fake_aggregate(protocol_path: Path, output_dir: Path, *, allowed_output_root: Path) -> int:
        aggregate_calls.append((protocol_path, output_dir))
        return 0

    monkeypatch.setattr(harness, "aggregate_command", fake_aggregate)
    output = tmp_path / "runs"
    assert harness.run_command(PROTOCOL_PATH, output, allowed_output_root=tmp_path) == 0
    assert len(list((output / "raw").glob("*.json"))) == 27
    first = json.loads((output / "raw" / "01-csv-region-summary-r1-single.json").read_text())
    assert first["solved"] is False
    assert aggregate_calls == [(PROTOCOL_PATH, output)]


def test_main_returns_two_for_incomplete_aggregate(tmp_path: Path, monkeypatch) -> None:
    harness = load_harness()
    monkeypatch.setattr(
        harness,
        "aggregate_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("incomplete")),
    )
    assert (
        harness.main(
            [
                "aggregate",
                "--protocol",
                str(PROTOCOL_PATH),
                "--output",
                str(tmp_path),
            ]
        )
        == 2
    )


def test_m23_public_docs_link_valid_v2_and_disclose_invalid_batch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    action_plan = (ROOT / "ACTION_PLAN.md").read_text(encoding="utf-8")
    milestone = (ROOT / "milestones" / "milestone_023.md").read_text(encoding="utf-8")

    for text in (readme, action_plan, milestone):
        normalized = " ".join(text.split())
        assert "docs/evaluation/m23/protocol.json" in text
        assert "2026-07-27-haiku-4-5-invalid-8dbebff/INVALID.md" in text
        assert "不自动宣称 Triad 优于 Single" in normalized
        assert "2026-07-27-haiku-4-5/report.md" in text
    assert "| **M23**" in action_plan
    m23_row = next(line for line in action_plan.splitlines() if line.startswith("| **M23**"))
    assert "已完成并归档" in m23_row
    assert "openspec/changes/archive/2026-07-27-m23-collaboration-mode-evaluation/" in m23_row
    assert "状态: 已完成并归档" in milestone
    assert "[x] 完成 Comet verify 与归档" in milestone
    assert "旧完成率不得引用" in milestone
    assert (ROOT / "milestones" / "latest").read_text().strip() == "milestone_023.md"


def test_m23_does_not_modify_product_runtime_or_dependencies() -> None:
    protected = (
        "src/forgeagent/collaboration.py",
        "src/forgeagent/cli.py",
        "src/forgeagent/model_registry.py",
        "pyproject.toml",
        "uv.lock",
    )
    for path in protected:
        before = subprocess.run(
            [
                "git",
                "show",
                f"f6e0dda3c8a7f9c73400c240c0a999e20b12bbd6:{path}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert (ROOT / path).read_bytes() == before
