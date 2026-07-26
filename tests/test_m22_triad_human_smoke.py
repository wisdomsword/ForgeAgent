from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "m22-triad-human-smoke.py"
    spec = importlib.util.spec_from_file_location("m22_triad_human_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_state(workdir: Path, **overrides: object) -> Path:
    state: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "triad",
        "status": "completed",
        "phase": "completed",
        "stop_reason": "completed",
        "plan": [
            {
                "id": "moving_average",
                "behavior": "Provide moving_average and its CLI.",
                "acceptance": "Files, pytest, and JSON output pass.",
            }
        ],
        "plan_digest": "b" * 64,
        "generator_attempts": 1,
        "evaluator_attempts": 1,
        "rejections": 0,
        "last_evaluation": [
            {
                "id": "moving_average",
                "passed": True,
                "observed": "All checks pass.",
                "expected": "All checks pass.",
                "location": "calc.py",
            }
        ],
    }
    state.update(overrides)
    directory = workdir / ".forgeagent" / "collaborations"
    directory.mkdir(parents=True, exist_ok=True)
    state_file = directory / f"{'a' * 32}.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def test_build_command_preserves_triad_and_manual_stdio_contract(tmp_path):
    smoke = _load_smoke_module()
    models = smoke.SmokeModels("claude-sonnet-5", "claude-haiku-4-5", "claude-haiku-4-5")
    command = smoke.build_forgeagent_command(tmp_path / "forgeagent", models)
    assert command == [
        str(tmp_path / "forgeagent"),
        "--model",
        "claude-sonnet-5",
        "--tier",
        "restricted",
        "--no-identity",
        "--no-memory",
        "run",
        "--mode",
        "triad",
        "--planner-model",
        "claude-haiku-4-5",
        "--evaluator-model",
        "claude-haiku-4-5",
        "--max-rejections",
        "2",
        smoke.GOAL,
    ]


def test_success_state_has_no_collaboration_failures(tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path)
    state = smoke.load_collaboration_state(tmp_path)
    assert smoke.collaboration_failures(state) == []


def test_plan_rejection_is_reported_explicitly(tmp_path):
    smoke = _load_smoke_module()
    _write_state(
        tmp_path,
        status="stopped",
        phase="stopped",
        stop_reason="needs_confirmation",
        generator_attempts=0,
        evaluator_attempts=0,
        last_evaluation=[],
    )
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("needs_confirmation" in item for item in failures)


def test_invalid_role_submission_is_reported_explicitly(tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path, status="failed", phase="failed", stop_reason="invalid_role_submission")
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("invalid_role_submission" in item for item in failures)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"status": "synthetic-status-secret"}, "status is not completed: invalid"),
        ({"phase": "synthetic-phase-secret"}, "phase is not completed: invalid"),
        (
            {"stop_reason": "synthetic-stop-reason-secret"},
            "stop_reason is not completed: invalid",
        ),
    ],
)
def test_unknown_lifecycle_values_are_not_echoed_in_failures(tmp_path, overrides, expected):
    smoke = _load_smoke_module()
    _write_state(tmp_path, **overrides)
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert expected in failures
    assert "synthetic-" not in "\n".join(failures)


def test_boolean_attempt_is_not_accepted_as_integer(tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path, generator_attempts=True)
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("generator_attempts" in item for item in failures)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"plan": []}, "plan"),
        ({"plan_digest": "not-a-digest"}, "plan_digest"),
        ({"generator_attempts": 0}, "generator_attempts"),
        ({"evaluator_attempts": 0}, "evaluator_attempts"),
        ({"last_evaluation": []}, "last_evaluation"),
        ({"last_evaluation": [{"id": "moving_average", "passed": False}]}, "passed"),
    ],
)
def test_invalid_success_state_projection_is_rejected(tmp_path, overrides, field):
    smoke = _load_smoke_module()
    _write_state(tmp_path, **overrides)
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any(field in item for item in failures)


def test_state_discovery_requires_exactly_one_regular_json(tmp_path):
    smoke = _load_smoke_module()
    with pytest.raises(ValueError, match="exactly one collaboration state"):
        smoke.load_collaboration_state(tmp_path)
    _write_state(tmp_path)
    second = tmp_path / ".forgeagent" / "collaborations" / "second.json"
    second.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one collaboration state"):
        smoke.load_collaboration_state(tmp_path)


def test_state_discovery_ignores_symlink_candidate(tmp_path):
    smoke = _load_smoke_module()
    state_file = _write_state(tmp_path)
    target = tmp_path / "state-target.json"
    state_file.replace(target)
    state_file.symlink_to(target)
    with pytest.raises(ValueError, match="exactly one collaboration state"):
        smoke.load_collaboration_state(tmp_path)


def test_state_loader_hides_discovery_error(monkeypatch, tmp_path):
    smoke = _load_smoke_module()

    def fail_glob(self, pattern):
        raise OSError("synthetic-discovery-secret")

    monkeypatch.setattr(Path, "glob", fail_glob)
    with pytest.raises(ValueError, match="could not discover collaboration state") as error:
        smoke.load_collaboration_state(tmp_path)
    assert error.value.__cause__ is None


def test_state_loader_hides_read_error(monkeypatch, tmp_path):
    smoke = _load_smoke_module()
    state_file = _write_state(tmp_path)
    original_read_text = Path.read_text

    def fail_state_read(self, *args, **kwargs):
        if self == state_file:
            raise OSError("synthetic-read-secret")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_state_read)
    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)
    assert error.value.__cause__ is None


def test_state_loader_rejects_invalid_json_without_echoing_content(tmp_path):
    smoke = _load_smoke_module()
    secret = "synthetic-state-secret"
    state_file = _write_state(tmp_path)
    state_file.write_text("{" + secret, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None


def test_state_loader_rejects_non_object_json(tmp_path):
    smoke = _load_smoke_module()
    state_file = _write_state(tmp_path)
    state_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)
    assert error.value.__cause__ is None


def test_plan_and_evaluation_ids_must_match_in_order(tmp_path):
    smoke = _load_smoke_module()
    _write_state(
        tmp_path,
        plan=[{"id": "first"}, {"id": "second"}],
        last_evaluation=[
            {"id": "second", "passed": True},
            {"id": "first", "passed": True},
        ],
    )
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("last_evaluation" in item for item in failures)


def test_plan_ids_must_be_unique_nonempty_strings(tmp_path):
    smoke = _load_smoke_module()
    _write_state(
        tmp_path,
        plan=[{"id": ""}, {"id": ""}],
        last_evaluation=[{"id": "", "passed": True}, {"id": "", "passed": True}],
    )
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("plan" in item for item in failures)
