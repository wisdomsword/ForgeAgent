"""Portable contracts for a source checkout prepared for GitHub review."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT = "docs/superpowers/reports/2026-11-18-fix-github-release-readiness-verify.md"


def test_github_ci_requires_offline_and_docker_gates_without_publishing() -> None:
    ci = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
    assert ci["permissions"] == {"contents": "read"}
    assert set(ci["jobs"]) == {"offline-verification", "linux-docker-container"}
    offline = ci["jobs"]["offline-verification"]
    docker = ci["jobs"]["linux-docker-container"]
    for job in (offline, docker):
        assert job["runs-on"] == "ubuntu-24.04"
        assert job.get("continue-on-error") is not True
        assert not job.get("services")  # GitHub's built-in daemon owns same-host mounts.
        artifacts = [step for step in job["steps"] if "upload-artifact@" in step.get("uses", "")]
        assert artifacts and all(step["if"] == "always()" for step in artifacts)
    offline_script = "\n".join(step.get("run", "") for step in offline["steps"])
    for command in (
        "uv==0.11.1",
        "@fission-ai/openspec@1.13.1",
        "uv sync --locked",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest -q",
        "tests.golden.runner",
        "openspec validate --all --strict",
        "uv build --out-dir dist",
    ):
        assert command in offline_script
    docker_script = "\n".join(step.get("run", "") for step in docker["steps"])
    for command in (
        'test "$(id -u)" -ne 0',
        "docker info",
        "docker pull python:3.11-slim",
        "-m container_integration",
        "tests == 10",
        "skipped == 0",
        "failures == 0",
        "errors == 0",
        "uv build --wheel",
        'test "$#" -eq 1',
        'test -f "$1"',
        "--user",
        '"$(id -u):$(id -g)"',
        '"$GITHUB_WORKSPACE:$GITHUB_WORKSPACE"',
        "m28_release_candidate_smoke.py",
        "rc-smoke.json",
        'set(r["checks"]) == names',
        'r["passed"] is True',
    ):
        assert command in docker_script
    for check in ("clean-wheel", "cli", "http", "single", "duo", "triad"):
        assert check in docker_script
    assert "API_KEY" not in docker_script and "TOKEN" not in docker_script
    assert "publish" not in ci["jobs"] and "id-token" not in ci["permissions"]


def test_local_credentials_and_runtime_state_are_ignored_but_rules_are_shareable() -> None:
    ignored = (
        ".env",
        ".env.local",
        ".env.production",
        "nested/.env.secret",
        ".forgeagent/loops/checkpoint.json",
        ".forgeagent/collaborations/session.json",
        ".forgeagent/receipts/action.json",
        ".forgeagent/Memory/state.json",
        ".forgeagent/MEMORY.md",
        ".forgeagent/MEMORY.md.backup",
        ".forgeagent/memory-backups/rollback.md",
        ".forgeagent/memory/state.json",
        ".forgeagent/backups/state.json",
    )
    shareable = ("AGENTS.md", ".forgeagent/AGENTS.md", ".forgeagent/skills/review/SKILL.md")
    for path in ignored + shareable:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT, check=False
        )
        assert result.returncode == (0 if path in ignored else 1), path


def test_readme_starts_with_reproducible_onboarding_and_security_boundary() -> None:
    readme = (ROOT / "README.md").read_text()
    intro = readme.split("## 当前验证", 1)[0]
    for marker in (
        "Git",
        "Python",
        "3.11",
        "uv",
        "git clone",
        "cd ForgeAgent",
        "uv sync --locked",
        "ANTHROPIC_API_KEY",
        "uv run forgeagent run",
        "真实",
        "费用",
        "restricted 不是 OS 级密封沙箱",
        "SECURITY.md",
    ):
        assert marker in intro
    assert REPORT in readme
    assert "1.13.1" in readme
    assert "3055 passed" not in readme.split("## 当前验证", 1)[1].split("\n## ", 1)[0]


def test_security_policy_provides_private_reporting_and_supported_versions() -> None:
    policy = (ROOT / "SECURITY.md").read_text()
    for marker in (
        "Supported versions",
        "0.1.0",
        "Private vulnerability reporting",
        "liu.mingling@gmail.com",
    ):
        assert marker in policy
    assert "public issue" in policy
    for document in (ROOT / "README.md", ROOT / "SECURITY.md"):
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", document.read_text()):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            assert (document.parent / target.split("#", 1)[0]).exists(), target


def test_github_junit_gate_rejects_missing_tests_skips_failures_and_errors(tmp_path: Path) -> None:
    ci = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
    script = next(
        step["run"]
        for step in ci["jobs"]["linux-docker-container"]["steps"]
        if "ET.parse" in step.get("run", "")
    )
    command = next(line for line in script.splitlines() if "ET.parse" in line)
    artifact = tmp_path / "artifacts/ci/container-junit.xml"
    artifact.parent.mkdir(parents=True)
    for tests, skipped, failures, errors in (
        (10, 0, 0, 0),
        (9, 0, 0, 0),
        (10, 1, 0, 0),
        (10, 0, 1, 0),
        (10, 0, 0, 1),
    ):
        artifact.write_text(
            f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
            f'failures="{failures}" errors="{errors}"/></testsuites>'
        )
        result = subprocess.run(
            ["sh", "-c", command], cwd=tmp_path, capture_output=True, check=False
        )
        assert (result.returncode == 0) == (tests == 10 and skipped == failures == errors == 0)
