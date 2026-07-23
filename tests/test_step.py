"""Unit tests for the Step loop (M3-3).

Uses MockClient to script LLM responses (no key, no network). Responses follow the
text-protocol markup from docs/text-protocol-spec.md.
"""

import json
import threading

import pytest

from forgeagent.audit import AuditEvent
from forgeagent.client import MockClient, ProviderAttempt
from forgeagent.context import ContextBudgetExceeded, ContextConfig, estimate_text_tokens
from forgeagent.executor import TrustedBackend
from forgeagent.models import (
    AssistantMessage,
    ClientError,
    Message,
    NativeToolCall,
    Role,
    StreamEvent,
    StreamEventKind,
    TokenUsage,
)
from forgeagent.protocol import EditArgs, FileReadArgs, MCPArgs, ToolCall
from forgeagent.runtime import Runtime
from forgeagent.skills import SkillDefinition, SkillRegistry
from forgeagent.step import RoundResult, Step, Termination, _apply_edit
from forgeagent.tools import ToolOutcome


class _RecordingAuditSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def _reply(text: str, stop_reason: str = "end_turn", tool_calls=None) -> AssistantMessage:
    return AssistantMessage(
        content=text, usage=TokenUsage(), stop_reason=stop_reason, tool_calls=tool_calls or []
    )


def _native_call(call_id: str, tool_name: str, **arguments) -> NativeToolCall:
    return NativeToolCall(id=call_id, name=tool_name, arguments=json.dumps(arguments))


def _step(script) -> Step:
    return Step(MockClient(script=script), TrustedBackend(), Runtime(), max_rounds=5)


def _user(text="go"):
    return [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content=text),
    ]


def _tool_call(tool_name: str, **arguments) -> str:
    import json

    return f"<!-- ToolCall: {json.dumps({'name': tool_name, 'arguments': arguments})} -->"


def _exec_call(code: str, name: str | None = None) -> str:
    args = {"code": code}
    if name:
        args["name"] = name
    return _tool_call("Exec", **args)


def _done(confidence=0.9) -> str:
    return f"---\ntask_status:\n  completed: true\n  confidence: {confidence}\n---\n"


def _registry_with_skill(marker: str = "SKILL-BODY-UNIQUE") -> SkillRegistry:
    return SkillRegistry(
        {
            "review-python": SkillDefinition(
                name="review-python",
                trigger="Use when reviewing Python.",
                steps=f"1. {marker}",
                failure_branches="Stop when the diff is unavailable.",
                completion_criteria="All findings are recorded.",
                source="user",
            )
        }
    )


class _RecordingPolicy:
    def __init__(self):
        self.views: list[list[Message]] = []

    def request_view(self, messages):
        view = list(messages)
        self.views.append(view)
        return view


class _OverBudgetPolicy:
    def __init__(self, detail="context does not fit"):
        self.detail = detail
        self.calls = 0

    def request_view(self, messages):
        self.calls += 1
        raise ContextBudgetExceeded(self.detail)


class _FirstViewThenOverBudgetPolicy:
    def __init__(self, detail="context does not fit"):
        self.detail = detail
        self.calls = 0

    def request_view(self, messages):
        self.calls += 1
        if self.calls == 1:
            return list(messages)
        raise ContextBudgetExceeded(self.detail)


# --- loop control ------------------------------------------------------------


def test_step_registers_skill_snapshot_for_parse_and_bounded_feedback():
    step = Step(
        MockClient(script=[]),
        TrustedBackend(),
        Runtime(),
        skills=_registry_with_skill(),
    )

    round_result = step._handle_reply(_reply(_tool_call("Skill", name="review-python")))

    assert round_result.parse_errors == []
    assert "SKILL-BODY-UNIQUE" in step._render_feedback(round_result)


def test_step_applies_policy_before_every_complete_call():
    client = _RecordingClient(
        script=[_reply(_exec_call("print('ok')")), _reply(_done())]
    )
    policy = _RecordingPolicy()

    Step(client, TrustedBackend(), Runtime(), context_policy=policy).run(_user())

    assert len(policy.views) == 2
    assert client.seen_messages == policy.views


def test_step_applies_policy_before_stream_call():
    done = _reply(_done())

    class _StreamRecordingClient(MockClient):
        def __init__(self):
            super().__init__(script=[])
            self.requests: list[list[Message]] = []

        def stream(self, messages, params=None):
            self.requests.append(list(messages))
            yield StreamEvent(kind=StreamEventKind.DONE, message=done)

    client = _StreamRecordingClient()
    policy = _RecordingPolicy()
    Step(
        client,
        TrustedBackend(),
        Runtime(),
        context_policy=policy,
        on_stream_text=lambda text, kind: None,
    ).run(_user())

    assert client.requests == policy.views


def test_step_cancellation_wins_before_context_policy():
    event = threading.Event()
    event.set()
    policy = _OverBudgetPolicy()

    rounds = Step(
        MockClient(script=[_reply(_done())]),
        TrustedBackend(),
        Runtime(),
        context_policy=policy,
        cancel_event=event,
    ).run(_user())

    assert policy.calls == 0
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_oversized_context_fails_before_provider_attempt_audit():
    sink = _RecordingAuditSink()
    client = MockClient(script=[_reply(_done())])

    rounds = Step(
        client,
        TrustedBackend(),
        Runtime(),
        context_policy=_OverBudgetPolicy(),
        audit_sink=sink,
    ).run(_user())

    assert rounds[-1].stopped_reason == Termination.FAILED
    assert client.calls_made == 0
    assert not any(event.event_type == "llm.attempt" for event in sink.events)


def test_oversized_context_detail_is_bounded():
    rounds = Step(
        MockClient(script=[_reply(_done())]),
        TrustedBackend(),
        Runtime(),
        context_policy=_OverBudgetPolicy("x" * 500),
    ).run(_user())

    assert rounds[-1].stopped_reason == Termination.FAILED
    assert rounds[-1].stopped_detail == "x" * 160


def test_latest_complete_round_over_budget_stops_before_second_provider_attempt():
    class _ProviderAttemptClient(MockClient):
        def complete(self, messages, params=None):
            self._notify_attempt(ProviderAttempt(attempt=1, status="started"))
            result = super().complete(messages, params)
            self._notify_attempt(ProviderAttempt(attempt=1, status="success"))
            return result

    sink = _RecordingAuditSink()
    client = _ProviderAttemptClient(script=[_reply(_exec_call("print('ok')"))])
    policy = _FirstViewThenOverBudgetPolicy("x" * 500)

    rounds = Step(
        client,
        TrustedBackend(),
        Runtime(),
        context_policy=policy,
        audit_sink=sink,
    ).run(_user())

    assert rounds[0].outcomes[0].success is True
    assert rounds[-1].stopped_reason == Termination.FAILED
    assert len(rounds[-1].stopped_detail) <= 160
    assert client.calls_made == 1
    assert policy.calls == 2
    logical_events = [event for event in sink.events if event.event_type != "llm.provider_attempt"]
    provider_events = [event for event in sink.events if event.event_type == "llm.provider_attempt"]
    assert [
        (event.event_type, event.attempt, event.result_status)
        for event in logical_events
        if event.event_type.startswith("llm.")
    ] == [
        ("llm.attempt", 1, "started"),
        ("llm.outcome", 1, "success"),
    ]
    assert [(event.attempt, event.result_status) for event in provider_events] == [
        (1, "started"),
        (1, "success"),
    ]


def test_step_cancel_event_stops_before_next_model_call():
    event = threading.Event()
    event.set()
    client = MockClient(script=[_reply(_done())])
    step = Step(client, TrustedBackend(), Runtime(), cancel_event=event)

    rounds = step.run(_user())

    assert client.calls_made == 0
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_step_audits_each_llm_attempt_and_outcome_without_prompt_content():
    sink = _RecordingAuditSink()
    step = Step(
        MockClient(script=[_reply(_done())]),
        TrustedBackend(),
        Runtime(),
        audit_sink=sink,
        task_id="task-audit-1",
    )

    step.run(_user("private prompt text"))

    assert [event.event_type for event in sink.events] == ["llm.attempt", "llm.outcome"]
    assert [event.attempt for event in sink.events] == [1, 1]
    assert len({event.operation_id for event in sink.events}) == 1
    assert all(event.task_id == "task-audit-1" for event in sink.events)
    assert "private prompt text" not in repr([event.parameters for event in sink.events])


def test_step_correlates_provider_attempts_with_logical_llm_operation():
    sink = _RecordingAuditSink()

    class _AttemptClient(MockClient):
        def complete(self, messages, params=None):
            self._notify_attempt(ProviderAttempt(attempt=1, status="started"))
            self._notify_attempt(ProviderAttempt(attempt=1, status="error", error_kind="network"))
            self._notify_attempt(ProviderAttempt(attempt=2, status="started"))
            result = super().complete(messages, params)
            self._notify_attempt(ProviderAttempt(attempt=2, status="success"))
            return result

    step = Step(
        _AttemptClient(script=[_reply(_done())]),
        TrustedBackend(),
        Runtime(),
        audit_sink=sink,
    )

    step.run(_user())

    provider = [event for event in sink.events if event.event_type == "llm.provider_attempt"]
    logical = [event for event in sink.events if event.event_type != "llm.provider_attempt"]
    assert [event.result_status for event in provider] == [
        "started",
        "error",
        "started",
        "success",
    ]
    assert {event.operation_id for event in provider + logical} == {logical[0].operation_id}


def test_step_scopes_provider_attempt_observer_to_each_audited_run():
    class _AttemptClient(MockClient):
        def complete(self, messages, params=None):
            self._notify_attempt(ProviderAttempt(attempt=1, status="started"))
            result = super().complete(messages, params)
            self._notify_attempt(ProviderAttempt(attempt=1, status="success"))
            return result

    client = _AttemptClient(script=[_reply(_done()), _reply(_done()), _reply(_done())])
    first_sink = _RecordingAuditSink()
    second_sink = _RecordingAuditSink()

    Step(
        client,
        TrustedBackend(),
        Runtime(),
        audit_sink=first_sink,
        task_id="first-task",
    ).run(_user())
    Step(client, TrustedBackend(), Runtime()).run(_user())
    Step(
        client,
        TrustedBackend(),
        Runtime(),
        audit_sink=second_sink,
        task_id="second-task",
    ).run(_user())

    first_provider = [
        event for event in first_sink.events if event.event_type == "llm.provider_attempt"
    ]
    second_provider = [
        event for event in second_sink.events if event.event_type == "llm.provider_attempt"
    ]
    assert [event.result_status for event in first_provider] == ["started", "success"]
    assert [event.result_status for event in second_provider] == ["started", "success"]
    assert {event.task_id for event in first_provider} == {"first-task"}
    assert {event.task_id for event in second_provider} == {"second-task"}


def test_step_restores_previous_attempt_observer_when_run_raises():
    sink = _RecordingAuditSink()
    observed: list[ProviderAttempt] = []
    control = RuntimeError("model failure")

    class _RaisingAttemptClient(MockClient):
        def complete(self, messages, params=None):
            self._notify_attempt(ProviderAttempt(attempt=1, status="started"))
            raise control

    client = _RaisingAttemptClient(script=[])
    client.set_attempt_observer(observed.append)
    step = Step(client, TrustedBackend(), Runtime(), audit_sink=sink)

    with pytest.raises(RuntimeError, match="model failure"):
        step.run(_user())
    audited_count = len(sink.events)
    client._notify_attempt(ProviderAttempt(attempt=2, status="success"))

    assert [(event.attempt, event.status) for event in observed] == [
        (1, "started"),
        (2, "success"),
    ]
    assert len(sink.events) == audited_count


def test_step_correlates_confirmation_and_tool_operation_with_tool_call_id():
    sink = _RecordingAuditSink()

    class _MCP:
        def public_tool_label(self, server, tool):
            return f"{server}:{tool}"

        def is_auto_approved(self, server, tool):
            return False

        def call_tool(self, server, tool, arguments):
            return {"ok": True, "text": "done"}

    step = Step(
        MockClient(script=[]),
        TrustedBackend(),
        Runtime(),
        mcp=_MCP(),
        confirmer=lambda args: True,
        audit_sink=sink,
    )

    outcome = step._dispatch(
        ToolCall(
            id="tool-call-approved",
            name="MCP",
            arguments=MCPArgs(server="gh", tool="create_issue"),
        )
    )

    assert outcome.success is True
    assert [event.event_type for event in sink.events] == [
        "confirmation.decision",
        "tool.operation",
    ]
    assert {event.operation_id for event in sink.events} == {"tool-call-approved"}
    assert sink.events[0].result_status == "approved"


def test_step_audits_fixed_error_outcome_when_complete_raises():
    sink = _RecordingAuditSink()
    control = RuntimeError("private /Users/admin/error detail")

    class _RaisingClient(MockClient):
        def complete(self, messages, params=None):
            raise control

    step = Step(_RaisingClient(script=[]), TrustedBackend(), Runtime(), audit_sink=sink)

    with pytest.raises(RuntimeError) as raised:
        step.run(_user())

    assert raised.value is control
    assert [event.result_status for event in sink.events] == ["started", "error"]
    assert sink.events[-1].parameters == {"model": "mock"}


def test_step_audits_fixed_interrupted_outcome_when_stream_callback_raises():
    sink = _RecordingAuditSink()
    control = RuntimeError("private callback detail")

    class _StreamingClient(MockClient):
        def stream(self, messages, params=None):
            yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, text="partial")

    def callback(text, kind):
        raise control

    step = Step(
        _StreamingClient(script=[]),
        TrustedBackend(),
        Runtime(),
        on_stream_text=callback,
        audit_sink=sink,
    )

    with pytest.raises(RuntimeError) as raised:
        step.run(_user())

    assert raised.value is control
    assert [event.result_status for event in sink.events] == ["started", "interrupted"]
    assert sink.events[-1].parameters == {"model": "mock"}


def test_step_audits_one_logical_tool_operation():
    sink = _RecordingAuditSink()
    step = Step(
        MockClient(script=[_reply(_exec_call("print('private code')")), _reply(_done())]),
        TrustedBackend(),
        Runtime(),
        audit_sink=sink,
        task_id="task-audit-2",
    )

    step.run(_user())

    tool_events = [event for event in sink.events if event.event_type == "tool.operation"]
    assert len(tool_events) == 1
    assert tool_events[0].parameters == {"tool": "Exec"}
    assert tool_events[0].result_status == "success"
    assert "private code" not in repr(tool_events[0].parameters)


def test_step_audits_missing_tool_handler_as_failed_operation():
    sink = _RecordingAuditSink()
    step = Step(
        MockClient(script=[]),
        TrustedBackend(),
        Runtime(),
        audit_sink=sink,
        task_id="task-audit-missing",
    )

    outcome = step._dispatch(
        ToolCall(id="missing-call", name="Missing", arguments=FileReadArgs(path="."))
    )

    assert outcome.success is False
    assert len(sink.events) == 1
    assert sink.events[0].event_type == "tool.operation"
    assert sink.events[0].result_status == "failed"


def test_step_cancel_event_wins_before_completed_result_is_published():
    event = threading.Event()

    class _CancellingClient(MockClient):
        def complete(self, messages, params=None):
            reply = super().complete(messages, params)
            event.set()
            return reply

    client = _CancellingClient(script=[_reply(_done())])
    step = Step(client, TrustedBackend(), Runtime(), cancel_event=event)

    rounds = step.run(_user())

    assert client.calls_made == 1
    assert rounds[-1].completed is False
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_step_cancel_event_is_checked_after_tool_execution():
    event = threading.Event()

    class _CancellingBackend(TrustedBackend):
        def execute(self, code, runtime):
            result = super().execute(code, runtime)
            event.set()
            return result

    client = MockClient(script=[_reply(_exec_call("print('done')")), _reply(_done())])
    step = Step(client, _CancellingBackend(secret_values=set()), Runtime(), cancel_event=event)

    rounds = step.run(_user())

    assert client.calls_made == 1
    assert rounds[-1].outcomes[0].success is True
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_step_cancel_event_stops_remaining_tools_in_same_reply():
    event = threading.Event()

    class _CancellingBackend(TrustedBackend):
        def __init__(self):
            super().__init__(secret_values=set())
            self.executed: list[str] = []

        def execute(self, code, runtime):
            self.executed.append(code)
            result = super().execute(code, runtime)
            event.set()
            return result

    backend = _CancellingBackend()
    reply = _exec_call("print('first')", name="first") + _exec_call(
        "print('second')", name="second"
    )
    step = Step(
        MockClient(script=[_reply(reply)]),
        backend,
        Runtime(),
        cancel_event=event,
    )

    rounds = step.run(_user())

    assert backend.executed == ["print('first')"]
    assert len(rounds[-1].outcomes) == 1
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_step_cancel_event_wins_before_client_error_is_published():
    event = threading.Event()

    class _CancellingClient(MockClient):
        def complete(self, messages, params=None):
            result = super().complete(messages, params)
            event.set()
            return result

    client = _CancellingClient(script=[ClientError(message="offline", kind="network", attempts=1)])
    step = Step(client, TrustedBackend(), Runtime(), cancel_event=event)

    rounds = step.run(_user())

    assert rounds[-1].text == ""
    assert rounds[-1].stopped_reason == Termination.CANCELLED


def test_prose_answer_is_nudged_once_then_accepted():
    # A prose answer with no tool activity is nudged toward the protocol once; a second
    # prose answer is accepted as an (unverified) soft completion, not a failure.
    step = _step([_reply("the answer is 42"), _reply("still prose, the answer is 42")])
    rounds = step.run(_user())
    assert len(rounds) == 2
    assert rounds[-1].stopped_reason == "answered_in_prose"
    assert rounds[-1].body == "still prose, the answer is 42"


def test_prose_nudge_lets_model_recover_via_protocol():
    # After the nudge, a model that switches to the protocol completes normally.
    step = _step([_reply("let me just tell you: 42"), _reply(_done())])
    rounds = step.run(_user())
    assert len(rounds) == 2
    assert rounds[-1].completed is True
    assert rounds[-1].stopped_reason == "completed"


def test_empty_response_ends_without_nudge():
    step = _step([_reply("")])
    rounds = step.run(_user())
    assert len(rounds) == 1
    assert rounds[0].stopped_reason == "empty_response"


def test_truncated_response_is_terminal():
    step = _step([_reply("partial ans", stop_reason="length")])
    rounds = step.run(_user())
    assert len(rounds) == 1
    assert rounds[0].stopped_reason == "truncated"


def test_declared_refusal_via_front_matter():
    fm = "---\ntask_status:\n  completed: false\n  status: refused\n---\nI won't do that"
    rounds = _step([_reply(fm)]).run(_user())
    assert rounds[0].completed is False
    assert rounds[0].stopped_reason == "refused"


def test_declared_need_info_via_front_matter():
    fm = "---\ntask_status:\n  completed: false\n  status: need_info\n---\nwhich file?"
    rounds = _step([_reply(fm)]).run(_user())
    assert rounds[0].stopped_reason == "needs_info"


@pytest.mark.parametrize(
    ("same_round_suffix", "expected_record_type"),
    [
        (_exec_call("print('hi')"), "outcome"),
        ('<!-- ToolCall: {"name": "Exec", "arguments": {"code": "x",}} -->', "parse_error"),
    ],
    ids=["tool", "parse_error"],
)
def test_need_info_precedes_same_round_feedback_and_stops_once(
    same_round_suffix, expected_record_type
):
    response = (
        "---\ntask_status:\n  completed: false\n  status: need_info\n---\n" + same_round_suffix
    )
    client = MockClient(script=[_reply(response), _reply(_done())])

    rounds = Step(client, TrustedBackend(), Runtime(), max_rounds=5).run(_user())

    assert client.calls_made == 1
    assert len(rounds) == 1
    assert rounds[0].stopped_reason == "needs_info"
    if expected_record_type == "outcome":
        assert len(rounds[0].outcomes) == 1
        assert rounds[0].outcomes[0].success is True
        assert rounds[0].parse_errors == []
    else:
        assert rounds[0].parse_errors
        assert rounds[0].outcomes == []


def test_code_executes_and_feedback_fed_back():
    # Round 1 runs code (prints), producing feedback; round 2 is scripted to complete.
    step = _step([_reply(_exec_call("print('hi')")), _reply(_done())])
    rounds = step.run(_user())
    assert len(rounds) == 2
    assert rounds[0].outcomes[0].success is True
    assert "hi" in rounds[0].outcomes[0].exec_result.stdout
    assert rounds[1].completed is True


def test_error_feedback_drives_next_round():
    # Round 1 code fails; feedback carries the error; round 2 completes.
    step = _step([_reply(_exec_call("1/0")), _reply(_done())])
    rounds = step.run(_user())
    assert rounds[0].outcomes[0].success is False
    assert "ZeroDivisionError" in rounds[0].outcomes[0].detail
    assert len(rounds) == 2  # error produced feedback -> a second round happened


def test_completed_status_waits_for_successful_tool_feedback():
    step = _step([_reply(_done() + _exec_call("print('hi')")), _reply(_done())])

    rounds = step.run(_user())

    assert len(rounds) == 2
    assert rounds[0].completed is False
    assert rounds[0].outcomes[0].success is True
    assert rounds[1].stopped_reason == "completed"


def test_completed_status_waits_for_failed_tool_feedback():
    step = _step([_reply(_done() + _exec_call("1/0")), _reply(_done())])

    rounds = step.run(_user())

    assert len(rounds) == 2
    assert rounds[0].completed is False
    assert rounds[0].outcomes[0].success is False
    assert rounds[1].stopped_reason == "completed"


def test_completed_status_waits_for_parse_error_feedback():
    malformed_call = '<!-- ToolCall: {"name": "Exec", "arguments": {"code": "x",}} -->'
    step = _step([_reply(_done() + malformed_call), _reply(_done())])

    rounds = step.run(_user())

    assert len(rounds) == 2
    assert rounds[0].completed is False
    assert rounds[0].parse_errors
    assert rounds[1].stopped_reason == "completed"


def test_refused_status_stops_after_recording_successful_tool_outcome():
    client = MockClient(
        script=[
            _reply(
                "---\ntask_status:\n  completed: false\n  status: refused\n---\n"
                + _exec_call("print('hi')")
            )
        ]
    )
    rounds = Step(client, TrustedBackend(), Runtime(), max_rounds=5).run(_user())

    assert client.calls_made == 1
    assert len(rounds) == 1
    assert rounds[0].outcomes[0].success is True
    assert rounds[0].stopped_reason == "refused"


def test_failed_status_stops_after_recording_parse_error():
    malformed_call = '<!-- ToolCall: {"name": "Exec", "arguments": {"code": "x",}} -->'
    client = MockClient(
        script=[
            _reply(
                "---\ntask_status:\n  completed: false\n  status: failed\n---\n" + malformed_call
            )
        ]
    )
    rounds = Step(client, TrustedBackend(), Runtime(), max_rounds=5).run(_user())

    assert client.calls_made == 1
    assert len(rounds) == 1
    assert rounds[0].parse_errors
    assert rounds[0].stopped_reason == "failed"


def test_long_exec_feedback_has_masked_continuation_in_next_provider_request(monkeypatch):
    # A block that prints a lot must not blow up the next round's context; feedback
    # keeps only the tail plus a marker noting how much was cut.
    import forgeagent.step as step_module
    import forgeagent.tools as tools_module

    secret = "continuation-secret"
    monkeypatch.setattr(step_module, "sensitive_env_values", lambda: {secret})
    monkeypatch.setattr(
        tools_module,
        "_EXEC_CONTINUATION",
        f"请缩小输出范围，或将工作分片执行后重试 {secret}",
    )
    client = _RecordingClient(
        script=[_reply(_exec_call("print('x' * 10_000)")), _reply(_done())]
    )
    step = Step(
        client,
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        context_config=ContextConfig(
            round_feedback_max_tokens=500,
            tool_result_max_tokens=200,
        ),
    )
    step.run(_user())
    feedback = client.seen_messages[1][-1].content
    assert isinstance(feedback, str)
    assert "[truncated:" in feedback
    assert "[continuation] 请缩小输出范围，或将工作分片执行后重试 ***REDACTED***" in feedback
    assert secret not in feedback
    assert len(feedback) < 10_000
    assert feedback.endswith("x" * 100)


def test_untruncated_exec_feedback_omits_continuation():
    client = _RecordingClient(script=[_reply(_exec_call("print('short')")), _reply(_done())])

    Step(client, TrustedBackend(), Runtime()).run(_user())

    feedback = client.seen_messages[1][-1].content
    assert isinstance(feedback, str)
    assert "short" in feedback
    assert "[truncated:" not in feedback
    assert "[continuation]" not in feedback


def test_feedback_metadata_overflow_keeps_outcomes_and_skips_next_provider_call(monkeypatch):
    reply = "".join(_exec_call("print('x' * 500)", name=f"block_{index}") for index in range(6))
    client = MockClient(script=[_reply(reply), _reply(_done())])
    sink = _RecordingAuditSink()
    step = Step(
        client,
        TrustedBackend(secret_values=set()),
        Runtime(),
        max_rounds=5,
        context_config=ContextConfig(
            round_feedback_max_tokens=20,
            tool_result_max_tokens=5,
        ),
        audit_sink=sink,
    )
    original_outcomes: list[ToolOutcome] = []
    render_feedback = Step._render_feedback

    def snapshot_then_render(self, round_result):
        original_outcomes.extend(
            outcome.model_copy(deep=True) for outcome in round_result.outcomes
        )
        return render_feedback(self, round_result)

    monkeypatch.setattr(Step, "_render_feedback", snapshot_then_render)

    rounds = step.run(_user())

    assert client.calls_made == 1
    assert len(rounds) == 1
    assert len(original_outcomes) == 6
    assert rounds[0].outcomes == original_outcomes
    assert rounds[0].stopped_reason == Termination.FAILED
    assert rounds[0].stopped_detail == "feedback metadata exceeds context budget"
    tool_events = [event for event in sink.events if event.event_type == "tool.operation"]
    assert len(tool_events) == 6


def test_step_appends_only_feedback_within_resolved_round_limit():
    client = _RecordingClient(script=[_reply(_exec_call("print('x' * 5000)")), _reply(_done())])
    config = ContextConfig(round_feedback_max_tokens=120, tool_result_max_tokens=40)

    rounds = Step(
        client,
        TrustedBackend(secret_values=set()),
        Runtime(),
        context_config=config,
    ).run(_user())

    assert len(rounds[0].outcomes[0].exec_result.stdout) == 5001
    feedback = client.seen_messages[1][-1].content
    assert isinstance(feedback, str)
    assert estimate_text_tokens(feedback) <= 120
    assert "truncated" in feedback


def test_webfetch_fixed_failure_detail_is_safe_in_step_feedback():
    secret_url = "https://secret-host.invalid/private?token=secret-value"
    feedback = _step([])._render_feedback(
        RoundResult(
            text="",
            outcomes=[
                ToolOutcome(tool="WebFetch", success=False, detail="WebFetch request failed")
            ],
        )
    )

    assert feedback == "[WebFetch None] FAILED: WebFetch request failed"
    assert secret_url not in feedback


def test_real_file_read_failure_has_fixed_detail_in_step_feedback(tmp_path):
    outside_path = tmp_path.parent / f"{tmp_path.name}-private" / "secret.txt"
    attempted_path = str(outside_path)
    outside_path.parent.mkdir()
    outside_path.write_text("do not disclose this file", encoding="utf-8")
    step = Step(
        MockClient([]),
        TrustedBackend(),
        Runtime(),
        tier="trusted",
        allowed_root=str(tmp_path),
    )
    outcome = step._dispatch(
        ToolCall(
            id="read-outside",
            name="FileRead",
            arguments=FileReadArgs(path=attempted_path),
        )
    )
    feedback = step._render_feedback(RoundResult(text="", outcomes=[outcome]))

    assert outcome.success is False
    assert feedback == "[FileRead None] FAILED: FileRead failed"
    assert attempted_path not in feedback


def test_max_rounds_stops():
    # Every round runs code that always produces feedback -> never completes.
    step = Step(
        MockClient(script=[_reply(_exec_call("print(1)")) for _ in range(10)]),
        TrustedBackend(),
        Runtime(),
        max_rounds=3,
    )
    rounds = step.run(_user())
    assert len(rounds) == 3
    assert rounds[-1].stopped_reason == "max_rounds"


def test_body_strips_front_matter_for_plain_text_answers():
    # A model can answer in prose without calling Exec; body must carry that answer
    # (front matter stripped) so callers can still show it.
    step = _step([_reply("---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\n60")])
    rounds = step.run(_user())
    assert rounds[0].body == "60"
    assert rounds[0].outcomes == []


def test_completion_via_front_matter_ends_immediately():
    step = _step([_reply(_done())])
    rounds = step.run(_user())
    assert len(rounds) == 1
    assert rounds[0].completed is True
    assert rounds[0].stopped_reason == "completed"


def test_refusal_ends_loop():
    step = _step([_reply("cannot help", stop_reason="refusal")])
    rounds = step.run(_user())
    assert rounds[0].completed is False
    assert rounds[0].stopped_reason == "refused"


def test_client_error_stops_loop():
    from forgeagent.models import ClientError

    step = _step([ClientError(message="down", kind="network", attempts=3)])
    rounds = step.run(_user())
    assert rounds[0].stopped_reason == "client_error:network"
    assert rounds[0].text == "down"


# --- cross-block state through the loop --------------------------------------


def test_cross_block_state_via_utils():
    script = [
        _reply(_exec_call("utils.set_state('n', 7)", name="b1")),
        _reply(_exec_call("print(utils.get_state('n') * 6)", name="b2")),
        _reply(_done()),
    ]
    step = _step(script)
    rounds = step.run(_user())
    assert "42" in rounds[1].outcomes[0].exec_result.stdout


# --- Edit runtime matching (deferred from M2) --------------------------------


def test_apply_edit_replaces_single():
    new_code, err = _apply_edit("a = 1", EditArgs(name="b", old="1", new="2"))
    assert err is None
    assert new_code == "a = 2"


def test_apply_edit_old_not_found():
    new_code, err = _apply_edit("a = 1", EditArgs(name="b", old="zzz", new="x"))
    assert new_code is None
    assert "not found" in err


def test_apply_edit_multiple_without_replace_all_errors():
    new_code, err = _apply_edit("x x x", EditArgs(name="b", old="x", new="y"))
    assert new_code is None
    assert "matches" in err and "replace_all" in err


def test_apply_edit_multiple_with_replace_all():
    new_code, err = _apply_edit("x x x", EditArgs(name="b", old="x", new="y", replace_all=True))
    assert err is None
    assert new_code == "y y y"


def test_edit_tool_bumps_version_in_loop():
    create = _tool_call("Exec", name="blk", code="v = 1")
    edit = _tool_call("Edit", name="blk", old="1", new="2")
    step = _step([_reply(create), _reply(edit), _reply(_done())])
    step.run(_user())
    assert step.blocks.get("blk").version == 2
    assert step.blocks.get("blk").code == "v = 2"


def test_edit_nonexistent_block_fails():
    edit = _tool_call("Edit", name="ghost", old="a", new="b")
    step = _step([_reply(edit), _reply(_done())])
    rounds = step.run(_user())
    assert rounds[0].outcomes[0].success is False
    assert "does not exist" in rounds[0].outcomes[0].detail


# --- native tool_calls channel (ToolSource.OPENAI, M6) ------------------------


def test_native_tool_call_drives_exec():
    call = _native_call("c1", "Exec", name="blk", code="print(42)")
    step = _step([_reply("", tool_calls=[call]), _reply(_done())])
    rounds = step.run(_user())
    assert rounds[0].outcomes[0].tool == "Exec"
    assert rounds[0].outcomes[0].success is True
    assert step.blocks.get("blk").code == "print(42)"


def test_native_tool_call_drives_edit_and_bumps_version():
    create = _native_call("c1", "Exec", name="blk", code="v = 1")
    edit = _native_call("c2", "Edit", name="blk", old="1", new="2")
    step = _step([_reply("", tool_calls=[create]), _reply("", tool_calls=[edit]), _reply(_done())])
    step.run(_user())
    assert step.blocks.get("blk").version == 2
    assert step.blocks.get("blk").code == "v = 2"


def test_both_channels_in_one_reply_both_execute():
    text_call = _tool_call("Exec", name="a", code="x = 1")
    native_call = _native_call("c1", "Exec", name="b", code="y = 2")
    step = _step([_reply(text_call, tool_calls=[native_call]), _reply(_done())])
    rounds = step.run(_user())
    assert len(rounds[0].outcomes) == 2
    assert step.blocks.get("a").code == "x = 1"
    assert step.blocks.get("b").code == "y = 2"


def _survey_call(question: str, options=None) -> str:
    args = {"question": question}
    if options:
        args["options"] = options
    return _tool_call("Survey", **args)


def test_survey_with_asker_feeds_answer_and_continues():
    # An answered Survey produces feedback and the loop continues to completion.
    from forgeagent.step import Step
    from forgeagent.tools import default_registry

    step = Step(
        MockClient(script=[_reply(_survey_call("which color?")), _reply(_done())]),
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        registry=default_registry(),
        asker=lambda args: "green",
    )
    rounds = step.run(_user())
    assert len(rounds) == 2
    assert rounds[0].outcomes[0].tool == "Survey"
    assert rounds[0].outcomes[0].success is True
    assert "green" in step._render_feedback(rounds[0])
    assert rounds[1].completed is True


def test_survey_without_asker_ends_needs_info():
    # Headless Step (no asker): a Survey call terminates the loop with NEEDS_INFO, and
    # the round carries the question as stopped_detail for Task to surface.
    from forgeagent.step import Step
    from forgeagent.tools import default_registry

    step = Step(
        MockClient(script=[_reply(_survey_call("which file should I edit?"))]),
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        registry=default_registry(),
    )
    rounds = step.run(_user())
    assert len(rounds) == 1
    assert rounds[0].stopped_reason == "needs_info"
    assert rounds[0].stopped_detail == "which file should I edit?"


def test_declared_completion_does_not_override_survey_needs_info():
    # A tool-bearing response cannot complete, so Survey's existing terminal signal
    # remains the outcome when no asker is available.
    from forgeagent.step import Step
    from forgeagent.tools import default_registry

    reply_text = _done() + _survey_call("anything else?")
    step = Step(
        MockClient(script=[_reply(reply_text)]),
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        registry=default_registry(),
    )
    rounds = step.run(_user())
    assert rounds[0].completed is False
    assert rounds[0].stopped_reason == "needs_info"


class _RecordingClient(MockClient):
    """MockClient that also records the `messages` list it saw on each call, so a
    test can assert on what the loop actually replayed into history — not just on
    what the rendering helper produces in isolation."""

    def __init__(self, script):
        super().__init__(script=script)
        self.seen_messages: list[list[Message]] = []

    def complete(self, messages, params=None):
        self.seen_messages.append(list(messages))
        return super().complete(messages, params)


def test_native_tool_call_is_replayed_into_convo_history():
    # A model using the native tool_calls channel must still see its own prior call in
    # history on the next round — dropping it would erase the model's own past actions
    # from its context (it only ever gets `messages`, no side-channel memory).
    call = _native_call("c1", "Exec", name="blk", code="print(1)")
    client = _RecordingClient(script=[_reply("", tool_calls=[call]), _reply(_done())])
    step = Step(client, TrustedBackend(), Runtime(), max_rounds=5)
    step.run(_user())

    assert len(client.seen_messages) == 2
    round2_messages = client.seen_messages[1]
    assistant_turn = next(m for m in round2_messages if m.role == Role.ASSISTANT)
    assert "ToolCall" in assistant_turn.content
    assert "blk" in assistant_turn.content
    assert "print(1)" in assistant_turn.content


# --- streaming (M9 Phase 3) ---------------------------------------------------


class _ScriptedStreamClient(MockClient):
    """A client whose stream() replays a pre-scripted event sequence per call, and
    whose complete() raises if ever invoked — proving _stream_or_complete takes the
    streaming branch rather than silently falling back to complete()."""

    def __init__(self, stream_script: list[list[StreamEvent | ClientError]]):
        super().__init__(script=[])
        self._stream_script = list(stream_script)
        self._stream_index = 0

    def complete(self, messages, params=None):
        raise AssertionError("complete() must not be called when on_stream_text is set")

    def stream(self, messages, params=None):
        events = self._stream_script[self._stream_index]
        self._stream_index += 1
        yield from events


def test_streaming_forwards_deltas_and_returns_done_message():
    # With on_stream_text set, the loop must consume stream() (never complete()),
    # forward every TEXT_DELTA/THINKING_DELTA to the callback, and treat the DONE
    # event's message exactly like a complete() reply for parsing/history/termination.
    done_message = _reply(_done())
    client = _ScriptedStreamClient(
        stream_script=[
            [
                StreamEvent(kind=StreamEventKind.THINKING_DELTA, text="pondering... "),
                StreamEvent(kind=StreamEventKind.TEXT_DELTA, text=done_message.content),
                StreamEvent(kind=StreamEventKind.DONE, message=done_message),
            ]
        ]
    )
    received: list[tuple[str, StreamEventKind]] = []
    step = Step(
        client,
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        on_stream_text=lambda text, kind: received.append((text, kind)),
    )
    rounds = step.run(_user())
    assert received == [
        ("pondering... ", StreamEventKind.THINKING_DELTA),
        (done_message.content, StreamEventKind.TEXT_DELTA),
    ]
    assert len(rounds) == 1
    assert rounds[0].completed is True
    assert rounds[0].stopped_reason == "completed"


def test_streaming_mid_stream_client_error_stops_loop_like_complete_would():
    # A ClientError yielded mid-stream (instead of a DONE) converges to the same
    # terminal shape as a complete()-returned ClientError (docs/m9 §3.1/§3.3).
    client = _ScriptedStreamClient(
        stream_script=[[ClientError(message="down", kind="network", attempts=1)]]
    )
    step = Step(
        client,
        TrustedBackend(),
        Runtime(),
        max_rounds=5,
        on_stream_text=lambda text, kind: None,
    )
    rounds = step.run(_user())
    assert rounds[0].stopped_reason == "client_error:network"
    assert rounds[0].text == "down"


def test_no_callback_uses_complete_not_stream():
    # on_stream_text=None (the default) is the existing non-streaming path — stream()
    # must never be consulted.
    class _StreamRaisesClient(MockClient):
        def stream(self, messages, params=None):
            raise AssertionError("stream() must not be called without on_stream_text")

    client = _StreamRaisesClient(script=[_reply(_done())])
    step = Step(client, TrustedBackend(), Runtime(), max_rounds=5)
    rounds = step.run(_user())
    assert rounds[0].completed is True
