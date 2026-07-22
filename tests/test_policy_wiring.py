"""Unit tests for AST policy wiring into Step + default tier (M4-3)."""

import json

from forgeagent.client import MockClient
from forgeagent.executor import RestrictedBackend, TrustedBackend
from forgeagent.models import AssistantMessage, Message, Role, TokenUsage
from forgeagent.runtime import Runtime
from forgeagent.step import Step
from forgeagent.task import Task, _backend_for_tier


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason="end_turn")


def _exec(code: str, name: str | None = None) -> str:
    args: dict = {"code": code}
    if name:
        args["name"] = name
    return f"<!-- ToolCall: {json.dumps({'name': 'Exec', 'arguments': args})} -->"


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\n"


def _trusted_step(script) -> Step:
    # Trusted backend keeps these tests fast/in-process; the wiring under test is the
    # analyzer, not the backend.
    return Step(MockClient(script=script), TrustedBackend(), Runtime(), max_rounds=5)


def _initial_conversation() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="goal"),
    ]


def test_static_feedback_attached_for_forbidden_import():
    step = _trusted_step([_reply(_exec("import ctypes\nprint('hi')")), _reply(_done())])
    rounds = step.run(_initial_conversation())
    outcome = rounds[0].outcomes[0]
    assert "forbidden-import" in outcome.static_feedback


def test_static_feedback_flags_dynamic_import_t7():
    step = _trusted_step([_reply(_exec("m = __import__('os')")), _reply(_done())])
    rounds = step.run(_initial_conversation())
    assert "dynamic-import" in rounds[0].outcomes[0].static_feedback


def test_static_feedback_does_not_block_trusted_execution():
    # A flagged import still runs under trusted tier (static layer is advisory only).
    step = _trusted_step([_reply(_exec("import ctypes\nprint('ran anyway')")), _reply(_done())])
    rounds = step.run(_initial_conversation())
    outcome = rounds[0].outcomes[0]
    assert outcome.success is True
    assert "ran anyway" in outcome.exec_result.stdout
    assert outcome.static_feedback  # but the advisory feedback is present


def test_clean_code_has_no_static_feedback():
    step = _trusted_step([_reply(_exec("print(1 + 1)")), _reply(_done())])
    rounds = step.run(_initial_conversation())
    assert rounds[0].outcomes[0].static_feedback == ""


def test_static_feedback_enters_rendered_feedback():
    # The advisory feedback must reach the conversation feedback so the model sees it.
    step = _trusted_step([_reply(_exec("import ctypes\nprint('x')")), _reply(_done())])
    step.run(_initial_conversation())
    # Round 1 produced feedback that includes the static advisory.
    fb = step._render_feedback(step.rounds[0])
    assert "forbidden-import" in fb


# --- default tier -------------------------------------------------------------


def test_backend_for_tier_mapping():
    assert isinstance(_backend_for_tier("trusted"), TrustedBackend)
    assert isinstance(_backend_for_tier("restricted"), RestrictedBackend)


def test_task_default_tier_is_restricted():
    task = Task(MockClient(script=[_reply(_done())]))
    assert isinstance(task._backend, RestrictedBackend)


def test_task_trusted_tier_selectable():
    task = Task(MockClient(script=[_reply(_done())]), tier="trusted")
    assert isinstance(task._backend, TrustedBackend)


def test_explicit_backend_overrides_tier():
    backend = TrustedBackend()
    task = Task(MockClient(script=[_reply(_done())]), tier="restricted", backend=backend)
    assert task._backend is backend
