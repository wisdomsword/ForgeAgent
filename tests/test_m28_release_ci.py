"""Contracts for the M28 installed-wheel Linux release gate."""

from __future__ import annotations

import hashlib
import json
import platform
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("clean-wheel", "cli", "http", "single", "duo", "triad")


def _wheel_selection_command() -> str:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    command = next(
        item
        for item in ci["linux-docker-container"]["script"]
        if "set -- artifacts/ci/dist/forgeagent-0.1.0-*.whl" in item
    )
    return command.split("su-exec forgeagent mkdir", maxsplit=1)[0]


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


def test_release_ci_wheel_cardinality_fails_closed(tmp_path: Path) -> None:
    command = _wheel_selection_command()
    wheel_dir = tmp_path / "artifacts" / "ci" / "dist"
    wheel_dir.mkdir(parents=True)

    assert 'test "$#" -eq 1 || exit 1;' in command
    assert 'test -f "$1" || exit 1;' in command
    assert subprocess.run(["sh", "-c", command], cwd=tmp_path).returncode != 0

    (wheel_dir / "forgeagent-0.1.0-one.whl").touch()
    assert subprocess.run(["sh", "-c", command], cwd=tmp_path).returncode == 0

    (wheel_dir / "forgeagent-0.1.0-two.whl").touch()
    assert subprocess.run(["sh", "-c", command], cwd=tmp_path).returncode != 0


def test_release_ci_bootstrap_failure_writes_bounded_report(tmp_path: Path) -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    command = next(
        item for item in ci["linux-docker-container"]["script"] if "docker run --rm" in item
    )

    for marker in (
        "if python -m pip install",
        "else python -c",
        "hashlib",
        "platform.python_version()",
        '"clean-wheel":"failed"',
        '"cli":"not-run"',
        '"http":"not-run"',
        '"single":"not-run"',
        '"duo":"not-run"',
        '"triad":"not-run"',
        "os.replace(temp,output)",
        "exit 1",
    ):
        assert marker in command

    fallback = shlex.split(command)[-1]
    wheel = tmp_path / "forgeagent-0.1.0-test.whl"
    wheel.write_bytes(b"candidate wheel")
    report_path = tmp_path / "rc-smoke.json"
    subprocess.run(
        [sys.executable, "-c", fallback, str(wheel), str(report_path)],
        check=True,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == {
        "schema": "forgeagent.release-candidate-smoke/v1",
        "version": "0.1.0",
        "python": platform.python_version(),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "passed": False,
        "checks": {
            "clean-wheel": "failed",
            "cli": "not-run",
            "http": "not-run",
            "single": "not-run",
            "duo": "not-run",
            "triad": "not-run",
        },
    }
