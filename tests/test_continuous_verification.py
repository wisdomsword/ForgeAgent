"""Offline contracts for the M24 CI and platform evidence surface."""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _ci() -> dict:
    return yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))


def _script(job: dict) -> str:
    return "\n".join(job.get("before_script", []) + job.get("script", []))


def _mark_names(function: object) -> set[str]:
    marks = getattr(function, "pytestmark", [])
    if not isinstance(marks, (list, tuple, set)):
        marks = [marks]
    return {getattr(mark, "name", "") for mark in marks}


def _allows_failure(value: object) -> bool:
    if isinstance(value, dict):
        return value.get("allow_failure") is True or any(
            _allows_failure(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_allows_failure(child) for child in value)
    return False


def test_required_ci_jobs_cover_all_gates() -> None:
    ci = _ci()
    security = ci["dependency-security"]
    assert security["stage"] == "verify"
    assert security.get("allow_failure") is not True
    assert "python3 scripts/audit_dependencies.py" in _script(security)
    assert security["artifacts"]["when"] == "always"
    offline = ci["offline-verification"]
    docker = ci["linux-docker-container"]
    assert offline["stage"] == docker["stage"] == "verify"
    assert offline["image"] == "node:22.22.0-bookworm-slim"
    assert offline.get("allow_failure") is not True
    assert docker.get("allow_failure") is not True
    assert not _allows_failure(ci["workflow"]["rules"])
    assert ci["variables"]["GIT_DEPTH"] == "0"
    assert {"artifacts/ci/golden/", "dist/"} <= set(offline["artifacts"]["paths"])
    offline_script = _script(offline)
    for expected in (
        "-r tools/ci-requirements.txt",
        "npm ci --prefix tools/openspec --ignore-scripts",
        "--break-system-packages",
    ):
        assert expected in offline_script
    for expected in (
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest -q",
        "tests.golden.runner",
        "openspec validate --all --strict",
        "uv build --out-dir dist",
    ):
        assert expected in offline_script


def test_docker_job_requires_preflight_and_zero_skip_junit() -> None:
    docker = _ci()["linux-docker-container"]
    script = _script(docker)
    assert docker["image"] == "docker:29.2.1-cli"
    assert docker["services"][0]["name"] == "docker:29.2.1-dind"
    assert docker["variables"]["DOCKER_HOST"] == "tcp://docker:2375"
    assert docker["variables"]["DOCKER_TLS_CERTDIR"] == ""
    assert docker["variables"]["TMPDIR"] == "$CI_PROJECT_DIR/.tmp"
    assert "docker-privileged" in docker["tags"]
    assert "-r tools/ci-requirements.txt" in _script(docker)
    assert "--break-system-packages" in _script(docker)
    assert docker["artifacts"]["reports"]["junit"] == ("artifacts/ci/container-junit.xml")
    assert "artifacts/ci/container-junit.xml" in docker["artifacts"]["paths"]
    for expected in (
        'mkdir -p artifacts/ci "$TMPDIR"',
        "adduser -D -u 1000 forgeagent",
        'chown -R forgeagent:forgeagent "$CI_PROJECT_DIR"',
        "su-exec forgeagent",
        "docker info",
        "docker pull python:3.11-slim",
        "docker image inspect python:3.11-slim",
        "-m container_integration",
        "--junitxml=artifacts/ci/container-junit.xml",
        "tests == 10",
        "skipped == 0",
    ):
        assert expected in script


def test_container_module_has_four_unit_and_ten_integration_tests() -> None:
    from tests import test_container_backend

    tests = [
        value
        for name, value in vars(test_container_backend).items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    marked = {test.__name__ for test in tests if "container_integration" in _mark_names(test)}
    docker_required = {test.__name__ for test in tests if "skipif" in _mark_names(test)}
    expected = {
        "test_normal_code_runs_in_container",
        "test_cross_block_state_roundtrip_through_containers",
        "test_same_path_mount_read_write",
        "test_timeout_kills_container_and_next_block_runs",
        "test_exception_in_container_captured",
        "test_t1_host_filesystem_not_visible",
        "test_t3_no_network_device",
        "test_t6_pids_limit_stops_fork_bomb",
        "test_t9_non_root_and_sys_masked",
        "test_t9_no_secret_env_inside_container",
    }
    assert len(tests) == 14
    assert marked == docker_required == expected


def test_platform_matrix_and_public_docs_are_linked() -> None:
    matrix = (ROOT / "docs/platform-support.md").read_text(encoding="utf-8")
    for status in ("verified", "configured", "supplemental", "scheduled", "deferred"):
        assert status in matrix
    assert "Linux Docker runner topology" in matrix
    assert "Linux amd64/arm64 + Docker Engine" not in matrix
    assert "Linux runner remains\n`configured`" not in matrix
    for platform in ("rootless Podman", "Windows native", "macOS"):
        assert platform in matrix
    for column in ("Prerequisites", "Current evidence", "Limitations", "Next Comet trigger"):
        assert column in matrix

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    action_plan = (ROOT / "ACTION_PLAN.md").read_text(encoding="utf-8")
    milestone = (ROOT / "milestones/milestone_024.md").read_text(encoding="utf-8")
    for text in (readme, action_plan, milestone):
        assert ".gitlab-ci.yml" in text
        assert "docs/platform-support.md" in text
    assert readme.count("## 当前验证") == 1
    current_section = readme.split("## 当前验证", 1)[1].split("\n## ", 1)[0]
    assert "十项零跳过 Linux Docker 集成" in current_section
    assert "github.com/wisdomsword/ForgeAgent/actions/runs/" in current_section
    assert "Linux Docker runner topology (M24 历史 container 运行)" in matrix
    assert "Linux amd64/arm64" not in current_section
    assert "Linux GitLab CI 已 verified" not in current_section
    report = "2026-11-18-fix-github-release-readiness-verify.md"
    assert f"docs/superpowers/reports/{report}" in current_section
    assert f"superpowers/reports/{report}" in matrix
    assert "1.13.1" in current_section and "1.13.1" in matrix
    assert "3055 passed" not in current_section
    assert "Current offline repository baseline: `3055" not in matrix
