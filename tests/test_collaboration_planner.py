"""Planner confirmation and Triad collaboration replay tests."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.client import MockClient
from forgeagent.collaboration import (
    AcceptanceItem,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    CollaborationStore,
    headless_plan_confirmer,
    plan_digest,
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


def _plan(items: list[dict[str, str]], *, completed: bool = False) -> AssistantMessage:
    marker = {"name": "SubmitPlan", "arguments": {"items": items}}
    suffix = f"\n{_done()}" if completed else ""
    return _reply(f"<!-- ToolCall: {json.dumps(marker)} -->{suffix}")


def _candidate() -> AssistantMessage:
    marker = {"name": "SubmitCandidate", "arguments": {}}
    return _reply(f"<!-- ToolCall: {json.dumps(marker)} -->")


def _evaluation(results: list[dict[str, object]]) -> AssistantMessage:
    marker = {"name": "SubmitEvaluation", "arguments": {"results": results}}
    return _reply(f"<!-- ToolCall: {json.dumps(marker)} -->")


def _items() -> list[dict[str, str]]:
    return [
        {
            "id": "artifact",
            "behavior": "The requested artifact is present",
            "acceptance": "A reader can observe the requested content",
        },
        {
            "id": "quality",
            "behavior": "The artifact is internally consistent",
            "acceptance": "All observable statements agree",
        },
    ]


def _results(*, passed: bool) -> list[dict[str, object]]:
    return [
        {
            "id": item["id"],
            "passed": passed,
            "observed": "visible result" if passed else "missing result",
            "expected": "visible result",
            "location": "artifact.txt",
        }
        for item in _items()
    ]


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


class _ConcurrentPlannerBuilder(_RoleBuilder):
    def __init__(
        self,
        scripts,
        *,
        winner: bool,
        ready: threading.Barrier,
        winner_committed: threading.Event,
        loser_finished: threading.Event,
    ):
        super().__init__(scripts)
        self.winner = winner
        self.ready = ready
        self.winner_committed = winner_committed
        self.loser_finished = loser_finished

    def __call__(self, role, attempt, registry, system_prompt):
        task = super().__call__(role, attempt, registry, system_prompt)
        if role != "planner" or attempt != 1:
            return task
        original = task.run

        def run(goal, *, cancel_event=None):
            self.ready.wait(timeout=2)
            if self.winner:
                outcome = original(goal, cancel_event=cancel_event)
                self.winner_committed.set()
                assert self.loser_finished.wait(timeout=3)
                return outcome
            assert self.winner_committed.wait(timeout=2)
            return original(goal, cancel_event=cancel_event)

        task.run = run
        return task


class _AuditSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def _runner(
    tmp_path: Path,
    builder: _RoleBuilder,
    *,
    plan_confirmer=None,
    audit_sink=None,
    collaboration_id: str = "c" * 32,
    **kwargs,
) -> CollaborationRunner:
    return CollaborationRunner.create(
        mode="triad",
        goal="create PRIVATE_GOAL artifact",
        allowed_root=str(tmp_path),
        role_task_builder=builder,
        plan_confirmer=plan_confirmer,
        audit_sink=audit_sink,
        collaboration_id=collaboration_id,
        **kwargs,
    )


def _persisted_triad_state(
    tmp_path: Path,
    *,
    phase: str,
    collaboration_id: str,
    generator_attempts: int = 0,
):
    store = CollaborationStore(str(tmp_path))
    state = store.create("create PRIVATE_GOAL artifact", "triad", collaboration_id=collaboration_id)
    items = tuple(AcceptanceItem.model_validate(item) for item in _items())
    state = store.save(
        state.model_copy(
            update={
                "phase": "needs_confirmation",
                "plan": items,
                "plan_digest": plan_digest(items),
            }
        ),
        expected_revision=state.revision,
    )
    if phase in {"generator", "evaluator"}:
        state = store.save(
            state.model_copy(update={"phase": "generator"}),
            expected_revision=state.revision,
        )
    if phase == "evaluator":
        state = store.save(
            state.model_copy(
                update={"phase": "evaluator", "generator_attempts": generator_attempts}
            ),
            expected_revision=state.revision,
        )
    store.close()


def _reopened_runner(
    tmp_path: Path,
    builder: _RoleBuilder,
    *,
    collaboration_id: str,
    plan_confirmer=None,
    audit_sink=None,
) -> CollaborationRunner:
    store = CollaborationStore(str(tmp_path), audit_sink=audit_sink)
    return CollaborationRunner(
        store=store,
        state=store.load(collaboration_id),
        role_task_builder=builder,
        plan_confirmer=plan_confirmer,
        audit_sink=audit_sink,
    )


def test_triad_approved_plan_rejects_then_uses_fresh_generator_and_passes(tmp_path: Path):
    summaries: list[str] = []
    builder = _RoleBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=False))],
            ("generator", 2): [_candidate()],
            ("evaluator", 2): [_evaluation(_results(passed=True))],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=lambda summary: summaries.append(summary) is None,
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.stop_reason == "completed"
    assert report.plan_item_count == 2
    assert (report.generator_attempts, report.evaluator_attempts, report.rejections) == (2, 2, 1)
    assert report.rounds == 5
    assert [call[0] for call in builder.calls] == [
        "planner",
        "generator",
        "evaluator",
        "generator",
        "evaluator",
    ]
    assert set(builder.registries[0].arg_schemas()) == {"SubmitPlan"}
    assert set(builder.registries[2].arg_schemas()) == {
        "FileRead",
        "FileList",
        "SubmitEvaluation",
    }
    assert len({id(registry) for registry in builder.registries}) == 5
    assert all(client.closed for client in builder.clients)
    assert "PRIVATE_GOAL" not in summaries[0]
    assert json.loads(builder.clients[1].first_user_message)["plan"] == _items()
    retry = json.loads(builder.clients[3].first_user_message)
    assert [item["id"] for item in retry["plan"]] == ["artifact", "quality"]
    assert [item["id"] for item in retry["rejection"]] == ["artifact", "quality"]


@pytest.mark.parametrize("confirmer", [None, headless_plan_confirmer("deny")])
def test_triad_without_approval_stops_at_confirmation(tmp_path: Path, confirmer):
    builder = _RoleBuilder({("planner", 1): [_plan(_items())]})

    report = _runner(tmp_path, builder, plan_confirmer=confirmer).run(
        "create PRIVATE_GOAL artifact"
    )

    assert report.status == "stopped"
    assert report.stop_reason == "needs_confirmation"
    assert report.plan_item_count == 2
    assert [call[0] for call in builder.calls] == ["planner"]


def test_triad_headless_preauthorize_runs_generator(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert [call[0] for call in builder.calls] == ["planner", "generator", "evaluator"]


def test_collaboration_role_prompts_explain_their_text_protocol(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    prompts = {role: prompt for role, _attempt, prompt in builder.calls}
    assert report.status == "completed"
    assert '"name":"SubmitPlan"' in prompts["planner"]
    assert '"items"' in prompts["planner"]
    assert "verifiable with FileList and FileRead" in prompts["planner"]
    assert "Do not require proof that pytest or another command actually ran" in prompts["planner"]
    assert "Never use XML/function_calls syntax" in prompts["planner"]
    assert '"name":"SubmitCandidate"' in prompts["generator"]
    assert "Do not substitute prose or task_status" in prompts["generator"]
    assert "SubmitCandidate does not create or validate artifacts" in prompts["generator"]
    assert "use FileWrite before SubmitCandidate" in prompts["generator"]
    assert "do not call SubmitCandidate in that response" in prompts["generator"]
    assert (
        "Optional verification failure does not invalidate successful writes"
        in prompts["generator"]
    )
    assert "Never use XML/function_calls syntax" in prompts["generator"]
    assert '"name":"SubmitEvaluation"' in prompts["evaluator"]
    assert '"results"' in prompts["evaluator"]
    assert '"name":"FileRead"' in prompts["evaluator"]
    assert "Never infer that an artifact exists" in prompts["evaluator"]
    assert "Do not reject solely because Exec is unavailable" in prompts["evaluator"]
    assert "Inspect one file per response" in prompts["evaluator"]
    assert "re-read only that file" in prompts["evaluator"]
    assert (
        "Never claim FileRead was truncated unless its feedback explicitly says truncated"
        in prompts["evaluator"]
    )
    assert "Never use XML/function_calls syntax" in prompts["evaluator"]


def test_planner_prose_recovery_names_only_its_registered_tool(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("planner", 1): [_reply("I will describe the plan."), _plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    recovery = str(builder.clients[0].requests[1][-1].content)
    assert report.status == "completed"
    assert "SubmitPlan" in recovery
    assert "Exec" not in recovery


def test_evaluator_completion_waits_for_required_submission(tmp_path: Path):
    builder = _RoleBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [
                _reply(_done()),
                _evaluation(_results(passed=True)),
            ],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    recovery = str(builder.clients[2].requests[1][-1].content)
    assert report.status == "completed"
    assert "SubmitEvaluation" in recovery
    assert "successfully" in recovery


def test_triad_submit_plan_loser_does_not_claim_or_poison_winner_state(tmp_path: Path):
    collaboration_id = "9" * 32
    ready = threading.Barrier(2)
    winner_committed = threading.Event()
    loser_finished = threading.Event()
    winner_builder = _ConcurrentPlannerBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        },
        winner=True,
        ready=ready,
        winner_committed=winner_committed,
        loser_finished=loser_finished,
    )
    loser_builder = _ConcurrentPlannerBuilder(
        {("planner", 1): [_plan(_items()), _reply(_done()), _reply(_done())]},
        winner=False,
        ready=ready,
        winner_committed=winner_committed,
        loser_finished=loser_finished,
    )
    winner = _runner(
        tmp_path,
        winner_builder,
        collaboration_id=collaboration_id,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    )
    loser = _reopened_runner(
        tmp_path,
        loser_builder,
        collaboration_id=collaboration_id,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    )
    reports = {}

    def run_loser() -> None:
        reports["loser"] = loser.run("create PRIVATE_GOAL artifact")
        loser_finished.set()

    winner_thread = threading.Thread(
        target=lambda: reports.setdefault("winner", winner.run("create PRIVATE_GOAL artifact"))
    )
    loser_thread = threading.Thread(target=run_loser)
    winner_thread.start()
    loser_thread.start()
    winner_thread.join(timeout=5)
    loser_thread.join(timeout=5)

    assert not winner_thread.is_alive()
    assert not loser_thread.is_alive()
    assert reports["loser"].stop_reason == "state_failure"
    assert reports["winner"].status == "completed"
    persisted = winner._store.load(collaboration_id)
    assert persisted.status == "completed"
    assert (persisted.generator_attempts, persisted.evaluator_attempts) == (1, 1)


def test_reopened_triad_waiting_for_confirmation_does_not_rerun_planner(tmp_path: Path):
    collaboration_id = "1" * 32
    _persisted_triad_state(tmp_path, phase="needs_confirmation", collaboration_id=collaboration_id)
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )
    runner = _reopened_runner(
        tmp_path,
        builder,
        collaboration_id=collaboration_id,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    )

    report = runner.run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert [call[0] for call in builder.calls] == ["generator", "evaluator"]


def test_reopened_confirmed_triad_starts_at_generator(tmp_path: Path):
    collaboration_id = "2" * 32
    _persisted_triad_state(tmp_path, phase="generator", collaboration_id=collaboration_id)
    builder = _RoleBuilder(
        {
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )
    runner = _reopened_runner(tmp_path, builder, collaboration_id=collaboration_id)

    report = runner.run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert [call[0] for call in builder.calls] == ["generator", "evaluator"]
    assert (report.generator_attempts, report.evaluator_attempts) == (1, 1)


def test_reopened_triad_at_evaluator_does_not_repeat_generator(tmp_path: Path):
    collaboration_id = "3" * 32
    _persisted_triad_state(
        tmp_path,
        phase="evaluator",
        collaboration_id=collaboration_id,
        generator_attempts=1,
    )
    builder = _RoleBuilder({("evaluator", 1): [_evaluation(_results(passed=True))]})
    runner = _reopened_runner(tmp_path, builder, collaboration_id=collaboration_id)

    report = runner.run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert [call[0] for call in builder.calls] == ["evaluator"]
    assert (report.generator_attempts, report.evaluator_attempts) == (1, 1)


def test_reopened_terminal_triad_returns_stable_report_without_roles(tmp_path: Path):
    collaboration_id = "4" * 32
    builder = _RoleBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )
    original = _runner(
        tmp_path,
        builder,
        collaboration_id=collaboration_id,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    )
    first_report = original.run("create PRIVATE_GOAL artifact")
    original.close()
    resumed_builder = _RoleBuilder({})
    resumed = _reopened_runner(tmp_path, resumed_builder, collaboration_id=collaboration_id)

    second_report = resumed.run("create PRIVATE_GOAL artifact")

    assert second_report == first_report
    assert resumed_builder.calls == []


@pytest.mark.parametrize("tamper", ["delete", "reorder", "change", "digest"])
def test_reopened_triad_keeps_persisted_plan_frozen(tmp_path: Path, tamper: str):
    collaboration_id = "5" * 32
    _persisted_triad_state(tmp_path, phase="generator", collaboration_id=collaboration_id)
    state_path = tmp_path / ".forgeagent" / "collaborations" / f"{collaboration_id}.json"

    class _TamperingBuilder(_RoleBuilder):
        def __call__(self, role, attempt, registry, system_prompt):
            task = super().__call__(role, attempt, registry, system_prompt)
            original = task.run

            def run(goal, *, cancel_event=None):
                outcome = original(goal, cancel_event=cancel_event)
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                if tamper == "delete":
                    payload["plan"] = payload["plan"][:1]
                elif tamper == "reorder":
                    payload["plan"] = list(reversed(payload["plan"]))
                elif tamper == "change":
                    payload["plan"][0]["acceptance"] = "A lower standard"
                changed = tuple(AcceptanceItem.model_validate(item) for item in payload["plan"])
                payload["plan_digest"] = "f" * 64 if tamper == "digest" else plan_digest(changed)
                state_path.write_text(json.dumps(payload), encoding="utf-8")
                return outcome

            task.run = run
            return task

    builder = _TamperingBuilder({("generator", 1): [_candidate()]})
    runner = _reopened_runner(tmp_path, builder, collaboration_id=collaboration_id)

    report = runner.run("create PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "state_failure"
    assert [call[0] for call in builder.calls] == ["generator"]


def test_planner_corrects_duplicate_and_how_only_submissions(tmp_path: Path):
    duplicate = [_items()[0], _items()[0]]
    how_only = [
        {
            "id": "artifact",
            "behavior": "The requested artifact is present",
            "acceptance": "Use library xyz",
        }
    ]
    builder = _RoleBuilder(
        {
            ("planner", 1): [
                _plan(duplicate),
                _plan(how_only),
                _plan(_items()),
                _reply(_done()),
            ],
            ("generator", 1): [_candidate()],
            ("evaluator", 1): [_evaluation(_results(passed=True))],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "completed"
    assert report.rounds == 5


def test_planner_tool_commit_completes_without_standalone_status(tmp_path: Path):
    builder = _RoleBuilder(
        {("planner", 1): [_plan(_items(), completed=True), _reply("plain"), _reply("still plain")]}
    )

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("deny"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "stopped"
    assert report.stop_reason == "needs_confirmation"
    assert report.plan_item_count == 2
    assert [call[0] for call in builder.calls] == ["planner"]


def test_loop_policy_keeps_recoverable_planner_failure_active(tmp_path: Path):
    builder = _RoleBuilder({("planner", 1): [_reply("plain"), _reply("still plain")]})
    runner = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
        recover_role_failures=True,
    )

    report = runner.run("create PRIVATE_GOAL artifact")
    persisted = runner._store.load(report.collaboration_id)

    assert report.status == "failed"
    assert report.stop_reason == "role_failed"
    assert persisted.status == "active"
    assert persisted.phase == "planning"
    assert persisted.rounds == 2


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([_reply(_done()), _reply(_done())], "invalid_role_submission"),
        ([ClientError(message="bad key", kind="auth", attempts=1)], "unrecoverable_failure"),
        ([_reply("cannot"), _reply("still cannot")], "invalid_role_submission"),
    ],
)
def test_triad_planner_failures_have_stable_reasons(tmp_path: Path, script, reason):
    builder = _RoleBuilder({("planner", 1): script})

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == reason
    assert [call[0] for call in builder.calls] == ["planner"]
    assert all(client.closed for client in builder.clients)


def test_triad_planner_configuration_failure_is_unrecoverable(tmp_path: Path):
    class _BrokenBuilder:
        calls = []

        def __call__(self, role, attempt, registry, system_prompt):
            self.calls.append(role)
            raise CollaborationRoleConfigurationError("PRIVATE_PROVIDER_TOKEN")

    builder = _BrokenBuilder()
    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "unrecoverable_failure"
    assert "PRIVATE_PROVIDER_TOKEN" not in repr(report)


def test_triad_cancel_after_planner_wins_before_confirmation(tmp_path: Path):
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

    confirmer_calls: list[str] = []
    builder = _CancellingBuilder({("planner", 1): [_plan(_items())]})

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=lambda summary: confirmer_calls.append(summary) is None,
    ).run("create PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    assert confirmer_calls == []


def test_triad_confirmation_exception_is_role_failure_not_denial(tmp_path: Path):
    sink = _AuditSink()
    builder = _RoleBuilder({("planner", 1): [_plan(_items())]})

    def broken_confirmer(summary: str) -> bool:
        raise RuntimeError(f"PRIVATE_CONFIRMATION_FAILURE:{summary}")

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=broken_confirmer,
        audit_sink=sink,
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "role_failed"
    plan_results = [
        event.result_status for event in sink.events if event.event_type == "collaboration.plan"
    ]
    assert plan_results == ["submitted"]
    assert "PRIVATE_CONFIRMATION_FAILURE" not in repr(sink.events)


@pytest.mark.parametrize("decision", [True, False])
def test_triad_cancel_during_confirmation_wins_without_decision_audit(
    tmp_path: Path, decision: bool
):
    cancel = threading.Event()
    sink = _AuditSink()
    builder = _RoleBuilder({("planner", 1): [_plan(_items())]})

    def cancelling_confirmer(summary: str) -> bool:
        assert "PRIVATE_GOAL" not in summary
        cancel.set()
        return decision

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=cancelling_confirmer,
        audit_sink=sink,
    ).run("create PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    plan_results = [
        event.result_status for event in sink.events if event.event_type == "collaboration.plan"
    ]
    assert plan_results == ["submitted"]


def test_triad_cancel_wins_over_planner_construction_failure(tmp_path: Path):
    cancel = threading.Event()

    class _CancellingBrokenBuilder:
        def __call__(self, role, attempt, registry, system_prompt):
            cancel.set()
            raise RuntimeError("PRIVATE_CONSTRUCTION_FAILURE")

    report = _runner(
        tmp_path,
        _CancellingBrokenBuilder(),
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    assert "PRIVATE_CONSTRUCTION_FAILURE" not in repr(report)


@pytest.mark.parametrize("cancelled_role", ["generator", "evaluator"])
def test_triad_cancel_wins_over_later_role_construction_failure(
    tmp_path: Path, cancelled_role: str
):
    cancel = threading.Event()
    scripts = {
        ("planner", 1): [_plan(_items())],
        ("generator", 1): [_candidate()],
    }

    class _CancellingBuilder(_RoleBuilder):
        def __call__(self, role, attempt, registry, system_prompt):
            if role == cancelled_role:
                cancel.set()
                raise RuntimeError("PRIVATE_CONSTRUCTION_FAILURE")
            return super().__call__(role, attempt, registry, system_prompt)

    report = _runner(
        tmp_path,
        _CancellingBuilder(scripts),
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact", cancel_event=cancel)

    assert report.status == "cancelled"
    assert report.stop_reason == "cancelled"
    assert "PRIVATE_CONSTRUCTION_FAILURE" not in repr(report)


@pytest.mark.parametrize("tamper", ["delete", "reorder", "change", "digest"])
def test_triad_plan_change_after_confirmation_fails_closed(tmp_path: Path, tamper: str):
    collaboration_id = "d" * 32
    state_path = tmp_path / ".forgeagent" / "collaborations" / f"{collaboration_id}.json"

    class _TamperingBuilder(_RoleBuilder):
        def __call__(self, role, attempt, registry, system_prompt):
            task = super().__call__(role, attempt, registry, system_prompt)
            if role == "generator":
                original = task.run

                def run(goal, *, cancel_event=None):
                    outcome = original(goal, cancel_event=cancel_event)
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    from forgeagent.collaboration import AcceptanceItem, plan_digest

                    if tamper == "delete":
                        payload["plan"] = payload["plan"][:1]
                    elif tamper == "reorder":
                        payload["plan"] = list(reversed(payload["plan"]))
                    elif tamper == "change":
                        payload["plan"][0]["acceptance"] = "A lower standard"
                    changed = tuple(AcceptanceItem.model_validate(item) for item in payload["plan"])
                    payload["plan_digest"] = (
                        "f" * 64 if tamper == "digest" else plan_digest(changed)
                    )
                    state_path.write_text(json.dumps(payload), encoding="utf-8")
                    return outcome

                task.run = run
            return task

    builder = _TamperingBuilder(
        {
            ("planner", 1): [_plan(_items())],
            ("generator", 1): [_candidate()],
        }
    )

    report = _runner(
        tmp_path,
        builder,
        collaboration_id=collaboration_id,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
    ).run("create PRIVATE_GOAL artifact")

    assert report.status == "failed"
    assert report.stop_reason == "state_failure"
    assert [call[0] for call in builder.calls] == ["planner", "generator"]


def test_triad_plan_audit_never_contains_goal_or_plan_text(tmp_path: Path):
    sink = _AuditSink()
    private_items = [
        {
            "id": "artifact",
            "behavior": "PRIVATE_PLAN_BEHAVIOR",
            "acceptance": "PRIVATE_PLAN_ACCEPTANCE",
        }
    ]
    builder = _RoleBuilder({("planner", 1): [_plan(private_items)]})

    report = _runner(
        tmp_path,
        builder,
        plan_confirmer=headless_plan_confirmer("deny"),
        audit_sink=sink,
    ).run("create PRIVATE_GOAL artifact")

    assert report.stop_reason == "needs_confirmation"
    events = [event for event in sink.events if event.event_type.startswith("collaboration.")]
    rendered = repr(events)
    assert "PRIVATE_GOAL" not in rendered
    assert "PRIVATE_PLAN_BEHAVIOR" not in rendered
    assert "PRIVATE_PLAN_ACCEPTANCE" not in rendered
    plan_events = [event for event in events if event.event_type == "collaboration.plan"]
    assert [event.result_status for event in plan_events] == ["submitted", "denied"]
    assert all(
        set(event.parameters)
        <= {"mode", "collaboration_id", "plan_item_count", "digest_prefix", "revision"}
        for event in plan_events
    )


def test_headless_plan_confirmer_rejects_unknown_policy():
    with pytest.raises(ValueError, match="policy"):
        headless_plan_confirmer("approve")
