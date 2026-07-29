"""Contracts for the M28 installed-wheel Linux release gate."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("clean-wheel", "cli", "http", "single", "duo", "triad")


def test_release_ci_runs_fixed_python_installed_wheel_smoke() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = ci["linux-docker-container"]
    script = "\n".join(job["script"])

    assert job.get("allow_failure") is not True
    assert job["artifacts"]["when"] == "always"
    assert {
        "artifacts/ci/container-junit.xml",
        "artifacts/ci/rc-smoke.json",
    } <= set(job["artifacts"]["paths"])
    for marker in (
        "uv build --wheel --out-dir artifacts/ci/dist",
        "forgeagent-0.1.0-*.whl",
        "python:3.11-slim",
        "docker run --rm",
        "--user 1000:1000",
        '-v "$CI_PROJECT_DIR:$CI_PROJECT_DIR"',
        '-w "$CI_PROJECT_DIR/.tmp/rc-work"',
        'HOME="$CI_PROJECT_DIR/.tmp/rc-home"',
        'TMPDIR="$CI_PROJECT_DIR/.tmp/rc-tmp"',
        '"$CI_PROJECT_DIR/$wheel"',
        '"$CI_PROJECT_DIR/scripts/m28_release_candidate_smoke.py"',
        '"$CI_PROJECT_DIR/artifacts/ci/rc-smoke.json"',
        'python "$2" --wheel "$1" --output "$3" --python python',
        "tests == 10",
        "skipped == 0",
        "forgeagent.release-candidate-smoke/v1",
    ):
        assert marker in script
    docker_command = next(command for command in job["script"] if "docker run --rm" in command)
    assert "API_KEY" not in docker_command
    assert "TOKEN" not in docker_command
    for check in CHECKS:
        assert check in script


def test_release_ci_report_assertion_is_exact() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    script = "\n".join(ci["linux-docker-container"]["script"])

    for marker in (
        "set(r) ==",
        'r["passed"] is True',
        'set(r["checks"])',
        'all(r["checks"][name] == "passed"',
    ):
        assert marker in script
