"""Task-level replay tests for the Duo collaboration controller."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.check_runner import CheckDefinition
from forgeagent.client import MockClient
from forgeagent.collaboration import (
    CollaborationError,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    EvaluationItem,
)
from forgeagent.models import AssistantMessage, ClientError, TokenUsage
from forgeagent.task import Task


def _reply(text: str, *, usage: TokenUsage | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=text,
        usage=usage or TokenUsage(input_tokens=1, output_tokens=2, total_prompt_tokens=1),
        stop_reason="end_turn",
    )


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\ndone"


def _candidate() -> AssistantMessage:
    marker = {"name": "SubmitCandidate", "arguments": {}}
    return _reply(f"<!-- ToolCall: {json.dumps(marker)} -->")


def _evaluation(*, passed: bool, observed: str = "observed", expected: str = "expected"):
    marker = {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "goal",
                    "passed": passed,
                    "observed": observed,
                    "expected": expected,
                    "location": "artifact.txt",
                }
            ]
        },
    }
    return _reply(f"<!-- ToolCall: {json.dumps(marker)} -->")


class _RecordingClient(MockClient):
    def __init__(self, script):
        super().__init__(script)
        self.first_user_message = ""
        self.requests = []
        self.closed = False

    def complete(self, messages, params=None):
        self.requests.append(list(messages))
        if not self.first_user_message:
            self.first_user_message = str(messages[-1].content)
        return super().complete(messages, params)

    def close(self):
        self.closed = True


class _RoleBuilder:
    def __init__(self, scripts):
        self.scripts = scripts
        self.calls = []
        self.clients = []
        self.registries = []

    def __call__(self, role, attempt, registry, system_prompt):
        client = _RecordingClient(self.scripts[(role, attempt)])
        task = Task(client, tool_registry=registry, system_prompt=system_prompt)
        self.calls.append((role, attempt, system_prompt))
        self.clients.append(client)
        self.registries.append(registry)
        return task


class _AuditSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def _runner(tmp_path: Path, builder: _RoleBuilder, **kwargs) -> CollaborationRunner:
    kwargs.setdefault("generator_model", "generator-model")
    kwargs.setdefault("evaluator_model", "evaluator-model")
    return CollaborationRunner.create(
        mode="duo",
        goal="write PRIVATE_GOAL artifact",
        allowed_root=str(tmp_path),
        role_task_builder=builder,
        collaboration_id="a" * 32,
        **kwargs,
    )


def test_duo_rejects_then_uses_fresh_generator_and_passes(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=False)],
            ("generator", 2): [_candidate()],
            ("evaluator", 2): [_evaluation(passed=True)],
        }
    )
    runner = _runner(tmp_path, builder)

    report = runner.run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert (report.generator_attempts, report.evaluator_attempts, report.rejections) == (2, 2, 1)
    assert report.rounds == 4
    assert report.usage.input_tokens == 4
    assert report.usage.output_tokens == 8
    assert report.usage.total_prompt_tokens == 4
    assert len({id(registry) for registry in builder.registries}) == 4
    assert all(client.closed for client in builder.clients)
    retry_data = json.loads(builder.clients[2].first_user_message)
    assert retry_data["goal"] == "write PRIVATE_GOAL artifact"
    assert retry_data["rejection"][0]["observed"] == "observed"
    assert retry_data["plan_digest"]


def test_duo_injects_host_checks_only_into_evaluator_registry(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=True)],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        evaluator_checks={"unit": CheckDefinition(id="unit", argv=(sys.executable, "-c", "pass"))},
    ).run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert "RunCheck" not in builder.registries[0].arg_schemas()
    assert "RunCheck" in builder.registries[1].arg_schemas()


def test_duo_requires_generator_strict_completion(tmp_path: Path):
    builder = _RoleBuilder({("generator", 1): [_reply("plain answer"), _reply("still plain")]})
    runner = _runner(tmp_path, builder)

    report = runner.run("write PRIVATE_GOAL artifact")
    persisted = runner._store.load(report.collaboration_id)

    assert report.status == "failed"
    assert report.stop_reason == "invalid_role_submission"
    assert persisted.status == "failed"
    assert report.generator_attempts == 1
    assert report.evaluator_attempts == 0


def test_recover_role_failures_requires_strict_bool(tmp_path: Path):
    builder = _RoleBuilder({("generator", 1): [_reply(_done())]})

    with pytest.raises(ValueError, match="recover_role_failures must be a bool"):
        _runner(tmp_path, builder, recover_role_failures=1)


def test_execution_tier_and_loop_id_are_validated(tmp_path: Path):
    builder = _RoleBuilder({("generator", 1): [_reply(_done())]})

    with pytest.raises(ValueError, match="execution_tier is invalid"):
        _runner(tmp_path, builder, execution_tier="host")
    with pytest.raises(ValueError, match="invalid loop id"):
        _runner(tmp_path, builder, loop_id="not-a-loop-id")


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([_reply(_done()), _reply(_done())], "invalid_role_submission"),
        ([ClientError(message="bad key", kind="auth", attempts=1)], "unrecoverable_failure"),
        ([_reply("cannot"), _reply("still cannot")], "invalid_role_submission"),
    ],
)
def test_duo_evaluator_failures_have_stable_reasons(tmp_path: Path, script, reason):
    builder = _RoleBuilder({("generator", 1): [_candidate()], ("evaluator", 1): script})

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == reason
    assert report.evaluator_attempts == 1
    assert all(client.closed for client in builder.clients)


def test_duo_rejection_limit_allows_initial_plus_two_retries(tmp_path: Path):
    scripts = {}
    for attempt in (1, 2, 3):
        scripts[("generator", attempt)] = [_candidate()]
        scripts[("evaluator", attempt)] = [_evaluation(passed=False)]
    builder = _RoleBuilder(scripts)

    report = _runner(tmp_path, builder, max_rejections=2).run("write PRIVATE_GOAL artifact")

    assert report.status == "stopped"
    assert report.stop_reason == "rejection_limit"
    assert (report.generator_attempts, report.evaluator_attempts, report.rejections) == (3, 3, 2)


def test_duo_cancel_wins_after_role_boundary_and_closes_resources(tmp_path: Path):
    cancel = threading.Event()

    class _CancellingBuilder(_RoleBuilder):
        def __call__(self, role, attempt, registry, system_prompt):
            task = super().__call__(role, attempt, registry, system_prompt)
            original = task.run

            def run(goal, *, cancel_event=None):
                outcome = original(goal, cancel_event=cancel_event)
                cancel.set()
                return outcome

            task.run = run
            return task

    builder = _CancellingBuilder({("generator", 1): [_candidate()]})

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    assert [role for role, _attempt, _prompt in builder.calls] == ["generator"]
    assert all(client.closed for client in builder.clients)


def test_duo_cancel_after_rejection_does_not_start_next_generator(tmp_path: Path):
    cancel = threading.Event()

    class _CancellingEvaluatorBuilder(_RoleBuilder):
        def __call__(self, role, attempt, registry, system_prompt):
            task = super().__call__(role, attempt, registry, system_prompt)
            if role != "evaluator":
                return task
            original = task.run

            def run(goal, *, cancel_event=None):
                outcome = original(goal, cancel_event=cancel_event)
                cancel.set()
                return outcome

            task.run = run
            return task

    builder = _CancellingEvaluatorBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=False)],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    assert [(role, attempt) for role, attempt, _prompt in builder.calls] == [
        ("generator", 1),
        ("evaluator", 1),
    ]


def test_duo_cancel_during_evaluator_registry_build_does_not_construct_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cancel = threading.Event()
    builder = _RoleBuilder({("generator", 1): [_candidate()]})
    original = __import__(
        "forgeagent.collaboration", fromlist=["build_evaluator_registry"]
    ).build_evaluator_registry

    def cancelling_registry(**kwargs):
        registry = original(**kwargs)
        cancel.set()
        return registry

    monkeypatch.setattr("forgeagent.collaboration.build_evaluator_registry", cancelling_registry)

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert [role for role, _attempt, _prompt in builder.calls] == ["generator"]


def test_duo_rejects_concurrent_run_without_blocking(tmp_path: Path):
    builder = _RoleBuilder({("generator", 1): [_reply(_done())]})
    runner = _runner(tmp_path, builder)
    assert runner._run_lock.acquire(blocking=False)
    try:
        with pytest.raises(CollaborationError, match="already running"):
            runner.run("write PRIVATE_GOAL artifact")
    finally:
        runner._run_lock.release()


def test_duo_audit_projection_uses_only_safe_counters(tmp_path: Path):
    sink = _AuditSink()
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [
                _evaluation(passed=False, observed="PRIVATE_EVIDENCE", expected="PRIVATE_PATH"),
            ],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        max_rejections=0,
        audit_sink=sink,
        loop_id="b" * 32,
    ).run("write PRIVATE_GOAL artifact")

    assert report.stop_reason == "rejection_limit"
    collaboration_events = [e for e in sink.events if e.event_type.startswith("collaboration.")]
    assert {e.event_type for e in collaboration_events} >= {
        "collaboration.role.start",
        "collaboration.role.outcome",
        "collaboration.evaluation",
        "collaboration.rejection",
        "collaboration.stop",
    }
    rendered = repr(collaboration_events)
    assert "PRIVATE_GOAL" not in rendered
    assert "PRIVATE_EVIDENCE" not in rendered
    assert "PRIVATE_PATH" not in rendered
    allowed = {
        "mode",
        "collaboration_id",
        "loop_id",
        "role",
        "phase",
        "model",
        "tier",
        "attempt",
        "round_count",
        "completed",
        "usage_available",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "total_prompt_tokens",
        "cost",
        "plan_item_count",
        "passed_item_count",
        "failed_item_count",
        "rejections",
        "generator_attempts",
        "evaluator_attempts",
        "rounds",
        "revision",
    }
    assert all(set(event.parameters) <= allowed for event in collaboration_events)
    assert all(event.parameters["loop_id"] == "b" * 32 for event in collaboration_events)
    role_events = [event for event in collaboration_events if ".role." in event.event_type]
    assert [event.event_type for event in role_events] == [
        "collaboration.role.start",
        "collaboration.role.outcome",
        "collaboration.role.start",
        "collaboration.role.outcome",
    ]
    assert {event.parameters["model"] for event in role_events} == {
        "generator-model",
        "evaluator-model",
    }
    assert all(event.duration_ms is not None for event in role_events)


def test_duo_close_is_idempotent_and_run_after_close_fails(tmp_path: Path):
    runner = _runner(tmp_path, _RoleBuilder({}))
    runner.close()
    runner.close()

    with pytest.raises(CollaborationError, match="closed"):
        runner.run("write PRIVATE_GOAL artifact")


def test_duo_role_exception_becomes_stable_failure(tmp_path: Path):
    sink = _AuditSink()

    class _BrokenBuilder:
        def __call__(self, role, attempt, registry, system_prompt):
            raise RuntimeError("private role construction failure")

    report = _runner(
        tmp_path,
        _BrokenBuilder(),
        generator_model="generator-model",
        audit_sink=sink,
    ).run("write PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "role_failed"
    assert "private role construction failure" not in repr(report)
    role_events = [event for event in sink.events if ".role." in event.event_type]
    assert [event.event_type for event in role_events] == [
        "collaboration.role.start",
        "collaboration.role.outcome",
    ]
    assert role_events[-1].result_status == "role_error"
    assert role_events[-1].parameters["usage_available"] is False
    assert "private role construction failure" not in repr(role_events)


def test_duo_role_configuration_exception_is_unrecoverable_without_leaking_details(tmp_path: Path):
    class _BrokenConfigurationBuilder:
        def __call__(self, role, attempt, registry, system_prompt):
            raise CollaborationRoleConfigurationError("PRIVATE_PROVIDER_TOKEN")

    report = _runner(tmp_path, _BrokenConfigurationBuilder()).run("write PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "unrecoverable_failure"
    assert "PRIVATE_PROVIDER_TOKEN" not in repr(report)
    assert "PRIVATE_GOAL" not in repr(report)


def test_duo_usage_unavailable_is_sticky(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [
                _reply(
                    _candidate().content,
                    usage=TokenUsage(input_tokens=2, output_tokens=3),
                )
            ],
            ("evaluator", 1): [_evaluation(passed=True)],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.usage_available is False
    assert report.usage.input_tokens == 3
    assert report.usage.output_tokens == 5


def test_duo_revalidates_all_plan_items_after_rejection(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=False)],
            ("generator", 2): [_candidate()],
            ("evaluator", 2): [_evaluation(passed=True)],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    evaluator_payloads = [
        json.loads(client.first_user_message) for client in (builder.clients[1], builder.clients[3])
    ]
    assert [payload["plan"][0]["id"] for payload in evaluator_payloads] == ["goal", "goal"]
    assert report.passed_item_count == 1


def test_duo_does_not_reuse_previous_evaluation_submission(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=False)],
            ("generator", 2): [_candidate()],
            ("evaluator", 2): [_reply(_done()), _reply(_done())],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "invalid_role_submission"
    assert report.evaluator_attempts == 2


def test_duo_invalid_evaluation_tool_call_is_invalid_submission(tmp_path: Path):
    marker = {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "wrong",
                    "passed": True,
                    "observed": "yes",
                    "expected": "yes",
                }
            ]
        },
    }
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [
                _reply(f"<!-- ToolCall: {json.dumps(marker)} -->"),
                _reply(_done()),
                _reply(_done()),
            ],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "invalid_role_submission"


def test_duo_pass_verdict_completes_without_standalone_status(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(passed=True)],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert report.passed_item_count == 1


def test_duo_evaluator_prose_recovers_to_structured_submission(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_reply("Everything passes."), _evaluation(passed=True)],
        }
    )

    report = _runner(tmp_path, builder).run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert len(builder.clients[1].requests) == 2
    recovery = str(builder.clients[1].requests[1][-1].content)
    assert "SubmitEvaluation must be called successfully" in recovery
    assert '<!-- ToolCall: {"name":"SubmitEvaluation","arguments":{...}} -->' in recovery
    assert "XML/function_calls syntax is not recognized" in recovery


def test_duo_resume_with_persisted_verdict_skips_evaluator(tmp_path: Path):
    builder = _RoleBuilder({})
    runner = _runner(tmp_path, builder)
    submitted = runner._store.save(
        runner._state.model_copy(update={"phase": "evaluator", "generator_attempts": 1}),
        expected_revision=runner._state.revision,
    )
    runner._state = runner._store.save(
        submitted.model_copy(
            update={
                "evaluator_attempts": 1,
                "last_evaluation": (
                    EvaluationItem(
                        id="goal",
                        passed=True,
                        observed="artifact exists",
                        expected="artifact exists",
                    ),
                ),
            }
        ),
        expected_revision=submitted.revision,
    )

    report = runner.run("write PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert builder.calls == []
    assert (report.generator_attempts, report.evaluator_attempts) == (1, 1)
