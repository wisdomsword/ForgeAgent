from __future__ import annotations

import importlib.util
import json
import os
import subprocess
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


def _config(smoke, workdir: Path):
    return smoke.SmokeConfig(
        workdir=workdir,
        forgeagent=workdir / "forgeagent",
        python=Path(sys.executable),
        models=smoke.SmokeModels("generator", "planner", "evaluator"),
    )


def _check_result(smoke, *, status="passed", exit_code=0, stdout="", stderr=""):
    return smoke.CheckResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


def test_main_rejects_non_tty_before_creating_workdir(monkeypatch, capsys):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(smoke.tempfile, "mkdtemp", lambda **kwargs: pytest.fail("created workdir"))

    assert smoke.main() == 2
    assert "interactive terminal" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value",
    ["", "model\nname", "m" * 501],
    ids=["empty", "control-character", "too-long"],
)
def test_main_rejects_invalid_model_environment_before_creating_workdir(monkeypatch, capsys, value):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("FORGEAGENT_M22_MODEL", value)
    monkeypatch.setattr(smoke.tempfile, "mkdtemp", lambda **kwargs: pytest.fail("created workdir"))

    assert smoke.main() == 2
    error = capsys.readouterr().err
    assert "model configuration" in error
    if value:
        assert value not in error


def test_models_from_environment_uses_defaults_and_explicit_overrides(monkeypatch):
    smoke = _load_smoke_module()
    for name in (
        "FORGEAGENT_M22_MODEL",
        "FORGEAGENT_M22_PLANNER_MODEL",
        "FORGEAGENT_M22_EVALUATOR_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert smoke.models_from_environment() == smoke.SmokeModels(
        "claude-sonnet-5", "claude-haiku-4-5", "claude-haiku-4-5"
    )

    monkeypatch.setenv("FORGEAGENT_M22_MODEL", "generator-override")
    monkeypatch.setenv("FORGEAGENT_M22_PLANNER_MODEL", "planner-override")
    monkeypatch.setenv("FORGEAGENT_M22_EVALUATOR_MODEL", "evaluator-override")

    assert smoke.models_from_environment() == smoke.SmokeModels(
        "generator-override", "planner-override", "evaluator-override"
    )


@pytest.mark.parametrize("missing", ["forgeagent", "python"])
def test_main_rejects_missing_venv_executable_before_creating_workdir(monkeypatch, capsys, missing):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        smoke.Path,
        "is_file",
        lambda path: path.name != missing,
    )
    monkeypatch.setattr(smoke.os, "access", lambda path, mode: mode == os.X_OK)
    monkeypatch.setattr(smoke.tempfile, "mkdtemp", lambda **kwargs: pytest.fail("created workdir"))

    assert smoke.main() == 2
    assert f".venv/bin/{missing}" in capsys.readouterr().err


def test_main_builds_config_from_environment_and_returns_smoke_result(monkeypatch, tmp_path):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("FORGEAGENT_M22_MODEL", "generator-override")
    monkeypatch.setenv("FORGEAGENT_M22_PLANNER_MODEL", "planner-override")
    monkeypatch.setenv("FORGEAGENT_M22_EVALUATOR_MODEL", "evaluator-override")
    monkeypatch.setattr(smoke.Path, "is_file", lambda path: True)
    monkeypatch.setattr(smoke.os, "access", lambda path, mode: mode == os.X_OK)

    calls: list[dict[str, object]] = []

    def fake_mkdtemp(**kwargs):
        calls.append(kwargs)
        return str(tmp_path / "workdir")

    captured_config = None

    def fake_run_smoke(config):
        nonlocal captured_config
        captured_config = config
        return 17

    monkeypatch.setattr(smoke.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    assert smoke.main() == 17
    assert calls == [{"prefix": "forgeagent-m22-human-", "dir": "/tmp"}]
    assert captured_config is not None
    assert captured_config.workdir == tmp_path / "workdir"
    assert captured_config.models == smoke.SmokeModels(
        "generator-override", "planner-override", "evaluator-override"
    )
    repository = Path(smoke.__file__).resolve().parents[1]
    assert captured_config.forgeagent == repository / ".venv" / "bin" / "forgeagent"
    assert captured_config.python == repository / ".venv" / "bin" / "python"


def test_main_converts_workdir_creation_error_to_stable_preflight_failure(monkeypatch, capsys):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(smoke.Path, "is_file", lambda path: True)
    monkeypatch.setattr(smoke.os, "access", lambda path, mode: mode == os.X_OK)

    def fail_mkdtemp(**kwargs):
        raise OSError("synthetic-workdir-secret")

    monkeypatch.setattr(smoke.tempfile, "mkdtemp", fail_mkdtemp)

    assert smoke.main() == 2
    error = capsys.readouterr().err
    assert "could not create workdir" in error
    assert "synthetic-workdir-secret" not in error


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


@pytest.mark.parametrize(
    "plan",
    [
        [{"id": "moving_average", "acceptance": "observable"}],
        [{"id": "moving_average", "behavior": "observable"}],
        [{"id": "moving_average", "behavior": " ", "acceptance": "observable"}],
        [{"id": "moving_average", "behavior": "observable\n", "acceptance": "observable"}],
        [{"id": "moving_average", "behavior": "x" * 1_001, "acceptance": "observable"}],
    ],
)
def test_plan_requires_bounded_safe_behavior_and_acceptance(tmp_path, plan):
    smoke = _load_smoke_module()
    _write_state(tmp_path, plan=plan)

    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))

    assert any("plan item" in failure for failure in failures)


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
    original_open = Path.open

    def fail_state_open(self, *args, **kwargs):
        if self == state_file:
            raise OSError("synthetic-read-secret")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_state_open)
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


def test_state_loader_rejects_oversized_json_before_unbounded_read(tmp_path):
    smoke = _load_smoke_module()
    state_file = _write_state(tmp_path)
    state_file.write_bytes(b"{" + b"x" * smoke.MAX_STATE_BYTES)

    with pytest.raises(ValueError, match="collaboration state is too large") as error:
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


@pytest.mark.parametrize(
    "plan",
    [
        [{"id": "x" * 65, "behavior": "observable", "acceptance": "observable"}],
        [{"id": "moving\naverage", "behavior": "observable", "acceptance": "observable"}],
        [
            {"id": f"item-{index}", "behavior": "observable", "acceptance": "observable"}
            for index in range(51)
        ],
    ],
    ids=["long-id", "unsafe-id", "too-many-items"],
)
def test_plan_matches_runtime_item_bounds(tmp_path, plan):
    smoke = _load_smoke_module()
    _write_state(tmp_path, plan=plan)

    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))

    assert any("plan" in failure for failure in failures)


@pytest.mark.parametrize("missing", ["calc.py", "test_calc.py"])
def test_artifact_check_requires_each_regular_source_file(tmp_path, missing):
    smoke = _load_smoke_module()
    for name in {"calc.py", "test_calc.py"} - {missing}:
        (tmp_path / name).write_text("pass\n", encoding="utf-8")

    calls = []

    def check(*args, **kwargs):
        calls.append((args, kwargs))
        return _check_result(smoke)

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable), check)

    assert any(missing in item for item in failures)
    assert calls == []


def test_artifact_check_stops_after_restricted_pytest_failure(tmp_path):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    calls = []

    def check(*args, **kwargs):
        calls.append((args, kwargs))
        return _check_result(smoke, status="failed", exit_code=4)

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable), check)

    assert failures == ["pytest check failed with exit code 4"]
    assert len(calls) == 1
    definition = calls[0][0][0]
    assert definition.argv[1:] == ("-m", "pytest", "-q")
    assert calls[0][1] == {"allowed_root": tmp_path}


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        ("[1.5, 2.5, 3.5]", "unexpected", "calc.py CLI output validation failed"),
        ("not json", "", "calc.py CLI output validation failed"),
        ("[1.5, 2.5]", "", "calc.py CLI output validation failed"),
    ],
)
def test_artifact_check_rejects_invalid_cli_output(tmp_path, stdout, stderr, expected):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    results = iter(
        [
            _check_result(smoke),
            _check_result(smoke, stdout=stdout, stderr=stderr),
        ]
    )

    def check(*args, **kwargs):
        return next(results)

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable), check)

    assert any(expected in item for item in failures)


def test_artifact_check_does_not_echo_cli_output_in_diagnostics(tmp_path):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    secret = "synthetic-cli-secret"
    calls = []
    results = iter(
        [
            _check_result(smoke),
            _check_result(smoke, stdout=secret, stderr=secret),
        ]
    )

    def check(*args, **kwargs):
        calls.append((args, kwargs))
        return next(results)

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable), check)

    assert failures == ["calc.py CLI output validation failed"]
    assert secret not in "\n".join(failures)
    assert calls[0][0][0].argv[1:] == ("-m", "pytest", "-q")
    assert calls[1][0][0].argv[1:] == ("calc.py", "[1,2,3,4]", "2")
    assert all(kwargs == {"allowed_root": tmp_path} for _, kwargs in calls)


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("synthetic-stdout-secret", ""),
        ("[1.5, 2.5, 3.5]", "synthetic-stderr-secret"),
    ],
)
def test_artifact_check_never_echoes_captured_cli_streams(tmp_path, stdout, stderr):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    results = iter(
        [
            _check_result(smoke),
            _check_result(smoke, stdout=stdout, stderr=stderr),
        ]
    )

    failures = smoke.artifact_failures(
        tmp_path, Path(sys.executable), lambda *a, **k: next(results)
    )

    assert failures == ["calc.py CLI output validation failed"]
    assert stdout not in "\n".join(failures)
    if stderr:
        assert stderr not in "\n".join(failures)


@pytest.mark.parametrize(
    "hostile_test",
    [
        "import os\ndef test_env(): assert os.getenv('FORGEAGENT_M22_TEST_SECRET') == 'secret'\n",
        "from pathlib import Path\ndef test_outside(): Path({outside!r}).write_text('changed')\n",
        "import socket\ndef test_network(): socket.gethostbyname('localhost')\n",
        "import subprocess, sys\ndef test_process(): subprocess.run([sys.executable, '-V'])\n",
    ],
    ids=["environment", "outside-root", "network", "process"],
)
def test_artifact_checks_restrict_hostile_generated_tests(tmp_path, monkeypatch, hostile_test):
    smoke = _load_smoke_module()
    outside = tmp_path.parent / "m22-outside.txt"
    outside.write_text("original", encoding="utf-8")
    monkeypatch.setenv("FORGEAGENT_M22_TEST_SECRET", "secret")
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        hostile_test.format(outside=str(outside)), encoding="utf-8"
    )

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable))

    assert failures == ["pytest check failed with exit code 1"]
    assert outside.read_text(encoding="utf-8") == "original"
    assert "secret" not in "\n".join(failures)


def test_artifact_check_converts_runner_exceptions_to_stable_failure(tmp_path):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")

    def fail_check(*args, **kwargs):
        raise OSError("synthetic-check-secret")

    failures = smoke.artifact_failures(tmp_path, Path(sys.executable), fail_check)

    assert failures == ["pytest check could not start"]
    assert "synthetic-check-secret" not in "\n".join(failures)


def test_state_loader_rejects_deeply_nested_json_without_crashing(tmp_path):
    smoke = _load_smoke_module()
    state_file = _write_state(tmp_path)
    state_file.write_text("[" * 2_000 + "]" * 2_000, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)

    assert error.value.__cause__ is None


def test_state_loader_converts_json_recursion_error_to_stable_failure(monkeypatch, tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path)

    def recurse(_text):
        raise RecursionError("synthetic-parser-secret")

    monkeypatch.setattr(smoke.json, "loads", recurse)
    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)

    assert error.value.__cause__ is None


def test_run_smoke_prints_stable_success_summary_and_inherits_forgeagent_stdio(tmp_path, capsys):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        _write_state(tmp_path)
        (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
        (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
        return subprocess.CompletedProcess(args[0], 0)

    results = iter([_check_result(smoke), _check_result(smoke, stdout="[1.5, 2.5, 3.5]\n")])

    assert smoke.run_smoke(config, run=fake_run, check=lambda *a, **k: next(results)) == 0

    output = capsys.readouterr().out
    assert "M22 TRIAD HUMAN SMOKE: PASS" in output
    assert f"workdir: {config.workdir}" in output
    assert "collaboration: " + "a" * 32 in output
    assert "generator_attempts: 1" in output
    assert "evaluator_attempts: 1" in output
    assert "rejections: 0" in output
    assert calls[0][1] == {"cwd": config.workdir, "check": False}


def test_success_summary_reports_nonnegative_rejection_count(tmp_path, capsys):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)

    def fake_run(*args, **kwargs):
        _write_state(tmp_path, rejections=2)
        (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
        (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
        return subprocess.CompletedProcess(args[0], 0)

    results = iter([_check_result(smoke), _check_result(smoke, stdout="[1.5, 2.5, 3.5]")])

    assert smoke.run_smoke(config, run=fake_run, check=lambda *a, **k: next(results)) == 0
    assert "rejections: 2" in capsys.readouterr().out


@pytest.mark.parametrize(
    "state_overrides",
    [
        {"status": "stopped", "phase": "stopped", "stop_reason": "needs_confirmation"},
        {"status": "failed", "phase": "failed", "stop_reason": "invalid_role_submission"},
    ],
)
def test_run_smoke_rejects_unsuccessful_state_and_always_prints_workdir(
    tmp_path, capsys, state_overrides
):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)

    def failed_state(*args, **kwargs):
        _write_state(tmp_path, **state_overrides)
        return subprocess.CompletedProcess(args[0], 0)

    assert smoke.run_smoke(config, run=failed_state) == 1
    output = capsys.readouterr().out
    assert "M22 TRIAD HUMAN SMOKE: FAIL" in output
    assert f"workdir: {config.workdir}" in output
    assert state_overrides["stop_reason"] in output


def test_run_smoke_rejects_forgeagent_nonzero_and_state_discovery_errors(tmp_path, capsys):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)

    def failed_forgeagent(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 9)

    assert smoke.run_smoke(config, run=failed_forgeagent) == 1
    output = capsys.readouterr().out
    assert "ForgeAgent failed with exit code 9" in output
    assert "expected exactly one collaboration state" in output
    assert f"workdir: {config.workdir}" in output


def test_run_smoke_converts_forgeagent_start_error_to_stable_failure(tmp_path, capsys):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)

    def fail_start(*args, **kwargs):
        raise OSError("synthetic-launch-secret")

    assert smoke.run_smoke(config, run=fail_start) == 1
    output = capsys.readouterr().out
    assert "ForgeAgent could not start" in output
    assert "synthetic-launch-secret" not in output
    assert f"workdir: {config.workdir}" in output


def test_failure_summary_does_not_echo_untrusted_state_fields(tmp_path, capsys):
    smoke = _load_smoke_module()
    secret = "synthetic-state-secret"
    config = _config(smoke, tmp_path)

    def failed_forgeagent(*args, **kwargs):
        _write_state(
            tmp_path,
            status="failed",
            phase="failed",
            stop_reason="invalid_role_submission",
            plan=[
                {
                    "id": "moving_average",
                    "behavior": secret,
                    "acceptance": "Files pass.",
                }
            ],
            last_evaluation=[
                {
                    "id": "moving_average",
                    "passed": False,
                    "observed": secret,
                    "expected": "Submit through the role tool.",
                    "location": "calc.py",
                }
            ],
            api_key=secret,
        )
        return subprocess.CompletedProcess(args[0], 1)

    assert smoke.run_smoke(config, run=failed_forgeagent) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "invalid_role_submission" in captured.out + captured.err


def test_run_smoke_returns_130_for_keyboard_interrupt(tmp_path, capsys):
    smoke = _load_smoke_module()
    config = _config(smoke, tmp_path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    assert smoke.run_smoke(config, run=interrupted) == 130
    assert f"workdir: {config.workdir}" in capsys.readouterr().out
