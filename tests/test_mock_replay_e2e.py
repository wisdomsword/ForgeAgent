"""Shared mock-replay coverage for the Task 8 golden scenarios."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from forgeagent.client import MockClient
from forgeagent.executor import RestrictedBackend
from forgeagent.http_config import HttpServiceConfig
from forgeagent.http_task_service import TaskService
from forgeagent.task import Task
from tests.golden import cases
from tests.golden.manifest import GOLDEN_SCENARIOS, GoldenEvidence
from tests.test_http_server import _request_via_handler

COMMON_IDS = ("G01", "G03", "G05", "G08", "G11", "G13", "G15", "G17", "G27", "G43")


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
        deadline = time.monotonic() + 5.0
        view = None
        while time.monotonic() < deadline:
            status, view, _raw = _request_via_handler(server, "GET", f"/tasks/{task_id}")
            assert status == 200
            if view is not None and view["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert view is not None and view["status"] not in {"queued", "running"}
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
