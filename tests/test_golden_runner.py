"""Contract tests for the executable golden validation runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from enum import IntEnum
from pathlib import Path

import pytest

from tests.golden.manifest import GOLDEN_SCENARIOS, GoldenCheckError, GoldenEvidence, GoldenScenario
from tests.golden.runner import (
    EXPECTED_IDS,
    EXPECTED_REAL_IDS,
    GoldenPreflightError,
    default_output_dir,
    main,
    render_markdown,
    run_suite,
    validate_manifest,
    write_reports,
)


def _pass(_: Path) -> GoldenEvidence:
    return GoldenEvidence(detail="checked", evidence={"value": [None, True, 1, 1.5, "ok"]})


def _fail(_: Path) -> GoldenEvidence:
    raise GoldenCheckError("expected check failed")


def _scenario(scenario_id: str, run_offline=_pass, *, real: bool = False) -> GoldenScenario:
    return GoldenScenario(
        scenario_id=scenario_id,
        title=f"Scenario {scenario_id}",
        run_offline=run_offline,
        run_real=(lambda _path, _client: _pass(_path)) if real else None,
    )


def test_manifest_has_exactly_the_approved_offline_and_real_ids():
    assert len(GOLDEN_SCENARIOS) == 20
    assert frozenset(scenario.scenario_id for scenario in GOLDEN_SCENARIOS) == EXPECTED_IDS
    assert (
        frozenset(
            scenario.scenario_id for scenario in GOLDEN_SCENARIOS if scenario.run_real is not None
        )
        == EXPECTED_REAL_IDS
    )


def test_manifest_preflight_rejects_duplicates_additions_and_catalog_prefix_matches(tmp_path):
    catalog = tmp_path / "catalog.md"
    catalog.write_text("### G010 is not G01\n", encoding="utf-8")
    duplicate = (_scenario("G01"), _scenario("G01"))

    with pytest.raises(GoldenPreflightError):
        validate_manifest(duplicate, catalog_path=catalog)

    complete_catalog = tmp_path / "complete.md"
    complete_catalog.write_text(
        "\n".join(f"### {scenario_id} definition" for scenario_id in EXPECTED_IDS),
        encoding="utf-8",
    )
    scenarios = tuple(
        _scenario(scenario_id, real=scenario_id in EXPECTED_REAL_IDS)
        for scenario_id in EXPECTED_IDS
    )
    validate_manifest(scenarios, catalog_path=complete_catalog)


def test_run_suite_returns_success_and_failure_exit_codes_and_shared_summary(tmp_path):
    passed = run_suite((_scenario("G01"),), mode="offline")
    failed = run_suite((_scenario("G01", _fail),), mode="offline")

    assert passed.exit_code == 0
    assert failed.exit_code == 1
    assert failed.failed == 1

    json_path, markdown_path = write_reports(failed, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == failed.total
    assert payload["passed"] == failed.passed
    assert payload["failed"] == failed.failed
    assert f"{failed.passed}/{failed.total}" in markdown_path.read_text(encoding="utf-8")
    assert render_markdown(failed) == markdown_path.read_text(encoding="utf-8")


def test_preflight_failure_does_not_create_an_output_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "not-created"
    monkeypatch.setattr("tests.golden.runner._load_manifest", lambda: (_scenario("G01"),))

    assert main(["--output-dir", str(output_dir)]) == 2
    assert not output_dir.exists()


class _IntegerEnum(IntEnum):
    VALUE = 1


class _IntegerSubclass(int):
    pass


class _ListSubclass(list):
    pass


@pytest.mark.parametrize(
    "evidence",
    [
        {"value": Path("not-json")},
        {"value": ("tuple",)},
        {1: "non-string key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": _IntegerEnum.VALUE},
        {"value": _IntegerSubclass(1)},
        {"value": _ListSubclass(["subclass"])},
    ],
)
def test_invalid_evidence_fails_only_its_scenario_and_reports_without_repr(tmp_path, evidence):
    class _SecretObject:
        def __repr__(self) -> str:
            return "secret-repr-must-not-appear"

    def invalid(_: Path) -> GoldenEvidence:
        return GoldenEvidence(detail="invalid", evidence=evidence)

    suite = run_suite((_scenario("G01", invalid), _scenario("G03")), mode="offline")

    assert suite.failed == 1
    assert suite.passed == 1
    assert suite.results[0].detail == "invalid evidence"
    assert suite.results[0].evidence == {}
    json_path, markdown_path = write_reports(suite, tmp_path)
    assert "secret-repr-must-not-appear" not in json_path.read_text(encoding="utf-8")
    assert "secret-repr-must-not-appear" not in markdown_path.read_text(encoding="utf-8")


def test_report_replaces_existing_files_atomically(tmp_path):
    suite = run_suite((_scenario("G01"),), mode="offline")
    json_path, markdown_path = write_reports(suite, tmp_path)
    json_path.write_text("stale", encoding="utf-8")
    markdown_path.write_text("stale", encoding="utf-8")

    replaced_json, replaced_markdown = write_reports(suite, tmp_path)

    assert replaced_json == json_path
    assert replaced_markdown == markdown_path
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema"] == "forgeagent.golden.v1"
    assert markdown_path.read_text(encoding="utf-8").startswith("# ForgeAgent Golden Validation")


@pytest.mark.parametrize("model_id", ["../../escape", "..", "gpt/5", "模型!@#", "x" * 80])
def test_real_output_directory_is_contained_and_bounded(tmp_path, model_id):
    root = tmp_path / "artifacts" / "golden" / "real"
    directory = default_output_dir(
        mode="real", model_id=model_id, artifact_root=tmp_path / "artifacts"
    )

    assert directory.is_relative_to(root)
    assert len(directory.name.rsplit("-", 1)[0]) <= 48


def test_normalized_model_collisions_receive_distinct_digest_directories(tmp_path):
    first = default_output_dir(mode="real", model_id="gpt/5", artifact_root=tmp_path / "artifacts")
    second = default_output_dir(mode="real", model_id="gpt:5", artifact_root=tmp_path / "artifacts")

    assert first != second
    assert first.parent == second.parent


def test_offline_main_restores_home_variables_after_normal_and_runner_failure(
    tmp_path, monkeypatch
):
    original = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")}
    output_dir = tmp_path / "normal"
    observed_homes: list[dict[str, str | None]] = []

    def observe_isolated_imports() -> None:
        observed_homes.append({name: os.environ.get(name) for name in original})

    monkeypatch.setattr(
        "tests.golden.runner._load_offline_configuration_modules", observe_isolated_imports
    )
    assert main(["--output-dir", str(output_dir)]) == 1
    assert observed_homes[0] != original
    assert {name: os.environ.get(name) for name in original} == original

    def raise_from_suite(*_args, **_kwargs):
        raise RuntimeError("runner exploded")

    monkeypatch.setattr("tests.golden.runner.run_suite", raise_from_suite)
    with pytest.raises(RuntimeError, match="runner exploded"):
        main(["--output-dir", str(tmp_path / "failure")])
    assert {name: os.environ.get(name) for name in original} == original


def test_standalone_offline_runner_ignores_hostile_parent_mcp_config(tmp_path):
    hostile_home = tmp_path / "hostile-home"
    hostile_config = hostile_home / ".forgeagent" / "mcp.yaml"
    hostile_config.parent.mkdir(parents=True)
    hostile_config.write_text("mcpServers: [not-a-mapping]", encoding="utf-8")
    output_dir = tmp_path / "offline-report"
    environment = os.environ | {"HOME": str(hostile_home), "USERPROFILE": str(hostile_home)}

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.golden.runner",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1, completed.stderr
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert payload["total"] == 20
    assert payload["passed"] == 0


def test_real_main_keeps_the_callers_home_for_model_resolution(tmp_path, monkeypatch):
    original = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")}
    observed_homes: list[dict[str, str | None]] = []

    def build_client(_: str) -> object:
        observed_homes.append({name: os.environ.get(name) for name in original})
        return object()

    monkeypatch.setattr("tests.golden.runner._build_real_client", build_client)
    assert main(["--real-model", "gpt/5", "--output-dir", str(tmp_path / "real")]) == 1
    assert observed_homes == [original]
    payload = json.loads((tmp_path / "real" / "results.json").read_text(encoding="utf-8"))
    assert payload["total"] == 5
