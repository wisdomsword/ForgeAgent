"""Unit tests for the Step loop (M3-3).

Uses MockClient to script LLM responses (no key, no network). Responses follow the
text-protocol markup from docs/text-protocol-spec.md.
"""

import json

from forgeagent.client import MockClient
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
from forgeagent.protocol import EditArgs
from forgeagent.runtime import Runtime
from forgeagent.step import RoundResult, Step, _apply_edit
from forgeagent.tools import ToolOutcome


def _reply(text: str, stop_reason: str = "end_turn", tool_calls=None) -> AssistantMessage:
    return AssistantMessage(
        content=text, usage=TokenUsage(), stop_reason=stop_reason, tool_calls=tool_calls or []
    )


def _native_call(call_id: str, tool_name: str, **arguments) -> NativeToolCall:
    return NativeToolCall(id=call_id, name=tool_name, arguments=json.dumps(arguments))


def _step(script) -> Step:
    return Step(MockClient(script=script), TrustedBackend(), Runtime(), max_rounds=5)


def _user(text="go"):
    return [Message(role=Role.USER, content=text)]


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


# --- loop control ------------------------------------------------------------


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


def test_long_stdout_is_truncated_in_feedback():
    # A block that prints a lot must not blow up the next round's context; feedback
    # keeps only the tail plus a marker noting how much was cut.
    step = _step([_reply(_exec_call("print('x' * 10_000)")), _reply(_done())])
    rounds = step.run(_user())
    feedback = step._render_feedback(rounds[0])
    assert "truncated" in feedback
    assert len(feedback) < 10_000
    assert feedback.endswith("x" * 100)


def test_webfetch_fixed_failure_detail_is_safe_in_step_feedback():
    secret_url = "https://secret-host.invalid/private?token=secret-value"
    feedback = _step([])._render_feedback(
        RoundResult(
            text="",
            outcomes=[
                ToolOutcome(
                    tool="WebFetch", success=False, detail="WebFetch request failed"
                )
            ],
        )
    )

    assert feedback == "[WebFetch None] FAILED: WebFetch request failed"
    assert secret_url not in feedback


def test_file_read_fixed_failure_detail_is_safe_in_step_feedback():
    host_path = "/host/private/secret.txt"
    feedback = _step([])._render_feedback(
        RoundResult(
            text="",
            outcomes=[ToolOutcome(tool="FileRead", success=False, detail="FileRead failed")],
        )
    )

    assert feedback == "[FileRead None] FAILED: FileRead failed"
    assert host_path not in feedback


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


def test_declared_completion_wins_over_survey_needs_info():
    # If the model both completes and calls Survey without an asker in one round, the
    # declared completion is the more reliable signal and takes precedence.
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
    assert rounds[0].stopped_reason == "completed"


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
        client, TrustedBackend(), Runtime(), max_rounds=5,
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
        client, TrustedBackend(), Runtime(), max_rounds=5,
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
