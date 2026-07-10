"""Unit tests for the Task loop (M3-4)."""

import json

from forgeagent.client import MockClient
from forgeagent.models import AssistantMessage, TokenUsage
from forgeagent.task import Task


def _reply(text: str, stop_reason: str = "end_turn") -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason=stop_reason)


def _tool_call(tool_name: str, **arguments) -> str:
    return f"<!-- ToolCall: {json.dumps({'name': tool_name, 'arguments': arguments})} -->"


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\ndone"


def test_task_completes_normally():
    task = Task(MockClient(script=[_reply(_done())]))
    outcome = task.run("do a thing")
    assert outcome.status.completed is True
    assert outcome.status.reason == "completed"


def test_task_refused():
    task = Task(MockClient(script=[_reply("cannot", stop_reason="refusal")]))
    outcome = task.run("do a bad thing")
    assert outcome.status.completed is False
    assert outcome.status.solved is False
    assert outcome.status.reason == "refused"


def test_task_prose_answer_is_solved_but_not_completed():
    # Prose answer (nudged once, then repeated) is a soft success: solved, unverified.
    script = [_reply("the sum is 60"), _reply("as I said, 60")]
    task = Task(MockClient(script=script))
    outcome = task.run("sum some numbers")
    assert outcome.status.completed is False
    assert outcome.status.solved is True
    assert outcome.status.reason == "answered_in_prose"
    assert outcome.status.detail == "as I said, 60"


def test_task_multi_step_state_carries_through():
    # Block 1 saves state, block 2 uses it, then completion.
    script = [
        _reply(_tool_call("Exec", name="b1", code="utils.set_state('v', 10)")),
        _reply(_tool_call("Exec", name="b2", code="print(utils.get_state('v') + 5)")),
        _reply(_done()),
    ]
    task = Task(MockClient(script=script))
    outcome = task.run("compute")
    assert outcome.status.completed is True
    # The second round's exec output reflects the carried state.
    assert "15" in outcome.rounds[1].outcomes[0].exec_result.stdout


def test_task_exhausts_max_rounds():
    # Always produces feedback, never completes.
    script = [_reply(_tool_call("Exec", code="print(1)")) for _ in range(6)]
    task = Task(MockClient(script=script), max_rounds=3)
    outcome = task.run("loop forever")
    assert outcome.status.completed is False
    assert outcome.status.reason == "max_rounds"


def test_task_client_error_surfaces():
    from forgeagent.models import ClientError

    task = Task(MockClient(script=[ClientError(message="x", kind="auth", attempts=1)]))
    outcome = task.run("go")
    assert outcome.status.completed is False
    assert outcome.status.reason == "client_error:auth"


def test_task_runtime_state_accessible_after_run():
    script = [
        _reply(_tool_call("Exec", code="utils.set_state('answer', 42)")),
        _reply(_done()),
    ]
    task = Task(MockClient(script=script))
    task.run("save answer")
    # The task owns the runtime; state persists after the run for inspection.
    assert task.runtime.get_state("answer") == 42
