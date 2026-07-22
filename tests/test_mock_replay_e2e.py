"""Shared mock-replay coverage for the Task 8 golden scenarios."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from forgeagent.client import MockClient
from forgeagent.context import ContextConfig
from forgeagent.executor import RestrictedBackend
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_task_service import TaskService
from forgeagent.models import Message, ModelCapability, Role
from forgeagent.task import Task
from tests.golden import cases
from tests.golden.manifest import GOLDEN_SCENARIOS, GoldenEvidence
from tests.test_http_server import _request_via_handler, _wait_for_terminal_via_handler

COMMON_IDS = ("G01", "G03", "G05", "G08", "G11", "G13", "G15", "G17", "G27", "G43")


class RecordingClient(MockClient):
    """Mock replay client that retains immutable request snapshots for prompt checks."""

    def __init__(self, script: list, capability: ModelCapability) -> None:
        super().__init__(script=script, capability=capability)
        self.calls: list[list[Message]] = []

    def complete(self, messages, params=None):
        self.calls.append([message.model_copy(deep=True) for message in messages])
        return super().complete(messages, params)


def _small_capability() -> ModelCapability:
    return ModelCapability(
        model_id="replay-context",
        context_window=300,
        max_output_tokens=20,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )


def _tool_round(name: str, output: str) -> str:
    return cases._exec(f"print({output!r})", name)


def _history_contents(messages: list[Message]) -> list[str]:
    return [str(message.content) for message in messages]


@pytest.mark.parametrize("scenario_id", COMMON_IDS)
def test_common_golden_case_replays_through_manifest(scenario_id: str, tmp_path: Path):
    scenario = next(item for item in GOLDEN_SCENARIOS if item.scenario_id == scenario_id)

    evidence = scenario.run_offline(tmp_path / scenario_id)

    assert type(evidence) is GoldenEvidence


def _g13_script() -> list:
    premature = cases._done()
    return [
        cases._reply(premature + "\n" + cases._exec("print(undefined_variable)", "calc")),
        cases._reply(premature + "\n" + cases._exec("print(2 + 2)", "calc")),
        cases._reply(cases._done()),
    ]


def test_golden_mock_replay_matches_http_safe_projection(tmp_path: Path):
    """The HTTP path preserves terminal semantics while hiding model/tool text."""
    goal = "Compute 2 + 2, recovering from the first execution error."
    golden = next(item for item in GOLDEN_SCENARIOS if item.scenario_id == "G13")
    evidence = golden.run_offline(tmp_path / "golden")
    assert evidence.detail == "completion required an independent third round"

    direct = Task(MockClient(script=_g13_script())).run(goal)
    service_root = tmp_path / "service"
    service_root.mkdir()
    captured = []

    class CapturingTask(Task):
        def run(self, goal, *, cancel_event=None):
            outcome = super().run(goal, cancel_event=cancel_event)
            captured.append(outcome)
            return outcome

    config = HttpServiceConfig(token="test-token", max_workers=1, max_queue=1, max_records=4)
    service = TaskService(
        factory=lambda _record: CapturingTask(
            MockClient(script=_g13_script()),
            backend=RestrictedBackend(allowed_root=str(service_root), secret_values=set()),
            allowed_root=str(service_root),
        ),
        config=config,
    )
    server = SimpleNamespace(config=config, task_service=service, audit_sink=None)
    try:
        status, initial, _raw = _request_via_handler(server, "POST", "/tasks", body={"goal": goal})
        assert status == 202
        assert initial is not None
        task_id = str(initial["task_id"])
        view = _wait_for_terminal_via_handler(server, task_id)
        assert captured
        assert view["status"] == direct.status.reason
        assert view["reason"] == direct.status.reason
        assert view["detail"] is None
        assert view["round_count"] == len(direct.rounds) == len(captured[0].rounds)
        direct_tool_count = sum(len(round_result.outcomes) for round_result in direct.rounds)
        service_tool_count = sum(len(round_result.outcomes) for round_result in captured[0].rounds)
        assert service_tool_count == direct_tool_count == 2
        assert "undefined_variable" not in repr(view)
        assert "stdout" not in repr(view)
        assert "NameError" not in repr(view)
    finally:
        service.shutdown(2.0)


def test_replay_requests_append_without_rewriting_prefix_below_context_threshold():
    client = RecordingClient(
        script=[
            cases._reply(_tool_round("first", "first-result")),
            cases._reply(_tool_round("second", "second-result")),
            cases._reply(cases._done()),
        ],
        capability=_small_capability(),
    )

    outcome = Task(
        client,
        system_prompt="stable-system-prompt",
        context_config=ContextConfig(
            utilization_ratio=1.0,
            round_feedback_max_tokens=80,
            tool_result_max_tokens=30,
        ),
    ).run("finish replay")

    assert outcome.status.completed is True
    assert len(client.calls) == 3
    for earlier, later in zip(client.calls, client.calls[1:], strict=False):
        assert later[: len(earlier)] == earlier
        assert [message.role for message in later[len(earlier) :]] == [
            Role.ASSISTANT,
            Role.USER,
        ]
    assert all(call[0].content == "stable-system-prompt" for call in client.calls)
    assert all(call[1].content == "finish replay" for call in client.calls)


def test_long_replay_slides_complete_rounds_and_keeps_bounded_feedback_honest():
    long_output = "long-detail-" * 120
    client = RecordingClient(
        script=[
            cases._reply(cases._exec("print('long-detail-' * 120)", "round-0")),
            cases._reply(_tool_round("round-1", "one")),
            cases._reply(_tool_round("round-2", "two")),
            cases._reply(_tool_round("round-3", "three")),
            cases._reply(cases._done()),
        ],
        capability=_small_capability(),
    )

    outcome = Task(
        client,
        system_prompt="stable-system-prompt",
        max_rounds=5,
        context_config=ContextConfig(
            utilization_ratio=1.0,
            round_feedback_max_tokens=120,
            tool_result_max_tokens=40,
        ),
    ).run("finish replay")

    assert outcome.status.completed is True
    assert len(client.calls) == 5

    stable_prefix = client.calls[0]
    assert len(stable_prefix) == 2
    assert all(call[:2] == stable_prefix for call in client.calls)
    assert client.calls[1][: len(client.calls[0])] == client.calls[0]

    # The first unit reaches the model before sliding, then leaves as an intact pair.
    assert "round-0" in "\n".join(_history_contents(client.calls[1]))
    assert "round-0" not in "\n".join(_history_contents(client.calls[-1][2:]))
    assert any(
        len(current) < len(previous) + 2
        for previous, current in zip(client.calls, client.calls[1:], strict=False)
    )
    retained_pair_suffixes_checked = 0
    for previous, current in zip(client.calls, client.calls[1:], strict=False):
        previous_history = previous[2:]
        current_history = current[2:]
        for history in (previous_history, current_history):
            assert len(history) % 2 == 0
            assert [message.role for message in history] == [
                role for _ in range(len(history) // 2) for role in (Role.ASSISTANT, Role.USER)
            ]

        previous_pairs = list(zip(previous_history[::2], previous_history[1::2], strict=True))
        current_pairs = list(zip(current_history[::2], current_history[1::2], strict=True))
        assert current_pairs
        new_tail_pair = current_pairs[-1]
        assert [message.role for message in new_tail_pair] == [Role.ASSISTANT, Role.USER]

        # Only the final pair was added since the preceding request; any earlier pair
        # retained through a slide must be an unchanged, ordered suffix of that request.
        retained_old_pairs = current_pairs[:-1]
        if retained_old_pairs:
            assert retained_old_pairs == previous_pairs[-len(retained_old_pairs) :]
            retained_pair_suffixes_checked += 1

    assert retained_pair_suffixes_checked > 0

    latest_request = client.calls[-1]
    assert "round-3" in str(latest_request[-2].content)
    assert "[Exec round-3]" in str(latest_request[-1].content)

    feedback = client.calls[1][-1].content
    assert isinstance(feedback, str)
    assert "[truncated:" in feedback
    assert f"original {len(long_output)} chars" in feedback
    assert "[continuation]" in feedback
    first_outcome = outcome.rounds[0].outcomes[0]
    assert first_outcome.exec_result is not None
    assert first_outcome.exec_result.stdout == long_output + "\n"
