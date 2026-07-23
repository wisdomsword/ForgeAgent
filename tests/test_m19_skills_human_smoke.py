from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

import forgeagent.cli as cli_module
import forgeagent.context as context_module
import forgeagent.mcp_manager as mcp_manager_module
import forgeagent.model_registry as model_registry_module
from forgeagent.models import Message
from forgeagent.skills import SkillRegistry


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "m19-skills-human-smoke.py"
    spec = importlib.util.spec_from_file_location("m19_skills_human_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixture_isolated_user_and_project_skills(tmp_path):
    smoke = _load_smoke_module()

    fixture = smoke.create_fixture(tmp_path)

    assert "USER_SKILL" in fixture.user_skill.read_text()
    assert "PROJECT_SKILL_V1" in fixture.project_skill.read_text()
    assert fixture.home.is_relative_to(tmp_path)
    assert fixture.project.is_relative_to(tmp_path)

    registry = SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        allow_project=False,
    )
    assert "USER_SKILL" in registry.read("review-python")


def test_client_reads_skill_then_accepts_expected_feedback():
    smoke = _load_smoke_module()
    state = smoke.SmokeState()
    client = smoke.DeterministicSkillClient("PROJECT_SKILL_V1", state)

    first = client.complete([Message(role="user", content="review")])
    second = client.complete([Message(role="system", content="[Skill None]\nPROJECT_SKILL_V1")])

    assert '"name": "Skill"' in first.content
    assert "PASS progressive loading: PROJECT_SKILL_V1" in second.content
    assert state.observed_markers == ["PROJECT_SKILL_V1"]


def test_factory_keeps_v1_until_v2_is_trusted(tmp_path):
    smoke = _load_smoke_module()
    fixture = smoke.create_fixture(tmp_path)
    state = smoke.SmokeState()
    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    factory = smoke.SmokeClientFactory(fixture, state)

    first = factory("mock")
    extra_before_reload = factory("mock")
    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    after_reload = factory("mock")

    assert first.expected_marker == "PROJECT_SKILL_V1"
    assert extra_before_reload.expected_marker == "PROJECT_SKILL_V1"
    assert after_reload.expected_marker == "PROJECT_SKILL_V2"
    assert "PROJECT_SKILL_V2" in fixture.project_skill.read_text()


def test_check_matrix_fails_closed_until_human_checks_pass():
    smoke = _load_smoke_module()
    state = smoke.SmokeState(observed_markers=["PROJECT_SKILL_V1", "PROJECT_SKILL_V2"])

    checks = smoke.evaluate_checks(
        state,
        trust_matches=True,
        completion_ok=False,
        history_ok=False,
    )

    assert checks["progressive V1"] is True
    assert checks["reload V2"] is True
    assert checks["Skill trust V2"] is True
    assert checks["slash completion"] is False
    assert checks["arrow history"] is False


def test_check_matrix_allows_extra_v1_tasks_before_reload():
    smoke = _load_smoke_module()
    state = smoke.SmokeState(
        observed_markers=[
            "PROJECT_SKILL_V1",
            "PROJECT_SKILL_V1",
            "PROJECT_SKILL_V1",
            "PROJECT_SKILL_V2",
        ]
    )

    checks = smoke.evaluate_checks(
        state,
        trust_matches=True,
        completion_ok=True,
        history_ok=True,
    )

    assert all(checks.values())


def test_main_rejects_non_tty(monkeypatch, capsys):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)

    assert smoke.main() == 2
    assert "real interactive terminal" in capsys.readouterr().err


def test_temporary_environment_restores_home_and_cwd(tmp_path, monkeypatch):
    smoke = _load_smoke_module()
    original_home = str(tmp_path / "original-home")
    original_cwd = Path.cwd()
    monkeypatch.setenv("HOME", original_home)

    with smoke.temporary_smoke_environment(tmp_path) as fixture:
        assert Path.home() == fixture.home
        assert Path.cwd() == fixture.project

    assert os.environ["HOME"] == original_home
    assert Path.cwd() == original_cwd


def test_temporary_environment_hides_and_restores_secret_environment(tmp_path, monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("M19_API_KEY", "deterministic-secret-value")

    with smoke.temporary_smoke_environment(tmp_path):
        assert "M19_API_KEY" not in os.environ

    assert os.environ["M19_API_KEY"] == "deterministic-secret-value"


def test_temporary_environment_isolates_import_time_config_paths(tmp_path):
    smoke = _load_smoke_module()
    original_paths = (
        context_module._DEFAULT_CONFIG_PATH,
        mcp_manager_module.DEFAULT_USER_MCP_PATH,
        model_registry_module.DEFAULT_USER_MODELS_PATH,
        model_registry_module.DEFAULT_USER_CONFIG_PATH,
    )

    with smoke.temporary_smoke_environment(tmp_path) as fixture:
        config_root = fixture.home / ".forgeagent"
        assert context_module._DEFAULT_CONFIG_PATH == config_root / "config.yaml"
        assert mcp_manager_module.DEFAULT_USER_MCP_PATH == config_root / "mcp.yaml"
        assert model_registry_module.DEFAULT_USER_MODELS_PATH == config_root / "models.yaml"
        assert model_registry_module.DEFAULT_USER_CONFIG_PATH == config_root / "config.yaml"

    assert (
        context_module._DEFAULT_CONFIG_PATH,
        mcp_manager_module.DEFAULT_USER_MCP_PATH,
        model_registry_module.DEFAULT_USER_MODELS_PATH,
        model_registry_module.DEFAULT_USER_CONFIG_PATH,
    ) == original_paths


def test_temporary_environment_restores_home_when_chdir_fails(tmp_path, monkeypatch):
    smoke = _load_smoke_module()
    original_home = str(tmp_path / "original-home")
    original_chdir = smoke.os.chdir
    attempts = 0
    monkeypatch.setenv("HOME", original_home)

    def fail_first_chdir(path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("synthetic chdir failure")
        original_chdir(path)

    monkeypatch.setattr(smoke.os, "chdir", fail_first_chdir)

    with pytest.raises(OSError, match="synthetic chdir failure"):
        with smoke.temporary_smoke_environment(tmp_path):
            pass

    assert os.environ["HOME"] == original_home


def test_temporary_environment_restores_secrets_when_cwd_restore_fails(tmp_path, monkeypatch):
    smoke = _load_smoke_module()
    original_home = str(tmp_path / "original-home")
    original_cwd = Path.cwd()
    original_chdir = smoke.os.chdir
    attempts = 0
    monkeypatch.setenv("HOME", original_home)
    monkeypatch.setenv("M19_API_KEY", "deterministic-secret-value")

    def fail_second_chdir(path):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("synthetic cwd restore failure")
        original_chdir(path)

    monkeypatch.setattr(smoke.os, "chdir", fail_second_chdir)
    try:
        with pytest.raises(OSError, match="synthetic cwd restore failure"):
            with smoke.temporary_smoke_environment(tmp_path):
                assert "M19_API_KEY" not in os.environ

        assert os.environ["HOME"] == original_home
        assert os.environ["M19_API_KEY"] == "deterministic-secret-value"
    finally:
        original_chdir(original_cwd)


def test_main_reports_ctrl_c_swallowed_by_repl_as_cancelled(monkeypatch, capsys):
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)

    def interrupting_reader(_prompt):
        raise KeyboardInterrupt

    def swallowing_repl(**kwargs):
        try:
            kwargs["read_line"]("forge> ")
        except KeyboardInterrupt:
            pass

    monkeypatch.setattr(cli_module, "_make_interactive_reader", lambda: interrupting_reader)
    monkeypatch.setattr(smoke, "repl", swallowing_repl)

    assert smoke.main() == 130
    assert "M19 human smoke CANCELLED" in capsys.readouterr().err


def test_trust_record_check_requires_approved_v2_content(tmp_path):
    smoke = _load_smoke_module()
    fixture = smoke.create_fixture(tmp_path)
    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    smoke.SmokeClientFactory(fixture, smoke.SmokeState())("mock")

    assert smoke.trust_record_matches_v2(fixture) is False

    SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=lambda _request: True,
    )
    assert smoke.trust_record_matches_v2(fixture) is True


def test_human_answers_and_summary_fail_closed(monkeypatch, capsys):
    smoke = _load_smoke_module()
    answers = iter(["yes", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert smoke._ask_yes("completion?") is True
    assert smoke._ask_yes("history?") is False
    assert smoke._print_summary({"completion": True}, []) == 0
    assert smoke._print_summary({"history": False}, ["history was not confirmed"]) == 1

    output = capsys.readouterr().out
    assert "M19 HUMAN SMOKE: PASS" in output
    assert "M19 HUMAN SMOKE: FAIL" in output
    assert "history was not confirmed" in output


def test_instructions_name_every_manual_step(capsys):
    smoke = _load_smoke_module()

    smoke._print_instructions()

    output = capsys.readouterr().out
    assert "type '/', then 'm'" in output
    assert "Keep the leading '/' visible" in output
    assert "accidentally submit m or re" in output
    assert "press Up, then Down" in output
    assert "review first snapshot" in output
    assert "review reloaded snapshot" in output
